// Tests des calculs du rendu téléphone (rendu.js) : node tests/js/rendu.test.mjs
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const ctx = { console, Math, Float32Array, Uint8Array, Int8Array, Map };
vm.createContext(ctx);
vm.runInContext(readFileSync(new URL("../../live/static/rendu.js", import.meta.url), "utf8") +
  "\nthis.M={maskToGrid,backgroundMotion,toLuma,half,blockSearch,blockFlow,MotionHistory,estimateLag,fallbackLag,renderTarget,canvasSize,MOTION};", ctx);
const { maskToGrid, backgroundMotion, blockFlow, MotionHistory, estimateLag, fallbackLag, renderTarget, canvasSize, MOTION } = ctx.M;
const N = MOTION.N;

// Image texturée déterministe, décalable de (dx, dy) pixels (contenu qui se déplace vers +dx, +dy).
function scene(dx = 0, dy = 0) {
  const img = new Float32Array(N * N);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const u = x - dx, v = y - dy;
    img[y * N + x] = 128 + 60 * Math.sin(u * 0.7) * Math.cos(v * 0.45) + 40 * Math.sin((u + 2 * v) * 0.31);
  }
  return img;
}

// Mouvement d'ensemble de 2 px à droite et 1 px vers le bas
let f = blockFlow(scene(0, 0), scene(2, 1));
assert.ok(f.valid > 40, "assez de blocs fiables");
assert.ok(Math.abs(f.gx - 2) < 0.3 && Math.abs(f.gy - 1) < 0.3, `global ${f.gx},${f.gy}`);

// Geste rapide (6 px entre deux images, au-delà de la recherche simple ±3) : suivi grâce aux deux niveaux
f = blockFlow(scene(0, 0), scene(6, -5));
assert.ok(Math.abs(f.gx - 6) < 0.6 && Math.abs(f.gy + 5) < 0.6, `rapide ${f.gx},${f.gy}`);

// Immobile → aucun mouvement
f = blockFlow(scene(), scene());
assert.ok(Math.abs(f.gx) < 0.05 && Math.abs(f.gy) < 0.05);

// Surface unie → aucun bloc fiable, mouvement nul
f = blockFlow(new Float32Array(N * N).fill(90), new Float32Array(N * N).fill(90));
assert.equal(f.valid, 0); assert.equal(f.gx, 0);

// Mouvement local : seule la moitié droite bouge (une main qui se lève)
const a = scene(), b = scene();
const moved = scene(0, -2);
for (let y = 0; y < N; y++) for (let x = N / 2; x < N; x++) b[y * N + x] = moved[y * N + x];
f = blockFlow(a, b);
const at = (i, j) => [f.flow[(j * 8 + i) * 2], f.flow[(j * 8 + i) * 2 + 1]];
assert.ok(Math.abs(at(1, 4)[1]) < 0.3, "côté gauche immobile");
assert.ok(Math.abs(at(6, 4)[1] + 2) < 0.4, `côté droit monte : ${at(6, 4)}`);

// Historique : déplacement cumulé sur un intervalle, positions par quart d'image
const h = new MotionHistory();
const one = { flow: new Float32Array(128).fill(1), gx: 1, gy: 1 };
for (let t = 33; t <= 330; t += 33) h.push(t, one);
assert.equal(h.displacement(100, 330).d[0], 7);   // images à 132…330
assert.deepEqual([...h.displacement(100, 330).bg], [0, 0]);   // pas de silhouette connue
assert.equal(h.pos[h.pos.length - 1].v[0], 10);

// Mesure du délai : l'IA reproduit le mouvement de la caméra avec 240 ms de retard
const X = (t) => 6 * Math.sin(t / 300) + 3 * Math.sin(t / 97);
const vec = (t) => Float32Array.from([X(t), 0.5 * X(t + 50), -X(t), 0, 0.3 * X(t), X(t - 40), 0, -X(t)]);
const cam = [], ai = [];
for (let t = 0; t <= 4000; t += 33) cam.push({ t, v: vec(t) });
for (let t = 300; t <= 4000; t += 66) ai.push({ t, v: vec(t - 240) });
const r = estimateLag(cam, ai);
assert.ok(r && Math.abs(r.lag - 240) <= 20 && r.conf > 0.5, JSON.stringify(r));

