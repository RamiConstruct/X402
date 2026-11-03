"use strict";
// Rendu côté téléphone de l'image IA :
//  1. agrandissement jusqu'en 1080p (interpolation bicubique + renforcement adaptatif des détails), calculé
//     par la carte graphique du téléphone (WebGL2), donc sans frais serveur ;
//  2. « fluidité » : prédiction du mouvement. Le téléphone mesure en continu le mouvement de la caméra
//     (champ de vecteurs 8×8 sur une image réduite 64×64) et déforme la dernière image IA reçue selon le
//     mouvement survenu depuis la prise de vue correspondante. Le délai caméra → image IA est mesuré en
//     comparant le mouvement de la caméra et celui de l'image IA (corrélation), avec une estimation réseau
//     en secours. Résultat : geste répercuté sans attendre l'IA, et images intermédiaires entre deux images IA.

const MOTION = { N: 64, G: 8, R: 3 };   // image d'analyse N×N, grille G×G, recherche ±R pixels par image

// ------------------------------------------------------------------ calculs purs (testés sous Node)
function toLuma(rgba, n) {
  const out = new Float32Array(n * n);
  for (let i = 0, j = 0; i < out.length; i++, j += 4) out[i] = 0.299 * rgba[j] + 0.587 * rgba[j + 1] + 0.114 * rgba[j + 2];
  return out;
}

