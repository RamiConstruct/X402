// Tests de la logique du mode automatique (rtc.js), exécutés par Node : node tests/js/autotune.test.mjs
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const ctx = { console, setInterval, clearInterval, setTimeout, clearTimeout, performance };
vm.createContext(ctx);
vm.runInContext(readFileSync(new URL("../../live/static/rtc.js", import.meta.url), "utf8") + "\nthis.pickInitialMode=pickInitialMode;this.AutoTune=AutoTune;", ctx);
const { pickInitialMode, AutoTune } = ctx;

// Mode de départ selon le réseau
assert.equal(pickInitialMode({ rttMs: 40, downlinkMbps: 20 }), "qualite");
assert.equal(pickInitialMode({ rttMs: 90, downlinkMbps: 6 }), "equilibre");
assert.equal(pickInitialMode({ rttMs: 260, downlinkMbps: 1.5 }), "rapide");
assert.equal(pickInitialMode({ rttMs: 60, saveData: true }), "rapide");
assert.equal(pickInitialMode({}), "equilibre");

const good = { rtt: 50, loss: 0, upFps: 30, downFps: 25 };
const badNet = { rtt: 400, loss: 8, upFps: 18, downFps: 10 };
const slowAi = { rtt: 50, loss: 0, upFps: 30, downFps: 7 };

// Réseau faible pendant 3 mesures → baisse du débit d'envoi, sans changer de mode
let t = new AutoTune({ mode: "equilibre", now: () => 0 });
let acts = [];
for (let i = 0; i < 3; i++) acts.push(...t.feed(badNet));
assert.deepEqual(acts.filter((a) => a.type === "bitrate").map((a) => a.level), ["eco"]);
assert.equal(acts.some((a) => a.type === "mode"), false);
// Retour à la normale après 5 bonnes mesures
acts = [];
for (let i = 0; i < 5; i++) acts.push(...t.feed(good));
assert.deepEqual(acts.filter((a) => a.type === "bitrate").map((a) => a.level), ["normal"]);

// L'IA rame (réseau bon, peu d'images reçues) pendant 5 mesures → mode plus rapide
let clock = 100_000;
t = new AutoTune({ mode: "qualite", now: () => clock });
acts = [];
for (let i = 0; i < 5; i++) acts.push(...t.feed(slowAi));
assert.deepEqual(acts.filter((a) => a.type === "mode").map((a) => a.mode), ["equilibre"]);
// Pas de nouveau changement avant 60 s, même si ça rame encore
acts = [];
for (let i = 0; i < 10; i++) acts.push(...t.feed(slowAi));
assert.equal(acts.some((a) => a.type === "mode"), false);
// Après 60 s : passage en rapide, puis plus rien en dessous
clock += 61_000;
acts = [];
for (let i = 0; i < 5; i++) acts.push(...t.feed(slowAi));
assert.deepEqual(acts.filter((a) => a.type === "mode").map((a) => a.mode), ["rapide"]);
clock += 61_000;
acts = [];
for (let i = 0; i < 10; i++) acts.push(...t.feed(slowAi));
assert.equal(acts.some((a) => a.type === "mode"), false);

// Réseau mauvais + peu d'images : c'est le réseau, pas l'IA → aucun changement de mode
t = new AutoTune({ mode: "qualite", now: () => 0 });
acts = [];
for (let i = 0; i < 8; i++) acts.push(...t.feed(badNet));
assert.equal(acts.some((a) => a.type === "mode"), false);

// Diffusion en cours : changement de mode interdit (couperait le direct)
t = new AutoTune({ mode: "qualite", allowModeSwitch: false, now: () => 0 });
acts = [];
for (let i = 0; i < 8; i++) acts.push(...t.feed(slowAi));
assert.equal(acts.some((a) => a.type === "mode"), false);

// Pas de décision pendant le démarrage (aucune image reçue encore)
t = new AutoTune({ mode: "qualite", now: () => 0 });
acts = [];
for (let i = 0; i < 6; i++) acts.push(...t.feed({ rtt: 50, loss: 0, upFps: 30, downFps: 0 }));
assert.equal(acts.length, 0);

console.log("autotune : tous les tests passent");
