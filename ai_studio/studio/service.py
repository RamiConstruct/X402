"""Logique métier : comptes, imports, devis, acceptation, exécution, règlement."""
from __future__ import annotations

import secrets
import shutil
import tempfile
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, update

from . import billing, ledger, media, moderation, planner, quotes, signing
from .auth import find_user, hash_password, issue_token, verify_password
from .config import Settings
from .db import Database
from .engines import Registry
from .models import Asset, Job, JobEvent, ProviderCall, Quote, RenderCache, User, now
from .providers import ADAPTERS, ProviderError, StepContext
from .storage import LocalStorage, sha256_file

ALLOWED_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Studio:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(settings.database_url)
        self.db.create_all()
        self.registry = Registry.load(settings.engines_dir)
        self.storage = LocalStorage(settings.storage_dir)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self.adapters = {name: cls() for name, cls in ADAPTERS.items()}

    # ------------------------------------------------------------------ comptes
    def register(self, email: str, password: str, invite: str = "") -> tuple[User, str]:
        if self.settings.invite_code and not secrets.compare_digest(invite or "", self.settings.invite_code):
            raise ServiceError("code d'invitation requis ou incorrect", 403)
        email = (email or "").strip().lower()
        if "@" not in email or len(email) > 320:
            raise ServiceError("adresse e-mail invalide")
        if len(password or "") < 10:
            raise ServiceError("mot de passe trop court (10 caractères minimum)")
        with self.db.session() as s:
            if find_user(s, email):
                raise ServiceError("compte déjà existant", 409)
            user = User(email=email, password_hash=hash_password(password))
            s.add(user)
            s.flush()
            if self.settings.signup_credits > 0:
                ledger.grant(s, user.id, self.settings.signup_credits, key=f"signup:{user.id}",
                             memo="crédits de bienvenue")
            return user, issue_token(s, user)

    def login(self, email: str, password: str) -> tuple[User, str]:
        with self.db.session() as s:
            user = find_user(s, email or "")
            if not user or not verify_password(password or "", user.password_hash):
                raise ServiceError("identifiants incorrects", 401)
            return user, issue_token(s, user)

    def account(self, user: User) -> dict:
        with self.db.session() as s:
            return {"id": user.id, "email": user.email,
                    "credits_available": ledger.balance(s, ledger.available(user.id)),
                    "credits_held": ledger.balance(s, ledger.held(user.id)),
                    "dev_mode": self.settings.dev_mode, "paid_providers": self.settings.allow_paid_providers}

    # ------------------------------------------------------------------ assets
    def import_video(self, user: User, filename: str, tmp_path: Path) -> Asset:
        ext = Path(filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise ServiceError(f"format non accepté ({', '.join(sorted(ALLOWED_EXT))})")
        if tmp_path.stat().st_size > self.settings.max_upload_mb * (1 << 20):
            raise ServiceError(f"fichier trop lourd (max {self.settings.max_upload_mb} Mo)", 413)
        try:
            pr = media.probe(tmp_path)
        except media.MediaError as e:
            raise ServiceError(f"vidéo illisible : {e}") from e
        if pr.duration_s > self.settings.max_duration_s + 0.5:
            raise ServiceError(f"vidéo trop longue pour le pilote (max {self.settings.max_duration_s} s)")
        return self._store_asset(user.id, tmp_path, filename, pr, parent=None, job_id=None, label="Original")

    def _store_asset(self, user_id: str, path: Path, filename: str, pr: media.Probe, *, parent: Asset | None,
                     job_id: str | None, label: str) -> Asset:
        sha = sha256_file(path)
        key = f"{user_id}/{sha[:2]}/{sha}{Path(filename).suffix.lower() or '.mp4'}"
        if not self.storage.exists(key):
            self.storage.put_file(key, path)
        with self.db.session() as s:
            a = Asset(user_id=user_id, filename=Path(filename).name[:255], storage_key=key, sha256=sha,
                      size_bytes=path.stat().st_size, duration_s=pr.duration_s, width=pr.width, height=pr.height,
                      fps=pr.fps, parent_id=parent.id if parent else None, job_id=job_id, label=label[:255])
            s.add(a)
            s.flush()
            a.root_id = (parent.root_id or parent.id) if parent else a.id
            return a

    def get_asset(self, user: User, asset_id: str) -> Asset:
        with self.db.session() as s:
            a = s.get(Asset, asset_id)
            if a is None or a.user_id != user.id:
                raise ServiceError("vidéo introuvable", 404)
            return a

    def asset_view(self, a: Asset) -> dict:
        exp, sig = signing.sign(self.settings.secret_key, a.id, ttl_s=6 * 3600)
        base = f"/files/{a.id}?exp={exp}&sig={sig}"
        return {"id": a.id, "root_id": a.root_id, "parent_id": a.parent_id, "job_id": a.job_id,
                "filename": a.filename, "label": a.label, "duration_s": round(a.duration_s, 3),
                "width": a.width, "height": a.height, "fps": round(a.fps, 2), "size_bytes": a.size_bytes,
                "created_at": _aware(a.created_at).isoformat(), "stream_url": base, "download_url": base + "&dl=1"}

    def projects(self, user: User) -> list[dict]:
        with self.db.session() as s:
            assets = s.execute(select(Asset).where(Asset.user_id == user.id).order_by(Asset.created_at)).scalars().all()
        groups: dict[str, list[Asset]] = {}
        for a in assets:
            if a.job_id and not a.parent_id:  # fichier intermédiaire envoyé à un fournisseur
                continue
            groups.setdefault(a.root_id or a.id, []).append(a)
        out = [{"root_id": rid, "title": items[0].filename, "versions": [self.asset_view(a) for a in items]}
               for rid, items in groups.items()]
        return sorted(out, key=lambda p: p["versions"][-1]["created_at"], reverse=True)

    def file_for(self, asset_id: str, exp: int, sig: str) -> tuple[Path, Asset]:
        if not signing.verify(self.settings.secret_key, asset_id, exp, sig):
            raise ServiceError("lien expiré ou invalide", 403)
        with self.db.session() as s:
            a = s.get(Asset, asset_id)
            if a is None:
                raise ServiceError("fichier introuvable", 404)
        return self.storage.path(a.storage_key), a

    # ------------------------------------------------------------------ devis
    def create_quote(self, user: User, asset_id: str, prompt: str, start_s: float | None, end_s: float | None) -> dict:
        a = self.get_asset(user, asset_id)
        verdict = moderation.check_prompt(prompt or "")
        if not verdict.allowed:
            raise ServiceError(f"instruction refusée par la modération ({verdict.category})", 422)
        start = max(0.0, float(start_s or 0.0))
        end = min(a.duration_s, float(end_s) if end_s not in (None, "") else a.duration_s)
        if end - start < 0.5:
            raise ServiceError("la plage sélectionnée doit durer au moins 0,5 s")
        try:
            steps = planner.plan(prompt)
        except planner.PlanError as e:
            raise ServiceError(str(e)) from e
        options = quotes.build_options(steps, self.registry, self.settings, asset_sha=a.sha256,
                                       asset_duration=a.duration_s, start=start, end=end,
                                       cache_lookup=self._cache_lookup)
        for o in options:
            if o.get("available") and o["total_price_credits"] > self.settings.max_job_credits:
                o["available"] = False
                o["reason"] = f"dépasse le plafond par tâche ({self.settings.max_job_credits} crédits)"
        with self.db.session() as s:
            q = Quote(user_id=user.id, asset_id=a.id, prompt=prompt.strip(), range_start_s=start, range_end_s=end,
                      plan={"steps": [st.to_dict() for st in steps]}, options=options,
                      expires_at=now() + timedelta(seconds=self.settings.quote_ttl_s))
            s.add(q)
            s.flush()
            return self.quote_view(q)

    def quote_view(self, q: Quote) -> dict:
        return {"id": q.id, "asset_id": q.asset_id, "prompt": q.prompt, "range": [q.range_start_s, q.range_end_s],
                "plan": q.plan["steps"], "options": q.options, "expires_at": _aware(q.expires_at).isoformat(),
                "accepted_option": q.accepted_option}

    def _cache_lookup(self, key: str) -> bool:
        with self.db.session() as s:
            hit = s.execute(select(RenderCache).where(RenderCache.cache_key == key)).scalar_one_or_none()
            return bool(hit and self.storage.exists(hit.storage_key))

    # ------------------------------------------------------------------ acceptation
    def accept_quote(self, user: User, quote_id: str, option_id: str) -> dict:
        with self.db.session() as s:
            q = s.get(Quote, quote_id)
            if q is None or q.user_id != user.id:
                raise ServiceError("devis introuvable", 404)
            if q.accepted_option:
                job = s.execute(select(Job).where(Job.quote_id == q.id)).scalar_one()
                return self.job_view(job)  # idempotent : double clic = même tâche
            if _aware(q.expires_at) < now():
                raise ServiceError("devis expiré : demandez un nouveau devis", 410)
            opt = next((o for o in q.options if o["id"] == option_id), None)
            if opt is None or not opt.get("available"):
                raise ServiceError("option indisponible")
            price = int(opt["total_price_credits"])
            if ledger.spent_last_24h(s, user.id) + price > self.settings.daily_credit_cap:
                raise ServiceError("plafond de dépense journalier atteint", 429)
            job = Job(user_id=user.id, quote_id=q.id, option_id=option_id, input_asset_id=q.asset_id,
                      status="queued", steps=opt["steps"], reserved_credits=price,
                      estimated_cost_micro=int(opt["total_cost_micro"]), simulated=bool(opt.get("simulated")))
            s.add(job)
            s.flush()
            try:
                ledger.reserve(s, user.id, job.id, price)
            except ledger.InsufficientCredits as e:
                raise ServiceError("crédits insuffisants pour ce devis", 402) from e
            q.accepted_option = option_id
            s.add(JobEvent(job_id=job.id, level="info", message=f"devis accepté, {price} crédits réservés",
                           data={"option": option_id}))
            return self.job_view(job)

    def job_view(self, job: Job, events: list[JobEvent] | None = None) -> dict:
        d = {"id": job.id, "status": job.status, "option_id": job.option_id, "steps": job.steps,
             "input_asset_id": job.input_asset_id, "output_asset_id": job.output_asset_id,
             "reserved_credits": job.reserved_credits, "charged_credits": job.charged_credits,
             "estimated_cost_micro": job.estimated_cost_micro, "actual_cost_micro": job.actual_cost_micro,
             "error": job.error, "simulated": job.simulated, "created_at": _aware(job.created_at).isoformat(),
             "finished_at": _aware(job.finished_at).isoformat() if job.finished_at else None}
        if events is not None:
            d["events"] = [{"level": e.level, "message": e.message, "data": e.data,
                            "at": _aware(e.created_at).isoformat()} for e in events]
        return d

    def get_job(self, user: User, job_id: str) -> dict:
        with self.db.session() as s:
            job = s.get(Job, job_id)
            if job is None or job.user_id != user.id:
                raise ServiceError("tâche introuvable", 404)
            ev = s.execute(select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.id)).scalars().all()
            return self.job_view(job, ev)

    def list_jobs(self, user: User, limit: int = 50) -> list[dict]:
        with self.db.session() as s:
            jobs = s.execute(select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc()).limit(limit)).scalars().all()
            return [self.job_view(j) for j in jobs]

    def transactions(self, user: User, limit: int = 100) -> list[dict]:
        from .models import LedgerEntry, LedgerTransaction
        with self.db.session() as s:
            rows = s.execute(
                select(LedgerTransaction, LedgerEntry.amount_credits)
                .join(LedgerEntry, LedgerEntry.transaction_id == LedgerTransaction.id)
                .where(LedgerEntry.account == ledger.available(user.id))
                .order_by(LedgerTransaction.created_at.desc()).limit(limit)).all()
            return [{"id": t.id, "kind": t.kind, "amount_credits": amt, "memo": t.memo, "job_id": t.job_id,
                     "at": _aware(t.created_at).isoformat()} for t, amt in rows]

    # ------------------------------------------------------------------ paiement (Stripe)
    @property
    def billing_enabled(self) -> bool:
        return bool(self.settings.stripe_secret_key and self.settings.stripe_webhook_secret)

    def billing_packs(self) -> dict:
        return {"enabled": self.billing_enabled,
                "packs": [{"id": k, **{x: v[x] for x in ("credits", "amount_cents", "currency")}} for k, v in billing.PACKS.items()]}

    def billing_checkout(self, user: User, pack_id: str) -> dict:
        if not self.billing_enabled:
            raise ServiceError("paiement pas encore activé", 503)
        try:
            return billing.create_checkout(self.settings.stripe_secret_key, pack_id=pack_id, user_id=user.id,
                                           email=user.email, base_url=self.settings.public_base_url or "http://localhost")
        except billing.BillingError as e:
            raise ServiceError(str(e), e.status) from e

    def billing_webhook(self, payload: bytes, signature: str) -> dict:
        if not self.billing_enabled:
            raise ServiceError("paiement pas encore activé", 503)
        try:
            event = billing.verify_event(payload, signature, self.settings.stripe_webhook_secret)
        except billing.BillingError as e:
            raise ServiceError(str(e), 400) from e
        paid = billing.paid_session(event)
        if not paid:
            return {"ok": True, "ignored": event.get("type")}
        session_id, uid, credits = paid
        with self.db.session() as s:
            if not s.get(User, uid):
                raise ServiceError("utilisateur inconnu", 400)
            ledger.topup(s, uid, credits, key=f"stripe:{session_id}", memo=f"achat de {credits} crédits (Stripe)")
        return {"ok": True, "credited": credits}

    def dev_topup(self, user: User, credits: int) -> dict:
        if not self.settings.dev_mode:
            raise ServiceError("indisponible hors mode développement", 403)
        if not 1 <= credits <= 10_000:
            raise ServiceError("montant invalide")
        with self.db.session() as s:
            ledger.topup(s, user.id, credits, key=f"devtopup:{user.id}:{time.time_ns()}", memo="crédits de test (dev)")
        return self.account(user)

    # ------------------------------------------------------------------ exécution
    def _event(self, job_id: str, message: str, data: dict | None = None, level: str = "info") -> None:
        with self.db.session() as s:
            s.add(JobEvent(job_id=job_id, level=level, message=message, data=data or {}))

    def claim_next(self) -> str | None:
        with self.db.session() as s:
            job_id = s.execute(select(Job.id).where(Job.status == "queued").order_by(Job.created_at).limit(1)).scalar_one_or_none()
            if job_id is None:
                return None
            res = s.execute(update(Job).where(Job.id == job_id, Job.status == "queued")
                            .values(status="running", started_at=now()))
            return job_id if res.rowcount == 1 else None

    def run_job(self, job_id: str) -> None:
        with self.db.session() as s:
            job = s.get(Job, job_id)
            src = s.get(Asset, job.input_asset_id)
            q = s.get(Quote, job.quote_id)
        work = Path(tempfile.mkdtemp(prefix=f"{job_id}_", dir=self.settings.data_dir))
        actual_cost = 0
        try:
            opt = next(o for o in q.options if o["id"] == job.option_id)
            if opt.get("cache_hit"):
                actual_cost = 0
                out_path = self._from_cache(opt["cache_key"], work)
                self._event(job_id, "résultat déjà calculé : réutilisé sans nouvel appel moteur")
            else:
                out_path, actual_cost = self._execute(job, src, q, work)
                self._cache_put(opt["cache_key"], out_path)
            pr = media.probe(out_path)
            out = self._store_asset(job.user_id, out_path, f"{Path(src.filename).stem}_v.mp4", pr, parent=src,
                                    job_id=job_id, label=q.prompt[:120])
            charged = min(job.reserved_credits, self._price_for_actual(job.steps, actual_cost, opt))
            with self.db.session() as s:
                j = s.get(Job, job_id)
                ledger.settle(s, j.user_id, j.id, j.reserved_credits, charged)
                j.status, j.output_asset_id, j.charged_credits = "succeeded", out.id, charged
                j.actual_cost_micro, j.finished_at = actual_cost, now()
            self._event(job_id, f"terminé : {charged} crédits débités, {job.reserved_credits - charged} libérés",
                        {"actual_cost_micro": actual_cost})
        except Exception as e:  # tout échec → remboursement intégral
            msg = str(e) if isinstance(e, (ProviderError, media.MediaError, ServiceError)) else "erreur interne"
            with self.db.session() as s:
                j = s.get(Job, job_id)
                ledger.settle(s, j.user_id, j.id, j.reserved_credits, 0)
                j.status, j.error, j.actual_cost_micro, j.finished_at = "failed", msg, actual_cost, now()
            self._event(job_id, f"échec : {msg} — {job.reserved_credits} crédits remboursés",
                        {"trace": traceback.format_exc()[-2000:]} if not isinstance(e, ProviderError) else {}, "error")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _price_for_actual(steps: list[dict], actual_cost: int, opt: dict) -> int:
        if opt.get("cache_hit"):
            return 0
        # Le prix suit le coût réel au prorata du devis, sans jamais dépasser la réservation.
        est = sum(s["cost_micro"] for s in steps)
        quoted = sum(s["price_credits"] for s in steps)
        if est <= 0:
            return quoted
        return -(-quoted * actual_cost // est)  # arrondi au crédit supérieur, explicite

    def _execute(self, job: Job, src: Asset, q: Quote, work: Path) -> tuple[Path, int]:
        src_path = self.storage.path(src.storage_key)
        start, end = q.range_start_s, q.range_end_s
        partial = start > 0.05 or end < src.duration_s - 0.05
        seg_steps = [(i, s) for i, s in enumerate(job.steps) if not s["capability"].startswith("format.")]
        fmt_steps = [(i, s) for i, s in enumerate(job.steps) if s["capability"].startswith("format.")]
        total_cost = 0

        current = src_path
        pre = post = None
        if seg_steps and partial:
            seg = work / "segment.mp4"
            media.cut(src_path, seg, start, end)
            if start > 0.05:
                pre = work / "pre.mp4"
                media.cut(src_path, pre, 0, start)
            if end < src.duration_s - 0.05:
                post = work / "post.mp4"
                media.cut(src_path, post, end, src.duration_s)
            current = seg
            self._event(job.id, f"segment {start:.2f}s → {end:.2f}s isolé ; le reste de la vidéo est conservé intact")

        for i, st in seg_steps:
            current, cost = self._run_step(job, i, st, current, work)
            total_cost += cost

        if seg_steps and partial:
            fps = src.fps if src.fps > 0 else 30.0
            parts = []
            for name, p in (("pre", pre), ("seg", current), ("post", post)):
                if p is not None:
                    n = work / f"n_{name}.mp4"
                    media.normalize(p, n, src.width, src.height, fps)
                    parts.append(n)
            joined = work / "joined.mp4"
            media.concat(parts, joined, work, total_s=self._expected_total(job, src, start, end))
            current = joined
            self._event(job.id, "segment réintégré dans la vidéo complète")

        for i, st in fmt_steps:
            current, cost = self._run_step(job, i, st, current, work)
            total_cost += cost

        if current == src_path:  # aucune étape n'a produit de fichier (cas impossible en pratique)
            raise ServiceError("aucune opération exécutée")
        return current, total_cost

    @staticmethod
    def _expected_total(job: Job, src: Asset, start: float, end: float) -> float | None:
        """Durée attendue après réassemblage ; None si une étape modifie la vitesse."""
        if any(s["capability"].startswith("speed.") for s in job.steps):
            return None
        return src.duration_s

    def _run_step(self, job: Job, index: int, st: dict, inp: Path, work: Path) -> tuple[Path, int]:
        engine = self.registry.get(st["engine_id"])
        reason = engine.unavailable_reason(self.settings)
        if reason:
            raise ProviderError(f"moteur {engine.id} devenu indisponible : {reason}")
        out = work / f"step{index}.mp4"
        key = f"{job.id}:step:{index}"
        input_url = None
        if self.settings.public_base_url and engine.paid:
            tmp = self._store_asset(job.user_id, inp, f"intermediate_{index}.mp4", media.probe(inp), parent=None,
                                    job_id=job.id, label="(intermédiaire)")
            exp, sig = signing.sign(self.settings.secret_key, tmp.id, ttl_s=3600)
            input_url = f"{self.settings.public_base_url}/files/{tmp.id}?exp={exp}&sig={sig}"
        with self.db.session() as s:
            call = ProviderCall(job_id=job.id, step_index=index, engine_id=engine.id, idempotency_key=key,
                                status="running", estimated_cost_micro=st["cost_micro"])
            s.add(call)
            s.flush()
            call_id = call.id
        self._event(job.id, f"étape {index + 1} : {st['label']} via {engine.display_name}")
        t0 = time.monotonic()
        ctx = StepContext(engine=engine, capability=st["capability"], input_path=inp, output_path=out,
                          prompt=st.get("prompt", ""), duration_s=float(st["duration_s"]), idempotency_key=key,
                          api_key=self.settings.provider_key(engine.provider), input_url=input_url,
                          log=lambda m, d: self._event(job.id, m, d))
        try:
            res = self.adapters[engine.adapter].run(ctx)
        except Exception as e:
            with self.db.session() as s:
                c = s.get(ProviderCall, call_id)
                c.status, c.error, c.duration_ms = "failed", str(e)[:2000], int((time.monotonic() - t0) * 1000)
            raise
        if not out.exists() or out.stat().st_size == 0:
            raise ProviderError("le moteur n'a produit aucun fichier")
        with self.db.session() as s:
            c = s.get(ProviderCall, call_id)
            c.status, c.actual_cost_micro, c.external_id = "succeeded", res.actual_cost_micro, res.external_id
            c.duration_ms = int((time.monotonic() - t0) * 1000)
        return out, res.actual_cost_micro

    def _cache_put(self, key: str, path: Path) -> None:
        skey = f"cache/{key[:2]}/{key}.mp4"
        self.storage.put_file(skey, path)
        with self.db.session() as s:
            if not s.execute(select(RenderCache).where(RenderCache.cache_key == key)).scalar_one_or_none():
                s.add(RenderCache(cache_key=key, storage_key=skey))

    def _from_cache(self, key: str, work: Path) -> Path:
        with self.db.session() as s:
            hit = s.execute(select(RenderCache).where(RenderCache.cache_key == key)).scalar_one()
        dst = work / "cached.mp4"
        shutil.copyfile(self.storage.path(hit.storage_key), dst)
        return dst

    # ------------------------------------------------------------------ worker
    def recover_stale(self) -> int:
        """Au démarrage : une tâche restée « running » est échouée et remboursée (état fournisseur inconnu)."""
        with self.db.session() as s:
            stale = s.execute(select(Job).where(Job.status == "running")).scalars().all()
            for j in stale:
                ledger.settle(s, j.user_id, j.id, j.reserved_credits, 0)
                j.status, j.error, j.finished_at = "failed", "interrompue par un redémarrage du serveur", now()
                s.add(JobEvent(job_id=j.id, level="error", message="tâche interrompue : crédits remboursés", data={}))
            return len(stale)

    def process_pending(self) -> int:
        n = 0
        while (job_id := self.claim_next()) is not None:
            self.run_job(job_id)
            n += 1
        return n

    def start_worker(self) -> None:
        if self._worker:
            return
        self.recover_stale()

        def loop():
            while not self._stop.is_set():
                if self.process_pending() == 0:
                    self._stop.wait(0.5)

        self._worker = threading.Thread(target=loop, name="studio-worker", daemon=True)
        self._worker.start()

    def stop_worker(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=10)
            self._worker = None
