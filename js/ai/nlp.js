/**
 * Agente NLP (español → restricciones formales).
 *
 * Pipeline determinista (funciona offline y sin latencia frente al jurado):
 *   1. Normalización (minúsculas, sin tildes).
 *   2. Reconocimiento de entidades: docente (nombre/apellido/"profesor de X"),
 *      asignaturas (alias, coincidencia más larga primero), días y franjas
 *      ("últimas 2 horas", "primera y segunda hora", "en la tarde", "bloques 3 a 5"…).
 *   3. Clasificación de intención: indisponibilidad docente, evitar/prohibir franjas,
 *      priorizar mañana, pesos de la función objetivo, comandos (ayuda/deshacer/reiniciar).
 *   4. Generación de la regla + su forma matemática sobre X[c,m,p,a,d,b].
 */
import { normalize, escapeRe, compressRanges } from '../core/utils.js';
import { AVOID_PENALTY } from '../engine/model.js';

export const DEMO_PROMPTS = [
  'El profesor Carlos Ruiz no puede asistir los viernes en las últimas 2 horas',
  'La profesora Laura Méndez no está disponible los lunes a primera y segunda hora',
  'Evitar que Matemáticas y Física se dicten en las últimas horas del día',
  'Priorizar 0 horas huecas para todos los docentes y evitar bloques consecutivos pesados',
  'El profesor Julián Ríos no puede dictar clase los miércoles en la tarde',
  'Prioriza Matemáticas en las primeras horas de la mañana',
];

let seq = 0;
export const newRuleId = () => `r${Date.now().toString(36)}${(seq++).toString(36)}`;

const DAY_KEYS = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo'];
const NUM = { un: 1, una: 1, uno: 1, dos: 2, tres: 3, cuatro: 4, cinco: 5, seis: 6, siete: 7 };
const ORD = {
  primer: 0, primera: 0, primero: 0, segunda: 1, segundo: 1, tercer: 2, tercera: 2, tercero: 2,
  cuarta: 3, cuarto: 3, quinta: 4, quinto: 4, sexta: 5, sexto: 5, septima: 6, septimo: 6, octava: 7, octavo: 7,
};
const NUMW = '(\\d+|un|una|dos|tres|cuatro|cinco|seis)';
const UNIT = '(?:horas?|bloques?|clases?|periodos?)';

const range = (a, b) => { const o = []; for (let i = Math.max(0, a); i <= b; i++) o.push(i); return o; };
const toNum = (w) => (/^\d+$/.test(w) ? parseInt(w, 10) : NUM[w]);
const wbTest = (text, word) => new RegExp(`\\b${escapeRe(word)}\\b`).test(text);

const NEG_RE = /\bno\s+(puede|podra|podria|esta|estara|asiste|asistira|va|ira|dicta|dictara|trabaja|labora|tiene disponibilidad)\b|\b(indisponible|ausente|incapacitad[oa]|sin disponibilidad|no disponible|bloquea|bloquear|bloquee|libera|liberar|libre de clases|permiso|licencia|cita medica)\b/;
const ONLY_RE = /\b(solo|solamente|unicamente)\s+(puede|podra|esta|estara|dicta|asiste|trabaja|disponible)\b/;
const AVOID_RE = /\b(evit\w*|no\s+(?:se\s+)?(?:dict\w*|program\w*|ubiq\w*|qued\w*|pong\w*|asign\w*|deb\w*|pued\w*)|nunca|prohib\w*|jamas|elimin\w*|sin\s+clases)\b/;
const HARD_RE = /\b(nunca|prohib\w*|jamas|obligatori\w*|no\s+(?:se\s+)?pued\w*|estrictamente|bajo ninguna)\b/;
const PREFER_RE = /\b(prioriz\w*|prefer\w*|temprano|primeras horas|primera hora|al inicio|al comienzo|en la manana|por la manana|de la manana|antes del recreo|mananas)\b/;
const GAPS_RE = /\b(huec\w*|tiempos? muertos?|ventanas?|horas muertas|horas libres entre)\b/;
const FATIGUE_RE = /\b(consecutiv\w*|seguid\w*|fatiga|pesad\w*|carga cognitiva|sin descanso)\b/;
const EQUITY_RE = /\b(equidad|equilibr\w*|balance\w*|balancea\w*|distribu\w*|equitativ\w*)\b/;

export function parseDays(n, nDays) {
  if (/\b(todos los dias|toda la semana|cualquier dia|diariamente|entre semana|cada dia)\b/.test(n)) return range(0, nDays - 1);
  const m = n.match(/\bde\s+(lunes|martes|miercoles|jueves|viernes)\s+a\s+(lunes|martes|miercoles|jueves|viernes)\b/);
  if (m) return range(DAY_KEYS.indexOf(m[1]), Math.min(nDays - 1, DAY_KEYS.indexOf(m[2])));
  const out = [];
  DAY_KEYS.forEach((k, i) => { if (i < nDays && new RegExp(`\\b${k}\\b`).test(n)) out.push(i); });
  return out;
}