// Mouvement de `prev` vers `cur` par blocs : pour chaque bloc, le décalage d (pixels) qui minimise
// Σ|cur(x) − prev(x − d)|. Blocs sans texture ou ambigus → interpolés depuis leurs voisins.
// Recherche en deux niveaux : d'abord sur l'image réduite de moitié (mouvements jusqu'à ±2R), puis
// affinage autour de ce résultat en pleine résolution — un geste rapide ou une image sautée reste suivi.
// Retourne { flow: Float32Array(G*G*2) en pixels, gx, gy (moyenne sur l'image), valid (blocs fiables) }.
function half(img, n) {
  const m = n >> 1, out = new Float32Array(m * m);
  for (let y = 0; y < m; y++) for (let x = 0; x < m; x++) {
    const i = 2 * y * n + 2 * x; out[y * m + x] = (img[i] + img[i + 1] + img[i + n] + img[i + n + 1]) / 4;
  }
  return out;
}
function blockFlow(prev, cur, n = MOTION.N, g = MOTION.G, r = MOTION.R) {
  if (n < 64) return blockSearch(prev, cur, n, g, r, null);
  const coarse = blockSearch(half(prev, n), half(cur, n), n >> 1, g, r, null);
  const init = new Int8Array(g * g * 2);
  for (let k = 0; k < init.length; k++) init[k] = Math.round(2 * coarse.flow[k]);
  return blockSearch(prev, cur, n, g, 2, init);
}
function blockSearch(prev, cur, n, g, r, init) {
  const b = n / g, flow = new Float32Array(g * g * 2), ok = new Uint8Array(g * g);
  const at = (img, x, y) => img[Math.min(n - 1, Math.max(0, y)) * n + Math.min(n - 1, Math.max(0, x))];
  const sad = (bx, by, dx, dy) => {
    let s = 0;
    for (let y = by; y < by + b; y++) for (let x = bx; x < bx + b; x++) s += Math.abs(cur[y * n + x] - at(prev, x - dx, y - dy));
    return s;
  };
  for (let j = 0; j < g; j++) for (let i = 0; i < g; i++) {
    const bx = i * b, by = j * b;
    let m = 0, m2 = 0;
    for (let y = by; y < by + b; y++) for (let x = bx; x < bx + b; x++) { const v = cur[y * n + x]; m += v; m2 += v * v; }
    m /= b * b;
    if (m2 / (b * b) - m * m < 16) continue;            // écart-type < 4 : surface unie, mouvement invisible
    const costs = new Map(), k0 = (j * g + i) * 2;
    const ix = init ? init[k0] : 0, iy = init ? init[k0 + 1] : 0;
    let best = Infinity, bdx = 0, bdy = 0;
    const scan = (cx0, cy0, rr) => {
      for (let dy = cy0 - rr; dy <= cy0 + rr; dy++) for (let dx = cx0 - rr; dx <= cx0 + rr; dx++) {
        const key = dx + "," + dy; if (costs.has(key)) continue;
        const c = sad(bx, by, dx, dy); costs.set(key, c);
        if (c < best) { best = c; bdx = dx; bdy = dy; }
      }
    };
    scan(0, 0, MOTION.R);                                // petits mouvements : toujours cherchés autour de 0
    if (ix || iy) scan(ix, iy, r);                       // grands mouvements : autour de l'estimation grossière
    const zero = costs.get("0,0");
    if (zero <= best * 1.04 + b * b * 0.5) { ok[j * g + i] = 1; continue; }   // immobile ou ambigu → 0
    // Affinage sous le pixel : parabole sur les coûts voisins.
    const sub = (cm, c0, cp) => { const den = cm - 2 * c0 + cp; return den > 0 ? Math.max(-0.5, Math.min(0.5, (cm - cp) / (2 * den))) : 0; };
    const cx = (dx) => costs.get(dx + "," + bdy), cy = (dy) => costs.get(bdx + "," + dy);
    const has = (dx, dy) => costs.has(dx + "," + dy);
    const fx = has(bdx - 1, bdy) && has(bdx + 1, bdy) ? sub(cx(bdx - 1), best, cx(bdx + 1)) : 0;
    const fy = has(bdx, bdy - 1) && has(bdx, bdy + 1) ? sub(cy(bdy - 1), best, cy(bdy + 1)) : 0;
    flow[(j * g + i) * 2] = bdx + fx; flow[(j * g + i) * 2 + 1] = bdy + fy; ok[j * g + i] = 1;
  }
  // Blocs non fiables : moyenne des voisins fiables (sinon 0). Puis médiane 3×3 contre les valeurs aberrantes.
  const filled = new Float32Array(flow);
  for (let k = 0; k < g * g; k++) {
    if (ok[k]) continue;
    const i = k % g, j = (k / g) | 0; let sx = 0, sy = 0, c = 0;
    for (let v = -1; v <= 1; v++) for (let u = -1; u <= 1; u++) {
      const ii = i + u, jj = j + v; if (ii < 0 || jj < 0 || ii >= g || jj >= g || !ok[jj * g + ii]) continue;
      sx += flow[(jj * g + ii) * 2]; sy += flow[(jj * g + ii) * 2 + 1]; c++;
    }
    if (c) { filled[k * 2] = sx / c; filled[k * 2 + 1] = sy / c; }
  }
  const out = new Float32Array(g * g * 2), med = (a) => { a.sort((x, y) => x - y); return a[a.length >> 1]; };
  let gx = 0, gy = 0, valid = 0;
  for (let j = 0; j < g; j++) for (let i = 0; i < g; i++) {
    const ax = [], ay = [];
    for (let v = -1; v <= 1; v++) for (let u = -1; u <= 1; u++) {
      const ii = i + u, jj = j + v; if (ii < 0 || jj < 0 || ii >= g || jj >= g) continue;
      ax.push(filled[(jj * g + ii) * 2]); ay.push(filled[(jj * g + ii) * 2 + 1]);
    }
    const k = j * g + i; out[k * 2] = med(ax); out[k * 2 + 1] = med(ay);
    gx += out[k * 2]; gy += out[k * 2 + 1]; if (ok[k]) valid++;
  }
  // Moyenne sur toute l'image : un geste local (main, visage) reste visible dans le signal global.
  return { flow: out, gx: gx / (g * g), gy: gy / (g * g), valid };
}

// Même calcul en Rust compilé en WebAssembly (motion_rs/, ~9× plus rapide) ; blockFlow reste le secours.
async function loadMotionWasm(url = "/motion.wasm?v=67084585") {
  try {
    const bytes = await (await fetch(url)).arrayBuffer();
    const { instance } = await WebAssembly.instantiate(bytes);
    const w = instance.exports, n2 = MOTION.N * MOTION.N, g2 = MOTION.G * MOTION.G * 2;
    return (prev, cur) => {
      const m = new Float32Array(w.memory.buffer);
      m.set(prev, w.prev_ptr() / 4); m.set(cur, w.cur_ptr() / 4); w.flow();
      const o = new Float32Array(w.memory.buffer, w.out_ptr(), g2 + 3);
      return { flow: o.slice(0, g2), gx: o[g2], gy: o[g2 + 1], valid: o[g2 + 2] };
    };
  } catch (e) { return null; }
}

