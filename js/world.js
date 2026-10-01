// Glitch Loom — "The Thread Road"
// One continuous pixel-art valley, drawn entirely in code. No image files.
// The camera walks the road from dawn (first question) to night (the journey).

export const THREADS = ['#ff5d73', '#ffd23f', '#5ce1e6', '#b28dff'];
const WORLDW = 3240, GAP = 300, X0 = 420;
export const SX = i => X0 + i * GAP;

/* ---------- small maths ---------- */
function mulberry(seed) { let t = seed >>> 0; return () => { t += 0x6D2B79F5; let r = Math.imul(t ^ t >>> 15, 1 | t); r ^= r + Math.imul(r ^ r >>> 7, 61 | r); return ((r ^ r >>> 14) >>> 0) / 4294967296; }; }
const h2 = (x, y) => { const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453; return s - Math.floor(s); };
const sm = f => f * f * (3 - 2 * f);
function vn(x, s = 7) { const i = Math.floor(x), f = sm(x - i); return h2(i, s) * (1 - f) + h2(i + 1, s) * f; }
function vn2(x, y) { const i = Math.floor(x), j = Math.floor(y), u = sm(x - i), v = sm(y - j); return (h2(i, j) * (1 - u) + h2(i + 1, j) * u) * (1 - v) + (h2(i, j + 1) * (1 - u) + h2(i + 1, j + 1) * u) * v; }
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map(v => v / 16);
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const rgb = h => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
const mix3 = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
const css = c => `rgb(${c[0] | 0},${c[1] | 0},${c[2] | 0})`;

/* ---------- drawing primitives ---------- */
const R = (c, x, y, w, h, col) => { c.fillStyle = col; c.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h)); };
function disc(c, cx, cy, r, col) { c.fillStyle = col; cx = Math.round(cx); cy = Math.round(cy); r = Math.max(0, Math.round(r)); for (let dy = -r; dy <= r; dy++) { const w = Math.floor(Math.sqrt(r * r - dy * dy) + .3); c.fillRect(cx - w, cy + dy, 2 * w + 1, 1); } }
function tri(c, cx, top, h, half, col) { c.fillStyle = col; for (let i = 0; i < h; i++) { const w = Math.round(half * (i + 1) / h); c.fillRect(Math.round(cx - w), Math.round(top + i), 2 * w + 1, 1); } }
function line(c, x0, y0, x1, y1, col) { x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1); c.fillStyle = col; const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1; let e = dx + dy; for (let n = 0; n < 600; n++) { c.fillRect(x0, y0, 1, 1); if (x0 === x1 && y0 === y1) break; const e2 = 2 * e; if (e2 >= dy) { e += dy; x0 += sx; } if (e2 <= dx) { e += dx; y0 += sy; } } }
function reveal(c, x, b, w, h, p, fn) { if (p <= .02) return; if (p >= .995) { fn(); return; } c.save(); c.beginPath(); c.rect(Math.round(x - w / 2), Math.round(b - h * p), w, Math.ceil(h * p) + 8); c.clip(); fn(); c.restore(); }

/* ---------- sky by time of day (0 dawn … 8 night) ---------- */
const SKY = [
  ['#2b3a7a', '#c86f9a', '#ffc28a', '#ffd9c4'],
  ['#3f7fd6', '#8cc4f2', '#ffe9c9', '#fff1e0'],
  ['#2f86e6', '#6fb8f5', '#cfeaff', '#ffffff'],
  ['#1f7ae0', '#5fb0f5', '#bfe4ff', '#ffffff'],
  ['#1b6fd8', '#55a8f0', '#c9ecff', '#fbffef'],
  ['#2a74cf', '#7ab6ea', '#ffe8b8', '#fff3d6'],
  ['#3a5fae', '#f0a36b', '#ffd27a', '#ffd9a0'],
  ['#2a2f6e', '#b8567e', '#ff9a5c', '#e9a28f'],
  ['#0b1033', '#1b2a5e', '#3a4f8a', '#6f7fc0'],
].map(k => k.map(rgb));
function skyAt(t) { t = clamp(t, 0, 8); const i = Math.min(7, Math.floor(t)), f = t - i; return SKY[i].map((c, k) => mix3(c, SKY[i + 1][k], f)); }

/* ---------- plants ---------- */
const GREEN = ['#2b7a3d', '#3f9a48', '#62bd55', '#8fdc6a'];
const BLOSSOM = ['#b84a7a', '#e0709a', '#f7a3c0', '#ffd7e4'];
const AMBER = ['#b8692a', '#dd8f35', '#f4b74e', '#ffdc86'];
function tree(c, x, b, s, rnd, pal = GREEN) {
  const tw = Math.max(2, Math.round(s / 4)), th = Math.round(s * 1.15);
  R(c, x - (tw >> 1), b - th, tw, th, '#6b4226'); R(c, x - (tw >> 1), b - th, 1, th, '#8a5a35');
  const cy = b - th - s * .55;
  const bl = [[0, 0, s], [-s * .72, s * .28, s * .68], [s * .72, s * .3, s * .64], [-s * .32, -s * .55, s * .6], [s * .36, -s * .5, s * .55]];
  for (const [dx, dy, r] of bl) disc(c, x + dx, cy + dy, r, pal[0]);
  for (const [dx, dy, r] of bl) disc(c, x + dx - 1.5, cy + dy - 1.5, r * .78, pal[1]);
  for (const [dx, dy, r] of bl) disc(c, x + dx - s * .24, cy + dy - s * .27, r * .44, pal[2]);
  for (let i = 0; i < s * 4; i++) { const a = rnd() * 6.28, d = rnd() * s * 1.2; const px = x + Math.cos(a) * d, py = cy + Math.sin(a) * d * .8; R(c, px, py, 1, 1, py < cy - 1 ? pal[3] : pal[0]); }
}
function pine(c, x, b, h, dark = '#1f5f4a', lit = '#2f8060') {
  R(c, x, b - 3, 1, 3, '#5a3a22');
  for (let k = 0; k < 3; k++) { const top = b - h + k * (h / 4), hh = h / 2.4, half = 2 + k * 1.6; tri(c, x, top, hh, half, dark); for (let i = 0; i < hh; i++) { const w = Math.round(half * (i + 1) / hh); R(c, x - w, top + i, Math.max(1, w), 1, lit); } }
}
function bush(c, x, b, s, pal = GREEN) { disc(c, x, b - s * .5, s, pal[0]); disc(c, x - 1, b - s * .5 - 1, s * .75, pal[1]); disc(c, x - s * .3, b - s * .8, s * .4, pal[2]); }
function flower(c, x, y, col) { R(c, x, y, 1, 3, '#2f7f3a'); R(c, x - 1, y - 1, 3, 1, col); R(c, x, y - 2, 1, 3, col); R(c, x, y - 1, 1, 1, '#fff6c2'); }
function person(c, x, y, shirt, step = 0, hair = '#3a2a4a') {
  R(c, x - 1, y - 9, 3, 3, '#f2c49b'); R(c, x - 1, y - 10, 3, 1, hair); R(c, x - 2, y - 6, 5, 4, shirt);
  R(c, x - 1 - (step ? 1 : 0), y - 2, 1, 2, '#2a2f4a'); R(c, x + 1 + (step ? 1 : 0), y - 2, 1, 2, '#2a2f4a');
}

