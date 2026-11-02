"use strict";
// WebRTC minimal WHIP (envoi) / WHEP (lecture) — partagé par la console et la page OBS.
const ICE = [{ urls: "stun:stun.l.google.com:19302" }, { urls: "stun:stun1.l.google.com:19302" }];

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
