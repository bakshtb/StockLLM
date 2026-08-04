import { reapplyTheme } from './hydrate.js';

export function initThemeToggle() {
  var themeBtn = document.getElementById('theme-toggle');
  if (!themeBtn) return;
  themeBtn.addEventListener('click', function () {
    var root = document.documentElement;
    var current = root.getAttribute('data-theme') ||
      (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    var next = current === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    themeBtn.textContent = next === 'dark' ? 'Light mode' : 'Dark mode';
    try { localStorage.setItem('stockllm-theme', next); } catch (e) {}
    reapplyTheme();
  });
}
