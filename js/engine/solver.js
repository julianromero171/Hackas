/**
 * Orquestador del motor híbrido:
 *   1) CSP constructivo (MRV)  2) Reparación dirigida + Kempe  3) Simulated Annealing
 * Multi-arranque si no se alcanza H=0. Soporta "warm start" desde el horario actual
 * (re-optimización incremental tras cada instrucción del copiloto) y lecciones fijadas.
 */
import { buildProblem, isValidGrid, DEFAULT_WEIGHTS } from './model.js';
import { TimetableState } from './state.js';
import { construct } from './construct.js';
import { anneal } from './annealing.js';
import { computeMetrics, assignRooms } from './metrics.js';
import { mulberry32, now, log10Factorial } from '../core/utils.js';

export const ENGINE_NAME = 'CSP constructivo + Kempe + Simulated Annealing';

export function solve({
  data, rules = [], weights = DEFAULT_WEIGHTS, warmGrid = null, pinned = [],
  seed, timeLimitMs = 900, maxAttempts = 4,
} = {}) {
  const t0 = now();
  const P = buildProblem(data, rules);
  const rng = mulberry32(seed ?? ((Math.random() * 2 ** 31) | 0));
  const useWarm = !!warmGrid && isValidGrid(P, warmGrid);
  const pin = new Uint8Array(P.lessons.length);
  if (useWarm) for (const id of pinned) if (id >= 0 && id < pin.length) pin[id] = 1;
  const hasPins = useWarm && pinned.length > 0;

  let best = null, attempts = 0, constructHard = null, iterations = 0, kempeMoves = 0;
  for (attempts = 0; attempts < maxAttempts; attempts++) {
    const grid = attempts === 0 && useWarm ? warmGrid : construct(P, rng, weights);
    const st = new TimetableState(P, grid, weights);
    if (constructHard === null) constructHard = st.totals().hard;
    const res = anneal(st, {
      rng,
      timeLimitMs: attempts === 0 ? timeLimitMs : timeLimitMs * 0.75,
      pinned: hasPins && attempts === 0 ? pin : null,
    });
    iterations += res.iterations;
    kempeMoves += res.kempeMoves;
    if (!best || res.hard < best.hard || (res.hard === best.hard && res.soft < best.soft)) best = res;
    if (best.hard === 0 || P.blocking) break;
  }

  const metrics = computeMetrics(P, best.grid, weights);
  const rooms = assignRooms(P, best.grid);
  return {
    grid: best.grid,
    rooms,
    metrics,
    issues: P.issues,
    stats: {
      engine: ENGINE_NAME,
      ms: now() - t0,
      iterations,
      kempeMoves,
      attempts: Math.min(attempts + 1, maxAttempts),
      constructHard,
      warm: useWarm,
      lessons: P.lessons.length,
      slots: P.S * P.nC,
      searchSpaceLog10: P.nC * log10Factorial(P.S),
    },
  };
}