// Rotation pure (les quarts bougent en sens opposés, moyenne globale nulle) : délai quand même mesuré
const rot = (t) => { const a = X(t); return Float32Array.from([a, -a, a, a, -a, -a, -a, a]); };
const r2 = estimateLag(cam.map((p) => ({ t: p.t, v: rot(p.t) })), ai.map((p) => ({ t: p.t, v: rot(p.t - 240) })));
assert.ok(r2 && Math.abs(r2.lag - 240) <= 20, "rotation " + JSON.stringify(r2));

// Caméra immobile : pas de mesure
const still = (s) => s.map((p) => ({ t: p.t, v: new Float32Array(8) }));
assert.equal(estimateLag(still(cam), still(ai)), null);

// Silhouette : masque 256×256 (personne au centre) → grille 64×64 adoucie
const conf = new Float32Array(256 * 256);
for (let y = 64; y < 192; y++) for (let x = 96; x < 160; x++) conf[y * 256 + x] = 1;
const gm = maskToGrid(conf, 256, 256);
assert.ok(gm[32 * 64 + 32] > 0.99 && gm[2 * 64 + 2] === 0, "centre = personne, coin = fond");
assert.ok(gm[32 * 64 + 23] > 0 && gm[32 * 64 + 23] < 1, "bord adouci");
// Mouvement du fond : la caméra glisse de 2 px, la personne (au centre) lève la main de −3 px
const fl = new Float32Array(128);
for (let j = 0; j < 8; j++) for (let i = 0; i < 8; i++) { const k = (j * 8 + i) * 2, inP = i >= 3 && i <= 4 && j >= 2 && j <= 5;
  fl[k] = 2; fl[k + 1] = inP ? -3 : 0; }
assert.deepEqual([...backgroundMotion(fl, gm)], [2, 0]);
// Historique avec mouvement du fond
const h2 = new MotionHistory(); h2.push(10, one, [1, -1]); h2.push(20, one, [1, -1]);
assert.deepEqual([...h2.displacement(0, 20).bg], [2, -2]);

// Délai de secours
assert.equal(fallbackLag({ rtt: 100, bufferMs: 20 }), 210);
assert.equal(fallbackLag({}), 270);

// Définition visée
assert.equal(renderTarget("auto", { shortPx: 1170 }), 1080);
assert.equal(renderTarget("auto", { shortPx: 1170, saveData: true }), 720);
assert.equal(renderTarget("720", { shortPx: 1170 }), 720);
assert.equal(renderTarget("1080", { shortPx: 750 }), 750);        // jamais plus que l'écran
assert.deepEqual({ ...canvasSize(390, 844, 3, 1080) }, { w: 1080, h: 2337 });
assert.deepEqual({ ...canvasSize(390, 844, 1, 1080) }, { w: 390, h: 844 }); // pas d'agrandissement inutile

// Module Rust/WebAssembly : mêmes résultats que la version JavaScript
const { instance } = await WebAssembly.instantiate(readFileSync(new URL("../../live/static/motion.wasm", import.meta.url)));
const w = instance.exports;
for (const [dx, dy] of [[0, 0], [2, 1], [-1, 3], [6, -5]]) {
  const p = scene(0, 0), c = scene(dx, dy), js = blockFlow(p, c);
  const m = new Float32Array(w.memory.buffer); m.set(p, w.prev_ptr() / 4); m.set(c, w.cur_ptr() / 4); w.flow();
  const o = new Float32Array(w.memory.buffer, w.out_ptr(), 131);
  for (let k = 0; k < 128; k++) assert.ok(Math.abs(o[k] - js.flow[k]) < 1e-4, `wasm ≠ js (${dx},${dy}) bloc ${k}`);
  assert.ok(Math.abs(o[128] - js.gx) < 1e-4 && o[130] === js.valid);
}

console.log("rendu : tous les tests passent");
