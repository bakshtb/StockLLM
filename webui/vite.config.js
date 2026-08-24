import { defineConfig } from "vite";

// Builds into dashboard/assets/dist/ -- generate_dashboard.py reads
// dist/.vite/manifest.json to link the hashed output files, so this must
// stay in sync with build_dashboard()'s ASSET_DIST_DIR constant.
//
// echarts.min.js lives in public/ and is copied through untouched (not
// bundled): it's already-minified third-party code vendored deliberately
// (see dashboard/assets/README.md), and running it through Rollup would buy
// nothing but risk.
export default defineConfig({
  // Relative, not the default "/": generate_dashboard.py links the built
  // CSS/JS with a relative "assets/dist/..." path so the generated HTML
  // works from any directory it's copied to (it's meant to be portable,
  // offline-capable output, not served from a fixed domain root) -- an
  // absolute base would emit "/assets/xxx.woff2" font url()s inside the
  // built CSS that 404 the moment the page isn't served from "/".
  base: "./",
  publicDir: "public",
  build: {
    outDir: "../dashboard/assets/dist",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: "src/main.js",
    },
  },
});
