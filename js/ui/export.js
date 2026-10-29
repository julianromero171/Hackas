/** Exportación a CSV (Excel-friendly) e impresión / PDF de todos los cursos. */
import { buildSchedule, blockTimes } from '../core/time.js';
import { escapeHtml, fmtNum } from '../core/utils.js';

export function exportCSV(store) {
  const { problem: P, result } = store;
  if (!P || !result) return;
  const times = blockTimes(P.data.jornada);
  const rows = [['Curso', 'Día', 'Bloque', 'Inicio', 'Fin', 'Asignatura', 'Docente', 'Aula', 'Tipo de espacio', 'Carga cognitiva']];
  P.courses.forEach((course, c) => {
    for (let d = 0; d < P.days; d++) {
      for (let b = 0; b < P.B; b++) {
        const t = d * P.B + b;
        const l = result.grid[c][t];
        const base = [course.nombre, P.data.jornada.dias[d], b + 1, times[b].inicio, times[b].fin];
        if (l < 0) { rows.push([...base, 'Libre', '', '', '', '']); continue; }
        const ls = P.lessons[l], sub = P.subjects[ls.s];
        const ri = result.rooms[c][t];
        const room = ri >= 0 ? P.rooms[ri] : null;
        rows.push([...base, sub.nombre, P.teachers[ls.p].nombre, room?.nombre || '', room ? (P.data.tiposEspacio?.[room.tipo] || room.tipo) : '', sub.cargaCognitiva]);
      }
    }
  });
  const csv = '\ufeff' + rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(';')).join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `horario_gnosoft_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1500);
}

export function printAll(store) {
  const { problem: P, result } = store;
  if (!P || !result) return;
  const sched = buildSchedule(P.data.jornada);
  const dias = P.data.jornada.dias;
  const m = result.metrics;
  const date = new Date().toLocaleDateString('es-CO', { dateStyle: 'long' });
  const pages = P.courses.map((course, c) => {
    let body = '';
    for (const row of sched) {
      if (row.recreo) { body += `<tr class="print-break"><td colspan="${dias.length + 1}">${escapeHtml(row.nombre)} · ${row.inicio}–${row.fin}</td></tr>`; continue; }
      body += `<tr><th>B${row.bloque + 1}<br><small>${row.inicio}–${row.fin}</small></th>`;
      for (let d = 0; d < dias.length; d++) {
        const t = d * P.B + row.bloque, l = result.grid[c][t];
        if (l < 0) { body += '<td>—</td>'; continue; }
        const ls = P.lessons[l], sub = P.subjects[ls.s], ri = result.rooms[c][t];
        body += `<td class="pc" style="--sc:${sub.color}"><b>${escapeHtml(sub.nombre)}</b><br>${escapeHtml(P.teachers[ls.p].nombre)}<br><small>${escapeHtml(ri >= 0 ? P.rooms[ri].nombre : '')}</small></td>`;
      }
      body += '</tr>';
    }
    return `<section class="print-page">
      <div class="print-head"><h2 style="font-size:18px;margin:0">${escapeHtml(P.data.institucion || '')} · Horario ${escapeHtml(course.nombre)}</h2>
      <span style="font-size:10px">${date} · Score IA ${fmtNum(m.score, 1)}% · Cruces ${m.hard.total} · Bloques de ${P.data.jornada.duracionBloque} min</span></div>
      <table class="print-table"><thead><tr><th style="width:70px"></th>${dias.map((d) => `<th>${d}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table>
      <p style="font-size:9px;color:#666;margin-top:6px">Generado por GnoSoft Timetable AI — ${escapeHtml(result.stats.engine)}</p>
    </section>`;
  });
  document.getElementById('print-area').innerHTML = pages.join('');
  setTimeout(() => window.print(), 50);
}
