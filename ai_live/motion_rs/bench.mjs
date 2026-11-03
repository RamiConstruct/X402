// Banc d'essai : blockFlow JavaScript (rendu.js) contre le module Rust/WebAssembly — node bench.mjs
import { readFileSync } from "node:fs";
import vm from "node:vm";
const ctx = { Math, Float32Array, Uint8Array, Int8Array, Map, console };
vm.createContext(ctx);
vm.runInContext(readFileSync(new URL("../live/static/rendu.js", import.meta.url), "utf8") + "\nthis.blockFlow=blockFlow;", ctx);
const { instance } = await WebAssembly.instantiate(readFileSync(new URL("../live/static/motion.wasm", import.meta.url)));
const w = instance.exports, mem = () => new Float32Array(w.memory.buffer);
const wasmFlow = (prev, cur) => {
  const m = mem(); m.set(prev, w.prev_ptr() / 4); m.set(cur, w.cur_ptr() / 4); w.flow();
  const o = mem().subarray(w.out_ptr() / 4, w.out_ptr() / 4 + 131); return { flow: o.slice(0, 128), gx: o[128], gy: o[129], valid: o[130] };
};
const N = 64;
const scene = (dx, dy, seed = 1) => { const a = new Float32Array(N * N);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) { const u = x - dx, v = y - dy;
    a[y * N + x] = 128 + 60 * Math.sin(u * 0.7 * seed) * Math.cos(v * 0.45) + 40 * Math.sin((u + 2 * v) * 0.31); } return a; };
const cases = [[0, 0], [2, 1], [-1, 3], [6, -5], [0.5, -0.5]];
let maxDiff = 0;
for (const [dx, dy] of cases) {
  const a = scene(0, 0), b = scene(dx, dy), j = ctx.blockFlow(a, b), r = wasmFlow(a, b);
  for (let k = 0; k < 128; k++) maxDiff = Math.max(maxDiff, Math.abs(j.flow[k] - r.flow[k]));
  console.log(`décalage (${dx},${dy}) : JS ${j.gx.toFixed(2)},${j.gy.toFixed(2)} | Rust ${r.gx.toFixed(2)},${r.gy.toFixed(2)} | blocs fiables ${j.valid}/${r.valid}`);
}
console.log("écart max entre les deux versions :", maxDiff.toExponential(2), "pixel");
const a = scene(0, 0), b = scene(3, -2), RUNS = 40;
for (let i = 0; i < 10; i++) { ctx.blockFlow(a, b); wasmFlow(a, b); }   // échauffement
let t = performance.now(); for (let i = 0; i < RUNS; i++) ctx.blockFlow(a, b); const js = (performance.now() - t) / RUNS;
t = performance.now(); for (let i = 0; i < RUNS; i++) wasmFlow(a, b); const rs = (performance.now() - t) / RUNS;
console.log(`temps par image : JavaScript ${js.toFixed(3)} ms | Rust/WebAssembly ${rs.toFixed(3)} ms | ×${(js / rs).toFixed(1)}`);
