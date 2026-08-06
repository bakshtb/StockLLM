import { resizeWithin } from './hydrate.js';

// Segmented pill tabs (see subtabs() in generate_dashboard.py): every panel
// is already server-rendered, this only toggles which one is visible. Scoped
// per .subtabs bar rather than globally, since a page can have more than one
// independent tab group (Ownership, Dividends/Options/Macro/Sentiment, and
// the top-level page tabs wrapping all of those). Linked to its panels by
// data-group/data-panels-for, not DOM adjacency -- the top-level bar lives
// in .sticky-top (so it sticks to the topbar) while its panels live in
// .wrap, several elements later, not as a sibling.
export function initSubtabs() {
  document.querySelectorAll('.subtabs').forEach(function (bar) {
    var panelsWrap = document.querySelector('[data-panels-for="' + bar.getAttribute('data-group') + '"]');
    // :scope > .subtab-panel, not a plain descendant selector -- a panel
    // can itself contain a *nested* subtabs group (e.g. the top-level
    // "main" group's Ownership panel contains its own "ownership" group,
    // Institutional/Insiders). A plain querySelectorAll('.subtab-panel')
    // matches those nested panels too, so switching an outer tab would
    // strip is-active from every inner panel on the whole page (none of
    // their data-panel values match the outer target) -- including the
    // one that should stay active in whatever tab was just switched to.
    // Real bug, not theoretical: clicking "Ownership" showed an empty
    // panel until manually re-clicking "Institutional", which only
    // "worked" because *that* click was correctly scoped to just the
    // inner group's own two panels.
    var panels = panelsWrap ? panelsWrap.querySelectorAll(':scope > .subtab-panel') : [];
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
