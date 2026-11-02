"use strict";
// WebRTC minimal WHIP (envoi) / WHEP (lecture) — partagé par la console et la page OBS.
let ICE = [{ urls: "stun:stun.l.google.com:19302" }, { urls: "stun:stun1.l.google.com:19302" }];
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

function gatherIce(pc, timeoutMs = 2000) {
  return new Promise((resolve) => {
    if (pc.iceGatheringState === "complete") return resolve();
    const t = setTimeout(resolve, timeoutMs);
    pc.addEventListener("icegatheringstatechange", () => {
      if (pc.iceGatheringState === "complete") { clearTimeout(t); resolve(); }
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

async function whipPublish(url, stream, headers) {
  const pc = new RTCPeerConnection({ iceServers: ICE });
  const track = stream.getVideoTracks()[0];
  track.contentHint = "motion";
  const tr = pc.addTransceiver(track, { direction: "sendonly", sendEncodings: [{ maxBitrate: 3_000_000 }] });
  preferH264(tr);
  const mic = stream.getAudioTracks()[0];  // le son du micro part avec la vidéo (diffusion directe)
  if (mic) pc.addTransceiver(mic, { direction: "sendonly" });
  await pc.setLocalDescription(await pc.createOffer());
  await gatherIce(pc);
  const answer = await postSdp(url, pc.localDescription.sdp, headers);
  await pc.setRemoteDescription({ type: "answer", sdp: answer });
  return pc;
}

async function whepPlay(url, videoEl, headers) {
  const pc = new RTCPeerConnection({ iceServers: ICE });
  preferH264(pc.addTransceiver("video", { direction: "recvonly" }));
  pc.ontrack = (e) => { videoEl.srcObject = e.streams[0] || new MediaStream([e.track]); videoEl.play().catch(() => {}); };
  await pc.setLocalDescription(await pc.createOffer());
  await gatherIce(pc);
  const answer = await postSdp(url, pc.localDescription.sdp, headers);
  await pc.setRemoteDescription({ type: "answer", sdp: answer });
  return pc;
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