export function parseBlocks(n, B) {
  let m;
  if ((m = n.match(new RegExp(`ultim[ao]s\\s+${NUMW}\\s+${UNIT}`))) || (m = n.match(new RegExp(`${NUMW}\\s+ultim[ao]s\\s+${UNIT}`)))) {
    const k = Math.min(B, toNum(m[1]) || 1);
    return range(B - k, B - 1);
  }
  if ((m = n.match(new RegExp(`primer[ao]s\\s+${NUMW}\\s+${UNIT}`))) || (m = n.match(new RegExp(`${NUMW}\\s+primer[ao]s\\s+${UNIT}`)))) {
    const k = Math.min(B, toNum(m[1]) || 1);
    return range(0, k - 1);
  }
  if (new RegExp(`ultim[ao]s\\s+${UNIT}`).test(n)) return range(B - 2, B - 1);
  if (new RegExp(`ultim[ao]\\s+${UNIT}`).test(n)) return [B - 1];
  if (new RegExp(`primer[ao]s\\s+${UNIT}`).test(n)) return range(0, 1);

  // Números explícitos: "bloque 3", "bloques 2 y 3", "horas 1 a 3", "bloques 4-6"
  m = n.match(/\b(?:bloques?|horas?|periodos?)\s+(\d+(?:\s*(?:,|y|e|a|al|-|hasta)\s*(?:la\s+|el\s+)?(?:hora\s+|bloque\s+)?\d+)*)/);
  if (m) {
    const tokens = m[1].match(/\d+|\ba\b|\bal\b|-|\bhasta\b/g) || [];
    const out = [];
    let pendingRange = false;
    for (const tk of tokens) {
      if (/^\d+$/.test(tk)) {
        const v = parseInt(tk, 10) - 1;
        if (pendingRange && out.length) { const from = out[out.length - 1]; out.push(...range(from + 1, v)); }
        else out.push(v);
        pendingRange = false;
      } else pendingRange = true;
    }
    const valid = [...new Set(out)].filter((b) => b >= 0 && b < B);
    if (valid.length) return valid.sort((a, b) => a - b);
  }

  // Ordinales: "primera y segunda hora", "tercer bloque"
  if (/\b(hora|horas|bloque|bloques|clase|periodo)\b/.test(n)) {
    const found = (n.match(/\b(primer[ao]?|segund[ao]|tercer[ao]?|cuart[ao]|quint[ao]|sext[ao]|septim[ao]|octav[ao])\b/g) || [])
      .map((w) => ORD[w]).filter((b) => b !== undefined && b < B);
    if (found.length) return [...new Set(found)].sort((a, b) => a - b);
  }
  if (/\b(tarde|tardes)\b/.test(n)) return range(Math.ceil(B / 2), B - 1);
  if (/\b(manana|mananas)\b/.test(n)) return range(0, Math.ceil(B / 2) - 1);
  return null;
}

export function findSubjects(n, subjects) {
  let text = ` ${n} `;
  const entries = [];
  for (const s of subjects) {
    const al = new Set([normalize(s.nombre), ...(s.alias || []).map(normalize)]);
    al.forEach((a) => a && entries.push([a, s.id]));
  }
  entries.sort((a, b) => b[0].length - a[0].length);
  const ids = [];
  for (const [a, id] of entries) {
    const re = new RegExp(`\\b${escapeRe(a)}\\b`);
    if (re.test(text)) {
      if (!ids.includes(id)) ids.push(id);
      text = text.replace(new RegExp(`\\b${escapeRe(a)}\\b`, 'g'), ' '.repeat(a.length));
    }
  }
  return { ids, rest: text };
}

export function findTeacher(n, teachers, subjects) {
  let best = null, bestScore = 0, tie = false;
  const ctx = /\b(profesor|profesora|profe|docente|maestro|maestra|teacher)\b/.test(n);
  for (const t of teachers) {
    const full = normalize(t.nombre);
    const parts = full.split(/\s+/);
    let score = 0;
    if (n.includes(full)) score = 10;
    else if (parts.length > 1 && wbTest(n, parts.slice(1).join(' '))) score = 6;
    else if (parts.length > 1 && wbTest(n, parts[parts.length - 1]) && ctx) score = 5;
    else if (ctx && wbTest(n, parts[0])) score = 3;
    if (score > bestScore) { best = t; bestScore = score; tie = false; }
    else if (score && score === bestScore) tie = true;
  }
  if (best && !tie) return best;
  const m = n.match(/\b(?:profesor|profesora|profe|docente|maestro|maestra)\s+de\s+([a-z ]+)/);
  if (m) {
    const { ids } = findSubjects(m[1], subjects);
    if (ids.length) {
      const cands = teachers.filter((t) => (t.asignaturas || []).includes(ids[0]));
      if (cands.length === 1) return cands[0];
    }
  }
  return null;
}

