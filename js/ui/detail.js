/** Panel de detalle contextual: curso, docente (carga, libres, restricciones) o aula. */
import { escapeHtml, initials } from '../core/utils.js';
import { blocksLabel } from '../ai/nlp.js';

export function renderDetail(el, store) {
  const { problem: P, result, view, entity, rules } = store;
  if (!P || !result) { el.innerHTML = ''; return; }
  const { grid, metrics, rooms } = result;
  const L = P.lessons;
  const dias = P.data.jornada.dias;

  if (view === 'docente') {
    const p = P.tIdx.get(entity.docente) ?? 0;
    const T = P.teachers[p];
    const st = metrics.teachers[p];
    const pct = Math.min(100, (st.horas / st.max) * 100);
    const courses = [...new Set(grid.flatMap((row, c) => row.some((l) => l >= 0 && L[l].p === p) ? [P.courses[c].nombre] : []))];
    const base = (T.noDisponible || []).map((nd) => `<span class="ent"><i data-lucide="calendar-x"></i>${escapeHtml(nd.dia)} · ${blocksLabel(nd.bloques.map((b) => b - 1), P.B)} <span class="text-slate-500">(ficha)</span></span>`);
    const ai = rules.filter((r) => r.teacherId === T.id).map((r) => `<span class="ent !bg-rose-500/15 !text-rose-200"><i data-lucide="sparkles"></i>${escapeHtml(r.label)}</span>`);
    const restr = [...ai, ...base];
    el.innerHTML = `
      <div class="rounded-xl border border-white/5 bg-white/[0.02] p-4 grid md:grid-cols-[auto,1fr,auto] gap-4 items-center">
        <div class="flex items-center gap-3">
          <span class="chip-avatar !w-12 !h-12 !rounded-xl !text-base">${initials(T.nombre)}</span>
          <div>
            <div class="text-white font-semibold">${escapeHtml(T.nombre)}</div>
            <div class="text-xs text-slate-400">${escapeHtml((T.asignaturas || []).map((s) => P.subjects[P.sIdx.get(s)]?.nombre).join(', '))} · ${escapeHtml(courses.join(', '))}</div>
          </div>
        </div>
        <div>
          <div class="flex justify-between text-xs mb-1"><span class="text-slate-400">Carga horaria semanal</span><span class="font-mono text-white">${st.horas} / ${st.max} h</span></div>
          <div class="loadbar ${pct > 90 ? 'is-high' : ''}"><span style="width:${pct.toFixed(1)}%"></span></div>
          <div class="mt-2 flex flex-wrap gap-1.5">${restr.length ? restr.join('') : '<span class="text-[11px] text-slate-500">Sin restricciones de disponibilidad activas</span>'}</div>
        </div>
        <div class="grid grid-cols-3 gap-2 text-center">
          <div class="stat"><div class="text-lg font-bold text-emerald-300">${st.libres}</div><div class="text-[10px] text-slate-400">Libres</div></div>
          <div class="stat"><div class="text-lg font-bold ${st.huecos ? 'text-amber-300' : 'text-white'}">${st.huecos}</div><div class="text-[10px] text-slate-400">Huecas</div></div>
          <div class="stat"><div class="text-lg font-bold text-rose-300">${st.noDisponibles}</div><div class="text-[10px] text-slate-400">No disp.</div></div>
        </div>
      </div>`;
    return;
  }

  if (view === 'curso') {
    const c = Math.max(0, P.courses.findIndex((x) => x.id === entity.curso));
    const course = P.courses[c];
    const perDay = dias.map((_, d) => {
      let heavy = 0, total = 0;
      for (let b = 0; b < P.B; b++) { const l = grid[c][d * P.B + b]; if (l >= 0) { total++; if (L[l].heavy) heavy++; } }
      return { heavy, total };
    });
    let lastHeavy = 0;
    for (let d = 0; d < P.days; d++) { const l = grid[c][d * P.B + P.B - 1]; if (l >= 0 && L[l].heavy) lastHeavy++; }
    el.innerHTML = `
      <div class="rounded-xl border border-white/5 bg-white/[0.02] p-4 flex flex-wrap items-center gap-6">
        <div>
          <div class="text-white font-semibold text-base">${escapeHtml(course.nombre)}</div>
          <div class="text-xs text-slate-400">${course.estudiantes} estudiantes · Aula base ${escapeHtml(P.rooms[P.homeroom[c]]?.nombre || '—')} · ${P.courseLessons[c].length} h/semana</div>
        </div>
        <div class="flex items-end gap-3 h-12" aria-label="Carga cognitiva diaria">
          ${perDay.map((x, d) => `
            <div class="flex flex-col items-center gap-1" title="${dias[d]}: ${x.heavy} pesadas / ${x.total} clases">
              <div class="w-6 h-9 rounded-md bg-white/5 overflow-hidden flex flex-col justify-end">
                <span style="height:${(x.heavy / P.B) * 100}%" class="block bg-gradient-to-t from-amber-400 to-rose-400"></span>
              </div>
              <span class="text-[10px] text-slate-500">${dias[d].slice(0, 3)}</span>
            </div>`).join('')}
        </div>
        <div class="flex gap-2 ml-auto">
          <span class="ent"><i data-lucide="brain" class="text-amber-300"></i>Pesadas al final: ${lastHeavy}</span>
          <span class="ent"><i data-lucide="mouse-pointer-click" class="text-cyan-300"></i>Click-to-Swap activo</span>
        </div>
      </div>`;
    return;
  }

  const r = P.rIdx.get(entity.aula) ?? 0;
  const room = P.rooms[r];
  const use = metrics.rooms[r];
  const perDay = dias.map((_, d) => {
    let n = 0;
    for (let b = 0; b < P.B; b++) for (let c = 0; c < P.nC; c++) if (rooms[c][d * P.B + b] === r) n++;
    return n;
  });
  el.innerHTML = `
    <div class="rounded-xl border border-white/5 bg-white/[0.02] p-4 flex flex-wrap items-center gap-6">
      <div>
        <div class="text-white font-semibold text-base">${escapeHtml(room.nombre)}</div>
        <div class="text-xs text-slate-400">${escapeHtml(P.data.tiposEspacio?.[room.tipo] || room.tipo)} · Capacidad ${room.capacidad}</div>
      </div>
      <div class="min-w-[200px] flex-1">
        <div class="flex justify-between text-xs mb-1"><span class="text-slate-400">Ocupación semanal</span><span class="font-mono text-white">${use.ocupados}/${P.S} · ${use.uso.toFixed(0)}%</span></div>
        <div class="loadbar"><span style="width:${use.uso.toFixed(1)}%"></span></div>
      </div>
      <div class="flex gap-2">${perDay.map((n, d) => `<span class="ent">${dias[d].slice(0, 3)} ${n}</span>`).join('')}</div>
    </div>`;
}
