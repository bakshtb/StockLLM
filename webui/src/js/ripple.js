// Material ripple feedback on click/tap -- a dependency-free ~20-line
// helper, not a component library, since that's all this page's handful of
// buttons need. Deliberately skips .info-ic (its popover child needs
// `overflow: visible`, which a contained ripple can't share) and anything
// added to the page after this runs (there is no dynamic content here --
// every button already exists in the server-rendered HTML).
var RIPPLE_SELECTOR = 'button.chip, .range-btn, .viz-toggle, .chart-disclosure summary';

function spawnRipple(el, x, y) {
  var rect = el.getBoundingClientRect();
  var size = Math.max(rect.width, rect.height) * 1.6;
  var span = document.createElement('span');
  span.className = 'ripple-effect';
  span.style.width = span.style.height = size + 'px';
  span.style.left = (x - rect.left - size / 2) + 'px';
  span.style.top = (y - rect.top - size / 2) + 'px';
  el.appendChild(span);
  span.addEventListener('animationend', function () { span.remove(); });
}

export function initRipple() {
  document.querySelectorAll(RIPPLE_SELECTOR).forEach(function (el) {
    el.addEventListener('pointerdown', function (e) {
      spawnRipple(el, e.clientX, e.clientY);
    });
  });
}
