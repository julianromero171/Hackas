/** Selector de entidad, grilla del horario (vista curso / docente / aula) y leyenda. */
import { buildSchedule } from '../core/time.js';
import { escapeHtml, shortName, initials } from '../core/utils.js';

export function renderSelector(el, store) {
  const { data, view, entity, rules } = store;
  let items;
  if (view === 'curso') {
    items = data.cursos.map((c) => ({ id: c.id, label: c.nombre, sub: `${c.estudiantes} estudiantes` }));
  } else if (view === 'docente') {
    items = data.docentes.map((d) => ({
      id: d.id,
      label: d.nombre,
      sub: (d.asignaturas || []).map((s) => data.asignaturas.find((a) => a.id === s)?.nombre || s).join(', '),
      avatar: initials(d.nombre),
      dot: rules.some((r) => r.teacherId === d.id),
    }));
  } else {
    items = data.aulas.map((a) => ({ id: a.id, label: a.nombre, sub: `${data.tiposEspacio?.[a.tipo] || a.tipo} · ${a.capacidad}` }));
  }
  const cur = entity[view];
  el.innerHTML = items.map((it) => `
    <button type="button" class="chip ${it.id === cur ? 'is-active' : ''}" data-entity="${it.id}" id="sel-${view}-${it.id}">
      ${it.avatar ? `<span class="chip-avatar">${it.avatar}</span>` : ''}
      <span class="flex flex-col items-start leading-tight">
        <span class="text-[13px] font-semibold">${escapeHtml(it.label)}</span>
        <span class="text-[10px] text-slate-400">${escapeHtml(it.sub)}</span>
      </span>
      ${it.dot ? '<span class="chip-dot" title="Tiene restricciones del copiloto"></span>' : ''}
    </button>`).join('');
}

