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
