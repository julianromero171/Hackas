/**
 * Estado incremental del horario con evaluación delta O(cursos + docentes afectados).
 *
 * Función objetivo:
 *   J = HARD·H + w_h·Huecos + w_f·Fatiga + w_m·Franjas + w_e·Equidad
 * donde H = cruces docentes + indisponibilidad + colisiones de aula + franjas prohibidas.
 */
import { HARD_WEIGHT } from './model.js';

export class TimetableState {
  constructor(P, grid, weights) {
    this.P = P;
    this.w = { gaps: 0, fatigue: 0, morning: 0, equity: 0, ...weights };
    this.grid = grid.map((r) => Int32Array.from(r));
    this.tc = Array.from({ length: P.nT }, () => new Uint8Array(P.S)); // clases por docente y slot
    this._cnt = new Uint8Array(P.nS);
    this._typeCnt = new Int32Array(P.types.length);
    this._teach = new Int32Array(P.nC * 2 + 2);
    this._nTeach = 0;
    this._ch = 0; this._cf = 0; this._cs = 0; this._ce = 0;
    this._lh = 0; this._ls = 0;
    this.dHard = 0; this.dSoft = 0;
    this.rebuild();
  }

  rebuild() {
    for (const r of this.tc) r.fill(0);
    const L = this.P.lessons;
    for (const row of this.grid) {
      for (let t = 0; t < row.length; t++) {
        const l = row[t];
        if (l >= 0) this.tc[L[l].p][t]++;
      }
    }
  }

  snapshot() { return this.grid.map((r) => Array.from(r)); }

  /** Violaciones duras del docente p en el slot t (cruce + indisponibilidad). */
  slotHard(p, t) {
    const n = this.tc[p][t];
    if (n === 0) return 0;
    return (n - 1) + (this.P.unavailable[p][t] ? n : 0);
  }

  /** Horas huecas del docente p el día d: (último − primero + 1) − clases. */
  dayGaps(p, d) {
    const B = this.P.B, row = this.tc[p], base = d * B;
    let first = -1, last = -1, cnt = 0;
    for (let b = 0; b < B; b++) {
      if (row[base + b] > 0) { if (first < 0) first = b; last = b; cnt++; }
    }
    return first < 0 ? 0 : last - first + 1 - cnt;
  }

  /** Lecciones sin aula compatible (tipo + capacidad) en el slot t. */
  roomHard(t) {
    const P = this.P, L = P.lessons, cnt = this._typeCnt;
    cnt.fill(0);
    for (let c = 0; c < P.nC; c++) {
      const l = this.grid[c][t];
      if (l >= 0) cnt[L[l].type]++;
    }
    let h = 0;
    for (let ty = 0; ty < cnt.length; ty++) {
      if (!cnt[ty]) continue;
      if (P.typeSimple[ty]) { if (cnt[ty] > P.typeSupply[ty]) h += cnt[ty] - P.typeSupply[ty]; }
      else h += this.matchDeficit(t, ty);
    }
    return h;
  }

  /** Emparejamiento óptimo por capacidad (lecciones desc. → aula más pequeña que sirva). */
  matchDeficit(t, ty) {
    const P = this.P, L = P.lessons, sizes = [];
    for (let c = 0; c < P.nC; c++) {
      const l = this.grid[c][t];
      if (l >= 0 && L[l].type === ty) sizes.push(L[l].size);
    }
    sizes.sort((a, b) => b - a);
    const rooms = P.typeRooms[ty];
    const used = new Uint8Array(rooms.length);
    let miss = 0;
    for (const sz of sizes) {
      let ok = false;
      for (let i = 0; i < rooms.length; i++) {
        if (!used[i] && P.rooms[rooms[i]].capacidad >= sz) { used[i] = 1; ok = true; break; }
      }
      if (!ok) miss++;
    }
    return miss;
  }

  /** Evalúa un curso completo: duras (franjas prohibidas) y blandas (fatiga, franjas, equidad). */
  courseEval(c) {
    const P = this.P, B = P.B, row = this.grid[c], L = P.lessons, cnt = this._cnt;
    const allowed = P.allowedPerDay[c], cap = P.heavyCap[c];
    let hard = 0, fat = 0, slot = 0, eq = 0;
    for (let d = 0; d < P.days; d++) {
      cnt.fill(0);
      let heavyDay = 0;
      const base = d * B;
      for (let b = 0; b < B; b++) {
        const t = base + b, l = row[t];
        if (l < 0) continue;
        const ls = L[l];
        if (P.forbidden[ls.s][t]) hard++;
        slot += P.softSlot[ls.s][t];
        cnt[ls.s]++;
        if (ls.heavy) {
          heavyDay++;
          if (b === B - 1) fat++; // materia pesada al final de la jornada
          else if (!P.breakAfter[b]) {
            const nx = row[t + 1];
            if (nx >= 0 && L[nx].heavy) fat++; // dos pesadas seguidas sin recreo
          }
        }
      }
      for (let s = 0; s < cnt.length; s++) if (cnt[s] > allowed[s]) eq += cnt[s] - allowed[s];
      if (heavyDay > cap) eq += heavyDay - cap;
    }
    this._ch = hard; this._cf = fat; this._cs = slot; this._ce = eq;
  }

