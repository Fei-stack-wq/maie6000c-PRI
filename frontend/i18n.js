/* UI translation only. API data is inserted after static text is translated. */
(function () {
  'use strict';
  const storageKey = 'reviewlens-language';
  const supported = value => value === 'en' || value === 'zh';
  const requested = new URLSearchParams(window.location.search).get('lang');
  let saved;
  try { saved = localStorage.getItem(storageKey); } catch (_) { /* URL works without storage. */ }
  const language = supported(requested) ? requested : supported(saved) ? saved : 'zh';
  const dictionary = window.ReviewLensEnglish || {};
  function normalizeSlots(text, slots) {
    return text.replace(/__rl_slot_(\d+)__/g, (token, index) => {
      if (!slots.includes(index)) slots.push(index);
      return `__rl_slot_${slots.indexOf(index)}__`;
    });
  }
  const templates = new Map();
  for (const [key, value] of Object.entries(dictionary)) {
    const slots = [];
    const normalized = normalizeSlots(key, slots);
    templates.set(normalized, value.replace(/__rl_slot_(\d+)__/g,
      (_, index) => `__rl_slot_${slots.indexOf(index)}__`));
  }

  function phrase(value) {
    if (language !== 'en') return value;
    const key = value.trim();
    let translated = dictionary[key];
    if (!Object.prototype.hasOwnProperty.call(dictionary, key)) {
      const slots = [];
      const normalized = normalizeSlots(key, slots);
      if (!templates.has(normalized)) return value;
      translated = templates.get(normalized).replace(/__rl_slot_(\d+)__/g,
        (_, index) => `__rl_slot_${slots[Number(index)]}__`);
    }
    return value.slice(0, value.indexOf(key)) + translated + value.slice(value.indexOf(key) + key.length);
  }

  // This receives source-code strings, never a completed page or API response.
  function t(value) {
    if (language !== 'en') return value;
    return String(value).split(/(<[^>]*>)/g).map(part => part.startsWith('<')
      ? part.replace(/\b(placeholder|title|aria-label|alt|content)="([^"]*)"/g,
        (_, name, text) => `${name}="${phrase(text).replace(/"/g, '&quot;')}"`)
      : phrase(part)).join('');
  }

  function html(strings, ...values) {
    const source = strings.reduce((text, part, index) => text + part +
      (index < values.length ? `__rl_slot_${index}__` : ''), '');
    // Replace in a single pass, so even placeholder-like user text stays intact.
    return t(source).replace(/__rl_slot_(\d+)__/g, (_, index) => String(values[Number(index)]));
  }

  window.I18n = Object.freeze({language, locale: language === 'en' ? 'en-US' : 'zh-CN', t, html});
  document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
  document.title = t(document.title);
  // Only the initial, static shell exists here. Never translate live review DOM.
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (!['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(node.parentElement?.tagName)) node.nodeValue = phrase(node.nodeValue);
  }
  document.querySelectorAll('[placeholder], [title], [aria-label], [alt], meta[content]').forEach(element => {
    ['placeholder', 'title', 'aria-label', 'alt', 'content'].forEach(name => {
      if (element.hasAttribute(name)) element.setAttribute(name, phrase(element.getAttribute(name)));
    });
  });

  const selector = document.getElementById('ui-language');
  if (!selector) return;
  selector.value = language;
  const dirtyForms = new Set();
  function rememberInput(event) {
    const form = event.target.closest?.('#app form');
    if (form && !/filter|search/.test(form.id)) dirtyForms.add(form);
  }
  document.addEventListener('input', rememberInput);
  document.addEventListener('change', rememberInput);
  selector.addEventListener('change', () => {
    const next = selector.value;
    selector.value = language;
    if (!supported(next) || next === language) return;
    if (document.querySelector('#app [aria-busy="true"], #app [inert]')) {
      document.getElementById('language-feedback').textContent = t('请等待当前操作完成后再切换语言。');
      return;
    }
    function navigate() {
      try { localStorage.setItem(storageKey, next); } catch (_) { /* Persist via URL instead. */ }
      const target = new URL(window.location.href);
      target.searchParams.set('lang', next);
      window.location.assign(target.href);
    }
    if (![...dirtyForms].some(form => form.isConnected)) { navigate(); return; }
    const dialog = document.createElement('dialog');
    dialog.className = 'language-confirm';
    dialog.setAttribute('aria-labelledby', 'language-confirm-title');
    dialog.innerHTML = t('<p id="language-confirm-title">切换语言会刷新当前页面，尚未保存的填写内容会丢失。是否继续？</p>') +
      '<form method="dialog"><button class="btn" value="cancel" autofocus>' + t('保留当前页面') +
      '</button><button class="btn btn-primary" value="switch">' + t('切换语言') + '</button></form>';
    dialog.addEventListener('close', () => {
      dialog.remove();
      selector.focus();
      if (dialog.returnValue === 'switch') navigate();
    });
    document.body.appendChild(dialog);
    dialog.showModal();
  });
})();
