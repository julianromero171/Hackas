/**
 * Cliente del motor: usa un Web Worker (module) y, si el navegador no lo soporta,
 * ejecuta el solver en el hilo principal de forma transparente.
 */
import { solve } from './solver.js';

export class SolverClient {
  constructor() {
    this.seq = 0;
    this.pending = new Map();
    this.worker = null;
    try {
      this.worker = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' });
      this.worker.onmessage = (e) => {
        const { id, ok, result, error } = e.data;
        const p = this.pending.get(id);
        if (!p) return;
        this.pending.delete(id);
        ok ? p.resolve(result) : p.reject(new Error(error));
      };
      this.worker.onerror = (e) => {
        console.warn('[GnoSoft] Worker no disponible, usando hilo principal.', e.message);
        this.worker = null;
        for (const [id, p] of this.pending) {
          this.pending.delete(id);
          this._local(p.payload).then(p.resolve, p.reject);
        }
      };
    } catch (err) {
      console.warn('[GnoSoft] Worker no soportado:', err);
      this.worker = null;
    }
  }

  _local(payload) {
    return new Promise((resolve, reject) => {
      setTimeout(() => {
        try { resolve(solve(payload)); } catch (e) { reject(e); }
      }, 0);
    });
  }

  solve(payload) {
    if (!this.worker) return this._local(payload);
    return new Promise((resolve, reject) => {
      const id = ++this.seq;
      this.pending.set(id, { resolve, reject, payload });
      this.worker.postMessage({ id, payload });
    });
  }
}
