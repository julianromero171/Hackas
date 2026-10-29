/**
 * GnoSoft Timetable AI — orquestador de la aplicación.
 * Conecta: datos → copiloto NLP → reglas → motor (Worker JS o CP-SAT) → dashboard.
 */
import { DEFAULT_WEIGHTS, buildProblem } from './engine/model.js';
import { SolverClient } from './engine/client.js';
import { computeMetrics, assignRooms, gridFromHorario, diffCells } from './engine/metrics.js';
import { explainSwap, slotLabel } from './engine/explain.js';
import { parseInstruction, DEMO_PROMPTS, blocksLabel } from './ai/nlp.js';
import { parseWithGemini } from './ai/llm.js';
import { Chat } from './ui/chat.js';
import * as cards from './ui/chatCards.js';
import { renderKpis } from './ui/kpis.js';
import { renderSelector, renderTimetable, renderLegend } from './ui/timetable.js';
import { renderDetail } from './ui/detail.js';
import { initSliders, setWeightsUI, renderRules } from './ui/controls.js';
import { exportCSV, printAll } from './ui/export.js';
import { toast } from './ui/toast.js';
import { openModal } from './ui/modal.js';
import { debounce, escapeHtml, sleep, fmtNum, log10Factorial } from './core/utils.js';

const $ = (sel) => document.querySelector(sel);
const icons = () => window.lucide?.createIcons();

const store = {
  data: null,
  problem: null,
  rules: [],
  weights: { ...DEFAULT_WEIGHTS },
  result: null,
  prevMetrics: null,
  view: 'curso',
  entity: { curso: null, docente: null, aula: null },
  pinned: new Set(),
  swapSel: null,
  changed: new Set(),
  engine: localStorage.getItem('gs.engine') || 'js',
  cpsatAvailable: false,
  timeBudget: +(localStorage.getItem('gs.budget') || 900),
  gemini: { key: localStorage.getItem('gs.geminiKey') || '', model: localStorage.getItem('gs.geminiModel') || 'gemini-2.5-flash' },
  solving: false,
  token: 0,
};
window.gnosoft = store; // depuración desde consola

const solver = new SolverClient();
let chat;

// ------------------------------------------------------------------ Init
async function init() {
  try {
    const res = await fetch('data/school.json', { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    store.data = await res.json();
  } catch (e) {
    $('#timetable').innerHTML = `<div class="p-8 text-rose-300 text-sm">No se pudo cargar <code>data/school.json</code> (${escapeHtml(e.message)}).<br>Sirve la app con un servidor HTTP: <code>python -m http.server 8080</code> o <code>uvicorn backend.main:app</code>.</div>`;
    return;
  }
  const d = store.data;
  store.entity = {
    curso: d.cursos[0].id,
    docente: d.docentes[0].id,
    aula: (d.aulas.find((a) => a.tipo !== 'estandar') || d.aulas[0]).id,
  };
  rebuildProblem();

  chat = new Chat({
    list: $('#chat-messages'), suggestions: $('#chat-suggestions'), form: $('#chat-form'), input: $('#chat-input'),
    onSend: handleInstruction, prompts: DEMO_PROMPTS,
  });
  chat.addBot(cards.welcome(d));
  updateAiMode();

  initSliders(store, debounce(() => runSolve({ reason: 'weights' }), 350));
  bindEvents();
  checkBackend();
  await runSolve({ cold: true, reason: 'inicial' });
  icons();
}

function rebuildProblem() {
  store.problem = buildProblem(store.data, store.rules);
}

function bindEvents() {
  $('#view-tabs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-view]');
    if (!b) return;
    store.view = b.dataset.view;
    store.swapSel = null;
    renderView();
  });
  $('#entity-selector').addEventListener('click', (e) => {
    const b = e.target.closest('[data-entity]');
    if (!b) return;
    store.entity[store.view] = b.dataset.entity;
    store.swapSel = null;
    renderView();
  });
  $('#timetable').addEventListener('click', (e) => {
    const cell = e.target.closest('[data-t]');
    if (!cell || store.view !== 'curso' || store.solving) return;
    onCourseCellClick(+cell.dataset.t);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && store.swapSel) { store.swapSel = null; renderView(); }
  });
  $('#btn-optimize').addEventListener('click', async () => {
    const out = await runSolve({ reason: 'manual' });
    if (out) toast(`Horario re-optimizado en ${fmtNum(out.result.stats.ms, 0)} ms · Score ${fmtNum(out.result.metrics.score, 1)}%`, 'success');
  });
  $('#btn-reset').addEventListener('click', async () => {
    store.pinned.clear();
    const out = await runSolve({ cold: true, reason: 'reset' });
    if (out) toast('Horario generado desde cero (bloques fijados liberados).', 'info');
  });
  $('#btn-csv').addEventListener('click', () => { exportCSV(store); toast('CSV exportado (separador “;”, compatible con Excel).', 'success'); });
  $('#btn-print').addEventListener('click', () => printAll(store));
  $('#btn-settings').addEventListener('click', openSettings);
  $('#settings-dialog').addEventListener('close', onSettingsClose);
  $('#set-budget').addEventListener('input', (e) => { $('#set-budget-out').textContent = `${e.target.value} ms`; });
}

