/** Tarjetas de respuesta del copiloto (comprensión, forma matemática, resultado). */
import { escapeHtml, fmtNum } from '../core/utils.js';
import { daysLabel, blocksLabel, weightFormal, WEIGHT_LABELS } from '../ai/nlp.js';

const subjNames = (ids, data) => ids.map((id) => data.asignaturas.find((s) => s.id === id)?.nombre || id).join(', ');

export function welcome(data) {
  return `
    <p class="font-semibold text-white">¡Hola! Soy el Copiloto IA de GnoSoft 👋</p>
    <p class="mt-1 text-slate-300">Escríbeme restricciones en español natural y las traduzco a restricciones formales sobre
      <span class="font-mono text-cyan-300">X[c,m,p,a,d,b]</span> para re-optimizar los ${data.cursos.length} cursos en milisegundos.</p>
    <ul class="mt-2 space-y-1 text-slate-400 text-[12px]">
      <li>• <b class="text-slate-300">Disponibilidad docente:</b> días, “últimas 2 horas”, “en la tarde”…</li>
      <li>• <b class="text-slate-300">Franjas pedagógicas:</b> evitar / prohibir / priorizar asignaturas.</li>
      <li>• <b class="text-slate-300">Función objetivo:</b> horas huecas, fatiga, equidad.</li>
      <li>• Comandos: <span class="font-mono">ayuda</span>, <span class="font-mono">deshacer</span>, <span class="font-mono">reiniciar restricciones</span>.</li>
    </ul>`;
}

export function help() {
  return `
    <p class="font-semibold text-white">Esto es lo que entiendo:</p>
    <div class="mt-2 space-y-2 text-[12px]">
      <div><span class="tag tag-hard">Dura</span> <span class="text-slate-300">“La profesora Laura Méndez no está disponible los lunes a primera y segunda hora”</span></div>
      <div><span class="tag tag-hard">Dura</span> <span class="text-slate-300">“Ana Torres solo puede de lunes a miércoles”</span></div>
      <div><span class="tag tag-hard">Dura</span> <span class="text-slate-300">“Nunca programar Educación Física en el bloque 1”</span></div>
      <div><span class="tag tag-soft">Blanda</span> <span class="text-slate-300">“Evitar que Matemáticas y Física se dicten en las últimas horas”</span></div>
      <div><span class="tag tag-soft">Blanda</span> <span class="text-slate-300">“Prioriza Matemáticas en las primeras horas de la mañana”</span></div>
      <div><span class="tag tag-obj">Objetivo</span> <span class="text-slate-300">“Priorizar 0 horas huecas y evitar bloques consecutivos pesados”</span></div>
    </div>
    <p class="mt-2 text-[11px] text-slate-500">También puedes hacer clic en dos bloques del horario para intercambiarlos: la IA valida cada cambio.</p>`;
}

export function notUnderstood(parsed, data) {
  const notes = parsed.notes?.length ? `<p class="mt-1 text-amber-200 text-[12px]">${parsed.notes.join('<br>')}</p>` : '';
  return `
    <p class="text-slate-200">No logré convertir esa instrucción en una restricción 🤔</p>${notes}
    <p class="mt-2 text-[12px] text-slate-400">Prueba con docentes como <b>${escapeHtml(data.docentes.slice(0, 3).map((d) => d.nombre).join(', '))}</b>, días (lunes…viernes) y franjas (“primera hora”, “últimas 2 horas”, “en la tarde”). Escribe <span class="font-mono">ayuda</span> para ver ejemplos.</p>`;
}

export function rejected(msg) {
  return `<div class="flex items-start gap-2"><i data-lucide="shield-alert" class="w-4 h-4 text-rose-300 mt-0.5 shrink-0"></i><div><p class="text-rose-200 font-semibold">Restricción rechazada: haría el horario infactible</p><p class="text-[12px] text-slate-300 mt-1">${msg}</p></div></div>`;
}

function entityChips(rule, data) {
  const B = data.jornada.bloquesPorDia;
  const chips = [];
  if (rule.teacherId) chips.push(`<span class="ent"><i data-lucide="user"></i>${escapeHtml(data.docentes.find((d) => d.id === rule.teacherId)?.nombre || rule.teacherId)}</span>`);
  if (rule.subjectIds?.length) chips.push(`<span class="ent"><i data-lucide="book-open"></i>${escapeHtml(subjNames(rule.subjectIds, data))}</span>`);
  if (rule.type === 'teacher_unavailable') {
    const d = rule.only ? rule.onlyDays : rule.days;
    const b = rule.only ? rule.onlyBlocks : rule.blocks;
    chips.push(`<span class="ent"><i data-lucide="calendar"></i>${rule.only ? 'Solo ' : ''}${escapeHtml(daysLabel(d, data))}</span>`);
    chips.push(`<span class="ent"><i data-lucide="clock"></i>${escapeHtml(blocksLabel(b, B))}</span>`);
  } else if (rule.type === 'subject_avoid') {
    if (rule.days?.length) chips.push(`<span class="ent"><i data-lucide="calendar"></i>${escapeHtml(daysLabel(rule.days, data))}</span>`);
    chips.push(`<span class="ent"><i data-lucide="clock"></i>${escapeHtml(blocksLabel(rule.blocks, B))}</span>`);
  } else if (rule.type === 'subject_prefer_morning') {
    chips.push('<span class="ent"><i data-lucide="sunrise"></i>Primeras horas</span>');
  }
  return chips.join(' ');
}

