// Dense tables (data_table() in generate_dashboard.py, e.g. Analyst's
// "Recent rating actions") can render wider than their .table-scroll
// container -- intentional, that's what the container's overflow-x:auto
// is for (see data_table()'s own docstring) -- but nothing signalled that
// there was more to see, so the extra columns just read as cut off.
// Toggles .is-scrollable/.is-scrolled-to-end (see components.css) from a
// real overflow measurement, not a guess, and keeps it correct across a
// resize or late-loading content that changes column widths.
export function initTableScrollHints() {
  var scrolls = document.querySelectorAll('.table-scroll');
  if (!scrolls.length) return;

  function checkOverflow(el) {
    el.classList.toggle('is-scrollable', el.scrollWidth > el.clientWidth + 1);
  }
  function checkEnd(el) {
    el.classList.toggle('is-scrolled-to-end', el.scrollLeft + el.clientWidth >= el.scrollWidth - 1);
  }

  scrolls.forEach(function (el) {
    checkOverflow(el);
    checkEnd(el);
    el.addEventListener('scroll', function () { checkEnd(el); });
  });
  window.addEventListener('resize', function () {
    scrolls.forEach(checkOverflow);
  });

  // A table inside a not-yet-active .subtab-panel measures 0x0 while
  // display:none, so it always reads as "not scrollable" at page load if
  // it isn't on the first tab -- re-check once a tab switch (desktop
  // sidebar-nav, its inner nested groups, or a mobile-tabbar click, which
  // itself just proxies a click onto the same real button) has actually
  // made it visible. Delegated on document, not a per-button listener, so
  // this doesn't care which of those three triggered it.
  document.addEventListener('click', function (e) {
    if (!e.target.closest('.subtab-btn')) return;
    // Both, not just checkOverflow -- while hidden, scrollWidth/clientWidth
    // are both 0, and 0 >= 0-1 is true, so checkEnd's initial pass above
    // already (wrongly) marked a not-yet-visible table "scrolled to end";
    // that never gets corrected once real dimensions exist unless this
    // re-runs it too.
    requestAnimationFrame(function () {
      scrolls.forEach(function (el) { checkOverflow(el); checkEnd(el); });
    });
  });
}