// Historique des mouvements mesurés (horodatés) : déplacement cumulé entre deux instants,
// et position globale cumulée (pour mesurer le délai).
// Mouvement moyen de chaque quart d'image [x0, y0, x1, y1, x2, y2, x3, y3] : une rotation ou un geste
// local, qui s'annulent dans la moyenne globale, restent visibles par quart.
function quadMeans(flow, g = MOTION.G) {
  const q = new Float32Array(8), h = g >> 1, n = h * h;
  for (let j = 0; j < g; j++) for (let i = 0; i < g; i++) {
    const k = (j >= h ? 2 : 0) + (i >= h ? 1 : 0), b = (j * g + i) * 2;
    q[k * 2] += flow[b] / n; q[k * 2 + 1] += flow[b + 1] / n;
  }
  return q;
}

class MotionHistory {
  constructor(g = MOTION.G, keepMs = 1500) { this.g = g; this.keep = keepMs; this.items = []; this.V = new Float32Array(8); this.pos = []; }
  push(ts, f) {
    const q = quadMeans(f.flow, this.g);
    for (let k = 0; k < 8; k++) this.V[k] += q[k];
    this.items.push({ ts, flow: f.flow }); this.pos.push({ t: ts, v: Float32Array.from(this.V) });
    while (this.items.length && this.items[0].ts < ts - this.keep) this.items.shift();
    while (this.pos.length > 2 && this.pos[0].t < ts - 4000) this.pos.shift();
  }
  get last() { return this.items.length ? this.items[this.items.length - 1].ts : 0; }
  // Somme des mouvements des images prises dans ]from, to] — en pixels de l'image d'analyse.
  displacement(from, to) {
    const d = new Float32Array(this.g * this.g * 2);
    for (const it of this.items) if (it.ts > from && it.ts <= to) for (let k = 0; k < d.length; k++) d[k] += it.flow[k];
    return d;
  }
}

// Position cumulée interpolée à l'instant t (série triée {t, v}).
function posAt(s, t) {
  if (t <= s[0].t) return s[0].v;
  if (t >= s[s.length - 1].t) return s[s.length - 1].v;
  let lo = 0, hi = s.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (s[m].t <= t) lo = m; else hi = m; }
  const a = s[lo], b = s[hi], f = (t - a.t) / (b.t - a.t || 1), out = new Float32Array(a.v.length);
  for (let k = 0; k < out.length; k++) out[k] = a.v[k] + (b.v[k] - a.v[k]) * f;
  return out;
}
// Écart moyen par quart entre deux mouvements (vecteurs de 8 valeurs : 4 quarts × x, y).
function quadDist(a1, a2, c1, c2) {
  let e = 0;
  for (let k = 0; k < a1.length; k += 2) e += Math.hypot((a2[k] - a1[k]) - (c2[k] - c1[k]), (a2[k + 1] - a1[k + 1]) - (c2[k + 1] - c1[k + 1]));
  return e / (a1.length / 2);
}

// Délai caméra → image IA : le décalage temporel qui superpose le mieux les mouvements de l'image IA
// à ceux de la caméra (comparés par quart d'image). Retourne { lag (ms), conf (0–1) } ou null s'il n'y a
// pas assez de mouvement ou si aucun décalage ne se détache nettement.
function estimateLag(cam, ai, { maxLag = 900, step = 10, win = 120, span = 3000 } = {}) {
  if (cam.length < 10 || ai.length < 6) return null;
  const tEnd = ai[ai.length - 1].t, samples = ai.filter((p) => p.t > tEnd - span && p.t - win > ai[0].t);
  if (samples.length < 5) return null;
  const zero = new Float32Array(cam[0].v.length);
  let energy = 0;
  for (const p of samples) energy += quadDist(zero, zero, posAt(cam, p.t - win), posAt(cam, p.t));
  if (energy / samples.length < 0.12) return null;      // presque immobile : rien à mesurer
  // Mouvements de l'image IA, calculés une fois.
  const aiMoves = samples.map((p) => [p.t, posAt(ai, p.t - win), posAt(ai, p.t)]);
  let best = Infinity, bestLag = 0, sum = 0, n = 0;
  for (let lag = 0; lag <= maxLag; lag += step) {
    let e = 0, c = 0;
    for (const [t, a1, a2] of aiMoves) {
      const t0 = t - lag; if (t0 - win < cam[0].t) continue;
      e += quadDist(a1, a2, posAt(cam, t0 - win), posAt(cam, t0)); c++;
    }
    if (c < 5) continue;
    e /= c; sum += e; n++;
    if (e < best) { best = e; bestLag = lag; }
  }
  if (!n) return null;
  return { lag: bestLag, conf: Math.max(0, Math.min(1, 1 - best / (sum / n || 1))) };
}