async function checkBackend() {
  try {
    const ctrl = new AbortController();
    setTimeout(() => ctrl.abort(), 1500);
    const res = await fetch('api/health', { signal: ctrl.signal, cache: 'no-store' });
    const j = res.ok ? await res.json() : null;
    store.cpsatAvailable = !!j?.ok;
  } catch {
    store.cpsatAvailable = false;
  }
  if (!store.cpsatAvailable && store.engine === 'cpsat') store.engine = 'js';
  renderEngineStatus();
}

function updateAiMode() {
  const el = $('#ai-mode');
  el.textContent = store.gemini.key ? 'Gemini + NLP' : 'NLP local';
}

// ------------------------------------------------------------------ Solve
async function runSolve({ cold = false, reason = '' } = {}) {
  const token = ++store.token;
  store.solving = true;
  renderEngineStatus();
  const prevGrid = store.result?.grid || null;
  const prevMetrics = store.result?.metrics || null;
  let result;
  try {
    if (store.engine === 'cpsat' && store.cpsatAvailable) {
      result = await solveCpsat();
    } else {
      result = await solver.solve({
        data: store.data,
        rules: store.rules,
        weights: store.weights,
        warmGrid: cold ? null : prevGrid,
        pinned: cold ? [] : [...store.pinned],
        timeLimitMs: store.timeBudget,
        seed: (Math.random() * 1e9) | 0,
      });
    }
  } catch (err) {
    console.error(err);
    if (token === store.token) { store.solving = false; renderEngineStatus(); }
    toast(`Error del motor: ${err.message}`, 'error');
    return null;
  }
  if (token !== store.token) return null; // resultado obsoleto
  store.changed = diffCells(store.problem, prevGrid, result.grid);
  result.moved = store.changed.size;
  if (cold) store.pinned.clear();
  store.prevMetrics = prevMetrics;
  store.result = result;
  store.solving = false;
  renderAll();
  store.changed = new Set();
  return { result, prevGrid, prevMetrics, reason };
}

async function solveCpsat() {
  const res = await fetch('api/solve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data: store.data, rules: store.rules, weights: store.weights, timeLimit: 10 }),
  });
  if (!res.ok) throw new Error(`CP-SAT HTTP ${res.status}`);
  const out = await res.json();
  if (!out.horario) throw new Error(`CP-SAT: ${out.status}${out.issues?.length ? ' — ' + out.issues.join(' ') : ''}`);
  const P = store.problem;
  const grid = gridFromHorario(P, out.horario);
  return {
    grid,
    rooms: assignRooms(P, grid),
    metrics: computeMetrics(P, grid, store.weights),
    issues: P.issues,
    stats: {
      engine: `Google OR-Tools CP-SAT (${out.status})`,
      ms: out.wallTimeMs,
      iterations: out.branches || 0,
      kempeMoves: 0,
      attempts: 1,
      constructHard: null,
      lessons: P.lessons.length,
      slots: P.S * P.nC,
      searchSpaceLog10: P.nC * log10Factorial(P.S),
      objective: out.objective,
    },
  };
}

