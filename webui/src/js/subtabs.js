import { resizeWithin } from './hydrate.js';

// Segmented pill tabs (see subtabs() in generate_dashboard.py): every panel
// is already server-rendered, this only toggles which one is visible. Scoped
// per .subtabs bar rather than globally, since a page can have more than one
// independent tab group (Ownership, Dividends/Options/Macro/Sentiment).
export function initSubtabs() {
  document.querySelectorAll('.subtabs').forEach(function (bar) {
    var panels = bar.nextElementSibling ? bar.nextElementSibling.querySelectorAll('.subtab-panel') : [];
    bar.querySelectorAll('.subtab-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var target = btn.getAttribute('data-target');
        bar.querySelectorAll('.subtab-btn').forEach(function (b) {
          b.classList.toggle('is-active', b === btn);
        });
        panels.forEach(function (p) {
          var show = p.getAttribute('data-panel') === target;
          p.classList.toggle('is-active', show);
          // A panel that was display:none sizes any chart inside it to 0 --
          // same ResizeObserver insurance as viz-toggle.js's chart-disclosure
          // handling, for the same reason (WebView quirks in HA's own UI).
          if (show) resizeWithin(p);
        });
      });
    });
  });
}
