import { resizeWithin } from './hydrate.js';

export function initVizToggle() {
  document.querySelectorAll('.viz-toggle').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var card = btn.closest('.viz-card');
      var nowTable = card.classList.toggle('is-table-view');
      btn.textContent = nowTable ? 'View chart' : 'View as table';
      btn.setAttribute('aria-pressed', String(nowTable));
      // A chart that was display:none (table view) sizes to 0 -- the
      // ResizeObserver in hydrate.js already catches this, but call
      // explicitly too as cheap insurance against ResizeObserver quirks in
      // some embedded WebViews (this runs inside Home Assistant's own UI).
      if (!nowTable) resizeWithin(card);
    });
  });

  // <details class="chart-disclosure"> starts collapsed (chart div at
  // 0x0) -- the ResizeObserver in hydrate.js already catches most size
  // changes, but explicitly resizing on the native `toggle` event too is
  // the same cheap insurance as the .viz-toggle handler above, for the
  // same reason (WebView ResizeObserver quirks inside Home Assistant's UI).
  document.querySelectorAll('.chart-disclosure').forEach(function (details) {
    details.addEventListener('toggle', function () {
      if (details.open) resizeWithin(details);
    });
  });
}
