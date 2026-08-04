// "Download for AI Chat": decodes the base64 Markdown export embedded
// in #llm-export-data (see build_dashboard()'s comment on why base64,
// not raw/escaped text) and triggers a real file download via a
// Blob + temporary <a download>, entirely client-side -- no server
// round-trip, works the same whether this page came from the CLI or
// the webapp.
export function initLlmExport() {
  var exportBtn = document.getElementById('llm-export-btn');
  if (!exportBtn) return;
  exportBtn.addEventListener('click', function () {
    var dataEl = document.getElementById('llm-export-data');
    if (!dataEl) return;
    var bytes = Uint8Array.from(atob(dataEl.textContent), function (c) { return c.charCodeAt(0); });
    var text = new TextDecoder('utf-8').decode(bytes);
    var blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = (exportBtn.getAttribute('data-ticker') || 'stockllm') + '-research-export.md';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });
}
