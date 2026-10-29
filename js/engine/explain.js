/**
 * Validación explicable de ediciones manuales (Click-to-Swap).
 * Devuelve si el intercambio es válido y, si no, mensajes en lenguaje natural y una
 * alternativa por cadena de Kempe cuando existe.
 */
import { TimetableState } from './state.js';
import { kempeChain } from './kempe.js';

export function slotLabel(P, t) {
  const d = (t / P.B) | 0, b = t % P.B;
  return `${P.data.jornada.dias[d]} · bloque ${b + 1}`;
}

export function lessonViolations(P, st, c, t) {
  const l = st.grid[c][t];
  if (l < 0) return [];
  const L = P.lessons, ls = L[l];
  const T = P.teachers[ls.p], sub = P.subjects[ls.s];
  const where = slotLabel(P, t);
  const out = [];
  for (let y = 0; y < P.nC; y++) {
    if (y === c) continue;
    const o = st.grid[y][t];
    if (o >= 0 && L[o].p === ls.p) {
      out.push(`<b>Cruce docente:</b> ${T.nombre} ya dicta ${P.subjects[L[o].s].nombre} en <b>${P.courses[y].nombre}</b> el ${where}.`);
    }
  }
  if (P.unavailable[ls.p][t]) {
    out.push(`<b>Disponibilidad:</b> ${T.nombre} no está disponible el ${where} (${P.unavailReason[ls.p][t]}).`);
  }
  if (P.forbidden[ls.s][t]) {
    out.push(`<b>Regla pedagógica dura:</b> ${sub.nombre} no puede dictarse el ${where}.`);
  }
  if ((P.typeScarce[ls.type] || !P.typeSimple[ls.type]) && st.roomHard(t) > 0) {
    const typeName = P.data.tiposEspacio?.[P.types[ls.type]] || P.types[ls.type];
    for (let y = 0; y < P.nC; y++) {
      if (y === c) continue;
      const o = st.grid[y][t];
      if (o >= 0 && L[o].type === ls.type) {
        out.push(`<b>Colisión de espacio:</b> ${typeName} ya está ocupado por <b>${P.courses[y].nombre}</b> (${P.subjects[L[o].s].nombre}) el ${where}.`);
      }
    }
  }
  return out;
}

export function explainSwap(P, grid, weights, c, t1, t2) {
  const st = new TimetableState(P, grid, weights);
  const before = st.totals();
  st.swap([c], t1, t2);
  const after = st.totals();
  const ok = after.hard === 0 || after.hard < before.hard;
  const result = { ok, before, after, messages: [], grid: null, kempe: null };
  if (ok) {
    result.grid = st.snapshot();
    return result;
  }
  result.messages = [...new Set([...lessonViolations(P, st, c, t1), ...lessonViolations(P, st, c, t2)])];
  st.swap([c], t1, t2); // deshacer

  const chain = kempeChain(st, c, t1, t2);
  if (chain.length > 1) {
    st.swap(chain, t1, t2);
    const k = st.totals();
    if (k.hard === 0 || k.hard < before.hard) {
      result.kempe = { courses: chain.filter((x) => x !== c), grid: st.snapshot(), after: k };
    }
    st.swap(chain, t1, t2);
  }
  return result;
}
