"""API HTTP (FastAPI) + interface web statique."""
from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .models import User
from .service import ServiceError, Studio

STATIC = Path(__file__).parent / "static"


class Credentials(BaseModel):
    email: str
    password: str
    invite: str = ""


class QuoteRequest(BaseModel):
    asset_id: str
    prompt: str = Field(max_length=1000)
    start_s: float | None = None
    end_s: float | None = None


class AcceptRequest(BaseModel):
    option_id: str


class TopupRequest(BaseModel):
    credits: int


def create_app(settings: Settings | None = None, studio: Studio | None = None) -> FastAPI:
    settings = settings or Settings()
    studio = studio or Studio(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if settings.run_worker:
            studio.start_worker()
        yield
        studio.stop_worker()

    app = FastAPI(title="AI STUDIO", version="0.1.0", lifespan=lifespan)
    app.state.studio = studio

    @app.exception_handler(ServiceError)
    async def _service_error(_req: Request, exc: ServiceError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    def current_user(authorization: str = Header(default="")) -> User:
        from .auth import user_for_token
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "authentification requise")
        with studio.db.session() as s:
            user = user_for_token(s, authorization[7:])
        if user is None:
            raise HTTPException(401, "session expirée")
        return user

    @app.get("/api/health")
    def health():
        from . import media
        return {"ok": True, "ffmpeg": media.available(), "paid_providers": settings.allow_paid_providers}

    @app.post("/api/auth/register")
    def register(c: Credentials):
        user, token = studio.register(c.email, c.password, c.invite)
        return {"token": token, "account": studio.account(user)}

    @app.post("/api/auth/login")
    def login(c: Credentials):
        user, token = studio.login(c.email, c.password)
        return {"token": token, "account": studio.account(user)}

    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        return studio.account(user)

    @app.get("/api/engines")
    def engines(_user: User = Depends(current_user)):
        return studio.registry.describe(settings)

    @app.post("/api/assets")
    def upload(file: UploadFile = File(...), user: User = Depends(current_user)):
        limit = settings.max_upload_mb * (1 << 20)
        with tempfile.NamedTemporaryFile(delete=False, dir=settings.data_dir, suffix=Path(file.filename or "").suffix) as tmp:
            written = 0
            while chunk := file.file.read(1 << 20):
                written += len(chunk)
                if written > limit:
                    tmp.close()
                    Path(tmp.name).unlink(missing_ok=True)
                    raise ServiceError(f"fichier trop lourd (max {settings.max_upload_mb} Mo)", 413)
                tmp.write(chunk)
        try:
            asset = studio.import_video(user, file.filename or "video.mp4", Path(tmp.name))
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        return studio.asset_view(asset)

    @app.get("/api/projects")
    def projects(user: User = Depends(current_user)):
        return studio.projects(user)

    @app.get("/api/assets/{asset_id}")
    def asset(asset_id: str, user: User = Depends(current_user)):
        return studio.asset_view(studio.get_asset(user, asset_id))

    @app.get("/files/{asset_id}")
    def file(asset_id: str, exp: int, sig: str, dl: int = 0):
        path, a = studio.file_for(asset_id, exp, sig)
        name = a.filename if a.filename.lower().endswith(".mp4") else Path(a.filename).stem + ".mp4"
        return FileResponse(path, media_type="video/mp4", filename=name if dl else None)

    @app.post("/api/quotes")
    def quote(req: QuoteRequest, user: User = Depends(current_user)):
        return studio.create_quote(user, req.asset_id, req.prompt, req.start_s, req.end_s)

    @app.post("/api/quotes/{quote_id}/accept")
    def accept(quote_id: str, req: AcceptRequest, user: User = Depends(current_user)):
        return studio.accept_quote(user, quote_id, req.option_id)

    @app.get("/api/jobs")
    def jobs(user: User = Depends(current_user)):
        return studio.list_jobs(user)

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str, user: User = Depends(current_user)):
        return studio.get_job(user, job_id)

    @app.get("/api/ledger")
    def transactions(user: User = Depends(current_user)):
        return studio.transactions(user)

    @app.get("/api/billing/packs")
    def packs(_user: User = Depends(current_user)):
        return studio.billing_packs()

    @app.post("/api/billing/checkout")
    def checkout(body: dict = Body(...), user: User = Depends(current_user)):
        return studio.billing_checkout(user, str(body.get("pack", "")))

    @app.post("/api/billing/webhook")
    async def stripe_webhook(request: Request):
        return studio.billing_webhook(await request.body(), request.headers.get("stripe-signature", ""))

    @app.post("/api/dev/credits")
    def dev_credits(req: TopupRequest, user: User = Depends(current_user)):
        return studio.dev_topup(user, req.credits)

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app

