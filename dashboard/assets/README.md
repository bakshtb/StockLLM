# Vendored assets

`echarts.min.js` — Apache ECharts 5.6.1, full build, downloaded from
`https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js`. Apache-2.0 licensed (see
the file's own header comment — do not strip it). Vendored rather than loaded from a
CDN so the dashboard works with no external network access at runtime (this add-on
runs inside a Home Assistant container that may have no internet egress). To upgrade,
just re-download the same URL and replace the file; nothing else in this repo depends
on a specific ECharts version.

`dashboard.js` — hand-written, no build step. The runtime that reads
`window.__CHARTS__` (emitted by `dashboard/generate_dashboard.py`) and renders it via
ECharts. See its own comments for the theme/resize/fallback design.