// ------------------------------------------------------------------ Render
function renderAll() {
  if (!store.result) return;
  renderKpis(store.result.metrics, store.prevMetrics);
  renderView();
  renderEngineStatus();
  renderSolverLog();
  renderRules(store, removeRule);
  renderIssues();
  icons();
}

function renderView() {
  document.querySelectorAll('#view-tabs [data-view]').forEach((b) => {
    const active = b.dataset.view === store.view;
    b.classList.toggle('is-active', active);
    b.setAttribute('aria-selected', active);
  });
  renderSelector($('#entity-selector'), store);
  renderDetail($('#detail-panel'), store);
  renderTimetable($('#timetable'), store);
  renderLegend($('#legend'), store);
  const P = store.problem;
  const j = P.data.jornada;
  $('#tt-subtitle').textContent = `${P.nC} cursos · ${P.S * P.nC} bloques semanales · bloques de ${j.duracionBloque} min desde las ${j.horaInicio}`;
  const hint = $('#swap-hint');
  if (store.view === 'curso') {
    hint.innerHTML = store.swapSel
      ? `<span class="spinner !w-3 !h-3"></span><span class="text-cyan-300">Bloque seleccionado (${escapeHtml(slotLabel(P, store.swapSel.t))}). Elige otro bloque para intercambiar · Esc para cancelar.</span>`
      : '<i data-lucide="mouse-pointer-click" class="w-3.5 h-3.5 text-cyan-300"></i><span>Edición manual validada por IA: haz clic en dos bloques para intercambiarlos.</span>';
  } else {
    hint.innerHTML = store.view === 'docente'
      ? '<i data-lucide="info" class="w-3.5 h-3.5"></i><span>Bloques libres, horas huecas y restricciones activas del docente.</span>'
      : '<i data-lucide="info" class="w-3.5 h-3.5"></i><span>Ocupación del espacio con validación de tipo y capacidad.</span>';
  }
  icons();
}

function renderEngineStatus() {
  const el = $('#engine-status');
  if (store.solving) {
    el.innerHTML = '<span class="spinner"></span><span>Optimizando…</span>';
    return;
  }
  const r = store.result;
  if (!r) { el.innerHTML = ''; return; }
  const ok = r.metrics.hard.total === 0;
  const eng = store.engine === 'cpsat' && store.cpsatAvailable ? 'OR-Tools CP-SAT' : 'CSP + Kempe + SA';
  el.innerHTML = `<span class="dot-live ${ok ? '' : 'dot-bad'}"></span><span class="text-slate-200 font-medium">${eng}</span><span class="text-slate-500">·</span><span class="font-mono">${fmtNum(r.stats.ms, 0)} ms</span><span class="text-slate-500">·</span><span class="${ok ? 'text-emerald-300' : 'text-rose-300'}">${r.metrics.hard.total} cruces</span>`;
}

function renderSolverLog() {
  const r = store.result;
  if (!r) return;
  const s = r.stats;
  const rows = [
    ['Motor', s.engine],
    ['Tiempo', `${fmtNum(s.ms, 0)} ms`],
    ['Lecciones', `${s.lessons} (${s.slots} bloques)`],
    ['Espacio de búsqueda', `≈ 10^${Math.round(s.searchSpaceLog10 || 0)}`],
    ['Iteraciones', fmtNum(s.iterations || 0, 0)],
    ['Cadenas de Kempe', fmtNum(s.kempeMoves || 0, 0)],
    ['Conflictos iniciales', s.constructHard ?? '—'],
    ['Conflictos finales', r.metrics.hard.total],
    ['Arranques', `${s.attempts}${s.warm ? ' · incremental' : ''}`],
    ['Objetivo J', fmtNum(r.metrics.objective, 1)],
  ];
  $('#solver-log').innerHTML = rows.map(([k, v], i) => `
    <dt class="text-slate-400 ${i === 0 ? 'col-span-2' : ''}">${k}</dt>
    <dd class="text-right font-mono text-slate-200 ${i === 0 ? 'col-span-2 !text-left text-[11px] text-cyan-200 -mt-1' : ''}">${escapeHtml(String(v))}</dd>`).join('');
}

