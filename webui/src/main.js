import './styles/tokens.css';
import './styles/base.css';
import './styles/components.css';
import './styles/responsive.css';
import './styles/skeleton.css';

// hydrate.js runs its own chart init immediately (self-invoking, same as
// before this file existed) -- imported for its side effect, not its
// exports, here.
import './js/hydrate.js';
import { initVizToggle } from './js/viz-toggle.js';
import { initChartToolbar } from './js/chart-toolbar.js';
import { initLlmExport } from './js/llm-export.js';
import { initThemeToggle } from './js/theme-toggle.js';
import { initInfoPopovers } from './js/info-popovers.js';
import { initSubtabs } from './js/subtabs.js';

function initAll() {
  initVizToggle();
  initChartToolbar();
  initLlmExport();
  initThemeToggle();
  initInfoPopovers();
  initSubtabs();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAll);
} else {
  initAll();
}
