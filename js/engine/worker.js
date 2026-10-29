/** Web Worker: ejecuta el motor fuera del hilo de UI para mantener 60 fps. */
import { solve } from './solver.js';

self.onmessage = (e) => {
  const { id, payload } = e.data;
  try {
    const result = solve(payload);
    self.postMessage({ id, ok: true, result });
  } catch (err) {
    self.postMessage({ id, ok: false, error: err?.message || String(err) });
  }
};