// Délai de secours tant qu'aucune mesure fiable : aller-retour réseau + tampon de lecture + calcul + images.
function fallbackLag(net = {}) { return Math.min(900, (net.rtt ?? 150) + (net.bufferMs ?? 30) + 90); }

// Définition visée (côté court en pixels) : préférence de l'utilisateur, plafonnée par l'écran.
function renderTarget(pref, { shortPx = 1080, saveData = false } = {}) {
  const p = pref === "auto" ? (saveData ? 720 : 1080) : Number(pref) || 1080;
  return Math.max(240, Math.min(p, Math.max(480, shortPx)));
}
// Taille du canevas pour une zone d'affichage cssW×cssH : côté court = target (sans dépasser l'écran réel).
function canvasSize(cssW, cssH, dpr, target) {
  const nw = cssW * dpr, nh = cssH * dpr, s = Math.min(1, target / Math.min(nw, nh));
  return { w: Math.max(2, Math.round(nw * s)), h: Math.max(2, Math.round(nh * s)) };
}

// ------------------------------------------------------------------ rendu WebGL2 (navigateur)
const VS = `#version 300 es
in vec2 p; out vec2 v;
void main(){ v = vec2(p.x * 0.5 + 0.5, 0.5 - p.y * 0.5); gl_Position = vec4(p, 0.0, 1.0); }`;
const FS = `#version 300 es
precision highp float;
in vec2 v; out vec4 o;
uniform sampler2D u_img, u_flow;
uniform vec2 u_tex, u_scale, u_off;
uniform float u_sharp, u_warp;
vec3 px(vec2 uv){ return texture(u_img, uv).rgb; }
// Bicubique Catmull-Rom en 9 lectures filtrées.
vec3 bicubic(vec2 uv){
  vec2 sz = 1.0 / u_tex, p = uv * sz, t1 = floor(p - 0.5) + 0.5, f = p - t1;
  vec2 w0 = f * (-0.5 + f * (1.0 - 0.5 * f)), w1 = 1.0 + f * f * (-2.5 + 1.5 * f);
  vec2 w2 = f * (0.5 + f * (2.0 - 1.5 * f)), w3 = f * f * (-0.5 + 0.5 * f);
  vec2 w12 = w1 + w2, o12 = w2 / w12;
  vec2 a = (t1 - 1.0) * u_tex, b = (t1 + o12) * u_tex, c = (t1 + 2.0) * u_tex;
  return px(vec2(a.x, a.y)) * w0.x * w0.y + px(vec2(b.x, a.y)) * w12.x * w0.y + px(vec2(c.x, a.y)) * w3.x * w0.y
       + px(vec2(a.x, b.y)) * w0.x * w12.y + px(b) * w12.x * w12.y + px(vec2(c.x, b.y)) * w3.x * w12.y
       + px(vec2(a.x, c.y)) * w0.x * w3.y + px(vec2(b.x, c.y)) * w12.x * w3.y + px(vec2(c.x, c.y)) * w3.x * w3.y;
}
void main(){
  vec2 uv = v * u_scale + u_off;
  uv -= texture(u_flow, uv).xy * u_warp;                 // prédiction du mouvement
  uv = clamp(uv, u_tex * 0.5, 1.0 - u_tex * 0.5);
  vec3 c = clamp(bicubic(uv), 0.0, 1.0);
  // Renforcement adaptatif (type CAS) : fort sur les zones douces, faible sur les contours déjà nets.
  vec3 n = px(uv - vec2(0.0, u_tex.y)), s = px(uv + vec2(0.0, u_tex.y)), e = px(uv + vec2(u_tex.x, 0.0)), w = px(uv - vec2(u_tex.x, 0.0));
  vec3 mn = min(c, min(min(n, s), min(e, w))), mx = max(c, max(max(n, s), max(e, w)));
  vec3 amp = sqrt(clamp(min(mn, 1.0 - mx) / max(mx, vec3(1e-4)), 0.0, 1.0));
  o = vec4(clamp(c + (c - (n + s + e + w) * 0.25) * amp * u_sharp, 0.0, 1.0), 1.0);
}`;