function renderIssues() {
  const errs = (store.problem?.issues || []).filter((i) => i.nivel === 'error');
  $('#issues').innerHTML = errs.length
    ? `<div class="glass rounded-xl border !border-rose-500/40 p-4 text-sm text-rose-200 flex gap-3"><i data-lucide="octagon-alert" class="w-5 h-5 shrink-0"></i><div><b>Datos de entrada infactibles:</b><ul class="list-disc ml-5 mt-1 text-rose-100/90">${errs.map((e) => `<li>${escapeHtml(e.msg)}</li>`).join('')}</ul></div></div>`
    : '';
}

// ------------------------------------------------------------------ Click-to-swap
function onCourseCellClick(t) {
  const P = store.problem;
  const c = P.courses.findIndex((x) => x.id === store.entity.curso);
  if (!store.swapSel) { store.swapSel = { c, t }; renderView(); return; }
  if (store.swapSel.t === t) { store.swapSel = null; renderView(); return; }
  const t1 = store.swapSel.t;
  store.swapSel = null;
  attemptSwap(c, t1, t);
}

function attemptSwap(c, t1, t2) {
  const P = store.problem;
  const grid = store.result.grid;
  const ex = explainSwap(P, grid, store.weights, c, t1, t2);
  if (ex.ok) {
    const prevScore = store.result.metrics.score;
    commitGrid(ex.grid, [c], t1, t2);
    toast(`Intercambio validado ✓ · 0 cruces · Score ${fmtNum(prevScore, 1)}% → ${fmtNum(store.result.metrics.score, 1)}%`, 'success');
    return;
  }
  const course = P.courses[c].nombre;
  const kempe = ex.kempe;
  let kempeHtml = '<p class="mt-4 text-[12.5px] text-slate-400">No existe una cadena de Kempe que haga válido este intercambio. Prueba otra franja o pide al copiloto que re-optimice.</p>';
  let kempeScore = null;
  if (kempe) {
    kempeScore = computeMetrics(P, kempe.grid, store.weights).score;
    kempeHtml = `
      <div class="mt-4 rounded-xl border border-cyan-400/30 bg-cyan-400/5 p-3 text-[12.5px]">
        <div class="flex items-center gap-2 text-cyan-200 font-semibold"><i data-lucide="git-compare-arrows" class="w-4 h-4"></i>Alternativa encontrada: cadena de Kempe</div>
        <p class="mt-1 text-slate-300">Intercambiando simultáneamente las mismas franjas en <b>${kempe.courses.map((x) => P.courses[x].nombre).join(', ')}</b> se mantienen <b>0 cruces</b>. Score resultante: <b>${fmtNum(kempeScore, 1)}%</b>.</p>
      </div>`;
  }
  openModal(`
    <div class="flex items-start gap-3">
      <span class="kpi-icon bg-rose-500/15 text-rose-300 !w-10 !h-10"><i data-lucide="shield-alert"></i></span>
      <div class="min-w-0">
        <h3 class="text-white font-bold text-base">Intercambio bloqueado por la IA</h3>
        <p class="text-[12.5px] text-slate-400">${escapeHtml(course)}: ${escapeHtml(slotLabel(P, t1))} ⇄ ${escapeHtml(slotLabel(P, t2))} generaría ${ex.after.hard} violación(es) de restricciones duras:</p>
      </div>
    </div>
    <ul class="mt-4 space-y-2 text-[13px] text-slate-200">${ex.messages.map((m) => `<li class="flex gap-2 rounded-lg bg-rose-500/5 border border-rose-500/20 p-2.5"><i data-lucide="x-circle" class="w-4 h-4 text-rose-300 shrink-0 mt-0.5"></i><span>${m}</span></li>`).join('')}</ul>
    ${kempeHtml}
    <div class="mt-5 flex justify-end gap-2">
      <button type="button" class="btn" data-close>Cancelar</button>
      ${kempe ? '<button type="button" class="btn btn-primary" id="btn-apply-kempe"><i data-lucide="git-compare-arrows"></i>Aplicar cadena de Kempe</button>' : ''}
    </div>`, {
    onMount: (root, close) => {
      root.querySelector('#btn-apply-kempe')?.addEventListener('click', () => {
        commitGrid(kempe.grid, [c, ...kempe.courses], t1, t2);
        close();
        toast(`Cadena de Kempe aplicada en ${kempe.courses.length + 1} cursos · 0 cruces`, 'success');
      });
    },
  });
}

