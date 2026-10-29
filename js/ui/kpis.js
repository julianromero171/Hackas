/** Tarjetas KPI en vivo con animación de conteo y deltas. */
import { fmtNum, escapeHtml } from '../core/utils.js';

function animateNumber(el, to, { dec = 0, suffix = '' } = {}) {
  if (!el) return;
  const from = parseFloat(el.dataset.current ?? '0') || 0;
  const start = performance.now();
  const dur = 750;
  cancelAnimationFrame(el._raf);
  const step = (t) => {
    const k = Math.min(1, (t - start) / dur);
    const e = 1 - Math.pow(1 - k, 3);
    el.textContent = fmtNum(from + (to - from) * e, dec) + suffix;
    if (k < 1) el._raf = requestAnimationFrame(step);
    else el.dataset.current = String(to);
  };
  el._raf = requestAnimationFrame(step);
}

/** better: 'up' si subir es bueno, 'down' si bajar es bueno */
function delta(el, cur, prev, { better = 'up', dec = 1, suffix = '' } = {}) {
  if (!el) return;
  if (prev === undefined || prev === null) { el.innerHTML = ''; return; }
  const d = cur - prev;
  if (Math.abs(d) < Math.pow(10, -dec) / 2) { el.innerHTML = '<span class="delta delta-flat">=</span>'; return; }
  const good = better === 'up' ? d > 0 : d < 0;
  el.innerHTML = `<span class="delta ${good ? 'delta-up' : 'delta-down'}">${d > 0 ? '▲' : '▼'} ${fmtNum(Math.abs(d), dec)}${suffix}</span>`;
}

export function renderKpis(m, prev) {
  // Cruces
  const kc = document.getElementById('kpi-conflicts');
  const hard = m.hard.total;
  kc.classList.toggle('is-bad', hard > 0);
  animateNumber(kc.querySelector('[data-value]'), hard);
  kc.querySelector('[data-badge]').innerHTML = hard === 0
    ? '<span class="tag tag-ok">0 % error</span>'
    : '<span class="tag tag-hard">revisar</span>';
  kc.querySelector('[data-sub]').textContent =
    `Docentes ${m.hard.teacherClashes} · Cursos ${m.hard.courseClashes} · Aulas ${m.hard.roomConflicts} · Disp. ${m.hard.unavailability}`;

  // Score
  const ks = document.getElementById('kpi-score');
  animateNumber(ks.querySelector('[data-value]'), m.score, { dec: 1, suffix: '%' });
  delta(ks.querySelector('[data-delta]'), m.score, prev?.score, { dec: 1 });
  const ring = document.getElementById('score-ring');
  const C = 2 * Math.PI * 26;
  ring.setAttribute('stroke-dasharray', C.toFixed(2));
  ring.setAttribute('stroke-dashoffset', (C * (1 - Math.max(0, Math.min(100, m.score)) / 100)).toFixed(2));
  ks.querySelector('[data-sub]').textContent =
    `Huecos ${m.subscores.gaps.toFixed(0)} · Fatiga ${m.subscores.fatigue.toFixed(0)} · Franjas ${m.subscores.morning.toFixed(0)} · Equidad ${m.subscores.equity.toFixed(0)}`;

  // Huecos
  const kg = document.getElementById('kpi-gaps');
  animateNumber(kg.querySelector('[data-value]'), m.gaps.total);
  delta(kg.querySelector('[data-delta]'), m.gaps.total, prev?.gaps?.total, { better: 'down', dec: 0 });
  kg.querySelector('[data-sub]').textContent = `${m.gaps.teachersZero}/${m.teachers.length} docentes con 0 horas huecas`;

  // Equidad
  const ke = document.getElementById('kpi-equity');
  animateNumber(ke.querySelector('[data-value]'), m.equity.index, { dec: 1, suffix: '%' });
  delta(ke.querySelector('[data-delta]'), m.equity.index, prev?.equity?.index, { dec: 1 });
  ke.querySelector('[data-sub]').textContent =
    `Fatiga: ${m.fatigue.consecutive} consecutivas · ${m.fatigue.lastBlock} al final del día`;

  // Laboratorios
  const kl = document.getElementById('kpi-labs');
  animateNumber(kl.querySelector('[data-value]'), m.labs.usage, { dec: 0, suffix: '%' });
  kl.querySelector('[data-bars]').innerHTML = m.labs.rooms.map((r) => `
    <div>
      <div class="flex justify-between text-[10.5px] text-slate-400"><span class="truncate">${escapeHtml(r.nombre)}</span><span class="font-mono">${r.ocupados} bl · ${r.uso.toFixed(0)}%</span></div>
      <div class="minibar"><span style="width:${r.uso.toFixed(1)}%"></span></div>
    </div>`).join('');
}
