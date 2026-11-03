//! Mouvement de `prev` vers `cur` par blocs (image 64×64, grille 8×8), en deux niveaux.
//! Port fidèle de `blockFlow` (live/static/rendu.js). Aucune dépendance, mémoire statique :
//! le JavaScript écrit les images aux adresses `prev_ptr()` / `cur_ptr()`, appelle `flow()`,
//! puis lit 128 vecteurs + [gx, gy, valid] à l'adresse `out_ptr()`.
#![no_std]

const N: usize = 64;
const G: usize = 8;
const R: i32 = 3;

static mut PREV: [f32; N * N] = [0.0; N * N];
static mut CUR: [f32; N * N] = [0.0; N * N];
static mut OUT: [f32; G * G * 2 + 3] = [0.0; G * G * 2 + 3];

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! { loop {} }

#[no_mangle] pub extern "C" fn prev_ptr() -> *mut f32 { core::ptr::addr_of_mut!(PREV) as *mut f32 }
#[no_mangle] pub extern "C" fn cur_ptr() -> *mut f32 { core::ptr::addr_of_mut!(CUR) as *mut f32 }
#[no_mangle] pub extern "C" fn out_ptr() -> *mut f32 { core::ptr::addr_of_mut!(OUT) as *mut f32 }

fn half(img: &[f32], n: usize, out: &mut [f32]) {
    let m = n / 2;
    for y in 0..m { for x in 0..m {
        let i = 2 * y * n + 2 * x;
        out[y * m + x] = (img[i] + img[i + 1] + img[i + n] + img[i + n + 1]) * 0.25;
    } }
}

#[inline(always)]
fn at(img: &[f32], n: usize, x: i32, y: i32) -> f32 {
    let cx = x.clamp(0, n as i32 - 1) as usize; let cy = y.clamp(0, n as i32 - 1) as usize;
    img[cy * n + cx]
}

fn sad(prev: &[f32], cur: &[f32], n: usize, b: usize, bx: usize, by: usize, dx: i32, dy: i32) -> f32 {
    let mut s = 0.0;
    // Intérieur sans bornes à vérifier quand le décalage reste dans l'image (cas le plus fréquent).
    let inside = bx as i32 - dx >= 0 && by as i32 - dy >= 0 && (bx + b) as i32 - dx <= n as i32 && (by + b) as i32 - dy <= n as i32;
    for y in by..by + b {
        if inside {
            let row_c = &cur[y * n + bx..y * n + bx + b];
            let py = (y as i32 - dy) as usize; let px = (bx as i32 - dx) as usize;
            let row_p = &prev[py * n + px..py * n + px + b];
            for k in 0..b { s += (row_c[k] - row_p[k]).abs(); }
        } else {
            for x in bx..bx + b { s += (cur[y * n + x] - at(prev, n, x as i32 - dx, y as i32 - dy)).abs(); }
        }
    }
    s
}

