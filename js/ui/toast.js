import { escapeHtml } from '../core/utils.js';

const STYLES = {
  success: { icon: 'check-circle-2', cls: 'border-emerald-400/30 text-emerald-200' },
  error: { icon: 'shield-alert', cls: 'border-rose-400/40 text-rose-200' },
  info: { icon: 'info', cls: 'border-cyan-400/30 text-cyan-100' },
  warn: { icon: 'triangle-alert', cls: 'border-amber-400/40 text-amber-100' },
};

/** Notificación flotante. `html` permite contenido enriquecido controlado. */
export function toast(message, type = 'info', { html = false, ms = 3600 } = {}) {
  const root = document.getElementById('toast-root');
  if (!root) return;
  const s = STYLES[type] || STYLES.info;
  const el = document.createElement('div');
  el.className = `toast glass rounded-xl px-4 py-3 text-[13px] flex items-start gap-2.5 max-w-sm border ${s.cls}`;
  el.innerHTML = `<i data-lucide="${s.icon}" class="w-4 h-4 mt-0.5 shrink-0"></i><div>${html ? message : escapeHtml(message)}</div>`;
  root.appendChild(el);
  window.lucide?.createIcons();
  setTimeout(() => {
    el.style.transition = 'opacity .3s, transform .3s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(6px)';
    setTimeout(() => el.remove(), 320);
  }, ms);
}
