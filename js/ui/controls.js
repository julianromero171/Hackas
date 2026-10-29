/** Sliders de pesos de la función objetivo y lista de reglas activas. */
import { escapeHtml } from '../core/utils.js';

const KEYS = ['gaps', 'fatigue', 'morning', 'equity'];

function paint(input) {
  const pct = ((+input.value - +input.min) / (+input.max - +input.min)) * 100;
  input.style.setProperty('--val', `${pct}%`);
  const out = document.querySelector(`[data-out="${input.dataset.weight}"]`);
  if (out) out.textContent = input.value;
}

export function initSliders(store, onChange) {
  for (const k of KEYS) {
    const el = document.getElementById(`w-${k}`);
    el.value = store.weights[k];
    paint(el);
    el.addEventListener('input', () => {
      store.weights[k] = +el.value;
      paint(el);
      onChange(k);
    });
  }
}

export function setWeightsUI(weights) {
  for (const k of KEYS) {
    const el = document.getElementById(`w-${k}`);
    if (!el) continue;
    el.value = weights[k];
    paint(el);
    el.closest('div')?.parentElement?.classList.add('transition');
  }
}

const ICON = { teacher_unavailable: 'user-x', subject_avoid: 'ban', subject_prefer_morning: 'sunrise' };

export function renderRules(store, onRemove) {
  const list = document.getElementById('rules-list');
  document.getElementById('rules-count').textContent = store.rules.length;
  if (!store.rules.length) {
    list.innerHTML = '<li class="text-xs text-slate-500">Aún no hay restricciones. Escribe una instrucción en el copiloto o usa una sugerencia.</li>';
    return;
  }
  list.innerHTML = store.rules.map((r) => `
    <li class="group flex items-start gap-2.5 rounded-xl p-2.5 bg-white/[0.03] border border-white/5 hover:border-white/10 transition">
      <span class="kpi-icon !w-7 !h-7 !rounded-lg ${r.hard ? 'bg-rose-500/15 text-rose-300' : 'bg-violet-500/15 text-violet-300'}"><i data-lucide="${ICON[r.type] || 'sparkles'}" class="!w-3.5 !h-3.5"></i></span>
      <div class="min-w-0 flex-1">
        <div class="text-[12.5px] text-slate-200 leading-snug">${escapeHtml(r.label)}</div>
        <div class="mt-1 flex items-center gap-1.5"><span class="tag ${r.hard ? 'tag-hard' : 'tag-soft'}">${r.hard ? 'Dura' : 'Blanda'}</span><span class="font-mono text-[10px] text-slate-500 truncate">${escapeHtml(r.formal.split('\n')[0])}</span></div>
      </div>
      <button type="button" class="opacity-50 group-hover:opacity-100 text-slate-400 hover:text-rose-300 transition" data-remove-rule="${r.id}" aria-label="Eliminar restricción" id="rm-${r.id}"><i data-lucide="x" class="w-4 h-4"></i></button>
    </li>`).join('');
  list.querySelectorAll('[data-remove-rule]').forEach((b) => b.addEventListener('click', () => onRemove(b.dataset.removeRule)));
}
