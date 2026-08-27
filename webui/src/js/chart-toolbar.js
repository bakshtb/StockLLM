// Price chart range-preset buttons (1M/3M/6M/1Y/2Y/All): each button's
// data-days becomes a percentage of the chart's own total data length
// (not a fixed date -- the chart's total history varies by ticker, e.g.
// a recent IPO has less than 6 years) and is applied as a dataZoom
// action directly via the real echarts instance, found the same way the
// standalone verification harness confirmed works (see
// price_history_chart()'s docstring in generate_dashboard.py).
export function initChartToolbar() {
  document.querySelectorAll('.chart-toolbar').forEach(function (toolbar) {
    var chartEl = toolbar.parentElement && toolbar.parentElement.querySelector('.echarts-container');
    if (!chartEl || !window.echarts) return;
    var buttons = toolbar.querySelectorAll('.range-btn');
    // Precomputed server-side (data-pct/data-pct-cls, data-footer-* on each
    // button, see section_price_chart()) -- this just swaps which one is
    // displayed, no client-side recomputation from chart data.
    var pctLabel = toolbar.querySelector('.chart-range-pct');
    var footer = toolbar.parentElement && toolbar.parentElement.querySelector('.hero-chart-footer');
    var footerDate = footer && footer.querySelector('.footer-date');
    var footerHigh = footer && footer.querySelector('.footer-high');
    var footerLow = footer && footer.querySelector('.footer-low');
    var footerPct = footer && footer.querySelector('.footer-pct');
    buttons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var inst = echarts.getInstanceByDom(chartEl);
        if (!inst) return;
        var total = inst.getOption().series[0].data.length;
        var days = parseInt(btn.getAttribute('data-days'), 10);
        var startPct = days === 0 ? 0 : Math.max(0, (1 - days / total) * 100);
        inst.dispatchAction({ type: 'dataZoom', start: startPct, end: 100 });
        buttons.forEach(function (b) { b.classList.toggle('is-active', b === btn); });
        if (pctLabel) {
          pctLabel.textContent = btn.getAttribute('data-pct');
          pctLabel.className = 'chart-range-pct ' + btn.getAttribute('data-pct-cls');
        }
        // A button with no usable window (see _range_footer_data()) omits
        // the data-footer-* attributes entirely -- leave the footer as-is
        // rather than blanking it out to "null"/"undefined".
        if (footerDate && btn.hasAttribute('data-footer-date')) {
          footerDate.textContent = btn.getAttribute('data-footer-date');
          footerHigh.textContent = 'High ' + btn.getAttribute('data-footer-high');
          footerLow.textContent = 'Low ' + btn.getAttribute('data-footer-low');
          footerPct.textContent = btn.getAttribute('data-footer-pct');
          footerPct.className = 'footer-pct delta ' + btn.getAttribute('data-footer-pct-cls');
        }
      });
    });
  });
}