// ---------------- Presentación ----------------
export function daysLabel(days, data) {
  const all = data.jornada.dias;
  if (!days?.length || days.length === all.length) return 'Todos los días';
  return compressRanges(days).map(([a, b]) => (a === b ? all[a] : `${all[a]} a ${all[b]}`)).join(', ');
}

export function blocksLabel(blocks, B) {
  if (!blocks?.length || blocks.length === B) return 'Toda la jornada';
  return compressRanges(blocks).map(([a, b]) => (a === b ? `Bloque ${a + 1}` : `Bloques ${a + 1}–${b + 1}`)).join(', ');
}

const subjNames = (ids, data) =>
  ids.map((id) => data.asignaturas.find((s) => s.id === id)?.nombre || id).join(' y ');

export function describeRule(rule, data) {
  const B = data.jornada.bloquesPorDia;
  switch (rule.type) {
    case 'teacher_unavailable': {
      const name = data.docentes.find((d) => d.id === rule.teacherId)?.nombre || rule.teacherId;
      if (rule.only) return `${name}: solo disponible ${daysLabel(rule.onlyDays, data)} · ${blocksLabel(rule.onlyBlocks, B)}`;
      return `${name} no disponible · ${daysLabel(rule.days, data)} · ${blocksLabel(rule.blocks, B)}`;
    }
    case 'subject_avoid': {
      const d = rule.days?.length && rule.days.length < data.jornada.dias.length ? ` · ${daysLabel(rule.days, data)}` : '';
      return `${subjNames(rule.subjectIds, data)}: ${rule.hard ? 'prohibido' : 'evitar'} ${blocksLabel(rule.blocks, B).toLowerCase()}${d}`;
    }
    case 'subject_prefer_morning':
      return `Priorizar ${subjNames(rule.subjectIds, data)} en las primeras horas`;
    default:
      return rule.text || rule.type;
  }
}

const shortDay = (d) => d.slice(0, 3);
const setStr = (arr) => `{${arr.join(',')}}`;

export function formalize(rule, data) {
  const dias = data.jornada.dias;
  const D = (rule.days?.length ? rule.days : dias.map((_, i) => i)).map((d) => shortDay(dias[d]));
  const Bs = (rule.blocks || []).map((b) => b + 1);
  switch (rule.type) {
    case 'teacher_unavailable':
      if (rule.slots?.length) {
        return `X[c,m,${rule.teacherId},a,d,b] = 0    ∀ c,m,a\n∀ (d,b) ∈ Ω,  |Ω| = ${rule.slots.length} franjas fuera de disponibilidad`;
      }
      return `X[c,m,${rule.teacherId},a,d,b] = 0    ∀ c,m,a\nd ∈ ${setStr(D)} ,  b ∈ ${setStr(Bs)}`;
    case 'subject_avoid':
      return rule.hard
        ? `Σ_{c,p,a} X[c,m,p,a,d,b] = 0\nm ∈ ${setStr(rule.subjectIds)} ,  d ∈ ${setStr(D)} ,  b ∈ ${setStr(Bs)}`
        : `min  w_m · ${AVOID_PENALTY} · Σ_{c,p,a,d} X[c,m,p,a,d,b]\nm ∈ ${setStr(rule.subjectIds)} ,  b ∈ ${setStr(Bs)}`;
    case 'subject_prefer_morning':
      return `min  w_m · Σ_{c,p,a,d,b} (b−1) · X[c,m,p,a,d,b]\nm ∈ ${setStr(rule.subjectIds)}   (penaliza bloques tardíos)`;
    default:
      return '';
  }
}

export function weightFormal(key, v) {
  switch (key) {
    case 'gaps': return `min  w_h · Σ_{p,d} ( fin_{p,d} − ini_{p,d} + 1 − Σ_b Y_{p,d,b} )\nY_{p,d,b} = Σ_{c,m,a} X[c,m,p,a,d,b] ,  w_h = ${v}`;
    case 'fatigue': return `min  w_f · Σ_{c,d,b} ( H_{c,d,b} · H_{c,d,b+1} + H_{c,d,|B|} )\nH = materias de alta carga cognitiva ,  w_f = ${v}`;
    case 'equity': return `min  w_e · Σ_{c,m,d} max(0, Σ_b X[c,m,·,·,d,b] − ⌈h_{c,m}/|D|⌉)\nw_e = ${v}`;
    case 'morning': return `min  w_m · Σ penalización_franja(m,b) · X[c,m,p,a,d,b] ,  w_m = ${v}`;
    default: return '';
  }
}