/* ---------- buildings (static) ---------- */
function school(c, x, b) { R(c, x - 13, b - 16, 26, 16, '#f3e2c0'); R(c, x + 8, b - 16, 5, 16, '#dcc69c'); tri(c, x, b - 27, 11, 16, '#d2503f'); R(c, x - 16, b - 17, 33, 1, '#a83a30'); R(c, x - 2, b - 34, 5, 8, '#f3e2c0'); tri(c, x, b - 38, 4, 4, '#d2503f'); R(c, x, b - 32, 1, 2, '#ffd23f'); R(c, x - 2, b - 8, 5, 8, '#7a4d2b'); R(c, x - 10, b - 12, 4, 5, '#4f6f96'); R(c, x + 3, b - 12, 4, 5, '#4f6f96'); }
function college(c, x, b) { R(c, x - 18, b - 2, 36, 2, '#bdb5a3'); R(c, x - 16, b - 20, 32, 18, '#d6cfbf'); tri(c, x, b - 30, 9, 18, '#c2b9a6'); R(c, x - 19, b - 21, 39, 2, '#eee8da'); for (let k = 0; k < 5; k++) R(c, x - 15 + k * 7, b - 19, 2, 17, '#f7f3ea'); R(c, x - 2, b - 9, 4, 7, '#6b4a2f'); R(c, x - 11, b - 14, 3, 5, '#4f6f96'); R(c, x + 8, b - 14, 3, 5, '#4f6f96'); }
function workshop(c, x, b) { R(c, x - 14, b - 15, 28, 15, '#b5654a'); for (let r = 0; r < 15; r += 3) R(c, x - 14, b - 15 + r, 28, 1, '#9c513a'); for (let t = 0; t < 3; t++) for (let r = 0; r < 7; r++) R(c, x - 14 + t * 9, b - 22 + r, r + 3, 1, t % 2 ? '#56657a' : '#66768c'); R(c, x + 9, b - 31, 3, 10, '#8a4a38'); R(c, x - 5, b - 9, 10, 9, '#3d2b22'); R(c, x - 12, b - 11, 4, 4, '#4f6f96'); R(c, x + 8, b - 11, 4, 4, '#4f6f96'); }
const WINDOWS = { school: [[-10, -12, 4, 5], [3, -12, 4, 5]], college: [[-11, -14, 3, 5], [8, -14, 3, 5], [-4, -14, 2, 4], [2, -14, 2, 4]], workshop: [[-12, -11, 4, 4], [8, -11, 4, 4]] };