function commitGrid(newGrid, courses, t1, t2) {
  const P = store.problem;
  for (const c of courses) {
    for (const t of [t1, t2]) {
      const l = newGrid[c][t];
      if (l >= 0) store.pinned.add(l);
    }
  }
  store.changed = diffCells(P, store.result.grid, newGrid);
  store.prevMetrics = store.result.metrics;
  store.result = {
    ...store.result,
    grid: newGrid,
    rooms: assignRooms(P, newGrid),
    metrics: computeMetrics(P, newGrid, store.weights),
    moved: store.changed.size,
  };
  renderAll();
  store.changed = new Set();
}

// ------------------------------------------------------------------ Copiloto
async function handleInstruction(text) {
  chat.addUser(text);
  chat.setBusy(true);
  const typing = chat.typing('Analizando instrucción');
  let parsed;
  try {
    if (store.gemini.key) {
      try {
        parsed = await parseWithGemini(text, store.data, store.gemini);
        if (!parsed.actions.length) parsed = parseInstruction(text, store.data);
      } catch (err) {
        console.warn('[Gemini] fallback a NLP local:', err);
        parsed = parseInstruction(text, store.data);
      }
    } else {
      await sleep(280);
      parsed = parseInstruction(text, store.data);
    }
  } finally {
    typing.remove();
  }

  if (!parsed.actions.length) {
    chat.addBot(cards.notUnderstood(parsed, store.data));
    chat.setBusy(false);
    return;
  }

  const applied = [];
  let mustSolve = false;
  for (const a of parsed.actions) {
    if (a.kind === 'help') { chat.addBot(cards.help()); continue; }
    if (a.kind === 'clear') {
      store.rules = [];
      store.pinned.clear();
      store.weights = { ...DEFAULT_WEIGHTS };
      setWeightsUI(store.weights);
      applied.push(a); mustSolve = true; continue;
    }
    if (a.kind === 'undo') {
      a.removed = store.rules.pop();
      applied.push(a); mustSolve = !!a.removed; continue;
    }
    if (a.kind === 'weights') {
      Object.assign(store.weights, a.changes);
      setWeightsUI(store.weights);
      applied.push(a); mustSolve = true; continue;
    }
    if (a.kind === 'rule') {
      const check = feasibilityCheck(a.rule);
      if (!check.ok) { chat.addBot(cards.rejected(check.msg)); continue; }
      store.rules.push(a.rule);
      applied.push(a); mustSolve = true;
    }
  }

  if (applied.length) chat.addBot(cards.understanding(applied, store.data, parsed.source));
  if (parsed.notes?.length) chat.addBot(`<p class="text-amber-200 text-[12px]">${parsed.notes.join('<br>')}</p>`);

  if (mustSolve) {
    rebuildProblem();
    const t2 = chat.typing('Re-optimizando 180 bloques');
    const out = await runSolve({ reason: 'chat' });
    t2.remove();
    if (out) chat.addBot(cards.resultCard(out, impactLines(applied, out)));
  }
  chat.setBusy(false);
}

