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
    buttons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var inst = echarts.getInstanceByDom(chartEl);
        if (!inst) return;
        var total = inst.getOption().series[0].data.length;
        var days = parseInt(btn.getAttribute('data-days'), 10);
        var startPct = days === 0 ? 0 : Math.max(0, (1 - days / total) * 100);
        inst.dispatchAction({ type: 'dataZoom', start: startPct, end: 100 });
        buttons.forEach(function (b) { b.classList.toggle('is-active', b === btn); });
      });
    });
  });
}
