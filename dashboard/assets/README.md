# Assets

`icon.png` — the only file checked in here directly. Purely cosmetic (iOS
"Add to Home Screen" icon); a missing/deleted copy never breaks the
dashboard itself.

`dist/` — **not checked in.** Build output of `webui/` (a Vite project),
produced by `npm ci && npm run build` inside `webui/`, or automatically as
part of the Docker image's builder stage (see `../../Dockerfile`). Contains:

- `echarts.min.js` — Apache ECharts, vendored (see `webui/public/echarts.min.js`
  for the source of truth and its own licensing note), copied straight
  through by Vite's `publicDir` mechanism, not bundled.
- `assets/main-<hash>.js` / `assets/main-<hash>.css` — the dashboard's
  actual CSS/JS, source in `webui/src/`.
- `.vite/manifest.json` — read by `dashboard/generate_dashboard.py`'s
  `load_built_assets()` to find the current hashed filenames above.

`dashboard.assets.ensure_vendored_assets()` copies `dist/` and `icon.png`
next to every generated dashboard HTML file. If `dist/` doesn't exist yet
(webui/ was never built), dashboard generation fails loudly with
instructions rather than silently shipping an unstyled page.
