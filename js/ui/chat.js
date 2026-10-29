/** Panel de chat del copiloto. */
import { escapeHtml } from '../core/utils.js';

export class Chat {
  constructor({ list, suggestions, form, input, onSend, prompts = [] }) {
    this.list = list;
    this.form = form;
    this.input = input;
    this.busy = false;
    suggestions.innerHTML = prompts.map((p, i) => `<button type="button" class="sugg" data-prompt="${escapeHtml(p)}" id="sugg-${i}">${escapeHtml(p)}</button>`).join('');
    suggestions.addEventListener('click', (e) => {
      const b = e.target.closest('[data-prompt]');
      if (b && !this.busy) onSend(b.dataset.prompt);
    });
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const v = input.value.trim();
      if (!v || this.busy) return;
      input.value = '';
      onSend(v);
    });
  }

  setBusy(b) {
    this.busy = b;
    this.input.disabled = b;
    this.form.querySelector('button[type="submit"]').disabled = b;
    if (!b) this.input.focus();
  }

  _append(html) {
    const wrap = document.createElement('div');
    wrap.innerHTML = html.trim();
    const node = wrap.firstElementChild;
    this.list.appendChild(node);
    window.lucide?.createIcons();
    requestAnimationFrame(() => this.list.scrollTo({ top: this.list.scrollHeight, behavior: 'smooth' }));
    return node;
  }

  addUser(text) {
    return this._append(`<div class="msg msg-user"><div class="bubble-user">${escapeHtml(text)}</div></div>`);
  }

  addBot(html) {
    return this._append(`<div class="msg"><div class="bot-avatar"><i data-lucide="sparkles"></i></div><div class="bubble-bot">${html}</div></div>`);
  }

  typing(label = 'Analizando instrucción') {
    const node = this._append(`<div class="msg"><div class="bot-avatar"><i data-lucide="sparkles"></i></div><div class="bubble-bot flex items-center gap-2"><span class="typing"><span></span><span></span><span></span></span><span class="text-xs text-slate-400" data-label>${escapeHtml(label)}…</span></div></div>`);
    return {
      set: (l) => { const el = node.querySelector('[data-label]'); if (el) el.textContent = `${l}…`; },
      remove: () => node.remove(),
    };
  }
}