export const WEIGHT_LABELS = { gaps: 'Horas huecas docentes', fatigue: 'Fatiga cognitiva consecutiva', morning: 'Preferencia matutina / franjas', equity: 'Equidad pedagógica' };

export function finalizeRule(rule, text, data) {
  const full = { id: newRuleId(), enabled: true, text, days: [], blocks: [], subjectIds: [], hard: false, ...rule };
  full.label = describeRule(full, data);
  full.formal = formalize(full, data);
  return full;
}

// ---------------- Parser principal ----------------
export function parseInstruction(text, data) {
  const n = ' ' + normalize(text).replace(/[¿?¡!.;:()"“”]/g, ' ').replace(/\s+/g, ' ').trim() + ' ';
  const B = data.jornada.bloquesPorDia;
  const nDays = data.jornada.dias.length;
  const res = { source: 'nlp', understood: false, actions: [], entities: {}, notes: [] };

  if (/^\s*(ayuda|help|\?|que puedes hacer|comandos|como funciona)\b/.test(n)) {
    res.actions.push({ kind: 'help' }); res.understood = true; return res;
  }
  if (/\b(reinicia\w*|resetea\w*|reset|limpia\w*|borra\w*|elimina\w*|quita\w*)\b.*\b(restricciones|reglas|todo)\b/.test(n) && !/\bultima\b/.test(n)) {
    res.actions.push({ kind: 'clear' }); res.understood = true; return res;
  }
  if (/\b(deshacer|deshaz|revierte|quita la ultima|elimina la ultima|borra la ultima)\b/.test(n)) {
    res.actions.push({ kind: 'undo' }); res.understood = true; return res;
  }

  const teacher = findTeacher(n, data.docentes, data.asignaturas);
  const days = parseDays(n, nDays);
  const blocks = parseBlocks(n, B);
  res.entities = { teacher: teacher?.id || null, days, blocks };

  let handledTeacher = false;
  const neg = NEG_RE.test(n), only = ONLY_RE.test(n);
  if (teacher && (neg || only)) {
    handledTeacher = true;
    if (!days.length && !blocks) {
      res.notes.push(`Identifiqué a <b>${teacher.nombre}</b>, pero no el día ni la franja. Ej.: “${teacher.nombre} no puede los martes en la tarde”.`);
    } else {
      const d = days.length ? days : range(0, nDays - 1);
      const b = blocks?.length ? blocks : range(0, B - 1);
      let rule;
      if (only && !neg) {
        const slots = [];
        for (let dd = 0; dd < nDays; dd++) for (let bb = 0; bb < B; bb++) if (!(d.includes(dd) && b.includes(bb))) slots.push([dd, bb]);
        rule = { type: 'teacher_unavailable', teacherId: teacher.id, slots, only: true, onlyDays: d, onlyBlocks: b, hard: true };
      } else {
        rule = { type: 'teacher_unavailable', teacherId: teacher.id, days: d, blocks: b, hard: true };
      }
      res.actions.push({ kind: 'rule', rule: finalizeRule(rule, text, data) });
    }
  }

  let subjText = n;
  if (teacher) subjText = subjText.replace(new RegExp(escapeRe(normalize(teacher.nombre)), 'g'), ' ');
  const { ids: subjectIds } = findSubjects(subjText, data.asignaturas);
  res.entities.subjects = subjectIds;

  let subjectRule = false;
  if (!handledTeacher && subjectIds.length) {
    if (AVOID_RE.test(n)) {
      let b = blocks;
      if (!b && /\b(final|ultim\w*)\b/.test(n)) b = range(B - 2, B - 1);
      if (b) {
        const rule = { type: 'subject_avoid', subjectIds, days, blocks: b, hard: HARD_RE.test(n) };
        res.actions.push({ kind: 'rule', rule: finalizeRule(rule, text, data) });
        subjectRule = true;
      }
    } else if (PREFER_RE.test(n)) {
      const rule = { type: 'subject_prefer_morning', subjectIds };
      res.actions.push({ kind: 'rule', rule: finalizeRule(rule, text, data) });
      subjectRule = true;
    }
  }

  if (GAPS_RE.test(n)) {
    const relax = /\b(relaj\w*|permit\w*|ignor\w*|no importa)\b/.test(n);
    res.actions.push({ kind: 'weights', key: 'gaps', changes: { gaps: relax ? 2 : 10 } });
  }
  if (FATIGUE_RE.test(n) && !subjectRule) res.actions.push({ kind: 'weights', key: 'fatigue', changes: { fatigue: 10 } });
  if (EQUITY_RE.test(n)) res.actions.push({ kind: 'weights', key: 'equity', changes: { equity: 10 } });

  res.understood = res.actions.length > 0;
  return res;
}
