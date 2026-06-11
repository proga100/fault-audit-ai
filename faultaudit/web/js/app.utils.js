function reportItems() {
  return state.report?.items?.length ? state.report.items : state.flaggedItems;
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function hashText(text) {
  let hash = 0;
  for (let i = 0; i < text.length; i++) {
    hash = ((hash << 5) - hash) + text.charCodeAt(i);
    hash |= 0;
  }
  return hash;
}

function printReportStyles() {
  return `
    @page { size: letter; margin: 0.42in; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: #f4f7fb;
      color: #132033;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      font-size: 11px;
      line-height: 1.42;
    }
    .report-shell {
      max-width: 1040px;
      margin: 0 auto;
      background: #ffffff;
      min-height: 100vh;
      padding: 26px;
    }
    .brand-hero {
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 20px 22px;
      border-radius: 18px;
      color: #ffffff;
      background: linear-gradient(135deg, #174ea6 0%, #2563eb 58%, #0f766e 100%);
    }
    .brand-mark {
      display: grid;
      place-items: center;
      width: 54px;
      height: 54px;
      border: 1px solid rgba(255,255,255,.35);
      border-radius: 15px;
      background: rgba(255,255,255,.14);
      font-weight: 900;
      letter-spacing: .04em;
    }
    .eyebrow, .section-label {
      margin: 0;
      color: #50709f;
      font-size: 9px;
      font-weight: 800;
      letter-spacing: .11em;
      text-transform: uppercase;
    }
    .brand-hero .eyebrow { color: rgba(255,255,255,.76); }
    h1 {
      margin: 2px 0 3px;
      font-size: 25px;
      line-height: 1.08;
      letter-spacing: 0;
    }
    .subtitle {
      margin: 0;
      max-width: 760px;
      color: rgba(255,255,255,.84);
      font-size: 12px;
    }
    .meta-grid, .kpi-grid {
      display: grid;
      grid-template-columns: repeat(6, 1fr);
      gap: 9px;
      margin-top: 14px;
    }
    .meta-grid div, .kpi-card, .summary-panel {
      border: 1px solid #d9e2ef;
      border-radius: 12px;
      background: #f8fbff;
    }
    .meta-grid div {
      min-width: 0;
      padding: 9px 10px;
    }
    .meta-grid span, .kpi-card span {
      display: block;
      color: #64748b;
      font-size: 9px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: .08em;
    }
    .meta-grid strong {
      display: block;
      margin-top: 3px;
      overflow-wrap: anywhere;
      color: #1e293b;
      font-size: 10px;
    }
    .kpi-grid { grid-template-columns: repeat(4, 1fr); }
    .kpi-card {
      padding: 13px 14px;
      page-break-inside: avoid;
    }
    .kpi-card strong {
      display: block;
      margin-top: 6px;
      color: #0f172a;
      font-size: 22px;
      line-height: 1;
    }
    .kpi-card.risk {
      border-color: #f3c6a2;
      background: #fff7ed;
    }
    .kpi-card.risk strong { color: #b45309; }
    .summary-panel {
      display: grid;
      grid-template-columns: 1.45fr 1fr;
      gap: 20px;
      margin-top: 14px;
      padding: 15px 16px;
      page-break-inside: avoid;
    }
    .summary-panel p:last-child {
      margin: 5px 0 0;
      color: #334155;
    }
    .findings-section { margin-top: 18px; }
    .section-heading {
      display: flex;
      align-items: end;
      justify-content: space-between;
      margin-bottom: 9px;
    }
    .section-heading h2 {
      margin: 2px 0 0;
      font-size: 18px;
      letter-spacing: 0;
    }
    .section-heading > p {
      margin: 0;
      color: #64748b;
      font-weight: 700;
    }
    table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      border: 1px solid #d8e1ee;
      border-radius: 12px;
      overflow: hidden;
    }
    thead { display: table-header-group; }
    tr { page-break-inside: avoid; }
    th {
      background: #edf4ff;
      color: #274060;
      border-bottom: 1px solid #d8e1ee;
      padding: 8px 7px;
      text-align: left;
      font-size: 9px;
      text-transform: uppercase;
      letter-spacing: .07em;
    }
    td {
      border-bottom: 1px solid #e6edf6;
      padding: 8px 7px;
      vertical-align: top;
      overflow-wrap: anywhere;
    }
    tbody tr:nth-child(even) { background: #fbfdff; }
    tbody tr:last-child td { border-bottom: 0; }
    .row-num {
      width: 28px;
      color: #64748b;
      font-weight: 800;
      text-align: right;
    }
    .mono {
      color: #334155;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 9px;
    }
    .amount {
      color: #92400e;
      font-weight: 800;
      white-space: nowrap;
    }
    .reasons { min-width: 112px; }
    .reason-pill {
      display: inline-block;
      margin: 0 3px 3px 0;
      padding: 2px 6px;
      border: 1px solid #bfdbfe;
      border-radius: 999px;
      background: #eff6ff;
      color: #1d4ed8;
      font-size: 9px;
      font-weight: 800;
      text-transform: capitalize;
      white-space: nowrap;
    }
    .muted, .empty { color: #64748b; }
    footer {
      display: flex;
      justify-content: space-between;
      gap: 18px;
      margin-top: 18px;
      padding-top: 10px;
      border-top: 1px solid #d8e1ee;
      color: #64748b;
      font-size: 10px;
    }
    footer strong { color: #174ea6; }
    @media print {
      body { background: #ffffff; }
      .report-shell {
        max-width: none;
        padding: 0;
      }
      .brand-hero, .meta-grid div, .kpi-card, .summary-panel, table {
        print-color-adjust: exact;
        -webkit-print-color-adjust: exact;
      }
    }
  `;
}

function escHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function escAttr(s) {
  return escHtml(s).replace(/'/g,'&#39;');
}

function toolChipClass(label) {
  const s = String(label || '').toLowerCase();
  if (s.includes('mongodb mcp')) return 'mongo';
  if (s.includes('gemini') || s.includes('vertex')) return 'gemini';
  if (s.includes('human')) return 'human';
  return 'detector';
}

function statusLabel(status) {
  return {
    pending: 'Pending Human Approval',
    approved: 'Approved by Auditor',
    rejected: 'Rejected',
  }[status] || status;
}

function fmtCurrency(n) {
  if (n == null) return '$—';
  return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function fmtTs(ts) {
  if (!ts) return '—';
  try { return new Date(ts).toLocaleString('en-US', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' }); } catch { return ts; }
}

function tsNow() {
  const now = new Date();
  return now.toLocaleTimeString('en-US', { hour12: false, hour:'2-digit', minute:'2-digit', second:'2-digit' });
}

function setStatusBadge(type, text) {
  const badge = document.getElementById('run-status-badge');
  badge.classList.remove('hidden');
  badge.classList.add('flex');
  const dot = document.getElementById('status-dot');
  const label = document.getElementById('status-text');
  label.textContent = text;
  const colors = {
    planning: 'bg-blue-400',
    executing: 'bg-purple-400',
    awaiting: 'bg-yellow-400 animate-pulse',
    done: 'bg-green-400',
    error: 'bg-red-400',
  };
  dot.className = `w-1.5 h-1.5 rounded-full ${colors[type] || 'bg-gray-400'}`;
}

function setKpiBaselineMode() {
  setText('kpi-spend-label', 'Total Spend');
  setText('kpi-spend-note', 'Baseline scope — run an audit to surface risk');
  setText('kpi-flags-label', 'Invoices in Scope');
  setText('kpi-flags-note', 'Baseline invoice count before findings');
  setText('kpi-vendors-label', 'Vendors in Scope');
  setText('kpi-vendors-note', 'Baseline vendor population');
  setKpiColor('kpi-at-risk', 'text-gray-200');
  setKpiColor('kpi-flags', 'text-gray-200');
  setKpiColor('kpi-vendors', 'text-brand-300');
}

function setKpiAuditMode() {
  setText('kpi-spend-label', 'At Risk');
  setText('kpi-spend-note', 'Human-reviewed suspicious value');
  setText('kpi-flags-label', 'Flags');
  setText('kpi-flags-note', 'Suspicious invoices proposed by agents');
  setText('kpi-vendors-label', 'Vendors Checked');
  setText('kpi-vendors-note', 'Vendor population scanned for this run');
  setKpiColor('kpi-at-risk', 'text-accent-red');
  setKpiColor('kpi-flags', 'text-accent-orange');
  setKpiColor('kpi-vendors', 'text-brand-300');
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setKpiColor(id, colorClass) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('text-gray-200', 'text-accent-red', 'text-accent-orange', 'text-brand-300');
  el.classList.add(colorClass);
}

function animateKPI(id, target) {
  const el = document.getElementById(id);
  const cur = parseInt(el.textContent.replace(/[^0-9]/g,'')) || 0;
  const step = Math.ceil((target - cur) / 12);
  if (step <= 0) { el.textContent = target; return; }
  let val = cur;
  const t = setInterval(() => {
    val = Math.min(val + step, target);
    el.textContent = val;
    el.classList.add('kpi-update');
    setTimeout(() => el.classList.remove('kpi-update'), 250);
    if (val >= target) clearInterval(t);
  }, 40);
}

function animateKPICurrency(id, target) {
  const el = document.getElementById(id);
  const cur = parseInt(el.textContent.replace(/[^0-9]/g,'')) || 0;
  const steps = 20;
  const step = (target - cur) / steps;
  if (step <= 0) { el.textContent = fmtCurrency(target); return; }
  let val = cur;
  let i = 0;
  const t = setInterval(() => {
    i++;
    val = i >= steps ? target : cur + step * i;
    el.textContent = fmtCurrency(val);
    if (i >= steps) clearInterval(t);
  }, 35);
}

function scrollTimeline() {
  const pane = document.getElementById('timeline-scroll');
  if (!pane) return;
  pane.scrollTo({ top: pane.scrollHeight, behavior: 'smooth' });
}

function focusTimelineElement(el, opts = {}) {
  if (!el) return;
  const pane = document.getElementById('timeline-scroll');
  if (!pane) return;
  const distanceFromBottom = pane.scrollHeight - pane.scrollTop - pane.clientHeight;
  const nearBottom = distanceFromBottom < 180;
  if (opts.force || nearBottom) {
    el.scrollIntoView({ behavior: 'smooth', block: opts.block || 'end', inline: 'nearest' });
  }
  if (opts.attention) {
    el.classList.remove('timeline-attention');
    void el.offsetWidth;
    el.classList.add('timeline-attention');
  }
}

function focusTimelineGate(gateEl) {
  if (!gateEl) return;
  focusTimelineElement(gateEl, { force: true, attention: true, block: 'end' });
  const primary = gateEl.querySelector('[data-timeline-primary]');
  if (!primary) return;
  const focusPrimary = () => {
    focusTimelineElement(primary, { force: true, block: 'end' });
    primary.classList.remove('timeline-button-attention');
    void primary.offsetWidth;
    primary.classList.add('timeline-button-attention');
  };
  requestAnimationFrame(focusPrimary);
  setTimeout(focusPrimary, 220);
}

function resetUI() {
  // Reset state
  state.runId = null;
  state.stepCount = 0;
  state.flaggedItems = [];
  state.atRisk = 0;
  state.rowDecisions = {};
  state.itemStatuses = {};
  state.invoiceExplanations = {};
  state.invoiceExplainLoading = {};
  state.reportGenerating = false;
  state.report = null;
  state.deptCounts = {};
  state.vendorFlags = {};
  state.approvalLog = [];
  state.selectedFindingId = null;
  state.selectedGateInvoiceId = null;
  state._lastPlan = '';
  state.pendingTimelineCards = {};
  state.activeToolCards = {};
  if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }

  // Reset timeline
  document.getElementById('timeline').innerHTML = `
    <div id="timeline-empty" class="py-12 text-center">
      <div class="w-12 h-12 mx-auto mb-3 rounded-full bg-surface-700 flex items-center justify-center">
        <svg class="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/></svg>
      </div>
      <p class="text-sm text-gray-600">No audit running</p>
      <p class="text-xs text-gray-700 mt-1">Launch a mission to see live steps</p>
    </div>
  `;

  // Reset gates
  document.getElementById('gate-plan').classList.add('hidden');
  document.getElementById('gate-action').classList.add('hidden');
  document.getElementById('plan-edit-area').classList.remove('hidden');
  document.getElementById('mission-invoice-review')?.classList.add('hidden');
  document.getElementById('mission-dashboard-header')?.classList.remove('hidden');
  document.getElementById('mission-dashboard-content')?.classList.remove('hidden');

  // Reset KPIs
  setKpiBaselineMode();
  document.getElementById('kpi-at-risk').textContent = '$0';
  document.getElementById('kpi-flags').textContent = '0';
  document.getElementById('kpi-vendors').textContent = '—';
  document.getElementById('dept-chart').innerHTML = '<p class="text-xs text-gray-600 italic">Waiting for data…</p>';
  document.getElementById('vendor-chart').innerHTML = '<p class="text-xs text-gray-600 italic">Waiting for data…</p>';
  document.getElementById('report-content').innerHTML = `
    <div class="py-8 text-center">
      <div class="w-10 h-10 mx-auto mb-2 rounded-full bg-surface-700 flex items-center justify-center">
        <svg class="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
      </div>
      <p class="text-sm text-gray-600">Report will appear here when the audit completes</p>
    </div>
  `;
  document.getElementById('download-btn').classList.add('hidden');
  document.getElementById('download-btn').classList.remove('flex');
  document.getElementById('download-pdf-btn')?.classList.add('hidden');
  document.getElementById('download-pdf-btn')?.classList.remove('flex');
  document.getElementById('download-excel-btn')?.classList.add('hidden');
  document.getElementById('download-excel-btn')?.classList.remove('flex');
  document.getElementById('run-id-display').classList.add('hidden');
  document.getElementById('run-status-badge').classList.add('hidden');
  document.getElementById('run-status-badge').classList.remove('flex');
  renderFindingsView();
  renderReportsView();
  renderApprovalLog();
  seedBaselineKpis();

  // Reset launch btn
  const btn = document.getElementById('launch-btn');
  btn.disabled = false;
  btn.innerHTML = `
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
    Run Audit Mission
  `;
}

// Very simple Markdown renderer (no dependencies)
function renderMarkdown(md) {
  if (!md) return '<p class="text-gray-600 italic">No report content</p>';
  let html = escHtml(md);
  // headings
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  // bold / italic
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong class="text-gray-200">$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  // code blocks
  html = html.replace(/```[\w]*\n([\s\S]*?)```/g, '<pre>$1</pre>');
  // inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // hr
  html = html.replace(/^---+$/gm, '<hr/>');
  // list items
  html = html.replace(/^\- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, s => `<ul>${s}</ul>`);
  // paragraphs
  html = html.replace(/\n\n+/g, '</p><p class="text-gray-400 text-xs">');
  return `<p class="text-gray-400 text-xs">${html}</p>`;
}