  _collectTeachers(C, t1, t2) {
    const arr = this._teach, L = this.P.lessons;
    let n = 0;
    const push = (p) => {
      for (let i = 0; i < n; i++) if (arr[i] === p) return;
      arr[n++] = p;
    };
    for (let i = 0; i < C.length; i++) {
      const row = this.grid[C[i]];
      const a = row[t1], b = row[t2];
      if (a >= 0) push(L[a].p);
      if (b >= 0) push(L[b].p);
    }
    this._nTeach = n;
  }

  _localCost(C, t1, t2) {
    const P = this.P, w = this.w, B = P.B;
    const d1 = (t1 / B) | 0, d2 = (t2 / B) | 0;
    let hard = 0, soft = 0;
    for (let i = 0; i < this._nTeach; i++) {
      const p = this._teach[i];
      hard += this.slotHard(p, t1) + this.slotHard(p, t2);
      soft += w.gaps * (this.dayGaps(p, d1) + (d2 !== d1 ? this.dayGaps(p, d2) : 0));
    }
    hard += this.roomHard(t1) + this.roomHard(t2);
    for (let i = 0; i < C.length; i++) {
      this.courseEval(C[i]);
      hard += this._ch;
      soft += w.fatigue * this._cf + w.morning * this._cs + w.equity * this._ce;
    }
    this._lh = hard; this._ls = soft;
  }

  /** Intercambia los slots t1 y t2 en todos los cursos de C. */
  swap(C, t1, t2) {
    const L = this.P.lessons;
    for (let i = 0; i < C.length; i++) {
      const row = this.grid[C[i]];
      const a = row[t1], b = row[t2];
      if (a >= 0) { const p = L[a].p; this.tc[p][t1]--; this.tc[p][t2]++; }
      if (b >= 0) { const p = L[b].p; this.tc[p][t2]--; this.tc[p][t1]++; }
      row[t1] = b; row[t2] = a;
    }
  }

  /** Aplica el movimiento y deja en this.dHard / this.dSoft el delta de costo. */
  applyMove(C, t1, t2) {
    this._collectTeachers(C, t1, t2);
    this._localCost(C, t1, t2);
    const h0 = this._lh, s0 = this._ls;
    this.swap(C, t1, t2);
    this._localCost(C, t1, t2);
    this.dHard = this._lh - h0;
    this.dSoft = this._ls - s0;
  }

  totals() {
    const P = this.P, w = this.w;
    let hard = 0, gaps = 0, fat = 0, slot = 0, eq = 0;
    for (let p = 0; p < P.nT; p++) {
      for (let t = 0; t < P.S; t++) hard += this.slotHard(p, t);
      for (let d = 0; d < P.days; d++) gaps += this.dayGaps(p, d);
    }
    for (let t = 0; t < P.S; t++) hard += this.roomHard(t);
    for (let c = 0; c < P.nC; c++) {
      this.courseEval(c);
      hard += this._ch; fat += this._cf; slot += this._cs; eq += this._ce;
    }
    const soft = w.gaps * gaps + w.fatigue * fat + w.morning * slot + w.equity * eq;
    return { hard, gaps, fat, slot, eq, soft, objective: HARD_WEIGHT * hard + soft };
  }

  /** Celdas (codificadas c*S+t) que participan en alguna violación dura. */
  conflictCells() {
    const P = this.P, L = P.lessons, out = [];
    for (let t = 0; t < P.S; t++) {
      const rh = this.roomHard(t);
      for (let c = 0; c < P.nC; c++) {
        const l = this.grid[c][t];
        if (l < 0) continue;
        const ls = L[l];
        if (this.tc[ls.p][t] > 1 || P.unavailable[ls.p][t] || P.forbidden[ls.s][t] || (rh > 0 && !P.typeSimple[ls.type]) || (rh > 0 && P.typeScarce[ls.type])) {
          out.push(c * P.S + t);
        }
      }
    }
    return out;
  }
}
