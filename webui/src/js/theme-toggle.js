import { reapplyTheme } from './hydrate.js';

function resolveTheme() {
  var root = document.documentElement;
  return root.getAttribute('data-theme') ||
    (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
}

// The company logo (see section_header() in generate_dashboard.py) is a
// single <img> carrying both theme URLs as data-light/data-dark -- this
// only ever picks between them, matching the same "re-run on toggle"
// shape hydrate.js's reapplyTheme() already uses for charts. Run once at
// load too (not just on toggle), since the very first render always
// starts on the light URL (the <img>'s plain src attribute) regardless
// of what resolveTheme() actually resolves to on a dark-themed first visit.
function applyLogoForTheme() {
  var img = document.getElementById('company-logo-img');
  if (!img) return;
  var src = resolveTheme() === 'dark' ? img.dataset.dark : img.dataset.light;
  if (src && img.src !== src) img.src = src;
}

export function initThemeToggle() {
  applyLogoForTheme();
  var themeBtn = document.getElementById('theme-toggle');
  if (!themeBtn) return;
  themeBtn.addEventListener('click', function () {
    var root = document.documentElement;
    var next = resolveTheme() === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    themeBtn.textContent = next === 'dark' ? 'Light mode' : 'Dark mode';
    try { localStorage.setItem('stockllm-theme', next); } catch (e) {}
    reapplyTheme();
    applyLogoForTheme();
  });
}
