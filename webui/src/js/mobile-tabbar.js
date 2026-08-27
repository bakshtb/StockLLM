// Field's mobile bottom tab bar: a second, curated way to reach the same 9
// top-level panels the desktop sidebar-nav already renders (see
// _mobile_tabbar() in generate_dashboard.py for why 9 tabs became 5 groups).
// Every button here -- group icon or secondary chip -- is a click-proxy onto
// the real .subtab-btn elements subtabs.js already wires up, so panel-swap
// and chart-resize logic is never duplicated; this only tracks which group
// icon and which chip (for a multi-member group) currently look selected.
export function initMobileTabbar() {
  var bar = document.querySelector('.mobile-tabbar');
  var mainBar = document.querySelector('.subtabs.sidebar-nav[data-group="main"]');
  if (!bar || !mainBar) return;

  function realBtn(target) {
    return mainBar.querySelector('.subtab-btn[data-target="' + target + '"]');
  }

  bar.querySelectorAll('.mobile-tabbar-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      bar.querySelectorAll('.mobile-tabbar-btn').forEach(function (b) {
        b.classList.toggle('is-active', b === btn);
      });
      var groupId = btn.getAttribute('data-mobile-group');
      document.querySelectorAll('.mobile-tabbar-chips').forEach(function (row) {
        var isThisGroup = row.getAttribute('data-mobile-chips-for') === groupId;
        row.classList.toggle('is-active', isThisGroup);
        if (isThisGroup) {
          row.querySelectorAll('.mobile-tabbar-chip').forEach(function (c, i) {
            c.classList.toggle('is-active', i === 0);
          });
        }
      });
      var real = realBtn(btn.getAttribute('data-target'));
      if (real) real.click();
    });
  });

  document.querySelectorAll('.mobile-tabbar-chips').forEach(function (row) {
    row.querySelectorAll('.mobile-tabbar-chip').forEach(function (chip) {
      chip.addEventListener('click', function () {
        row.querySelectorAll('.mobile-tabbar-chip').forEach(function (c) {
          c.classList.toggle('is-active', c === chip);
        });
        var real = realBtn(chip.getAttribute('data-target'));
        if (real) real.click();
      });
    });
  });
}