function feasibilityCheck(rule) {
  const before = new Set((store.problem?.issues || []).map((i) => i.msg));
  const P2 = buildProblem(store.data, [...store.rules, rule]);
  const added = P2.issues.filter((i) => i.nivel === 'error' && !before.has(i.msg));
  return added.length ? { ok: false, msg: added.map((i) => escapeHtml(i.msg)).join('<br>') } : { ok: true };
}

/** Explica el impacto concreto de cada regla comparando el horario anterior y el nuevo. */
function impactLines(applied, { result, prevGrid, prevMetrics }) {
  const P = store.problem, L = P.lessons, out = [];
  const g0 = prevGrid, g1 = result.grid;
  const count = (grid, pred) => {
    if (!grid) return null;
    let n = 0;
    grid.forEach((row) => row.forEach((l, t) => { if (l >= 0 && pred(L[l], t)) n++; }));
    return n;
  };
  for (const a of applied) {
    if (a.kind === 'rule') {
      const r = a.rule;
      if (r.type === 'teacher_unavailable') {
        const p = P.tIdx.get(r.teacherId);
        const pred = (ls, t) => ls.p === p && P.unavailable[p][t];
        const b0 = count(g0, pred), b1 = count(g1, pred);
        const name = P.teachers[p].nombre;
        out.push(b0 ? `${escapeHtml(name)} tenía <b>${b0}</b> clase(s) en la franja bloqueada → reubicadas sin cruces (ahora <b>${b1}</b>).`
          : `${escapeHtml(name)} no tenía clases en esa franja; la restricción queda blindada para futuras optimizaciones.`);
      } else if (r.type === 'subject_avoid') {
        const ids = new Set(r.subjectIds.map((id) => P.sIdx.get(id)));
        const days = r.days?.length ? new Set(r.days) : null;
        const blocks = new Set(r.blocks);
        const pred = (ls, t) => ids.has(ls.s) && blocks.has(t % P.B) && (!days || days.has((t / P.B) | 0));
        out.push(`${escapeHtml(r.subjectIds.map((id) => P.subjects[P.sIdx.get(id)].nombre).join(' y '))} en ${escapeHtml(blocksLabel(r.blocks, P.B).toLowerCase())}: <b>${count(g0, pred) ?? '—'}</b> → <b>${count(g1, pred)}</b> clases.`);
      } else if (r.type === 'subject_prefer_morning') {
        for (const id of r.subjectIds) {
          const si = P.sIdx.get(id);
          const avg = (grid) => {
            if (!grid) return null;
            let s = 0, n = 0;
            grid.forEach((row) => row.forEach((l, t) => { if (l >= 0 && L[l].s === si) { s += (t % P.B) + 1; n++; } }));
            return n ? s / n : 0;
          };
          const a0 = avg(g0), a1 = avg(g1);
          out.push(`Bloque promedio de ${escapeHtml(P.subjects[si].nombre)}: <b>${a0 === null ? '—' : fmtNum(a0, 2)}</b> → <b>${fmtNum(a1, 2)}</b> (1 = primera hora).`);
        }
      }
    } else if (a.kind === 'weights') {
      const k = Object.keys(a.changes)[0];
      if (k === 'gaps') out.push(`Horas huecas docentes: <b>${prevMetrics?.gaps.total ?? '—'}</b> → <b>${result.metrics.gaps.total}</b> (${result.metrics.gaps.teachersZero}/${P.nT} docentes con 0).`);
      if (k === 'fatigue') out.push(`Eventos de fatiga cognitiva: <b>${prevMetrics?.fatigue.total ?? '—'}</b> → <b>${result.metrics.fatigue.total}</b>.`);
      if (k === 'equity') out.push(`Índice de equidad: <b>${prevMetrics ? fmtNum(prevMetrics.equity.index, 1) : '—'}%</b> → <b>${fmtNum(result.metrics.equity.index, 1)}%</b>.`);
    }
  }
  return out;
}

