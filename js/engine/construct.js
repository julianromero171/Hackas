/**
 * Fase 1 — CSP constructivo con heurística MRV (Minimum Remaining Values):
 * se ubican primero las lecciones más restringidas (docente con poca holgura,
 * espacios escasos, materias pesadas) en el slot de menor costo (forward checking
 * sobre cruces docentes, disponibilidad, aulas y franjas prohibidas).
 */
import { HARD_WEIGHT } from './model.js';

export function construct(P, rng, weights = {}) {
  const { nC, S, B, lessons: L } = P;
  const grid = Array.from({ length: nC }, () => new Int32Array(S).fill(-1));
  const tc = Array.from({ length: P.nT }, () => new Uint8Array(S));
  const tyc = P.types.map(() => new Uint8Array(S));
  const wm = weights.morning ?? 1;

  const key = new Float64Array(L.length);
  for (const l of L) {
    key[l.id] = (P.teacherAvail[l.p] - P.teacherLoad[l.p])
      + (P.typeScarce[l.type] ? -8 : 0)
      + (l.heavy ? -2 : 0)
      + rng() * 3;
  }
  const order = L.map((l) => l.id).sort((a, b) => key[a] - key[b]);

  for (const id of order) {
    const l = L[id];
    const row = grid[l.c];
    let best = -1, bestCost = Infinity;
    for (let t = 0; t < S; t++) {
      if (row[t] >= 0) continue;
      let cost = 0;
      if (tc[l.p][t]) cost += HARD_WEIGHT;
      if (P.unavailable[l.p][t]) cost += HARD_WEIGHT;
      if (P.forbidden[l.s][t]) cost += HARD_WEIGHT;
      if (!P.typeSimple[l.type] || P.typeScarce[l.type]) {
        if (tyc[l.type][t] >= P.typeSupply[l.type]) cost += HARD_WEIGHT;
      }
      const b = t % B, base = t - b;
      let dup = 0, heavyDay = 0;
      for (let k = 0; k < B; k++) {
        const o = row[base + k];
        if (o >= 0) {
          if (L[o].s === l.s) dup++;
          if (L[o].heavy) heavyDay++;
        }
      }
      cost += dup * 6 + P.softSlot[l.s][t] * wm * 0.5;
      if (l.heavy) { cost += heavyDay * 2; if (b === B - 1) cost += 3; }
      cost += rng() * 1.5;
      if (cost < bestCost) { bestCost = cost; best = t; }
    }
    if (best < 0) continue; // sin espacio (inviable estáticamente; se reporta en issues)
    row[best] = id;
    tc[l.p][best]++;
    tyc[l.type][best]++;
  }
  return grid.map((r) => Array.from(r));
}