fn search(prev: &[f32], cur: &[f32], n: usize, r: i32, init: Option<&[i32; G * G * 2]>, out: &mut [f32; G * G * 2 + 3]) {
    let b = n / G;
    let mut flow = [0f32; G * G * 2];
    let mut ok = [false; G * G];
    const W: usize = 2 * 8 + 1; // fenêtre de coûts : ±8 autour de 0 (assez pour les deux niveaux)
    for j in 0..G { for i in 0..G {
        let (bx, by) = (i * b, j * b);
        let (mut m, mut m2) = (0f32, 0f32);
        for y in by..by + b { for x in bx..bx + b { let v = cur[y * n + x]; m += v; m2 += v * v; } }
        let bb = (b * b) as f32; m /= bb;
        if m2 / bb - m * m < 16.0 { continue; }
        let k0 = (j * G + i) * 2;
        let (ix, iy) = init.map(|v| (v[k0], v[k0 + 1])).unwrap_or((0, 0));
        let mut costs = [f32::NAN; W * W];
        let idx = |dx: i32, dy: i32| -> Option<usize> {
            if dx.abs() > 8 || dy.abs() > 8 { None } else { Some(((dy + 8) as usize) * W + (dx + 8) as usize) } };
        let (mut best, mut bdx, mut bdy) = (f32::INFINITY, 0i32, 0i32);
        let scan = |cx: i32, cy: i32, rr: i32, costs: &mut [f32; W * W], best: &mut f32, bdx: &mut i32, bdy: &mut i32| {
            for dy in cy - rr..=cy + rr { for dx in cx - rr..=cx + rr {
                if let Some(q) = idx(dx, dy) { if !costs[q].is_nan() { continue; }
                    let c = sad(prev, cur, n, b, bx, by, dx, dy); costs[q] = c;
                    if c < *best { *best = c; *bdx = dx; *bdy = dy; } }
            } }
        };
        scan(0, 0, R, &mut costs, &mut best, &mut bdx, &mut bdy);
        if ix != 0 || iy != 0 { scan(ix, iy, r, &mut costs, &mut best, &mut bdx, &mut bdy); }
        let zero = costs[idx(0, 0).unwrap()];
        if zero <= best * 1.04 + bb * 0.5 { ok[j * G + i] = true; continue; }
        let get = |dx: i32, dy: i32| idx(dx, dy).map(|q| costs[q]).filter(|c| !c.is_nan());
        let sub = |cm: f32, c0: f32, cp: f32| { let den = cm - 2.0 * c0 + cp; if den > 0.0 { ((cm - cp) / (2.0 * den)).clamp(-0.5, 0.5) } else { 0.0 } };
        let fx = match (get(bdx - 1, bdy), get(bdx + 1, bdy)) { (Some(a), Some(c)) => sub(a, best, c), _ => 0.0 };
        let fy = match (get(bdx, bdy - 1), get(bdx, bdy + 1)) { (Some(a), Some(c)) => sub(a, best, c), _ => 0.0 };
        flow[k0] = bdx as f32 + fx; flow[k0 + 1] = bdy as f32 + fy; ok[j * G + i] = true;
    } }
    // Voisins pour les blocs non fiables, puis médiane 3×3.
    let mut filled = flow;
    for k in 0..G * G {
        if ok[k] { continue; }
        let (i, j) = ((k % G) as i32, (k / G) as i32); let (mut sx, mut sy, mut c) = (0f32, 0f32, 0f32);
        for v in -1..=1 { for u in -1..=1 {
            let (ii, jj) = (i + u, j + v);
            if ii < 0 || jj < 0 || ii >= G as i32 || jj >= G as i32 { continue; }
            let q = jj as usize * G + ii as usize; if !ok[q] { continue; }
            sx += flow[q * 2]; sy += flow[q * 2 + 1]; c += 1.0;
        } }
        if c > 0.0 { filled[k * 2] = sx / c; filled[k * 2 + 1] = sy / c; }
    }
    let (mut gx, mut gy, mut valid) = (0f32, 0f32, 0f32);
    for j in 0..G as i32 { for i in 0..G as i32 {
        let (mut ax, mut ay, mut c) = ([0f32; 9], [0f32; 9], 0usize);
        for v in -1..=1 { for u in -1..=1 {
            let (ii, jj) = (i + u, j + v);
            if ii < 0 || jj < 0 || ii >= G as i32 || jj >= G as i32 { continue; }
            let q = jj as usize * G + ii as usize; ax[c] = filled[q * 2]; ay[c] = filled[q * 2 + 1]; c += 1;
        } }
        let med = |a: &mut [f32]| { a.sort_unstable_by(|x, y| x.partial_cmp(y).unwrap_or(core::cmp::Ordering::Equal)); a[a.len() / 2] };
        let k = j as usize * G + i as usize;
        out[k * 2] = med(&mut ax[..c]); out[k * 2 + 1] = med(&mut ay[..c]);
        gx += out[k * 2]; gy += out[k * 2 + 1]; if ok[k] { valid += 1.0; }
    } }
    out[G * G * 2] = gx / (G * G) as f32; out[G * G * 2 + 1] = gy / (G * G) as f32; out[G * G * 2 + 2] = valid;
}

#[no_mangle]
pub extern "C" fn flow() {
    unsafe {
        let prev = &*core::ptr::addr_of!(PREV); let cur = &*core::ptr::addr_of!(CUR);
        let out = &mut *core::ptr::addr_of_mut!(OUT);
        let (mut hp, mut hc) = ([0f32; N * N / 4], [0f32; N * N / 4]);
        half(prev, N, &mut hp); half(cur, N, &mut hc);
        let mut coarse = [0f32; G * G * 2 + 3];
        search(&hp, &hc, N / 2, R, None, &mut coarse);
        let mut init = [0i32; G * G * 2];
        for k in 0..G * G * 2 { init[k] = libm_round(2.0 * coarse[k]); }
        search(prev, cur, N, 2, Some(&init), out);
    }
}

// Arrondi comme Math.round (pas de libm en no_std).
fn libm_round(x: f32) -> i32 { let f = x + 0.5; let t = f as i32; if (t as f32) > f { t - 1 } else { t } }