export function renderTimetable(el, store) {
  const { problem: P, result, view, entity } = store;
  if (!result || !P) return;
  const { grid, rooms, metrics } = result;
  const L = P.lessons;
  const days = P.data.jornada.dias;
  const sched = buildSchedule(P.data.jornada);
  const conflictSet = new Set(metrics.conflicts || []);
  let cellFn;

  if (view === 'curso') {
    const c = Math.max(0, P.courses.findIndex((x) => x.id === entity.curso));
    cellFn = (t) => {
      const l = grid[c][t];
      const sel = store.swapSel && store.swapSel.c === c && store.swapSel.t === t;
      const changed = store.changed.has(c * P.S + t);
      if (l < 0) return `<button type="button" class="tt-empty ${sel ? 'is-selected' : ''}" data-t="${t}" id="cell-${c}-${t}">Libre</button>`;
      const ls = L[l], sub = P.subjects[ls.s], T = P.teachers[ls.p];
      const ri = rooms[c][t];
      const room = ri >= 0 ? P.rooms[ri].nombre : 'Sin aula';
      const pinned = store.pinned.has(l);
      const conflict = conflictSet.has(c * P.S + t);
      return `<button type="button" class="tt-cell ${sel ? 'is-selected' : ''} ${changed ? 'is-changed' : ''} ${conflict ? 'is-conflict' : ''}" style="--sc:${sub.color}" data-t="${t}" id="cell-${c}-${t}" title="${escapeHtml(`${sub.nombre} · ${T.nombre} · ${room}`)}">
        <div class="flex items-start justify-between gap-1"><span class="tt-subject">${escapeHtml(sub.nombre)}</span>
          <span class="flex gap-0.5 shrink-0">${ls.heavy ? '<i data-lucide="brain" class="tt-ico text-amber-300/90"></i>' : ''}${pinned ? '<i data-lucide="lock" class="tt-ico text-cyan-300"></i>' : ''}</span></div>
        <div class="tt-meta">${escapeHtml(shortName(T.nombre))}</div>
        <div class="tt-room"><i data-lucide="map-pin" class="tt-ico"></i>${escapeHtml(room)}</div>
      </button>`;
    };
  } else if (view === 'docente') {
    const p = P.tIdx.get(entity.docente) ?? 0;
    const at = new Array(P.S).fill(null);
    grid.forEach((row, c) => row.forEach((l, t) => { if (l >= 0 && L[l].p === p) (at[t] ||= []).push(c); }));
    const span = Array.from({ length: P.days }, (_, d) => {
      let first = -1, last = -1;
      for (let b = 0; b < P.B; b++) if (at[d * P.B + b]) { if (first < 0) first = b; last = b; }
      return [first, last];
    });
    cellFn = (t) => {
      const cs = at[t];
      const d = (t / P.B) | 0, b = t % P.B;
      if (cs) {
        const c = cs[0], l = grid[c][t], ls = L[l], sub = P.subjects[ls.s];
        const ri = rooms[c][t];
        const conflict = cs.length > 1 || P.unavailable[p][t];
        return `<div class="tt-cell ${conflict ? 'is-conflict' : ''} ${store.changed.has(c * P.S + t) ? 'is-changed' : ''}" style="--sc:${sub.color}">
          <span class="tt-subject">${escapeHtml(P.courses[c].nombre)}${cs.length > 1 ? ` <span class="text-rose-300">+${cs.length - 1}</span>` : ''}</span>
          <div class="tt-meta">${escapeHtml(sub.nombre)}</div>
          <div class="tt-room"><i data-lucide="map-pin" class="tt-ico"></i>${escapeHtml(ri >= 0 ? P.rooms[ri].nombre : 'Sin aula')}</div>
        </div>`;
      }
      if (P.unavailable[p][t]) {
        return `<div class="tt-unavailable" title="${escapeHtml(P.unavailReason[p][t] || '')}"><i data-lucide="ban"></i><span>No disponible</span></div>`;
      }
      const [first, last] = span[d];
      if (first >= 0 && b > first && b < last) return '<div class="tt-gap"><i data-lucide="hourglass"></i>Hora hueca</div>';
      return '<div class="tt-free"><i data-lucide="coffee"></i>Libre</div>';
    };
  } else {
    const r = P.rIdx.get(entity.aula) ?? 0;
    const at = new Array(P.S).fill(null);
    rooms.forEach((row, c) => row.forEach((ri, t) => { if (ri === r) (at[t] ||= []).push(c); }));
    cellFn = (t) => {
      const cs = at[t];
      if (!cs) return '<div class="tt-free">Disponible</div>';
      const c = cs[0], l = grid[c][t], ls = L[l], sub = P.subjects[ls.s];
      return `<div class="tt-cell" style="--sc:${sub.color}">
        <span class="tt-subject">${escapeHtml(P.courses[c].nombre)} · ${escapeHtml(sub.nombre)}</span>
        <div class="tt-meta">${escapeHtml(P.teachers[ls.p].nombre)}</div>
        <div class="tt-room"><i data-lucide="users" class="tt-ico"></i>${P.courses[c].estudiantes} / ${P.rooms[r].capacidad} puestos</div>
      </div>`;
    };
  }

  let html = `<table class="tt-table w-full min-w-[780px]"><thead><tr><th class="tt-th w-[96px]"></th>${days.map((d) => `<th class="tt-th">${d}</th>`).join('')}</tr></thead><tbody>`;
  for (const row of sched) {
    if (row.recreo) {
      html += `<tr><td colspan="${days.length + 1}"><div class="tt-break-inner"><i data-lucide="coffee"></i>${escapeHtml(row.nombre)} · ${row.inicio}–${row.fin}</div></td></tr>`;
      continue;
    }
    const b = row.bloque;
    html += `<tr><td class="tt-time"><div class="text-[11px] font-semibold text-slate-300">Bloque ${b + 1}</div><div class="text-[10px] text-slate-500 font-mono">${row.inicio}–${row.fin}</div></td>`;
    for (let d = 0; d < days.length; d++) html += `<td class="tt-td">${cellFn(d * P.B + b)}</td>`;
    html += '</tr>';
  }
  el.innerHTML = html + '</tbody></table>';
}

export function renderLegend(el, store) {
  const { problem: P, view } = store;
  if (!P) return;
  const marks = `
    <span class="ent"><i data-lucide="brain" class="text-amber-300"></i>Alta carga cognitiva</span>
    <span class="ent"><i data-lucide="lock" class="text-cyan-300"></i>Fijado manualmente</span>`;
  if (view === 'curso') {
    el.innerHTML = P.subjects.map((s) => `<span class="ent"><span class="legend-dot" style="background:${s.color}"></span>${escapeHtml(s.nombre)}</span>`).join('') + marks;
  } else if (view === 'docente') {
    el.innerHTML = `
      <span class="ent"><span class="legend-dot" style="background:repeating-linear-gradient(-45deg,#f43f5e 0 3px,transparent 3px 6px)"></span>No disponible</span>
      <span class="ent"><span class="legend-dot" style="background:#fbbf24"></span>Hora hueca</span>
      <span class="ent"><span class="legend-dot" style="border:1px dashed #64748b"></span>Libre</span>`;
  } else {
    el.innerHTML = Object.entries(P.data.tiposEspacio || {}).map(([k, v]) => `<span class="ent"><i data-lucide="door-open"></i>${escapeHtml(v)}</span>`).join('');
  }
}
