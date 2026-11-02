"use strict";
// WebRTC minimal WHIP (envoi) / WHEP (lecture) — partagé par la console et la page OBS.
// STUN Cloudflare en premier (anycast : réponse la plus proche), Google en secours.
let ICE = [{ urls: "stun:stun.cloudflare.com:3478" }, { urls: "stun:stun.l.google.com:19302" }];

// L'IA travaille en 512×512 : capturer directement en carré 512 évite d'envoyer (et d'encoder)
// 3,5 fois plus de pixels pour rien. Le navigateur recadre et réduit lui-même (crop-and-scale).
const AI_SIZE = 512;
function videoConstraints(extra = {}) {
  return { width: { ideal: AI_SIZE }, height: { ideal: AI_SIZE }, aspectRatio: { ideal: 1 },
           frameRate: { ideal: 30, max: 30 }, resizeMode: "crop-and-scale", ...extra };
}
// Serveurs TURN fournis par la console (indispensables avec un GPU loué derrière un NAT).
function setIceServers(extra) { if (Array.isArray(extra) && extra.length) ICE = [...ICE, ...extra]; }

function preferH264(transceiver) {
  try {
    const caps = RTCRtpSender.getCapabilities("video");
    const h264 = caps.codecs.filter((c) => c.mimeType.toLowerCase() === "video/h264");
    const rest = caps.codecs.filter((c) => c.mimeType.toLowerCase() !== "video/h264");
    if (h264.length && transceiver.setCodecPreferences) transceiver.setCodecPreferences([...h264, ...rest]);
  } catch {}
}

// WHIP sans « trickle » : on attend les candidats réseau, mais pas plus que nécessaire —
// dès qu'une adresse publique (srflx) ou un relais est trouvé, 150 ms de plus suffisent.
function gatherIce(pc, timeoutMs = 1200) {
  return new Promise((resolve) => {
    if (pc.iceGatheringState === "complete") return resolve();
    let done = false;
    const finish = () => { if (!done) { done = true; clearTimeout(t); resolve(); } };
    const t = setTimeout(finish, timeoutMs);
    pc.addEventListener("icegatheringstatechange", () => { if (pc.iceGatheringState === "complete") finish(); });
    pc.addEventListener("icecandidate", (e) => {
      if (e.candidate && /typ (srflx|relay)/.test(e.candidate.candidate)) setTimeout(finish, 150);
    });
  });
}

async function postSdp(url, sdp, headers = {}) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/sdp", ...headers }, body: sdp });
  if (!r.ok) {
    let msg = r.status + "";
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.text();
}

// opts.audio : n'envoyer le micro que s'il sert (diffusion directe) ; opts.maxBitrate : 1,5 Mbit/s
// suffisent largement pour du 512×512 à 30 i/s en H.264 (encodage matériel sur téléphone).
async function whipPublish(url, stream, headers, opts = {}) {
  const { audio = true, maxBitrate = 1_500_000 } = opts;
  const pc = new RTCPeerConnection({ iceServers: ICE, bundlePolicy: "max-bundle" });
  const track = stream.getVideoTracks()[0];
  track.contentHint = "motion";
  const tr = pc.addTransceiver(track, { direction: "sendonly",
    sendEncodings: [{ maxBitrate, maxFramerate: 30, priority: "high", networkPriority: "high" }] });
  preferH264(tr);
  const mic = audio ? stream.getAudioTracks()[0] : null;
  if (mic) pc.addTransceiver(mic, { direction: "sendonly" });
  await pc.setLocalDescription(await pc.createOffer());
  await gatherIce(pc);
  const answer = await postSdp(url, pc.localDescription.sdp, headers);
  await pc.setRemoteDescription({ type: "answer", sdp: answer });
  // En cas de réseau faible : garder la fluidité (30 i/s) et baisser la netteté plutôt que l'inverse.
  try {
    const p = tr.sender.getParameters();
    p.degradationPreference = "maintain-framerate";
    (p.encodings || []).forEach((e) => { e.maxBitrate = maxBitrate; e.maxFramerate = 30; });
    await tr.sender.setParameters(p);
  } catch {}
  return pc;
}

// Lecture au plus près du direct : tampon de gigue minimal (le navigateur l'augmente seul si le réseau saccade).
function lowLatency(receiver) {
  try { if ("jitterBufferTarget" in receiver) receiver.jitterBufferTarget = 0; } catch {}
  try { if ("playoutDelayHint" in receiver) receiver.playoutDelayHint = 0; } catch {}
}

async function whepPlay(url, videoEl, headers) {
  const pc = new RTCPeerConnection({ iceServers: ICE });
  preferH264(pc.addTransceiver("video", { direction: "recvonly" }));
  pc.ontrack = (e) => { lowLatency(e.receiver); videoEl.srcObject = e.streams[0] || new MediaStream([e.track]); videoEl.play().catch(() => {}); };
  await pc.setLocalDescription(await pc.createOffer());
  await gatherIce(pc);
  const answer = await postSdp(url, pc.localDescription.sdp, headers);
  await pc.setRemoteDescription({ type: "answer", sdp: answer });
  return pc;
}

