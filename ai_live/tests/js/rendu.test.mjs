// Tests des calculs du rendu téléphone (rendu.js) : node tests/js/rendu.test.mjs
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const ctx = { console, Math, Float32Array, Uint8Array, Int8Array, Map };
vm.createContext(ctx);
vm.runInContext(readFileSync(new URL("../../live/static/rendu.js", import.meta.url), "utf8") +
  "\nthis.M={toLuma,half,blockSearch,blockFlow,MotionHistory,estimateLag,fallbackLag,renderTarget,canvasSize,MOTION};", ctx);
const { blockFlow, MotionHistory, estimateLag, fallbackLag, renderTarget, canvasSize, MOTION } = ctx.M;
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

// Historique : déplacement cumulé sur un intervalle
const h = new MotionHistory();
const one = { flow: new Float32Array(128).fill(1), gx: 1, gy: 1 };
for (let t = 33; t <= 330; t += 33) h.push(t, one);
assert.equal(h.displacement(100, 330)[0], 7);   // images à 132…330
assert.equal(h.pos[h.pos.length - 1].x, 10);

// Mesure du délai : l'IA reproduit le mouvement de la caméra avec 240 ms de retard
const cam = [], ai = [];
const X = (t) => 6 * Math.sin(t / 300) + 3 * Math.sin(t / 97);
for (let t = 0; t <= 4000; t += 33) cam.push({ t, x: X(t), y: 0.5 * X(t + 50) });
for (let t = 300; t <= 4000; t += 66) ai.push({ t, x: X(t - 240), y: 0.5 * X(t - 240 + 50) });
const r = estimateLag(cam, ai);
assert.ok(r && Math.abs(r.lag - 240) <= 20 && r.conf > 0.5, JSON.stringify(r));

// Caméra immobile : pas de mesure
assert.equal(estimateLag(cam.map((p) => ({ t: p.t, x: 0, y: 0 })), ai.map((p) => ({ t: p.t, x: 0, y: 0 }))), null);

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

console.log("rendu : tous les tests passent");
