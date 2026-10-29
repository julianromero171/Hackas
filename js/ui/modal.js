/** Modal genérico. Devuelve una función para cerrarlo. */
export function openModal(html, { onMount, width = 'w-[min(560px,94vw)]' } = {}) {
  const root = document.getElementById('modal-root');
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.innerHTML = `<div class="glass modal-card rounded-2xl p-6 ${width}" role="dialog" aria-modal="true">${html}</div>`;
  const close = () => {
    backdrop.style.transition = 'opacity .18s';
    backdrop.style.opacity = '0';
    setTimeout(() => backdrop.remove(), 180);
    document.removeEventListener('keydown', onKey);
  };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop || e.target.closest('[data-close]')) close();
  });
  document.addEventListener('keydown', onKey);
  root.appendChild(backdrop);
  window.lucide?.createIcons();
  onMount?.(backdrop, close);
  return close;
}
