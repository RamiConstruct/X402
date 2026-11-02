"""Test de bout en bout du moteur Daydream (vidéo → WHIP → IA → WHEP, changement de scène en cours).

Usage (sur une machine avec un vrai accès réseau, ex. le serveur) :
  DAYDREAM_API_KEY=... python ai_live/tools/check_daydream.py video.mp4 dossier_sortie
Affiche le délai de la 1re image IA, les débits envoyés/reçus et enregistre quelques images (PPM).
"""
import asyncio, os, sys, time
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer
from live.engine import EngineConfig, StreamEngine
from live.scene import Scene, SceneHistory
from live.commands import apply_command

async def gather(pc):
    if pc.iceGatheringState == "complete": return
    done = asyncio.Event()
    @pc.on("icegatheringstatechange")
    def _(): 
        if pc.iceGatheringState == "complete": done.set()
    await asyncio.wait_for(done.wait(), 15)

async def main(video, out):
    eng = StreamEngine(EngineConfig(name="dd", base_url="https://api.daydream.live", api_key=os.environ["DAYDREAM_API_KEY"]))
    scene = Scene()
    t0 = time.time(); d = await asyncio.to_thread(eng.create, scene); sid = d["id"]
    print(f"flux créé en {time.time()-t0:.1f}s")
    pub = RTCPeerConnection(); player = MediaPlayer(video, options={"stream_loop": "-1"})
    sent = []
    from aiortc import MediaStreamTrack
    class Count(MediaStreamTrack):
        kind = "video"
        def __init__(s, t): super().__init__(); s.t = t
        async def recv(s):
            f = await s.t.recv(); sent.append(time.time()); return f
    pub.addTrack(Count(player.video))
    await pub.setLocalDescription(await pub.createOffer()); await gather(pub)
    ans, whep = await asyncio.to_thread(eng.whip, d["whip_url"], pub.localDescription.sdp)
    await pub.setRemoteDescription(RTCSessionDescription(ans, "answer"))
    print("WHIP OK, whep:", bool(whep))
    sub = RTCPeerConnection(); sub.addTransceiver("video", direction="recvonly")
    frames = []; first = {}
    @sub.on("track")
    def on_track(tr):
        async def rd():
            while True:
                try: f = await tr.recv()
                except Exception: return
                first.setdefault("t", time.time()); frames.append(time.time())
                n = len(frames)
                if n in (30, 120, 300, 450):
                    a = f.to_ndarray(format="rgb24"); hh, ww = a.shape[:2]
                    open(f"{out}/ia_{n}.ppm", "wb").write(b"P6 %d %d 255\n" % (ww, hh) + a.tobytes())
        asyncio.ensure_future(rd())
    await sub.setLocalDescription(await sub.createOffer()); await gather(sub)
    t1 = time.time()
    sdp = await asyncio.to_thread(eng.whep, whep, sub.localDescription.sdp, 120, 0.5)
    await sub.setRemoteDescription(RTCSessionDescription(sdp, "answer"))
    for _ in range(60):
        if frames: break
        await asyncio.sleep(0.5)
    print(f"1re image IA {first.get('t', time.time())-t1:.1f}s après WHEP")
    await asyncio.sleep(8)
    h = SceneHistory(scene); res = apply_command(h, "transforme-moi en chevalier, décor château"); s2 = h.current
    print("commande:", res.ok, res.message[:80], "| prompt:", s2.prompt()[:100] if hasattr(s2, "prompt") else "")
    try: await asyncio.to_thread(eng.update, sid, s2); print("changement de scène OK")
    except Exception as e: print("changement de scène ERREUR", str(e)[:200])
    await asyncio.sleep(10)
    w = [t for t in frames if t > time.time() - 10]
    ws = [t for t in sent if t > time.time() - 10]; print(f"envoyées ~{len(ws)/10:.1f} i/s")
    print(f"images reçues: {len(frames)}, débit ~{len(w)/10:.1f} i/s sur les 10 dernières s")
    await pub.close(); await sub.close(); player.video.stop()
    await asyncio.to_thread(eng.delete, sid); print("flux supprimé")

asyncio.run(main(sys.argv[1], sys.argv[2]))
