/**
 * Función de evaluación (fitness) y métricas de cumplimiento del horario.
 *
 * Score de Calidad IA (0–100) = promedio ponderado (pesos de los sliders) de 4 sub-scores:
 *   S_huecos  = 1 − min(1, huecos / días-docente activos)
 *   S_fatiga  = 1 − min(1, eventos de fatiga / lecciones pesadas)
 *   S_franjas = 1 − penalización de franjas / penalización máxima posible
 *   S_equidad = Índice de Equidad Pedagógica / 100
 * Si existe cualquier violación dura el score se castiga ×0.5 (no debería ocurrir).
 */
import { TimetableState } from './state.js';
import { HARD_WEIGHT } from './model.js';

/** Asigna aula concreta a cada lección (prefiere el aula base del curso). */
export function assignRooms(P, grid) {
  const { nC, S, lessons: L, rooms } = P;
  const out = Array.from({ length: nC }, () => new Array(S).fill(-1));
  for (let t = 0; t < S; t++) {
    const byType = new Map();
    for (let c = 0; c < nC; c++) {
      const l = grid[c][t];
      if (l < 0) continue;
      const ty = L[l].type;
      if (!byType.has(ty)) byType.set(ty, []);
      byType.get(ty).push(c);
    }
    for (const [ty, cs] of byType) {
      const candidates = P.typeRooms[ty];
      const used = new Set();
      cs.sort((a, b) => L[grid[b][t]].size - L[grid[a][t]].size);
      const pending = [];
      for (const c of cs) {
        const hr = P.homeroom[c];
        const size = L[grid[c][t]].size;
        if (hr >= 0 && rooms[hr].tipo === P.types[ty] && !used.has(hr) && rooms[hr].capacidad >= size) {
          out[c][t] = hr;
          used.add(hr);
        } else pending.push(c);
      }
      for (const c of pending) {
        const size = L[grid[c][t]].size;
        const r = candidates.find((ri) => !used.has(ri) && rooms[ri].capacidad >= size);
        if (r !== undefined) { out[c][t] = r; used.add(r); }
      }
    }
  }
  return out;
}