function removeRule(id) {
  const r = store.rules.find((x) => x.id === id);
  store.rules = store.rules.filter((x) => x.id !== id);
  rebuildProblem();
  runSolve({ reason: 'remove' });
  if (r) toast(`Restricción eliminada: ${r.label}`, 'info');
}

// ------------------------------------------------------------------ Settings
function openSettings() {
  const j = store.data.jornada;
  const form = $('#settings-form');
  form.querySelectorAll('input[name="duracion"]').forEach((r) => { r.checked = +r.value === j.duracionBloque; });
  $('#set-start').value = j.horaInicio;
  $('#set-blocks').value = `${j.bloquesPorDia} bloques · ${j.dias.length} días`;
  const opts = Array.from({ length: j.bloquesPorDia - 1 }, (_, i) => `<option value="${i + 1}">Después del bloque ${i + 1}</option>`).join('');
  const [r1, r2] = [j.recreos?.[0], j.recreos?.[1]];
  $('#set-break1-after').innerHTML = opts;
  $('#set-break2-after').innerHTML = `<option value="0">Sin segundo recreo</option>${opts}`;
  $('#set-break1-after').value = r1?.despuesDeBloque ?? 2;
  $('#set-break1-min').value = r1?.duracion ?? 20;
  $('#set-break2-after').value = r2?.despuesDeBloque ?? 0;
  $('#set-break2-min').value = r2?.duracion ?? 30;
  const cps = $('#engine-cpsat');
  cps.disabled = !store.cpsatAvailable;
  $('#cpsat-note').textContent = store.cpsatAvailable ? 'Backend FastAPI conectado ✓' : 'Requiere backend FastAPI (uvicorn)';
  form.querySelectorAll('input[name="engine"]').forEach((r) => { r.checked = r.value === store.engine; });
  $('#set-budget').value = store.timeBudget;
  $('#set-budget-out').textContent = `${store.timeBudget} ms`;
  $('#set-gemini-key').value = store.gemini.key;
  $('#set-gemini-model').value = store.gemini.model;
  $('#settings-dialog').showModal();
  icons();
}

function onSettingsClose() {
  const dlg = $('#settings-dialog');
  if (dlg.returnValue !== 'save') return;
  const form = $('#settings-form');
  const j = store.data.jornada;
  j.duracionBloque = +(form.querySelector('input[name="duracion"]:checked')?.value || j.duracionBloque);
  j.horaInicio = $('#set-start').value || j.horaInicio;
  const b1 = +$('#set-break1-after').value, m1 = Math.max(5, +$('#set-break1-min').value || 20);
  const b2 = +$('#set-break2-after').value, m2 = Math.max(5, +$('#set-break2-min').value || 30);
  const recreos = [{ despuesDeBloque: b1, duracion: m1, nombre: 'Recreo pedagógico' }];
  if (b2 && b2 !== b1) recreos.push({ despuesDeBloque: b2, duracion: m2, nombre: 'Almuerzo' });
  j.recreos = recreos.sort((a, b) => a.despuesDeBloque - b.despuesDeBloque);
  store.engine = form.querySelector('input[name="engine"]:checked')?.value || 'js';
  store.timeBudget = +$('#set-budget').value;
  store.gemini.key = $('#set-gemini-key').value.trim();
  store.gemini.model = $('#set-gemini-model').value.trim() || 'gemini-2.5-flash';
  localStorage.setItem('gs.engine', store.engine);
  localStorage.setItem('gs.budget', String(store.timeBudget));
  localStorage.setItem('gs.geminiKey', store.gemini.key);
  localStorage.setItem('gs.geminiModel', store.gemini.model);
  updateAiMode();
  rebuildProblem();
  runSolve({ reason: 'settings' }).then((out) => {
    if (out) toast(`Configuración aplicada · bloques de ${j.duracionBloque} min · ${out.result.stats.engine}`, 'success');
  });
}

init();
