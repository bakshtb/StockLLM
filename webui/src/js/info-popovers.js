// Info-icon popovers: click/Enter to toggle, click outside or Escape to close,
// only one open at a time so they never stack up on a long page.
export function initInfoPopovers() {
  function closeAllInfo(except) {
    document.querySelectorAll('.info-ic.is-open').forEach(function (el) {
      if (el !== except) el.classList.remove('is-open');
    });
  }
  document.querySelectorAll('.info-ic').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var wasOpen = btn.classList.contains('is-open');
      closeAllInfo(btn);
      btn.classList.toggle('is-open', !wasOpen);
    });
  });
  document.addEventListener('click', function () { closeAllInfo(null); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAllInfo(null);
  });
}