export function computeMetrics(P, grid, weights) {
  const st = new TimetableState(P, grid, weights);
  const { nT, nC, S, B, days, lessons: L } = P;
  const tot = st.totals();

  // ---------- Restricciones duras ----------
  let teacherClashes = 0, unavailability = 0, roomConflicts = 0, forbidden = 0;
  for (let p = 0; p < nT; p++) {
    for (let t = 0; t < S; t++) {
      const n = st.tc[p][t];
      if (n > 1) teacherClashes += n - 1;
      if (n > 0 && P.unavailable[p][t]) unavailability += n;
    }
  }
  for (let t = 0; t < S; t++) roomConflicts += st.roomHard(t);
  const seen = new Uint8Array(L.length);
  let placed = 0, duplicates = 0;
  for (let c = 0; c < nC; c++) {
    for (let t = 0; t < S; t++) {
      const l = grid[c][t];
      if (l < 0) continue;
      if (P.forbidden[L[l].s][t]) forbidden++;
      if (seen[l]) duplicates++;
      else { seen[l] = 1; placed++; }
    }
  }
  const unassigned = L.length - placed;
  let overload = 0;
  P.teachers.forEach((t, p) => { overload += Math.max(0, P.teacherLoad[p] - t.maxHorasSemana); });
  const hardTotal = teacherClashes + unavailability + roomConflicts + forbidden + unassigned + duplicates + overload;

  // ---------- Docentes / huecos ----------
  let gapsTotal = 0, teachersZero = 0, teacherDaysActive = 0;
  const teachers = P.teachers.map((t, p) => {
    let horas = 0, libres = 0, noDisp = 0, huecos = 0;
    for (let s = 0; s < S; s++) {
      const n = st.tc[p][s];
      if (n > 0) horas += n;
      else if (P.unavailable[p][s]) noDisp++;
      else libres++;
    }
    for (let d = 0; d < days; d++) {
      huecos += st.dayGaps(p, d);
      for (let b = 0; b < B; b++) if (st.tc[p][d * B + b]) { teacherDaysActive++; break; }
    }
    gapsTotal += huecos;
    if (huecos === 0) teachersZero++;
    return { id: t.id, nombre: t.nombre, horas, max: t.maxHorasSemana, libres, noDisponibles: noDisp, huecos };
  });

  // ---------- Fatiga cognitiva ----------
  let consecutive = 0, lastBlock = 0;
  for (let c = 0; c < nC; c++) {
    for (let d = 0; d < days; d++) {
      for (let b = 0; b < B; b++) {
        const t = d * B + b, l = grid[c][t];
        if (l < 0 || !L[l].heavy) continue;
        if (b === B - 1) lastBlock++;
        else if (!P.breakAfter[b]) {
          const nx = grid[c][t + 1];
          if (nx >= 0 && L[nx].heavy) consecutive++;
        }
      }
    }
  }

  // ---------- Equidad pedagógica ----------
  let spreadSum = 0, spreadN = 0, cvSum = 0;
  for (let c = 0; c < nC; c++) {
    const subjDays = new Map(), hours = new Map();
    const dayLoad = new Array(days).fill(0);
    for (let d = 0; d < days; d++) {
      for (let b = 0; b < B; b++) {
        const l = grid[c][d * B + b];
        if (l < 0) continue;
        const ls = L[l];
        hours.set(ls.s, (hours.get(ls.s) || 0) + 1);
        if (!subjDays.has(ls.s)) subjDays.set(ls.s, new Set());
        subjDays.get(ls.s).add(d);
        dayLoad[d] += ls.heavy ? 2 : 1;
      }
    }
    for (const [s, h] of hours) { spreadSum += subjDays.get(s).size / Math.min(h, days); spreadN++; }
    const mean = dayLoad.reduce((a, b) => a + b, 0) / days;
    const std = Math.sqrt(dayLoad.reduce((a, v) => a + (v - mean) ** 2, 0) / days);
    cvSum += mean > 0 ? std / mean : 0;
  }
  const spread = spreadN ? spreadSum / spreadN : 1;
  const balance = 1 - Math.min(1, cvSum / Math.max(1, nC));
  const equityIndex = 100 * (0.6 * spread + 0.4 * balance);

  // ---------- Espacios ----------
  const rooms = assignRooms(P, grid);
  const roomUse = P.rooms.map((r) => ({ id: r.id, nombre: r.nombre, tipo: r.tipo, capacidad: r.capacidad, ocupados: 0, uso: 0 }));
  rooms.forEach((row) => row.forEach((ri) => { if (ri >= 0) roomUse[ri].ocupados++; }));
  roomUse.forEach((r) => { r.uso = (r.ocupados / S) * 100; });
  const labs = roomUse.filter((r) => r.tipo.startsWith('lab'));
  const labUsage = labs.length ? labs.reduce((a, r) => a + r.uso, 0) / labs.length : 0;

  // ---------- Score ----------
  const sGaps = 1 - Math.min(1, gapsTotal / Math.max(1, teacherDaysActive));
  const sFat = 1 - Math.min(1, (consecutive + lastBlock) / Math.max(1, P.heavyTotal));
  const sMorning = P.maxSlotPenalty > 0 ? 1 - Math.min(1, tot.slot / P.maxSlotPenalty) : 1;
  const sEq = equityIndex / 100;
  const w = { gaps: 0, fatigue: 0, morning: 0, equity: 0, ...weights };
  const ws = w.gaps + w.fatigue + w.morning + w.equity;
  let score = ws > 0
    ? (100 * (w.gaps * sGaps + w.fatigue * sFat + w.morning * sMorning + w.equity * sEq)) / ws
    : (100 * (sGaps + sFat + sMorning + sEq)) / 4;
  if (hardTotal > 0) score *= 0.5;

  return {
    score,
    hard: { total: hardTotal, teacherClashes, courseClashes: duplicates, roomConflicts, unavailability, forbidden, unassigned, overload },
    conflicts: st.conflictCells(),
    gaps: { total: gapsTotal, teachersZero, teacherDaysActive },
    fatigue: { total: consecutive + lastBlock, consecutive, lastBlock },
    equity: { index: equityIndex, spread: spread * 100, balance: balance * 100, excess: tot.eq },
    morning: { penalty: tot.slot, score: sMorning * 100 },
    labs: { usage: labUsage, rooms: labs },
    rooms: roomUse,
    teachers,
    subscores: { gaps: sGaps * 100, fatigue: sFat * 100, morning: sMorning * 100, equity: sEq * 100 },
    objective: HARD_WEIGHT * tot.hard + tot.soft,
  };
}

/** Convierte {cursoId: [asignaturaId|null por slot]} (formato API) en grid de lecciones. */
export function gridFromHorario(P, horario) {
  return P.courses.map((course, c) => {
    const queues = new Map();
    for (const id of P.courseLessons[c]) {
      const sid = P.subjects[P.lessons[id].s].id;
      if (!queues.has(sid)) queues.set(sid, []);
      queues.get(sid).push(id);
    }
    const row = horario[course.id] || [];
    return Array.from({ length: P.S }, (_, t) => {
      const sid = row[t];
      return sid && queues.get(sid)?.length ? queues.get(sid).shift() : -1;
    });
  });
}

/** Convierte grid de lecciones al formato API {cursoId: [asignaturaId|null]}. */
export function horarioFromGrid(P, grid) {
  const out = {};
  P.courses.forEach((course, c) => {
    out[course.id] = grid[c].map((l) => (l >= 0 ? P.subjects[P.lessons[l].s].id : null));
  });
  return out;
}

/** Celdas (c*S+t) cuya asignatura cambió entre dos grids. */
export function diffCells(P, a, b) {
  const set = new Set();
  if (!a || !b) return set;
  const L = P.lessons;
  for (let c = 0; c < P.nC; c++) {
    for (let t = 0; t < P.S; t++) {
      const sa = a[c]?.[t] >= 0 ? L[a[c][t]]?.s : -1;
      const sb = b[c]?.[t] >= 0 ? L[b[c][t]]?.s : -1;
      if (sa !== sb) set.add(c * P.S + t);
    }
  }
  return set;
}