export function understanding(applied, data, source) {
  const parts = applied.map((a) => {
    if (a.kind === 'rule') {
      const r = a.rule;
      const tag = r.hard ? '<span class="tag tag-hard">Restricción dura</span>' : '<span class="tag tag-soft">Objetivo blando</span>';
      return `<div class="mt-2">${tag}<div class="mt-1.5 flex flex-wrap gap-1.5">${entityChips(r, data)}</div><div class="formal">${escapeHtml(r.formal)}</div></div>`;
    }
    if (a.kind === 'weights') {
      const [k, v] = Object.entries(a.changes)[0];
      return `<div class="mt-2"><span class="tag tag-obj">Función objetivo</span><div class="mt-1.5 text-[12px] text-slate-300">${escapeHtml(WEIGHT_LABELS[k])} → <b class="text-white">${v}/10</b></div><div class="formal">${escapeHtml(weightFormal(k, v))}</div></div>`;
    }
    if (a.kind === 'clear') return '<div class="mt-1 text-slate-300">Restricciones y pesos reiniciados.</div>';
    if (a.kind === 'undo') return `<div class="mt-1 text-slate-300">Deshice la última restricción${a.removed ? `: <i>${escapeHtml(a.removed.label)}</i>` : ''}.</div>`;
    return '';
  }).join('');
  const src = source === 'gemini' ? '<span class="tag tag-obj ml-1">Gemini</span>' : '<span class="tag tag-obj ml-1">NLP</span>';
  return `<p class="text-slate-200">Entendido ${src} — traduje tu instrucción a lenguaje matemático:</p>${parts}`;
}

export function resultCard({ result, prevMetrics }, impacts = []) {
  const m = result.metrics, s = result.stats;
  const d = (cur, prev, better = 'up', dec = 1, suffix = '') => {
    if (prev === undefined || prev === null) return '';
    const v = cur - prev;
    if (Math.abs(v) < Math.pow(10, -dec) / 2) return '<span class="delta delta-flat">=</span>';
    const good = better === 'up' ? v > 0 : v < 0;
    return `<span class="delta ${good ? 'delta-up' : 'delta-down'}">${v > 0 ? '+' : ''}${fmtNum(v, dec)}${suffix}</span>`;
  };
  const ok = m.hard.total === 0;
  return `
    <div class="flex items-center gap-2 font-semibold ${ok ? 'text-emerald-300' : 'text-amber-300'}">
      <i data-lucide="${ok ? 'check-circle-2' : 'triangle-alert'}" class="w-4 h-4"></i>
      Horario recalculado en ${fmtNum(s.ms, 0)} ms
    </div>
    <div class="mt-2 grid grid-cols-2 gap-2 text-[12px]">
      <div class="stat"><div class="text-slate-400 text-[10.5px]">Cruces</div><div class="font-bold ${ok ? 'text-emerald-300' : 'text-rose-300'}">${m.hard.total}</div></div>
      <div class="stat"><div class="text-slate-400 text-[10.5px]">Score IA</div><div class="font-bold text-white">${fmtNum(m.score, 1)}% ${d(m.score, prevMetrics?.score)}</div></div>
      <div class="stat"><div class="text-slate-400 text-[10.5px]">Horas huecas</div><div class="font-bold text-white">${m.gaps.total} ${d(m.gaps.total, prevMetrics?.gaps?.total, 'down', 0)}</div></div>
      <div class="stat"><div class="text-slate-400 text-[10.5px]">Bloques reubicados</div><div class="font-bold text-violet-300">${result.moved ?? 0}</div></div>
    </div>
    ${impacts.length ? `<ul class="mt-2 space-y-1 text-[12px] text-slate-300">${impacts.map((i) => `<li class="flex gap-1.5"><i data-lucide="corner-down-right" class="w-3.5 h-3.5 mt-0.5 text-cyan-300 shrink-0"></i><span>${i}</span></li>`).join('')}</ul>` : ''}
    <p class="mt-2 text-[10.5px] text-slate-500 font-mono">${escapeHtml(s.engine)} · ${fmtNum(s.iterations || 0, 0)} iteraciones · ${s.kempeMoves || 0} cadenas de Kempe</p>`;
}
