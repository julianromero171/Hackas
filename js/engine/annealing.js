/**
 * Fase 2/3 — Reparación + Simulated Annealing.
 *
 * Vecindario: (a) swap de dos slots dentro de un curso, (b) cadena de Kempe multi-curso.
 * - Mientras existan violaciones duras (H>0) se usa una penalización finita y los
 *   movimientos se enfocan en celdas en conflicto (reparación dirigida).
 * - Una vez H=0, cualquier movimiento que aumente H se rechaza: la búsqueda queda
 *   confinada al espacio factible y solo optimiza la función blanda.
 * Enfriamiento geométrico T = T0·(Tend/T0)^progreso, con corte por estancamiento.
 */
import { kempeChain } from './kempe.js';
import { now } from '../core/utils.js';

const INFEASIBLE_HARD_W = 40;

export function anneal(state, opts) {
  const P = state.P, g = state.grid, L = P.lessons, nC = P.nC, S = P.S;
  const {
    rng, timeLimitMs = 800, maxIters = 500000, T0 = 4, Tend = 0.03,
    kempeProb = 0.25, pinned = null, stallIters = 60000,
  } = opts;

  const tot = state.totals();
  let hard = tot.hard, soft = tot.soft;
  let bestHard = hard, bestSoft = soft;
  const bestGrid = state.snapshot();
  const start = now();
  let it = 0, accepted = 0, kempeMoves = 0, lastImprove = 0, T = T0;
  let conflicts = hard > 0 ? state.conflictCells() : [];
  const C1 = [0];

  for (it = 0; it < maxIters; it++) {
    if ((it & 511) === 0) {
      const el = now() - start;
      if (el > timeLimitMs) break;
      const frac = Math.max(it / maxIters, el / timeLimitMs);
      T = T0 * Math.pow(Tend / T0, frac);
      if (hard > 0) conflicts = state.conflictCells();
      if (bestHard === 0 && it - lastImprove > stallIters) break;
    }

    let c, t1;
    if (hard > 0 && conflicts.length && rng() < 0.75) {
      const code = conflicts[(rng() * conflicts.length) | 0];
      c = (code / S) | 0;
      t1 = code % S;
    } else {
      c = (rng() * nC) | 0;
      t1 = (rng() * S) | 0;
    }
    const t2 = (rng() * S) | 0;
    if (t1 === t2) continue;
    const row = g[c];
    const a = row[t1], b = row[t2];
    if (a < 0 && b < 0) continue;
    if (a >= 0 && b >= 0 && L[a].s === L[b].s) continue;

    let C;
    if (rng() < kempeProb) C = kempeChain(state, c, t1, t2);
    else { C1[0] = c; C = C1; }
    if (pinned && touchesPinned(pinned, g, C, t1, t2)) continue;

    state.applyMove(C, t1, t2);
    const dH = state.dHard, dS = state.dSoft;
    let accept;
    if (hard === 0) {
      accept = dH <= 0 && (dS <= 0 || rng() < Math.exp(-dS / T));
    } else {
      const d = dH * INFEASIBLE_HARD_W + dS;
      accept = d <= 0 || rng() < Math.exp(-d / (T * 4));
    }

    if (accept) {
      hard += dH;
      soft += dS;
      accepted++;
      if (C.length > 1) kempeMoves++;
      if (hard < bestHard || (hard === bestHard && soft < bestSoft - 1e-6)) {
        bestHard = hard;
        bestSoft = soft;
        for (let x = 0; x < nC; x++) {
          const src = g[x], dst = bestGrid[x];
          for (let t = 0; t < S; t++) dst[t] = src[t];
        }
        lastImprove = it;
      }
    } else {
      state.swap(C, t1, t2); // deshacer
    }
  }

  return { grid: bestGrid, hard: bestHard, soft: bestSoft, iterations: it, accepted, kempeMoves, elapsed: now() - start };
}

function touchesPinned(pinned, g, C, t1, t2) {
  for (let i = 0; i < C.length; i++) {
    const row = g[C[i]];
    const a = row[t1], b = row[t2];
    if ((a >= 0 && pinned[a]) || (b >= 0 && pinned[b])) return true;
  }
  return false;
}