/* ================================================================== */
export function createWorld(canvas) {
  const ctx = canvas.getContext('2d', { alpha: false });
  const A = document.createElement('canvas'), B = document.createElement('canvas'), skyT = document.createElement('canvas');
  const a = A.getContext('2d'), bq = B.getContext('2d'), sk = skyT.getContext('2d');
  let W = 0, H = 0, G = 0, scale = 3, wide = true, L = null, clouds = [], stars = [];
  let cam = 0, camT = 0, tod = 0, todT = 0, heroX = SX(0) - 50, heroT = heroX;
  let station = 0, sub = 0, centre = false, vis = {}, reduce = false;
  let last = 0, amb = 0, tick = -1, dirty = true, moving = false, first = true, dtc = 0, skyKey = -1;
  const tw = new Map(), sparks = [];

  const gy = x => G + Math.round(5 * Math.sin(x / 95) + 3 * Math.sin(x / 41 + 1.3));
  const pathY = x => gy(x) + 17 + Math.round(4 * Math.sin(x / 70 + 2));
  function T(key, target, speed = 9) { let v = tw.get(key); if (v === undefined || reduce || first) v = target; else { const d = target - v; if (Math.abs(d) < .004) v = target; else { v += d * (1 - Math.exp(-dtc * speed)); moving = true; } } tw.set(key, v); return v; }

  /* ---------- build the static world ---------- */
  function build() {
    const mk = (w) => { const c = document.createElement('canvas'); c.width = w; c.height = H; return c; };
    const far = mk(WORLDW), mid = mk(WORLDW), main = mk(WORLDW), fore = mk(Math.ceil(WORLDW * 1.5) + 200);
    let c = far.getContext('2d');
    // two mountain ranges for depth
    for (let pass = 0; pass < 2; pass++) {
      const col = pass ? ['#7f98c9', '#6a82b6', '#f4f8ff', '#cfdcf5'] : ['#a3b8df', '#93a9d3', '#ffffff', '#e2ebfb'];
      const amp = pass ? H * .30 : H * .38, off = pass ? 3 : 91;
      for (let x = 0; x < WORLDW; x++) {
        const ridge = k => 1 - Math.abs(2 * vn((k + off * 40) / 120, off) - 1);
        const n = k => Math.pow(ridge(k), 1.6) * .7 + vn((k + off) / 34, off + 1) * .2 + vn(k / 9, off + 2) * .1;
        const v = n(x), top = Math.round(G - 10 - v * amp), litF = ridge(x + 5) > ridge(x - 1);
        R(c, x, top, 1, G + 12 - top, litF ? col[0] : col[1]);
        if (v > .5) { const sn = Math.round(2 + (v - .5) * amp * .55 + h2(x >> 1, 3) * 4); R(c, x, top, 1, sn, litF ? col[2] : col[3]); }
        if (h2(x >> 2, 5) < .22) { const yy = top + 8 + Math.floor(h2(x >> 2, 9) * amp * .5); R(c, x, yy, 1, 3, litF ? col[1] : col[0]); }
      }
    }
    // rolling hills with tree lines
    c = mid.getContext('2d');
    const r1 = mulberry(21);
    for (let x = 0; x < WORLDW; x++) { const top = Math.round(G - 16 - 24 * vn(x / 170 + 5, 4) - 5 * vn(x / 48, 5)); R(c, x, top, 1, G + 12 - top, '#4a957a'); R(c, x, top, 1, 2, '#63b08c'); if (h2(x, 77) < .16) R(c, x, top + 4 + Math.floor(h2(x, 5) * 14), 2, 1, '#3f866c'); }
    for (let x = 4; x < WORLDW; x += 5 + Math.floor(r1() * 12)) { const top = Math.round(G - 16 - 24 * vn(x / 170 + 5, 4) - 5 * vn(x / 48, 5)); pine(c, x, top + 2, 8 + Math.floor(r1() * 7)); }
    for (let x = 0; x < WORLDW; x++) { const top = Math.round(G - 5 - 15 * vn(x / 120 + 9, 6)); R(c, x, top, 1, G + 12 - top, '#55a866'); R(c, x, top, 1, 1, '#79c47c'); }
    for (let x = 8; x < WORLDW; x += 9 + Math.floor(r1() * 20)) { const top = Math.round(G - 5 - 15 * vn(x / 120 + 9, 6)); bush(c, x, top + 2, 3 + Math.floor(r1() * 3), ['#357f4a', '#47985a', '#63b56c']); }

    // main ground, path and river
    c = main.getContext('2d');
    const y0 = G - 12, gh = H - y0, img = c.createImageData(WORLDW, gh), d = img.data;
    const P = ['#3d963f', '#4aa845', '#58b94c', '#6ccb57', '#8ee06a', '#b99a5f', '#d8bd82', '#ecd59a', '#3d8fe0', '#7cc0ff', '#2a6fc0', '#2f7a3a', '#358a3c'].map(rgb);
    const rx = SX(4);
    for (let x = 0; x < WORLDW; x++) {
      const g = gy(x), py = pathY(x);
      for (let y = Math.max(g, y0); y < H; y++) {
        const dd = y - g; let col;
        const rc = rx + dd * .35, hw = 14 + dd * .27, dr = Math.abs(x - rc);
        if (dd > 1 && dr < hw) { col = dr > hw - 2 ? P[10] : (((x + y * 3) % 13 < 4 && h2(x >> 1, y) > .45) ? P[9] : P[8]); }
        else if (dd > 1 && dr < hw + 2) col = P[11];
        else if (Math.abs(y - py) <= 3) col = Math.abs(y - py) === 3 ? P[5] : (h2(x * 3, y * 5) < .16 ? P[6] : P[7]);
        else if (dd < 2) col = P[4];
        else { const v = vn2(x / 36, y / 11) * .72 + h2(x, y) * .28; col = v < .34 ? P[0] : v < .56 ? P[1] : v < .8 ? P[2] : P[3]; if (y > H - 26 && h2(x, y + 9) < (y - (H - 26)) / 34) col = P[12]; }
        const o = ((y - y0) * WORLDW + x) * 4; d[o] = col[0]; d[o + 1] = col[1]; d[o + 2] = col[2]; d[o + 3] = 255;
      }
    }
    c.putImageData(img, 0, y0);
    const rnd = mulberry(11), items = [];
    const nearStation = x => { for (let i = 0; i < 9; i++) if (Math.abs(x - SX(i)) < 98) return true; return false; };
    for (let x = 14; x < WORLDW; x += 16 + Math.floor(rnd() * 34)) {
      if (nearStation(x)) continue;
      const k = rnd(), b = gy(x) + 2 + Math.floor(rnd() * 7);
      items.push({ b, f: k < .5 ? () => tree(c, x, b, 8 + Math.floor(rnd() * 6), rnd, rnd() < .16 ? BLOSSOM : rnd() < .12 ? AMBER : GREEN) : k < .72 ? () => pine(c, x, b, 16 + Math.floor(rnd() * 8), '#246b4c', '#38905f') : () => bush(c, x, b, 4 + Math.floor(rnd() * 3)) });
    }
    for (let i = 0; i < 9; i++) items.push({ b: gy(SX(i)) + 5, f: () => staticStation(c, i) });
    items.sort((p, q) => p.b - q.b).forEach(o => o.f());
    const fc = ['#ff5d73', '#ffd23f', '#ffffff', '#b28dff', '#ff9a5c'];
    for (let i = 0; i < 900; i++) { const x = Math.floor(rnd() * WORLDW), y = gy(x) + 7 + Math.floor(rnd() * (H - gy(x) - 30)); if (Math.abs(y - pathY(x)) < 6 || Math.abs(x - (rx + (y - gy(x)) * .35)) < 22 + (y - gy(x)) * .3) continue; if (i % 3) { R(c, x, y, 1, 2, '#2f8a3a'); R(c, x + 1, y - 1, 1, 2, '#2f8a3a'); R(c, x - 1, y - 1, 1, 1, '#9be27a'); } else flower(c, x, y, fc[i % 5]); }

    // foreground foliage
    c = fore.getContext('2d');
    const r3 = mulberry(5), FW = fore.width;
    for (let x = 0; x < FW; x += 8 + Math.floor(r3() * 16)) if (r3() < .5) { const s = 4 + Math.floor(r3() * 5); disc(c, x, H - 2 - s * .3, s, '#17502f'); disc(c, x - 1, H - 3 - s * .4, s * .7, '#1f6a3a'); }
    for (let x = 0; x < FW; x += 2 + Math.floor(r3() * 3)) { const hgt = 5 + Math.floor(r3() * r3() * 24), col = ['#17502f', '#1f6a3a', '#2c8446', '#3c9a50'][Math.floor(r3() * 4)], lean = (r3() - .5) * 8; for (let k = 0; k < hgt; k++) { const f = k / hgt; R(c, x + lean * f * f, H - 1 - k, f < .6 ? 2 : 1, 1, col); } if (r3() < .05) { const fy = H - hgt - 2; disc(c, x + lean, fy, 2, fc[Math.floor(r3() * 5)]); R(c, x + lean, fy, 1, 1, '#fff6c2'); } }
    R(c, 0, H - 3, FW, 3, '#134226');

    // clouds
    const r4 = mulberry(8); clouds = [];
    for (let i = 0; i < 9; i++) {
      const w = 40 + Math.floor(r4() * 70), hh = 16 + Math.floor(r4() * 16), cv = document.createElement('canvas'); cv.width = w; cv.height = hh + 4; const cc = cv.getContext('2d');
      const bl = []; for (let k = 0; k < 5 + w / 14; k++) { const px = 8 + r4() * (w - 16), rr = 4 + r4() * (hh * .42) * (1 - Math.abs(px / w - .5) * 1.2); bl.push([px, hh - rr * .6, Math.max(3, rr)]); }
      for (const [x, y, r] of bl) disc(cc, x, y + 2, r, '#a9c8ee'); for (const [x, y, r] of bl) disc(cc, x, y, r, '#e6f1ff'); for (const [x, y, r] of bl) disc(cc, x - r * .25, y - r * .3, r * .6, '#ffffff');
      cc.clearRect(0, hh, w, 8); R(cc, 6, hh - 1, w - 12, 1, '#a9c8ee');
      clouds.push({ cv, x: r4() * 900, y: Math.round(6 + r4() * (G * .5)), sp: .5 + r4() });
    }
    const r5 = mulberry(3); stars = []; for (let i = 0; i < 90; i++) stars.push([r5(), r5() * .8, r5()]);
    L = { far, mid, main, fore };
  }

  function staticStation(c, i) {
    const x = SX(i), b = gy(x) + 5;
    if (i === 0) { R(c, x - 40, b - 26, 2, 27, '#7a4d2b'); R(c, x - 40, b - 26, 1, 27, '#9a6a40'); R(c, x - 50, b - 25, 12, 4, '#d9a05c'); R(c, x - 38, b - 19, 12, 4, '#c98b4a'); R(c, x - 49, b - 13, 11, 4, '#d9a05c'); disc(c, x + 44, b - 2, 5, '#8d8d99'); disc(c, x + 43, b - 3, 3, '#b3b3c0'); tree(c, x - 74, gy(x - 74) + 3, 14, mulberry(2)); }
    if (i === 1) { for (let k = -5; k <= 5; k++) { const fx = x + k * 12; R(c, fx, gy(fx) - 3, 2, 8, '#c9a06a'); } for (let k = -5; k < 5; k++) { const fx = x + k * 12; line(c, fx, gy(fx), fx + 12, gy(fx + 12), '#e0bd88'); line(c, fx, gy(fx) + 3, fx + 12, gy(fx + 12) + 3, '#b98d55'); } tree(c, x + 80, gy(x + 80) + 3, 12, mulberry(4), BLOSSOM); }
    if (i === 2) { school(c, x - 42, b); college(c, x, b - 1); workshop(c, x + 43, b); bush(c, x - 66, b + 2, 4); bush(c, x + 68, b + 2, 4); }
    if (i === 3) { disc(c, x + 22, b + 34, 56, '#3f9a48'); disc(c, x + 19, b + 32, 53, '#4fae46'); disc(c, x + 10, b + 24, 40, '#5cc04e'); { const rm = mulberry(31); for (let k = 0; k < 120; k++) { const a2 = rm() * 6.28, d2 = Math.sqrt(rm()) * 50, mx2 = x + 20 + Math.cos(a2) * d2, my2 = b + 32 + Math.sin(a2) * d2; if (my2 > b - 14 && my2 < H - 4) { if (k % 4 === 0) flower(c, mx2, my2, ['#ff5d73', '#ffd23f', '#ffffff', '#b28dff'][k % 4 + (k >> 2) % 4 & 3]); else { R(c, mx2, my2, 1, 2, '#3a9440'); R(c, mx2 + 1, my2 - 1, 1, 2, '#7fd75f'); } } } } for (let k = 0; k < 5; k++) { R(c, x - 30 + k * 11, b - 5 - k * 7, 13, 3, '#d8d0bd'); R(c, x - 30 + k * 11, b - 2 - k * 7, 13, 5, '#a59c88'); } R(c, x + 30, b - 50, 1, 18, '#efe8da'); R(c, x - 48, b - 12, 2, 13, '#7a4d2b'); R(c, x - 36, b - 12, 2, 13, '#7a4d2b'); R(c, x - 49, b - 14, 16, 2, '#9a6a40'); pine(c, x + 58, b - 12, 18, '#246b4c', '#38905f'); }
    if (i === 4) { const py = pathY(x); R(c, x - 18, py - 10, 2, 11, '#7a4d2b'); R(c, x + 31, py - 10, 2, 11, '#7a4d2b'); tree(c, x - 60, gy(x - 60) + 3, 12, mulberry(6)); tree(c, x + 76, gy(x + 76) + 3, 11, mulberry(9), AMBER); }
    if (i === 5) { const hx = x - 40; R(c, hx - 20, b - 18, 40, 18, '#c2543f'); R(c, hx + 12, b - 18, 8, 18, '#a44434'); for (let r = 0; r < 12; r++) { const w = r < 5 ? 8 + r * 2.4 : 20 + (r - 5) * .5; R(c, hx - w, b - 30 + r, w * 2, 1, r % 4 === 3 ? '#4a566a' : '#5c6b7a'); } R(c, hx - 21, b - 19, 42, 1, '#f6efe2'); R(c, hx - 7, b - 13, 14, 13, '#f6efe2'); R(c, hx - 5, b - 11, 10, 11, '#4a2a22'); R(c, hx - 16, b - 12, 4, 5, '#4f6f96'); R(c, hx + 12, b - 12, 4, 5, '#4f6f96'); const tx = x + 42; disc(c, tx, b + 8, 14, '#4aa845'); disc(c, tx - 1, b + 6, 11, '#5cc04e'); for (let k = 0; k <= 44; k++) { const w = 6 - k * 5 / 44; R(c, tx - w, b - 4 - k, 1, 1, '#d8dde8'); R(c, tx + w, b - 4 - k, 1, 1, '#aab2c4'); if (k % 7 === 0) R(c, tx - w, b - 4 - k, w * 2, 1, '#c3cad8'); if (k % 7 === 3) line(c, tx - w, b - 4 - k, tx + w, b - 8 - k, '#b6bdcd'); } R(c, tx, b - 54, 1, 6, '#d8dde8'); R(c, x - 6, b + 14, 12, 2, '#c98b4a'); R(c, x - 5, b + 16, 1, 3, '#7a4d2b'); R(c, x + 4, b + 16, 1, 3, '#7a4d2b'); R(c, x - 6, b + 10, 12, 1, '#9a6a40'); }
    if (i === 6) { const mx = x + 8; for (let r = 0; r <= 30; r++) { const w = 5 + r * 4 / 30; R(c, mx - w, b - 30 + r, w * 2, 1, '#efe8da'); R(c, mx + w * .35, b - 30 + r, w * .65, 1, '#cfc6b3'); } tri(c, mx, b - 38, 8, 7, '#a8432f'); R(c, mx - 2, b - 7, 4, 7, '#6b4a2f'); R(c, mx - 1, b - 20, 3, 3, '#4f6f96'); disc(c, x - 38, b + 9, 5, '#a59c88'); disc(c, x - 38, b + 8, 4, '#d8d0bd'); line(c, x - 38, b + 8, x - 35, b + 5, '#5a5346'); bush(c, x + 40, b + 2, 5); }
    if (i === 7) { R(c, x - 24, b - 22, 48, 22, '#8a5a35'); R(c, x - 22, b - 20, 44, 20, '#6a4a33'); for (let r = 0; r < 5; r++) R(c, x - 28 + r, b - 27 + r, 56 - r, 1, r % 2 ? '#4a566a' : '#5c6b7a'); R(c, x - 22, b - 11, 44, 2, '#c98b4a'); R(c, x - 24, b - 22, 2, 22, '#9a6a40'); R(c, x + 22, b - 22, 2, 22, '#6b4226'); disc(c, x - 38, b + 1, 4, '#c98b4a'); R(c, x - 42, b - 1, 9, 1, '#7a4d2b'); tree(c, x + 66, gy(x + 66) + 3, 11, mulberry(12)); }
    if (i === 8) { tree(c, x - 66, gy(x - 66) + 4, 19, mulberry(14)); R(c, x - 24, b - 40, 3, 40, '#7a4d2b'); R(c, x + 21, b - 40, 3, 40, '#5f3b20'); R(c, x - 27, b - 43, 54, 4, '#9a6a40'); R(c, x - 27, b - 40, 54, 1, '#6b4226'); R(c, x - 26, b - 6, 52, 3, '#8a5a35'); R(c, x - 27, b - 1, 5, 2, '#5f3b20'); R(c, x + 22, b - 1, 5, 2, '#5f3b20'); }
  }

  /* ---------- things that answer to the brief ---------- */
  function kite(c, x, y, col, star) { for (let dy = -6; dy <= 7; dy++) { const w = dy < 0 ? Math.round(4 * (1 + dy / 6)) : Math.round(4 * (1 - dy / 7)); R(c, x - w, y + dy, 2 * w + 1, 1, col); } R(c, x, y - 6, 1, 14, 'rgba(0,0,0,.28)'); R(c, x - 4, y, 9, 1, 'rgba(0,0,0,.28)'); if (star) { R(c, x - 1, y - 2, 3, 1, '#fff'); R(c, x, y - 3, 1, 3, '#fff'); } for (let k = 0; k < 3; k++) R(c, x + (k % 2 ? 1 : -1), y + 9 + k * 3, 2, 1, col); }
  function dynamic(c, i) {
    const x = SX(i), b = gy(x) + 5, v = vis;
    if (i === 0) {
      const f = v.format, P = k => T('fmt:' + k, f === k ? 1 : 0);
      let p = P('course'); if (p > .02) for (let k = 0; k < 4; k++) { const fx = x - 18 + k * 17, fb = pathY(fx) - 3, q = clamp(p * 4 - k); if (q > 0) { R(c, fx, fb - 13 * q, 1, 13 * q, '#f2f2f2'); if (q > .7) { R(c, fx + 1, fb - 13, 6, 4, THREADS[k]); R(c, fx + 1, fb - 9, 3, 1, THREADS[k]); } } }
      p = P('workshop'); reveal(c, x + 6, b, 44, 34, p, () => { for (let r = 0; r < 8; r++) { const half = 13 + r; for (let xx = -half; xx <= half; xx++) R(c, x + 6 + xx, b - 31 + r, 1, 1, (Math.floor((xx + 40) / 4) % 2) ? '#ff7a59' : '#fff4e0'); } R(c, x - 13, b - 23, 2, 23, '#7a4d2b'); R(c, x + 24, b - 23, 2, 23, '#6b4226'); R(c, x - 7, b - 9, 26, 3, '#d9a05c'); R(c, x - 5, b - 6, 2, 6, '#7a4d2b'); R(c, x + 15, b - 6, 2, 6, '#7a4d2b'); R(c, x - 3, b - 12, 3, 3, THREADS[2]); R(c, x + 4, b - 11, 4, 2, THREADS[1]); R(c, x + 12, b - 13, 2, 4, THREADS[0]); });
      p = P('cohort'); reveal(c, x + 6, b + 8, 52, 16, p, () => { for (const [dx, dy] of [[-18, 0], [18, 0], [-10, -6], [10, -6], [-12, 6], [12, 6]]) { R(c, x + 6 + dx - 3, b + dy - 3, 6, 4, '#8a5a35'); R(c, x + 6 + dx - 3, b + dy - 3, 6, 1, '#c98b4a'); } R(c, x + 2, b, 9, 2, '#8d8d99'); R(c, x + 3, b - 1, 7, 1, '#5a3a22'); });
      p = P('talk'); reveal(c, x + 6, b, 40, 34, p, () => { R(c, x - 9, b - 27, 30, 21, '#8a2f4a'); for (let k = 0; k < 6; k++) R(c, x - 7 + k * 5, b - 27, 1, 21, '#6e2038'); R(c, x - 12, b - 6, 36, 6, '#a8713d'); R(c, x - 12, b - 6, 36, 1, '#d9a05c'); R(c, x + 3, b - 14, 6, 8, '#d9a05c'); R(c, x + 4, b - 15, 4, 1, '#fff4e0'); for (let k = 0; k < 7; k++) tri(c, x - 8 + k * 5, b - 30, 3, 2, THREADS[k % 4]); });
      p = P('clinic'); reveal(c, x + 6, b, 34, 32, p, () => { R(c, x - 7, b - 18, 26, 18, '#f0e0c0'); R(c, x - 5, b - 9, 22, 9, '#d9c49a'); for (let r = 0; r < 5; r++) R(c, x - 9 - r * .5, b - 23 + r, 30 + r, 1, r % 2 ? '#3f7fd6' : '#eaf5ff'); R(c, x + 3, b - 29, 7, 6, '#fff'); R(c, x + 5, b - 28, 3, 1, '#2a2f6e'); R(c, x + 7, b - 27, 1, 1, '#2a2f6e'); R(c, x + 6, b - 26, 1, 1, '#2a2f6e'); R(c, x + 6, b - 24, 1, 1, '#2a2f6e'); });
      p = P('__custom'); reveal(c, x + 6, b, 24, 28, p, () => { line(c, x, b, x + 6, b - 24, '#7a4d2b'); line(c, x + 12, b, x + 6, b - 24, '#7a4d2b'); R(c, x - 2, b - 22, 17, 13, '#fff'); R(c, x - 2, b - 22, 17, 1, '#d9a05c'); R(c, x + 1, b - 18, 8, 1, THREADS[3]); R(c, x + 1, b - 15, 11, 1, THREADS[2]); });
    }
    if (i === 1) {
      const names = v.topics || [], n = Math.max(names.length, v.entry ? 1 : 0), sep = v.mode === 'separate';
      const sway = reduce ? 0 : Math.round(Math.sin(amb * .7));
      for (let k = 0; k < 3; k++) {
        const on = k < n, up = T('kite:' + k, on ? (k < names.length ? 1 : .12) : 0, 5); if (up < .02) continue;
        const px = T('kpost:' + k, sep ? x - 34 + k * 34 : (names.length > 1 ? x : x - 6 + k * 4), 7), pb = gy(Math.round(px)) + 8;
        const kx = x - 26 + k * 28 + (k === 1 ? sway : -sway), ky = lerp(pb - 9, G - (H * .32) - k * 13, up);
        R(c, px, pb - 6, 2, 7, '#7a4d2b'); line(c, px, pb - 6, kx, ky + 7, '#f4f4f4'); kite(c, kx, ky, THREADS[k], v.world && k === 0);
      }
    }
    if (i === 2) {
      const au = v.audience, sel = { school: au === 'school' || au === 'mixed', college: au === 'college' || au === 'mixed', workshop: au === 'pro' || au === 'mixed' };
      const bx = { school: x - 42, college: x, workshop: x + 43 }, top = { school: 38, college: 31, workshop: 31 };
      let n = 0; for (const k of ['school', 'college', 'workshop']) { const p = T('aud:' + k, sel[k] ? 1 : 0); if (p > .02) { const fx = bx[k] + (k === 'workshop' ? -8 : 6), fy = b - top[k]; R(c, fx, fy - 9 * p, 1, 9 * p, '#f2f2f2'); if (p > .6) R(c, fx + 1, fy - 9, 6, 4, THREADS[n % 4]); for (let j = 0; j < 3; j++) { const q = clamp(p * 3 - j); if (q > .1) person(c, bx[k] - 8 + j * 8, b + 6 + (j % 2) * 3 + (1 - q) * 3, THREADS[(j + n) % 4], 0, j % 2 ? '#7a4d2b' : '#2a2030'); } } n++; }
      const pc = T('aud:custom', au === '__custom' ? 1 : 0); if (pc > .02) for (let j = 0; j < 5; j++) { const q = clamp(pc * 5 - j); if (q > .1) person(c, x - 18 + j * 9, b + 10 + (j % 2) * 2, THREADS[j % 4], 0); }
    }
    if (i === 3) {
      const map = { new: 0, some: 2, solid: 4 }, pr = v.prior, un = T('prior:unsure', pr === 'unsure' ? 1 : 0), has = T('prior:on', pr ? 1 : 0);
      const s = T('prior:s', pr in map ? map[pr] : 0, 6);
      if (has > .02) { const cx = lerp(x - 25 + s * 11, x - 56, un), cy = lerp(b - 5 - s * 7, b + 2, un); person(c, cx, cy, THREADS[0], Math.abs(s % 1) > .1 && Math.floor(amb * 8) % 2); }
      const fl = T('prior:flag', pr === 'solid' ? 1 : 0); if (fl > .3) { R(c, x + 31, b - 50, 7, 4, THREADS[1]); R(c, x + 31, b - 46, 4, 1, THREADS[1]); }
      if (un > .3) { R(c, x - 44, b - 9, 8, 7, '#fff'); R(c, x - 42, b - 8, 3, 1, '#2a2f6e'); R(c, x - 40, b - 7, 1, 2, '#2a2f6e'); R(c, x - 41, b - 4, 1, 1, '#2a2f6e'); }
    }
    if (i === 4) {
      const p = T('bridge', v.outcome || 0, 6), py = pathY(x), n = Math.round(p * 12);
      for (let k = 0; k < n; k++) { R(c, x - 16 + k * 4, py - 2, 3, 5, k % 2 ? '#c98b4a' : '#d9a05c'); R(c, x - 16 + k * 4, py + 3, 3, 1, '#7a4d2b'); }
      if (n > 1) for (let k = 0; k < n * 4; k++) { const f = k / 47; R(c, x - 17 + k, py - 9 + Math.round(Math.sin(f * Math.PI) * 4), 1, 1, '#f2e6cf'); }
      const fl = T('bridge:flag', (v.outcome || 0) >= 1 ? 1 : 0); if (fl > .02) { R(c, x + 40, py - 4 - 16 * fl, 1, 16 * fl, '#f2f2f2'); if (fl > .7) { R(c, x + 41, py - 20, 8, 5, THREADS[0]); R(c, x + 41, py - 15, 5, 1, THREADS[0]); } }
    }
    if (i === 5) {
      const dl = v.delivery, self = T('del:self', dl === 'self' || dl === 'blended' ? 1 : 0);
      if (self > .3) { R(c, x + 9, b + 7, 1, 7, '#5a5346'); R(c, x + 8, b + 4, 3, 4, '#3a3a44'); person(c, x - 2, b + 14, THREADS[2]); }
      const room = T('del:room', dl === 'room' || dl === 'blended' || dl === 'hybrid' ? 1 : 0); if (room > .3) for (let j = 0; j < 3; j++) person(c, x - 50 + j * 9, b + 8 + (j % 2) * 3, THREADS[(j + 1) % 4], 0, '#2a2030');
    }
    if (i === 6) {
      const mx = x + 8, hub = b - 30, ang = T('mill', (v.turn || 0) * Math.PI / 4, 5);
      for (let k = 0; k < 4; k++) { const t = ang + k * Math.PI / 2, ex = mx + Math.cos(t) * 22, ey = hub + Math.sin(t) * 22; line(c, mx, hub, ex, ey, '#7a4d2b'); const nx = -Math.sin(t), ny = Math.cos(t); for (let s = 6; s < 22; s += 1) for (let wdt = 1; wdt < 6; wdt++) if ((s + wdt) % 3) R(c, mx + Math.cos(t) * s + nx * wdt, hub + Math.sin(t) * s + ny * wdt, 1, 1, (s >> 1) % 2 ? '#f6efe2' : '#dcd3c0'); }
      disc(c, mx, hub, 2, '#5f3b20');
      const n = v.sessions || 0, gap = Math.min(12, 108 / Math.max(1, n)); for (let k = 0; k < 52; k++) { const p = T('stone:' + k, k < n ? 1 : 0, 10); if (p > .05) { const sx = Math.round(x - 52 + k * gap), sy = pathY(sx); R(c, sx - 2, sy - 1 - 2 * p, 5, 3, '#d8d0bd'); R(c, sx - 2, sy + 1 - 2 * p, 5, 1, '#a59c88'); } }
    }
    if (i === 7) {
      const it = v.limits || [], slot = { phones: [-17, -12], laptops: [-5, -12], nodevice: [8, -12], lowweb: [18, -12], free: [-21, -1], language: [-11, -1], access: [1, -1], none: [14, -1], __custom: [14, -1] };
      for (const k in slot) { const p = T('lim:' + k, it.includes(k) ? 1 : 0, 12); if (p < .05) continue; const ix = x + slot[k][0], iy = b + slot[k][1] - (1 - p) * 5;
        if (k === 'phones') { R(c, ix, iy - 7, 4, 7, '#1d2233'); R(c, ix + 1, iy - 6, 2, 4, '#7cc0ff'); }
        if (k === 'laptops') { R(c, ix, iy - 6, 8, 5, '#c3cad8'); R(c, ix + 1, iy - 5, 6, 3, '#7cc0ff'); R(c, ix - 1, iy - 1, 10, 1, '#8d8d99'); }
        if (k === 'nodevice') { R(c, ix, iy - 5, 6, 5, '#fff4e0'); R(c, ix + 1, iy - 3, 4, 1, '#b9a88a'); line(c, ix + 6, iy - 7, ix + 3, iy - 1, THREADS[1]); }
        if (k === 'lowweb') { R(c, ix, iy - 2, 1, 2, '#ff5d73'); R(c, ix + 2, iy - 4, 1, 4, '#6b7488'); R(c, ix + 4, iy - 6, 1, 6, '#6b7488'); }
        if (k === 'language') { R(c, ix, iy - 8, 9, 6, '#fff'); R(c, ix + 2, iy - 2, 2, 2, '#fff'); R(c, ix + 2, iy - 6, 5, 1, THREADS[3]); R(c, ix + 2, iy - 4, 3, 1, THREADS[3]); }
        if (k === 'access') { R(c, ix, iy - 9, 9, 9, '#2f6fd6'); R(c, ix + 4, iy - 8, 1, 1, '#fff'); R(c, ix + 2, iy - 6, 5, 1, '#fff'); R(c, ix + 4, iy - 6, 1, 3, '#fff'); R(c, ix + 3, iy - 3, 1, 2, '#fff'); R(c, ix + 5, iy - 3, 1, 2, '#fff'); }
        if (k === 'free') { R(c, ix, iy - 6, 8, 6, '#fff4e0'); R(c, ix + 1, iy - 7, 2, 1, '#fff4e0'); R(c, ix + 3, iy - 5, 3, 1, '#2f8a3a'); R(c, ix + 3, iy - 2, 3, 1, '#2f8a3a'); R(c, ix + 2, iy - 4, 1, 2, '#2f8a3a'); R(c, ix + 6, iy - 4, 1, 2, '#2f8a3a'); }
        if (k === '__custom') { R(c, ix, iy - 7, 8, 7, '#c98b4a'); R(c, ix, iy - 7, 8, 1, '#e0a868'); R(c, ix + 3, iy - 5, 2, 3, '#fff4e0'); }
        if (k === 'none') { R(c, ix, iy - 4, 5, 3, '#ffd23f'); R(c, ix + 4, iy - 6, 3, 3, '#ffd23f'); R(c, ix + 7, iy - 5, 1, 1, '#ff9a5c'); R(c, ix + 1, iy - 1, 1, 1, '#ff9a5c'); R(c, ix + 3, iy - 1, 1, 1, '#ff9a5c'); }
      }
    }
    if (i === 8) {
      const n = Math.max(1, (v.topics || []).length), lit = T('loom', v.lit ? 1 : 0, 3), rows = Math.round(lit * Math.min(30, (v.sessions || 3) * 3 + 6));
      for (let k = 0; k < 14; k++) R(c, x - 19 + k * 3, b - 39, 1, 33, v.topics && v.topics.length ? THREADS[k % n] : '#e9e2d0');
      for (let r = 0; r < rows; r++) for (let k = 0; k < 40; k++) R(c, x - 20 + k, b - 7 - r, 1, 1, THREADS[((k >> 1) + r + ((r >> 2) % 2 ? 1 : 0)) % Math.max(2, n + 1) % 4]);
      const m = v.sessions || 0, sp = Math.min(24, (W - 40) / Math.max(1, m)), st = x - sp * (m - 1) / 2;
      for (let k = 0; k < m; k++) { const lx = Math.round(st + k * sp), ly = pathY(lx) + 9; R(c, lx, ly - 11, 1, 11, '#5a5346'); R(c, lx - 1, ly - 15, 3, 4, '#2c2c38'); }
    }
  }
  function glow(c, x, y, r, col, al) { c.globalAlpha = al; disc(c, x, y, r, col); c.globalAlpha = al * .7; disc(c, x, y, r * .6, col); c.globalAlpha = 1; }
  function emissive(c, i, nf) {
    const x = SX(i), b = gy(x) + 5, v = vis, fl = reduce ? 0 : Math.floor(amb * 5) % 2;
    if (i === 0) { const p = T('fmt:cohort', v.format === 'cohort' ? 1 : 0); if (p > .5) { c.globalCompositeOperation = 'source-over'; tri(c, x + 6, b - 8 - fl, 7 + fl, 3, '#ff9a5c'); tri(c, x + 6, b - 5, 4, 2, '#ffe08a'); c.globalCompositeOperation = 'lighter'; glow(c, x + 6, b - 4, 12, '#ff9a5c', .1 + nf * .16); } }
    if (i === 2) { const au = v.audience, sel = { school: au === 'school' || au === 'mixed', college: au === 'college' || au === 'mixed', workshop: au === 'pro' || au === 'mixed' }, bx = { school: x - 42, college: x, workshop: x + 43 }, by = { school: b, college: b - 1, workshop: b }; for (const k in sel) { const p = T('aud:' + k, sel[k] ? 1 : 0); if (p > .4) { c.globalCompositeOperation = 'source-over'; for (const w of WINDOWS[k]) R(c, bx[k] + w[0], by[k] + w[1], w[2], w[3], '#ffe08a'); c.globalCompositeOperation = 'lighter'; for (const w of WINDOWS[k]) glow(c, bx[k] + w[0] + 2, by[k] + w[1] + 2, 6, '#ffb84a', .08 + nf * .14); } } }
    if (i === 5) { const dl = v.delivery, on = T('del:on', dl === 'live' || dl === 'blended' || dl === 'hybrid' ? 1 : 0), room = T('del:room', dl === 'room' || dl === 'blended' || dl === 'hybrid' ? 1 : 0), self = T('del:self', dl === 'self' || dl === 'blended' ? 1 : 0), tx = x + 42; c.globalCompositeOperation = 'source-over'; R(c, tx - 1, b - 56, 3, 3, on > .5 ? '#ff5d73' : '#7a3340'); if (on > .1) { for (let k = 1; k <= 3; k++) { const q = clamp(on * 3 - (k - 1)); if (q <= 0) continue; c.globalAlpha = q * (1 - k * .18); const r = 5 + k * 6; for (let t = -.9; t <= .9; t += .09) { R(c, tx + Math.cos(t) * r, b - 55 + Math.sin(t) * r, 1, 1, '#ffffff'); R(c, tx - Math.cos(t) * r, b - 55 + Math.sin(t) * r, 1, 1, '#ffffff'); } } c.globalAlpha = 1; c.globalCompositeOperation = 'lighter'; glow(c, tx, b - 55, 7, '#ff5d73', .2); } if (room > .4) { c.globalCompositeOperation = 'source-over'; R(c, x - 45, b - 11, 10, 11, '#ffe08a'); R(c, x - 56, b - 12, 4, 5, '#ffe08a'); R(c, x - 28, b - 12, 4, 5, '#ffe08a'); c.globalCompositeOperation = 'lighter'; glow(c, x - 40, b - 4, 14, '#ffb84a', .1 + nf * .12); } if (self > .4) { c.globalCompositeOperation = 'source-over'; R(c, x + 8, b + 5, 3, 2, '#ffe08a'); c.globalCompositeOperation = 'lighter'; glow(c, x + 9, b + 6, 8, '#ffb84a', .14 + nf * .12); } }
    if (i === 8) { const m = v.sessions || 0, sp = Math.min(24, (W - 40) / Math.max(1, m)), st = x - sp * (m - 1) / 2; for (let k = 0; k < m; k++) { const p = T('lan:' + k, v.lit ? 1 : 0, 2.2 + k * .9), s = T('lsel:' + k, v.sel === k ? 1 : 0, 12); if (p < .3) continue; const lx = Math.round(st + k * sp), ly = pathY(lx) + 9 - 13; c.globalCompositeOperation = 'source-over'; R(c, lx - 1, ly - 1, 3, 3, s > .5 ? '#ffffff' : '#ffe08a'); c.globalCompositeOperation = 'lighter'; glow(c, lx, ly, 8 + s * 7, THREADS[1], .1 + s * .14); }
      if (v.lit && !reduce) for (let k = 0; k < 14; k++) { const fx = x - 150 + h2(k, 1) * 300 + Math.sin(amb * .4 + k) * 6, fy = G + 10 + h2(k, 2) * (H - G - 40) + Math.cos(amb * .3 + k * 2) * 4; if ((Math.floor(amb * 1.5) + k) % 3) { c.globalCompositeOperation = 'source-over'; R(c, fx, fy, 1, 1, '#e8ff9a'); c.globalCompositeOperation = 'lighter'; glow(c, fx, fy, 3, '#c8ff6a', .16); } } }
    c.globalCompositeOperation = 'source-over';
  }

  /* ---------- frame ---------- */
  function drawSky(s) {
    const key = Math.round(tod * 400); if (key !== skyKey) { skyKey = key; const img = sk.createImageData(4, H), d = img.data, bands = 18; for (let y = 0; y < H; y++) for (let x = 0; x < 4; x++) { const f = clamp(y / (G + 6)), q = clamp(Math.floor(f * bands + BAYER[(y & 3) * 4 + x] * .999) / bands), col = q < .55 ? mix3(s[0], s[1], q / .55) : mix3(s[1], s[2], (q - .55) / .45), o = (y * 4 + x) * 4; d[o] = col[0]; d[o + 1] = col[1]; d[o + 2] = col[2]; d[o + 3] = 255; } sk.putImageData(img, 0, 0); }
    ctx.fillStyle = ctx.createPattern(skyT, 'repeat'); ctx.fillRect(0, 0, W, H);
  }
  function draw() {
    if (!L) return;
    const s = skyAt(tod), nf = clamp((tod - 5.6) / 2), night = clamp((tod - 6.8) / 1.2), cx = Math.round(cam);
    a.clearRect(0, 0, W, H);
    const drift = reduce ? 0 : amb * .6;
    for (const cl of clouds) { const span = W + 260, px = (((cl.x - cam * .08 + drift * cl.sp) % span) + span) % span - 130; a.drawImage(cl.cv, Math.round(px), cl.y); }
    a.drawImage(L.far, -Math.round(cam * .2), 0); a.drawImage(L.mid, -Math.round(cam * .45), 0); a.drawImage(L.main, -cx, 0);
    a.save(); a.translate(-cx, 0);
    for (let i = 0; i < 9; i++) if (Math.abs(SX(i) - (cam + W / 2)) < W / 2 + 200) dynamic(a, i);
    const hv = Math.abs(heroT - heroX) > .6 && !reduce; person(a, Math.round(heroX), pathY(Math.round(heroX)) + 1, '#2f4f9f', hv && Math.floor(amb * 9) % 2, '#3a2a4a'); R(a, Math.round(heroX) - 2, pathY(Math.round(heroX)) - 5, 5, 1, THREADS[0]);
    a.restore();
    a.drawImage(L.fore, -Math.round(cam * 1.5), 0);
    if (wide) { const bx = W - 6, by = -4; for (const [dx, dy, r] of [[0, 0, 22], [-24, 2, 15], [-40, -2, 11], [4, 22, 13], [-14, 16, 11]]) disc(a, bx + dx, by + dy, r, '#1f6a3a'); for (const [dx, dy, r] of [[-2, -2, 18], [-25, 0, 11], [3, 19, 9], [-15, 13, 8]]) disc(a, bx + dx, by + dy, r, '#2c8446'); for (const [dx, dy, r] of [[-8, 4, 8], [-28, 4, 5], [-2, 22, 4]]) disc(a, bx + dx, by + dy, r, '#46a052'); }
    bq.globalCompositeOperation = 'copy'; bq.drawImage(A, 0, 0); bq.globalCompositeOperation = 'multiply'; bq.fillStyle = css(s[3]); bq.fillRect(0, 0, W, H); bq.globalCompositeOperation = 'destination-in'; bq.drawImage(A, 0, 0);
    drawSky(s);
    if (night > 0) { for (const st of stars) { const tw2 = reduce ? 1 : ((Math.floor(amb * 1.2 + st[2] * 9) % 5) ? 1 : .4); ctx.globalAlpha = night * tw2 * (.5 + st[2] * .5); ctx.fillStyle = '#fff'; ctx.fillRect(Math.round(st[0] * W), Math.round(st[1] * G), 1, 1); } ctx.globalAlpha = 1; }
    const sx = W * (.84 - .045 * tod), sy = G - 10 - Math.sin(Math.PI * clamp((tod + .35) / 7.7)) * (G - 34);
    if (night < 1) { ctx.globalAlpha = 1 - night; ctx.globalCompositeOperation = 'lighter'; glow(ctx, sx, sy, 26, css(mix3([255, 236, 170], [255, 150, 90], clamp((tod - 5) / 2))), .1); glow(ctx, sx, sy, 16, '#ffe9a8', .14); ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1 - night; disc(ctx, sx, sy, 8, css(mix3([255, 246, 205], [255, 190, 120], clamp((tod - 5) / 2)))); ctx.globalAlpha = 1; }
    if (night > 0) { ctx.globalAlpha = night; const mx = W * .8, my = H * .15; ctx.globalCompositeOperation = 'lighter'; glow(ctx, mx, my, 18, '#9fb4ff', .1); ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = night; disc(ctx, mx, my, 7, '#f4f1d8'); disc(ctx, mx + 3, my - 2, 6, css(s[0])); ctx.globalAlpha = 1; }
    ctx.drawImage(B, 0, 0);
    ctx.save(); ctx.translate(-cx, 0);
    for (let i = 0; i < 9; i++) if (Math.abs(SX(i) - (cam + W / 2)) < W / 2 + 200) emissive(ctx, i, nf);
    const now = performance.now();
    for (let k = sparks.length - 1; k >= 0; k--) { const sp = sparks[k], t = (now - sp.t) / 420; if (t >= 1) { sparks.splice(k, 1); continue; } moving = true; ctx.globalAlpha = 1 - t; for (let j = 0; j < 8; j++) { const an = j * Math.PI / 4, d = 4 + t * 14 * (1 - t * .4); R(ctx, sp.x + Math.cos(an) * d, sp.y + Math.sin(an) * d, j % 2 ? 1 : 2, j % 2 ? 1 : 2, THREADS[j % 4]); } ctx.globalAlpha = 1; }
    ctx.restore();
    first = false;
  }
  function targets() { const f = centre ? .5 : (wide ? .68 : .5); camT = clamp(SX(station) + sub * 26 - f * W, 0, WORLDW - W); todT = clamp(station + sub * .14, 0, 8); heroT = SX(station) - 50 + sub * 12; }
  function frame(ts) {
    dtc = Math.min(.05, (ts - last) / 1000 || 0); last = ts; amb += dtc; moving = false;
    const step = (v, t, sp) => { const d = t - v; if (Math.abs(d) < .05) return t; moving = true; return reduce ? t : v + d * (1 - Math.exp(-dtc * sp)); };
    cam = step(cam, camT, 5.5); heroX = step(heroX, heroT, 4); const dT = todT - tod; if (Math.abs(dT) > .002) { tod = reduce ? todT : tod + dT * (1 - Math.exp(-dtc * 4)); moving = true; } else tod = todT;
    const tk = Math.floor(amb * 4); if (tk !== tick && !reduce) { tick = tk; dirty = true; }
    if (!L && window.innerWidth > 0 && window.innerHeight > 0) resize();
    try { if (L && (dirty || moving)) { dirty = false; draw(); if (moving) dirty = true; } }
    catch (e) { console.error('Loom world draw failed', e); }
    requestAnimationFrame(frame);
  }
  function resize() {
    const vw = window.innerWidth, vh = window.innerHeight; if (!(vw > 0 && vh > 0)) return;
    const w2 = vw >= 860, sc = Math.max(2, Math.floor(vh / (w2 ? 188 : 225))), nW = Math.ceil(vw / sc), nH = Math.ceil(vh / sc);
    const rebuild = nH !== H || w2 !== wide || !L; wide = w2; scale = sc; W = nW; H = nH; G = H - Math.round(H * (wide ? .38 : .3));
    canvas.width = W; canvas.height = H; canvas.style.width = W * scale + 'px'; canvas.style.height = H * scale + 'px'; A.width = B.width = W; A.height = B.height = H; skyT.width = 4; skyT.height = H; skyKey = -1;
    if (rebuild) build(); targets(); cam = camT; dirty = true;
  }
  let rt = 0; window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(resize, 120); });
  resize(); cam = camT; tod = todT; heroX = heroT; requestAnimationFrame(frame);

  return {
    go(st, sb = 0, opts = {}) { station = st; sub = sb; centre = !!opts.centre; targets(); if (first || reduce || opts.jump) { cam = camT; tod = todT; heroX = heroT; } dirty = true; },
    setVis(v) { vis = v; dirty = true; },
    spark() { if (reduce) return; const x = SX(station), y = gy(x) - 12; sparks.push({ x, y, t: performance.now() }); dirty = true; },
    setReduce(r) { reduce = r; dirty = true; },
    info: () => ({ W, H, scale, wide, cam, tod, station })
  };
}
