/**
 * Utilidades compartidas (sin dependencias de DOM: usables en navegador, Web Worker y Node).
 */

/** Minúsculas + sin tildes/diacríticos ("Miércoles" -> "miercoles", "Peña" -> "pena"). */
export const normalize = (s = '') =>
  String(s).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

export const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export function escapeHtml(s = '') {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** PRNG determinista (Mulberry32) para reproducibilidad de corridas. */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function rng() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const now = () => (globalThis.performance ? globalThis.performance.now() : Date.now());

export function debounce(fn, ms = 300) {
  let id;
  return (...args) => {
    clearTimeout(id);
    id = setTimeout(() => fn(...args), ms);
  };
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export const initials = (name = '') =>
  name.split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join('').toUpperCase();

export const shortName = (name = '') => {
  const p = name.split(/\s+/).filter(Boolean);
  return p.length > 1 ? `${p[0][0]}. ${p.slice(1).join(' ')}` : name;
};

/** [1,2,3,5] -> [[1,3],[5,5]] */
export function compressRanges(nums = []) {
  const s = [...new Set(nums)].sort((a, b) => a - b);
  const out = [];
  for (const n of s) {
    const last = out[out.length - 1];
    if (last && n === last[1] + 1) last[1] = n;
    else out.push([n, n]);
  }
  return out;
}

export function log10Factorial(n) {
  let s = 0;
  for (let k = 2; k <= n; k++) s += Math.log10(k);
  return s;
}

export const fmtNum = (v, dec = 0) =>
  Number(v).toLocaleString('es-CO', { minimumFractionDigits: dec, maximumFractionDigits: dec });