class Rendu {
  // opts : { canvas, ai (vidéo IA), cam (vidéo caméra), res: "auto"|"1080"|"720"|"480", fluid: bool, onInfo(info) }
  constructor(opts) {
    Object.assign(this, { res: "auto", fluid: true, onInfo: () => {} }, opts);
    const gl = this.canvas.getContext("webgl2", { alpha: false, antialias: false, desynchronized: true, preserveDrawingBuffer: false });
    if (!gl) throw new Error("WebGL2 indisponible");
    this.gl = gl;
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    const pr = gl.createProgram();
    gl.attachShader(pr, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(pr);
    if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(pr));
    gl.useProgram(pr); this.pr = pr;
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(pr, "p"); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const tex = (unit) => { const t = gl.createTexture(); gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, t);
      for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
      return t; };
    this.texImg = tex(0);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 255]));
    this.texFlow = tex(1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RG16F, MOTION.G, MOTION.G, 0, gl.RG, gl.FLOAT, new Float32Array(MOTION.G * MOTION.G * 2));
    this.u = {}; for (const n of ["u_img", "u_flow", "u_tex", "u_scale", "u_off", "u_sharp", "u_warp"]) this.u[n] = gl.getUniformLocation(pr, n);
    gl.uniform1i(this.u.u_img, 0); gl.uniform1i(this.u.u_flow, 1);
    // Analyse du mouvement (image réduite 64×64 lue par le processeur).
    const mk = () => { const c = document.createElement("canvas"); c.width = c.height = MOTION.N; return c.getContext("2d", { willReadFrequently: true }); };
    this.camCtx = mk(); this.aiCtx = mk();
    this.camHist = new MotionHistory(); this.aiHist = new MotionHistory(MOTION.G, 300); this.cand = null;
    this.prevCam = null; this.prevAi = null;
    this.flowFn = blockFlow; this.engine = "js";
    loadMotionWasm().then((f) => { if (f) { this.flowFn = f; this.engine = "rust"; } });
    this.lag = null; this.lagConf = 0; this.net = {};
    this.aiTs = 0; this.newFrame = false; this.srcW = 512; this.srcH = 512;
    this.frameDt = []; this.target = 0; this.running = true;
    this.disp = new Float32Array(MOTION.G * MOTION.G * 2);
    this._resize(); this._onResize = () => this._resize(); addEventListener("resize", this._onResize);
    this._watch(this.cam, (ts) => this._camFrame(ts));
    this._watch(this.ai, (ts) => this._aiFrame(ts));
    this._lagTimer = setInterval(() => this._updateLag(), 1000);
    const loop = (ts) => { if (!this.running) return; this._draw(ts); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  }
  setNet(s) { this.net = s || {}; }
  setFluid(on) { this.fluid = !!on; }
  setRes(r) { this.res = r; this._resize(); }
  get lagMs() { return Math.round(this.lag ?? fallbackLag(this.net)); }
  // Flux vidéo du rendu final (pour l'enregistrement d'essai en 1080p).
  stream(fps = 30) { if (!this._stream) this._stream = this.canvas.captureStream(fps); return this._stream; }
  stop() { this.running = false; clearInterval(this._lagTimer); removeEventListener("resize", this._onResize); }

  _watch(v, fn) {
    if (!v.requestVideoFrameCallback) { const id = setInterval(() => this.running ? fn(performance.now()) : clearInterval(id), 33); return; }
    const cb = (now) => { if (!this.running) return; fn(now); v.requestVideoFrameCallback(cb); };
    v.requestVideoFrameCallback(cb);
  }
  _luma(ctx, v) {
    if (!v.videoWidth) return null;
    ctx.drawImage(v, 0, 0, MOTION.N, MOTION.N);
    return toLuma(ctx.getImageData(0, 0, MOTION.N, MOTION.N).data, MOTION.N);
  }
  _camFrame(ts) {
    const cur = this._luma(this.camCtx, this.cam); if (!cur) return;
    if (this.prevCam) this.camHist.push(ts, this.flowFn(this.prevCam, cur));
    this.prevCam = cur;
  }
  _aiFrame(ts) {
    this.aiTs = ts; this.newFrame = true;
    if (!this.fluid) return;
    const cur = this._luma(this.aiCtx, this.ai); if (!cur) return;
    if (this.prevAi) this.aiHist.push(ts, this.flowFn(this.prevAi, cur));
    this.prevAi = cur;
  }
  _updateLag() {
    if (!this.fluid) return;
    const r = estimateLag(this.camHist.pos, this.aiHist.pos);
    // Une mesure n'est adoptée que si deux mesures successives concordent (à 60 ms près).
    if (r && r.conf >= 0.35) {
      const agree = this.cand != null && Math.abs(this.cand - r.lag) <= 60;
      this.cand = r.lag;
      if (agree) {
        this.lag = this.lag == null ? r.lag : 0.7 * this.lag + 0.3 * r.lag;
        this.lagConf = Math.max(this.lagConf * 0.8, r.conf);
      }
    } else this.lagConf *= 0.97;
    this.onInfo(this.info());
  }
  info() { return { w: this.canvas.width, h: this.canvas.height, short: Math.min(this.canvas.width, this.canvas.height), fluid: this.fluid, lagMs: this.lagMs, measured: this.lag != null, engine: this.engine }; }
  _resize() {
    const r = this.canvas.getBoundingClientRect(), dpr = devicePixelRatio || 1;
    const shortPx = Math.round(Math.min(screen.width, screen.height) * dpr);
    this.target = renderTarget(this.res, { shortPx, saveData: !!(navigator.connection || {}).saveData });
    const { w, h } = canvasSize(r.width || innerWidth, r.height || innerHeight, dpr, this.target);
    if (this.canvas.width !== w || this.canvas.height !== h) { this.canvas.width = w; this.canvas.height = h; }
    this.onInfo(this.info());
  }
  _draw(ts) {
    const gl = this.gl, v = this.ai;
    // Le téléphone peine (moins de 25 i/s affichées) : on baisse la définition d'un cran (auto seulement).
    // Fenêtre de 2 s (en durée, pas en nombre d'images : un téléphone très lent est détecté aussi vite).
    if (this.lastTs) { this.frameDt.push(ts - this.lastTs); while (this.frameDt.reduce((x, y) => x + y, 0) > 2000) this.frameDt.shift(); }
    this.lastTs = ts;
    if (!this.since) this.since = ts;
    if (this.res === "auto" && ts - this.since > 2000 && this.frameDt.length && this.target > 480) {
      const avg = this.frameDt.reduce((x, y) => x + y, 0) / this.frameDt.length;
      if (avg > 40) { this.res = this.target > 720 ? "720" : "480"; this.frameDt = []; this.since = ts; this._resize(); }
    }
    gl.activeTexture(gl.TEXTURE0);
    if (this.newFrame && v.videoWidth) {
      this.newFrame = false;
      try { gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, v); this.srcW = v.videoWidth; this.srcH = v.videoHeight; } catch {}
    }
    // Recadrage « cover » : remplir l'écran sans déformer.
    const cw = this.canvas.width, ch = this.canvas.height, ca = cw / ch, sa = this.srcW / this.srcH;
    const sx = ca > sa ? 1 : ca / sa, sy = ca > sa ? sa / ca : 1;
    gl.uniform2f(this.u.u_scale, sx, sy); gl.uniform2f(this.u.u_off, (1 - sx) / 2, (1 - sy) / 2);
    gl.uniform2f(this.u.u_tex, 1 / this.srcW, 1 / this.srcH);
    gl.uniform1f(this.u.u_sharp, Math.min(1, 0.35 + 0.35 * (Math.min(cw, ch) / Math.min(this.srcW, this.srcH) - 1)));
    gl.uniform1f(this.u.u_warp, this._prediction(ts));
    gl.viewport(0, 0, cw, ch);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  // Déplacement à appliquer à l'image IA affichée : mouvement de la caméra depuis la prise de vue
  // qui a produit cette image. Atténué si le délai n'est pas encore mesuré, coupé si l'IA est figée.
  _prediction(ts) {
    if (!this.fluid || !this.aiTs) return 0;
    const age = ts - this.aiTs;
    if (age > 500) return 0;
    const lag = this.lag ?? fallbackLag(this.net);
    const d = this.camHist.displacement(this.aiTs - lag, this.camHist.last);
    const lim = 0.06 * MOTION.N;                         // au plus 6 % de l'image : au-delà, la déformation se voit
    for (let k = 0; k < d.length; k += 2) {
      const m = Math.hypot(d[k], d[k + 1]), s = m > lim ? lim / m : 1;
      this.disp[k] = d[k] * s / MOTION.N; this.disp[k + 1] = d[k + 1] * s / MOTION.N;
    }
    const gl = this.gl;
    gl.activeTexture(gl.TEXTURE1);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, MOTION.G, MOTION.G, gl.RG, gl.FLOAT, this.disp);
    const strength = this.lag != null ? 0.9 : 0.6;
    return strength * (age > 250 ? (500 - age) / 250 : 1);
  }
}