// Mesures réseau toutes les 2 s : aller-retour (ms), envoi (kbit/s, i/s, résolution), réception (i/s),
// pertes (%) et retard ajouté par le tampon de lecture (ms). Sert à l'affichage et au diagnostic.
function netStats(pubPc, viewPc, onStats, everyMs = 2000) {
  let prev = {};
  return setInterval(async () => {
    const out = {};
    try {
      if (pubPc) (await pubPc.getStats()).forEach((r) => {
        if (r.type === "candidate-pair" && r.nominated && r.currentRoundTripTime != null) out.rtt = Math.round(r.currentRoundTripTime * 1000);
        if (r.type === "outbound-rtp" && r.kind === "video") {
          if (prev.bytes != null) out.upKbps = Math.round((r.bytesSent - prev.bytes) * 8 / (everyMs));
          prev.bytes = r.bytesSent; out.upFps = Math.round(r.framesPerSecond || 0);
          out.res = r.frameWidth ? `${r.frameWidth}×${r.frameHeight}` : undefined;
          out.limit = r.qualityLimitationReason && r.qualityLimitationReason !== "none" ? r.qualityLimitationReason : undefined;
        }
      });
      if (viewPc) (await viewPc.getStats()).forEach((r) => {
        if (r.type === "inbound-rtp" && r.kind === "video") {
          out.downFps = Math.round(r.framesPerSecond || 0);
          const lost = r.packetsLost - (prev.lost || 0), recv = r.packetsReceived - (prev.recv || 0);
          if (prev.recv != null && lost + recv > 0) out.loss = Math.round(100 * lost / (lost + recv));
          prev.lost = r.packetsLost; prev.recv = r.packetsReceived;
          if (r.jitterBufferEmittedCount) out.bufferMs = Math.round(1000 * r.jitterBufferDelay / r.jitterBufferEmittedCount);
        }
        if (out.rtt == null && r.type === "candidate-pair" && r.nominated && r.currentRoundTripTime != null) out.rtt = Math.round(r.currentRoundTripTime * 1000);
      });
    } catch {}
    onStats(out);
  }, everyMs);
}

// Qualité réseau en un mot (pour l'utilisateur) à partir des mesures.
function netGrade(s) {
  if (s.rtt == null && s.loss == null) return "";
  if ((s.loss ?? 0) >= 5 || (s.rtt ?? 0) >= 300) return "faible";
  if ((s.loss ?? 0) >= 2 || (s.rtt ?? 0) >= 150) return "moyen";
  return "bon";
}

function fpsMeter(videoEl, onFps) {
  let n = 0;
  const tick = () => { n++; videoEl.requestVideoFrameCallback(tick); };
  if (videoEl.requestVideoFrameCallback) videoEl.requestVideoFrameCallback(tick);
  return setInterval(() => { onFps(n); n = 0; }, 1000);
}

// ------------------------------------------------------------------ enregistrement d'essai (phase de test)
// Enregistre la sortie IA (+ le son du micro) sur l'appareil, sans rien publier.
function pickMime() {
  const c = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4;codecs=avc1,mp4a", "video/mp4"];
  return c.find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || "";
}
function makeRecorder(videoEl, micTrack) {
  let rec = null, chunks = [], t0 = 0;
  return {
    get recording() { return !!rec && rec.state === "recording"; },
    get seconds() { return rec ? Math.floor((Date.now() - t0) / 1000) : 0; },
    start() {
      const src = videoEl.srcObject;
      const v = src && src.getVideoTracks()[0];
      if (!v) throw new Error("pas encore d'image IA à enregistrer");
      if (!window.MediaRecorder) throw new Error("enregistrement non pris en charge par ce navigateur");
      const tracks = [v, ...(micTrack ? [micTrack] : [])];
      const mime = pickMime();
      rec = new MediaRecorder(new MediaStream(tracks), mime ? { mimeType: mime, videoBitsPerSecond: 4_000_000 } : undefined);
      chunks = []; t0 = Date.now();
      rec.ondataavailable = (e) => e.data && e.data.size && chunks.push(e.data);
      rec.start(1000);
    },
    stop() {
      return new Promise((resolve) => {
        if (!rec) return resolve(null);
        rec.onstop = () => {
          const type = rec.mimeType || "video/webm";
          const blob = new Blob(chunks, { type });
          const ext = type.includes("mp4") ? "mp4" : "webm";
          const d = new Date(), p = (n) => String(n).padStart(2, "0");
          const name = `essai-ai-live-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.${ext}`;
          const a = document.createElement("a");
          a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click();
          setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 5000);
          rec = null; resolve({ name, size: blob.size });
        };
        rec.stop();
      });
    },
  };
}
