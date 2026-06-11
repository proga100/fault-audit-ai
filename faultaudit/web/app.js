/* FaultAuditAI — Frontend application
 * Talks to: POST /api/mission, GET /api/events/:run_id (SSE), POST /api/approve/:run_id, GET /api/report/:run_id
 */

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────
const state = {
  runId: null,
  eventSource: null,
  stepCount: 0,
  flaggedItems: [],      // current FlaggedItem[]
  atRisk: 0,
  rowDecisions: {},      // invoice_id -> 'approve' | 'reject'
  itemStatuses: {},      // invoice_id -> pending | approved | rejected
  report: null,
  deptCounts: {},
  vendorFlags: {},
  approvalLog: [],
  appStatus: null,
  baselineStats: null,
  currentTab: 'mission',
  selectedFindingId: null,
};

// ─────────────────────────────────────────────────────────────────────────────
// Boot / shell
// ─────────────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadStatus();
  loadStats();
  renderFindingsView();
  renderApprovalLog();
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeAskDrawer();
  });
});

function switchTab(tab) {
  state.currentTab = tab;
  document.querySelectorAll('.app-view').forEach(v => v.classList.add('hidden'));
  document.getElementById(`${tab}-view`)?.classList.remove('hidden');
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`tab-${tab}`)?.classList.add('active');
  if (tab === 'findings') renderFindingsView();
  if (tab === 'reports') renderReportsView();
}

async function loadStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) return;
    state.appStatus = await res.json();
    renderIntegrationStrip();
  } catch {}
}

async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) return;
    state.baselineStats = await res.json();
    seedBaselineKpis();
  } catch {}
}

function renderIntegrationStrip() {
  const el = document.getElementById('integration-strip');
  if (!el || !state.appStatus) return;
  const s = state.appStatus;
  const runtime = s.agent_runtime_label || s.agent_runtime || 'runtime';
  el.classList.remove('hidden');
  el.innerHTML = `
    <span class="status-chip">${escHtml(runtime)}</span>
    <span class="tool-chip gemini">${escHtml(s.gemini_model || 'Gemini 3.x')}</span>
    <span class="tool-chip mongo">${s.mcp_enabled ? 'MongoDB MCP' : 'MongoDB MCP ready'}</span>
    <span class="tool-chip human">Human Approval</span>
    <span class="status-chip">${String(s.mode || 'demo').toUpperCase()}</span>
  `;
}

function seedBaselineKpis() {
  if (!state.baselineStats || state.runId) return;
  document.getElementById('kpi-at-risk').textContent = fmtCurrency(state.baselineStats.total_spend || 0);
  document.getElementById('kpi-flags').textContent = state.baselineStats.invoices ?? 0;
  document.getElementById('kpi-vendors').textContent = state.baselineStats.vendors ?? '—';
}

// ─────────────────────────────────────────────────────────────────────────────
// Template buttons
// ─────────────────────────────────────────────────────────────────────────────
function setTemplate(btn) {
  document.getElementById('mission-input').value = btn.dataset.text;
  document.querySelectorAll('.template-btn').forEach(b => b.classList.remove('border-brand-400','text-brand-300'));
  btn.classList.add('border-brand-400','text-brand-300');
}

// ─────────────────────────────────────────────────────────────────────────────
// Launch mission
// ─────────────────────────────────────────────────────────────────────────────
async function launchMission() {
  const text = document.getElementById('mission-input').value.trim();
  if (!text) { flashInput(); return; }

  resetUI();

  const btn = document.getElementById('launch-btn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div><span>Starting…</span>';

  try {
    const res = await fetch('/api/mission', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const { run_id } = await res.json();
    state.runId = run_id;

    document.getElementById('run-id-val').textContent = run_id.slice(0, 8);
    document.getElementById('run-id-display').classList.remove('hidden');
    document.getElementById('timeline-empty').classList.add('hidden');
    setStatusBadge('planning', 'Planning…');
    startSSE(run_id);
  } catch (err) {
    appendTimelineCard('error', { message: err.message });
    btn.disabled = false;
    btn.innerHTML = '<span>Run Audit Mission</span>';
  }
}

function flashInput() {
  const el = document.getElementById('mission-input');
  el.classList.add('ring-1','ring-accent-red','border-accent-red');
  setTimeout(() => el.classList.remove('ring-1','ring-accent-red','border-accent-red'), 1200);
}

// ─────────────────────────────────────────────────────────────────────────────
// SSE
// ─────────────────────────────────────────────────────────────────────────────
function startSSE(runId) {
  if (state.eventSource) state.eventSource.close();
  const es = new EventSource(`/api/events/${runId}`);
  state.eventSource = es;

  // Generic message handler — server may send named events or plain 'message'
  es.onmessage = (e) => handleRawEvent(e.data);

  // Named event handlers (server can send `event: plan` etc.)
  const eventTypes = ['plan','tool_call','tool_result','proposal','awaiting_approval','written','report_ready','error','done'];
  eventTypes.forEach(type => {
    es.addEventListener(type, (e) => handleRawEvent(e.data, type));
  });

  es.onerror = () => {
    setStatusBadge('error', 'Disconnected');
  };
}

function handleRawEvent(dataStr, forcedType) {
  let evt;
  try { evt = JSON.parse(dataStr); } catch { return; }
  const type = forcedType || evt.type;
  dispatchEvent(type, evt);
}

function dispatchEvent(type, evt) {
  switch (type) {
    case 'plan':              handlePlan(evt); break;
    case 'tool_call':         handleToolCall(evt); break;
    case 'tool_result':       handleToolResult(evt); break;
    case 'proposal':          handleProposal(evt); break;
    case 'awaiting_approval': handleAwaitingApproval(evt); break;
    case 'written':           handleWritten(evt); break;
    case 'report_ready':      handleReportReady(evt); break;
    case 'error':             handleError(evt); break;
    case 'done':              handleDone(evt); break;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Event handlers
// ─────────────────────────────────────────────────────────────────────────────
function handlePlan(evt) {
  setStatusBadge('planning', 'Plan received');
  const plan = evt.data?.plan || evt.data?.text || JSON.stringify(evt.data);
  appendTimelineCard('plan', { plan });
}

function handleToolCall(evt) {
  setStatusBadge('executing', 'Executing…');
  appendTimelineCard('tool_call', evt.data);
}

function handleToolResult(evt) {
  appendTimelineCard('tool_result', evt.data);

  // Update KPI: vendors checked
  if (evt.data?.count != null) {
    animateKPI('kpi-vendors', evt.data.count);
  }
  if (evt.data?.vendor_count != null) {
    animateKPI('kpi-vendors', evt.data.vendor_count);
  }
}

function handleProposal(evt) {
  const items = evt.data?.items || [];
  state.flaggedItems = items;

  // Dashboard reflects ALL flagged (server aggregates); table shows the top N for review.
  const total = evt.data?.total_flagged ?? items.length;
  state.atRisk = evt.data?.total_at_risk ?? items.reduce((s, i) => s + (i.amount || 0), 0);
  state.deptCounts = evt.data?.dept_counts || {};
  state.vendorFlags = evt.data?.vendor_counts || {};
  items.forEach(item => {
    state.rowDecisions[item.invoice_id] = 'approve';
    state.itemStatuses[item.invoice_id] = 'pending';
    item._agent = evt.data?.agent || evt.data?.adk_agent_name || 'Risk Triage Agent';
    item._tool_label = evt.data?.tool_label || 'Internal detector fallback';
  });

  animateKPICurrency('kpi-at-risk', state.atRisk);
  animateKPI('kpi-flags', total);
  renderDeptChart();
  renderVendorChart();

  const caption = document.getElementById('flagged-caption');
  if (caption) {
    caption.textContent = total > items.length
      ? `Top ${items.length} of ${total} flagged — review & approve:`
      : `${items.length} flagged items — review & approve:`;
  }

  appendTimelineCard('proposal', evt.data);
  renderFindingsView();
}

function handleAwaitingApproval(evt) {
  const gate = evt.data?.gate;
  setStatusBadge('awaiting', `Awaiting ${gate} approval`);

  if (gate === 'plan') {
    const plan = evt.data?.plan || state._lastPlan || '';
    document.getElementById('plan-edit-input').value = plan;
    document.getElementById('plan-edit-area').classList.remove('hidden');
    document.getElementById('gate-plan').classList.remove('hidden');
    scrollTimeline();
  } else if (gate === 'action') {
    renderFlaggedTable();
    document.getElementById('gate-action').classList.remove('hidden');
    scrollTimeline();
  }
  appendTimelineCard('awaiting_approval', evt.data);
}

function handleWritten(evt) {
  setStatusBadge('executing', 'Writing…');
  document.getElementById('gate-action').classList.add('hidden');
  state.flaggedItems.forEach(item => {
    state.itemStatuses[item.invoice_id] = state.rowDecisions[item.invoice_id] === 'approve'
      ? 'approved'
      : 'rejected';
  });
  renderFindingsView();
  appendTimelineCard('written', evt.data);
}

async function handleReportReady(evt) {
  setStatusBadge('done', 'Report ready');
  appendTimelineCard('report_ready', evt.data);
  // Fetch the actual report
  try {
    const res = await fetch(`/api/report/${state.runId}`);
    if (res.ok) {
      state.report = await res.json();
      renderReport(state.report);
      renderReportsView();
    }
  } catch {}
}

function handleError(evt) {
  setStatusBadge('error', 'Error');
  appendTimelineCard('error', evt.data);
  const btn = document.getElementById('launch-btn');
  btn.disabled = false;
  btn.innerHTML = 'Run Audit Mission';
}

function handleDone(evt) {
  setStatusBadge('done', 'Done');
  appendTimelineCard('done', evt.data);
  if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
  const btn = document.getElementById('launch-btn');
  btn.disabled = false;
  btn.innerHTML = 'Run Audit Mission';
}

// ─────────────────────────────────────────────────────────────────────────────
// Timeline card renderer
// ─────────────────────────────────────────────────────────────────────────────
const TYPE_META = {
  plan:              { icon: '📋', label: 'Plan',          badge: 'bg-blue-900/40 text-blue-300 border-blue-700/40' },
  tool_call:         { icon: '⚙️', label: 'Tool Call',     badge: 'bg-purple-900/40 text-purple-300 border-purple-700/40' },
  tool_result:       { icon: '📊', label: 'Tool Result',   badge: 'bg-cyan-900/40 text-cyan-300 border-cyan-700/40' },
  proposal:          { icon: '🚩', label: 'Proposal',      badge: 'bg-orange-900/40 text-orange-300 border-orange-700/40' },
  awaiting_approval: { icon: '⏸', label: 'Awaiting',      badge: 'bg-yellow-900/40 text-yellow-300 border-yellow-700/40' },
  written:           { icon: '✅', label: 'Written',        badge: 'bg-green-900/40 text-green-300 border-green-700/40' },
  report_ready:      { icon: '📄', label: 'Report Ready',  badge: 'bg-green-900/40 text-green-300 border-green-700/40' },
  error:             { icon: '❌', label: 'Error',          badge: 'bg-red-900/40 text-red-300 border-red-700/40' },
  done:              { icon: '🏁', label: 'Done',           badge: 'bg-green-900/40 text-green-300 border-green-700/40' },
};

function appendTimelineCard(type, data) {
  state.stepCount++;
  const meta = TYPE_META[type] || { icon:'•', label: type, badge: 'bg-surface-700 text-gray-400 border-surface-500' };

  const card = document.createElement('div');
  card.className = `timeline-card type-${type} fade-in rounded-lg bg-surface-800 border border-surface-600 p-3 pl-4`;

  let bodyHtml = '';

  if (type === 'plan') {
    const planText = data?.plan || data?.text || '';
    state._lastPlan = planText;
    bodyHtml = planText
      ? `<p class="text-xs text-gray-500 mt-1">Plan generated. Review or edit it in Gate 1.</p>`
      : '';
  } else if (type === 'tool_call') {
    const tool = data?.tool || data?.tool_name || data?.name || 'unknown';
    const args = data?.args || data?.input || {};
    bodyHtml = `
      <span class="text-xs font-mono text-purple-300 font-semibold">${escHtml(tool)}</span>
      ${Object.keys(args).length ? `<pre class="text-xs text-gray-500 font-mono mt-1 bg-surface-700/50 rounded p-2 overflow-x-auto">${escHtml(JSON.stringify(args, null, 2))}</pre>` : ''}
    `;
  } else if (type === 'tool_result') {
    const tool = data?.tool || data?.tool_name || data?.name || '';
    const count = data?.count ?? data?.hit_count ?? data?.total ?? null;
    const scores = data?.similarity_scores || data?.scores || [];
    let scoreHtml = '';
    if (scores.length) {
      scoreHtml = `<div class="mt-2 space-y-1">
        ${scores.slice(0,5).map((s,i) => `
          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-500 w-4">${i+1}</span>
            <div class="sim-bar-track flex-1"><div class="sim-bar-fill bg-cyan-500" style="width:${Math.round(s*100)}%"></div></div>
            <span class="text-xs text-gray-400 w-8 text-right">${(s*100).toFixed(0)}%</span>
          </div>`).join('')}
        ${scores.length > 5 ? `<p class="text-xs text-gray-600">+${scores.length-5} more</p>` : ''}
      </div>`;
    }
    bodyHtml = `
      ${tool ? `<span class="text-xs font-mono text-cyan-300">${escHtml(tool)}</span>` : ''}
      ${count != null ? `<span class="ml-2 text-xs text-gray-400">${count} hit${count !== 1 ? 's' : ''}</span>` : ''}
      ${scoreHtml}
    `;
  } else if (type === 'proposal') {
    const items = data?.items || [];
    bodyHtml = `<p class="text-xs text-gray-300 mt-1">${items.length} suspicious invoice${items.length !== 1 ? 's' : ''} identified.</p>`;
  } else if (type === 'awaiting_approval') {
    const gate = data?.gate || '';
    bodyHtml = `<p class="text-xs text-yellow-300/80 mt-1">Gate <span class="font-mono font-semibold">${escHtml(gate)}</span> — action required above</p>`;
  } else if (type === 'written') {
    const n = data?.flagged ?? data?.written_count ?? data?.count ?? '';
    bodyHtml = n !== '' ? `<p class="text-xs text-green-300/80 mt-1">${n} item${n !== 1 ? 's' : ''} committed to audit log.</p>` : '';
  } else if (type === 'report_ready') {
    bodyHtml = `<p class="text-xs text-green-300/80 mt-1">Audit report generated — see dashboard panel.</p>`;
  } else if (type === 'error') {
    const msg = data?.message || data?.error || JSON.stringify(data);
    bodyHtml = `<p class="text-xs text-red-300 mt-1 font-mono">${escHtml(msg)}</p>`;
  } else if (type === 'done') {
    bodyHtml = `<p class="text-xs text-green-300/80 mt-1">Audit run complete.</p>`;
  }

  const agent = data?.adk_agent_name || data?.agent || '';
  const toolLabel = data?.tool_label || data?.via || '';
  const chipHtml = `
    ${agent ? `<span class="agent-chip text-[10px]">${escHtml(agent)}</span>` : ''}
    ${toolLabel ? `<span class="tool-chip ${toolChipClass(toolLabel)} text-[10px]">${escHtml(toolLabel)}</span>` : ''}
  `;

  card.innerHTML = `
    <div class="flex items-center gap-2 mb-0.5">
      <span class="step-badge bg-surface-700 text-gray-400">${state.stepCount}</span>
      <span class="px-1.5 py-0.5 rounded border text-xs font-semibold ${meta.badge}">${meta.label}</span>
      ${chipHtml}
      <span class="ml-auto text-xs text-gray-600 font-mono">${tsNow()}</span>
    </div>
    ${bodyHtml}
  `;

  document.getElementById('timeline').appendChild(card);
  scrollTimeline();
}

// ─────────────────────────────────────────────────────────────────────────────
// Flagged items table (Gate 2)
// ─────────────────────────────────────────────────────────────────────────────
function renderFlaggedTable() {
  const tbody = document.getElementById('flagged-items-tbody');
  tbody.innerHTML = '';

  state.flaggedItems.forEach(item => {
    const tr = document.createElement('tr');
    tr.className = 'bg-surface-800 hover:bg-surface-700/50 transition-colors';
    tr.dataset.invoiceId = item.invoice_id;

    const reasons = (item.reasons || []).map(r =>
      `<span class="reason-chip ${r}">${r.replace(/_/g,' ')}</span>`
    ).join(' ');
    const shortId = escHtml(String(item.invoice_id).slice(0, 8));

    tr.innerHTML = `
      <td class="px-2 py-2">
        <input type="checkbox" class="item-cb rounded border-surface-500" data-id="${escHtml(item.invoice_id)}" checked onchange="handleCbChange(this)" />
      </td>
      <td class="px-2 py-2 text-xs text-gray-200 max-w-[130px] truncate" title="${escHtml(item.vendor_name)}">
        ${escHtml(item.vendor_name)}
        <span class="block font-mono text-[10px] text-gray-500">${shortId} · ${escHtml(item.department)}</span>
      </td>
      <td class="px-2 py-2 text-xs text-right font-mono font-semibold text-accent-red whitespace-nowrap">${fmtCurrency(item.amount)}</td>
      <td class="px-2 py-2"><div class="flex flex-wrap gap-1 max-w-[150px]">${reasons}</div></td>
      <td class="px-2 py-2 text-center">
        <div class="flex gap-1 justify-center">
          <button class="row-decision-btn approve active" data-id="${escHtml(item.invoice_id)}" data-action="approve" onclick="setRowDecision(this,'approve')">✓</button>
          <button class="row-decision-btn reject" data-id="${escHtml(item.invoice_id)}" data-action="reject" onclick="setRowDecision(this,'reject')">✕</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function setRowDecision(btn, decision) {
  const id = btn.dataset.id;
  state.rowDecisions[id] = decision;

  // Update button active states in row
  const row = btn.closest('tr');
  row.querySelectorAll('.row-decision-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  // Sync checkbox
  const cb = row.querySelector('.item-cb');
  if (cb) cb.checked = (decision === 'approve');
}

function handleCbChange(cb) {
  const id = cb.dataset.id;
  const decision = cb.checked ? 'approve' : 'reject';
  state.rowDecisions[id] = decision;
  const row = cb.closest('tr');
  row.querySelectorAll('.row-decision-btn').forEach(b => {
    if (b.dataset.action === decision) b.classList.add('active');
    else b.classList.remove('active');
  });
}

function toggleSelectAll(masterCb) {
  document.querySelectorAll('.item-cb').forEach(cb => {
    cb.checked = masterCb.checked;
    const id = cb.dataset.id;
    state.rowDecisions[id] = masterCb.checked ? 'approve' : 'reject';
    const row = cb.closest('tr');
    row.querySelectorAll('.row-decision-btn').forEach(b => {
      const isActive = (b.dataset.action === (masterCb.checked ? 'approve' : 'reject'));
      b.classList.toggle('active', isActive);
    });
  });
}

function approveAll() {
  document.getElementById('select-all-cb').checked = true;
  toggleSelectAll(document.getElementById('select-all-cb'));
  submitActionDecision();   // one click: select all + write
}

// ─────────────────────────────────────────────────────────────────────────────
// Approval submissions
// ─────────────────────────────────────────────────────────────────────────────
async function approvePlan() {
  const edited = document.getElementById('plan-edit-input')?.value.trim() || '';
  const original = state._lastPlan || '';
  const changed = edited && edited !== original;
  recordApproval('plan', 'approved', changed ? 'Edited plan approved' : 'Plan approved');
  await postApproval({ gate: 'plan', approved: true, ...(changed ? { edited_plan: edited } : {}) });
  document.getElementById('gate-plan').classList.add('hidden');
}
async function rejectPlan() {
  recordApproval('plan', 'rejected', 'Plan rejected');
  await postApproval({ gate: 'plan', approved: false });
  document.getElementById('gate-plan').classList.add('hidden');
}

function focusPlanEditor() {
  const input = document.getElementById('plan-edit-input');
  if (!input) return;
  input.focus();
  input.setSelectionRange(0, input.value.length);
}

async function submitActionDecision() {
  const approvedIds = [];
  const rejectedIds = [];
  Object.entries(state.rowDecisions).forEach(([id, dec]) => {
    if (dec === 'approve') approvedIds.push(id);
    else rejectedIds.push(id);
  });
  recordApproval('action', 'approved', `${approvedIds.length} approved, ${rejectedIds.length} rejected`);
  setStatusBadge('executing', 'Writing…');
  await postApproval({ gate: 'action', approved: true, approved_ids: approvedIds, rejected_ids: rejectedIds });
  document.getElementById('gate-action').classList.add('hidden');
}

function rejectAllAction() {
  state.flaggedItems.forEach(it => { state.rowDecisions[it.invoice_id] = 'reject'; });
  submitActionDecision();
}

async function postApproval(decision) {
  try {
    await fetch(`/api/approve/${state.runId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(decision),
    });
  } catch (err) {
    console.error('Approval error:', err);
  }
}

function recordApproval(gate, decision, detail) {
  state.approvalLog.unshift({ gate, decision, detail, ts: new Date().toISOString() });
  renderApprovalLog();
}

// ─────────────────────────────────────────────────────────────────────────────
// Dashboard renders
// ─────────────────────────────────────────────────────────────────────────────
function renderDeptChart() {
  const el = document.getElementById('dept-chart');
  const entries = Object.entries(state.deptCounts).sort((a,b) => b[1]-a[1]);
  if (!entries.length) return;
  const max = entries[0][1];
  const colors = ['bg-orange-500','bg-red-500','bg-yellow-500','bg-purple-500','bg-pink-500'];

  el.innerHTML = entries.slice(0,6).map(([dept, count], i) => `
    <div class="bar-chart-item">
      <span class="bar-chart-label" title="${escHtml(dept)}">${escHtml(dept)}</span>
      <div class="bar-chart-track">
        <div class="bar-chart-fill ${colors[i % colors.length]}" style="width:${Math.round(count/max*100)}%"></div>
      </div>
      <span class="bar-chart-value">${count}</span>
    </div>
  `).join('');
}

function renderVendorChart() {
  const el = document.getElementById('vendor-chart');
  const entries = Object.entries(state.vendorFlags).sort((a,b) => b[1]-a[1]);
  if (!entries.length) return;
  const max = entries[0][1];
  const colors = ['bg-purple-500','bg-pink-500','bg-indigo-500','bg-violet-500','bg-fuchsia-500'];

  el.innerHTML = entries.slice(0,6).map(([vendor, count], i) => `
    <div class="bar-chart-item">
      <span class="bar-chart-label" title="${escHtml(vendor)}">${escHtml(vendor)}</span>
      <div class="bar-chart-track">
        <div class="bar-chart-fill ${colors[i % colors.length]}" style="width:${Math.round(count/max*100)}%"></div>
      </div>
      <span class="bar-chart-value">${count}</span>
    </div>
  `).join('');
}

function renderReport(report) {
  document.getElementById('download-btn').classList.remove('hidden');
  document.getElementById('download-btn').classList.add('flex');
  document.getElementById('download-pdf-btn')?.classList.remove('hidden');
  document.getElementById('download-pdf-btn')?.classList.add('flex');
  document.getElementById('download-excel-btn')?.classList.remove('hidden');
  document.getElementById('download-excel-btn')?.classList.add('flex');

  document.getElementById('report-content').innerHTML = `
    <div class="mb-4 grid grid-cols-3 gap-3 p-3 bg-surface-700/40 rounded-lg border border-surface-600">
      <div class="text-center">
        <p class="text-xs text-gray-500">Flagged Items</p>
        <p class="text-lg font-bold text-accent-red tabular-nums">${report.flagged_count ?? 0}</p>
      </div>
      <div class="text-center">
        <p class="text-xs text-gray-500">Total At Risk</p>
        <p class="text-lg font-bold text-accent-orange tabular-nums">${fmtCurrency(report.total_at_risk ?? 0)}</p>
      </div>
      <div class="text-center">
        <p class="text-xs text-gray-500">Generated</p>
        <p class="text-xs font-mono text-gray-400 mt-1">${fmtTs(report.generated_at)}</p>
      </div>
    </div>
    ${renderReportSummary(report)}
    ${renderReportItemsTable(report.items || [])}
  `;
  renderReportsView();
}

function renderFindingsView() {
  const tbody = document.getElementById('findings-tbody');
  if (!tbody) return;
  document.getElementById('findings-count').textContent = `${state.flaggedItems.length} item${state.flaggedItems.length === 1 ? '' : 's'}`;
  if (!state.flaggedItems.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="px-3 py-8 text-center text-gray-600">No findings yet. Run a mission to populate this table.</td></tr>`;
    renderFindingDetail(null);
    return;
  }
  tbody.innerHTML = state.flaggedItems.map(item => {
    const status = state.itemStatuses[item.invoice_id] || 'pending';
    const reasons = (item.reasons || []).map(r => `<span class="reason-chip ${escHtml(r)}">${escHtml(String(r).replace(/_/g,' '))}</span>`).join(' ');
    const active = state.selectedFindingId === item.invoice_id ? 'active' : '';
    const agent = item._agent || 'Risk Triage Agent';
    const tool = item._tool_label || 'Internal detector fallback';
    return `
      <tr class="finding-row ${active}" onclick="selectFinding('${escAttr(item.invoice_id)}')">
        <td class="px-3 py-2 text-gray-200 max-w-[180px] truncate" title="${escHtml(item.vendor_name)}">${escHtml(item.vendor_name)}</td>
        <td class="px-3 py-2 font-mono">
          <button class="invoice-link" onclick="event.stopPropagation(); selectFinding('${escAttr(item.invoice_id)}'); openInvoiceDocument('${escAttr(item.invoice_id)}')" title="Open invoice document">
            ${escHtml(item.invoice_id)}
          </button>
        </td>
        <td class="px-3 py-2 text-gray-400">${escHtml(item.department)}</td>
        <td class="px-3 py-2 text-right font-mono text-accent-red">${fmtCurrency(item.amount)}</td>
        <td class="px-3 py-2"><div class="flex flex-wrap gap-1">${reasons}</div></td>
        <td class="px-3 py-2 text-gray-400">${escHtml(agent)}</td>
        <td class="px-3 py-2"><span class="tool-chip ${toolChipClass(tool)} text-[10px]">${escHtml(tool)}</span></td>
        <td class="px-3 py-2"><span class="status-pill ${status}">${statusLabel(status)}</span></td>
      </tr>
    `;
  }).join('');
  const selected = state.flaggedItems.find(i => i.invoice_id === state.selectedFindingId) || state.flaggedItems[0];
  if (!state.selectedFindingId && selected) state.selectedFindingId = selected.invoice_id;
  renderFindingDetail(selected);
}

function selectFinding(invoiceId) {
  state.selectedFindingId = invoiceId;
  renderFindingsView();
}

function renderFindingDetail(item) {
  const el = document.getElementById('finding-detail');
  if (!el) return;
  if (!item) {
    el.innerHTML = 'Select a finding to inspect its evidence.';
    return;
  }
  const reasons = (item.reasons || []).map(r => `<span class="reason-chip ${escHtml(r)}">${escHtml(String(r).replace(/_/g,' '))}</span>`).join(' ');
  const sim = item.similarity != null ? Math.max(0, Math.min(100, Math.round(item.similarity * 100))) : null;
  const detailLines = String(item.detail || 'No detail supplied.').split(';').map(s => s.trim()).filter(Boolean);
  const previewHtml = escAttr(buildInvoiceDocumentHtml(item, { embedded: true }));
  el.innerHTML = `
    <div class="space-y-4">
      <div>
        <p class="text-xs text-gray-500 uppercase tracking-wide">Invoice</p>
        <button onclick="openInvoiceDocument('${escAttr(item.invoice_id)}')" class="invoice-link font-mono">${escHtml(item.invoice_id)}</button>
      </div>
      <div>
        <p class="text-xs text-gray-500 uppercase tracking-wide">Vendor / Amount</p>
        <p class="text-gray-200">${escHtml(item.vendor_name)} · <span class="font-mono text-accent-red">${fmtCurrency(item.amount)}</span></p>
      </div>
      <div class="flex flex-wrap gap-1">${reasons}</div>
      ${sim != null ? `<div>
        <div class="flex justify-between text-xs text-gray-500 mb-1"><span>Similarity</span><span>${sim}%</span></div>
        <div class="sim-bar-track"><div class="sim-bar-fill bg-cyan-500" style="width:${sim}%"></div></div>
      </div>` : ''}
      <div>
        <p class="text-xs text-gray-500 uppercase tracking-wide mb-2">Evidence</p>
        <ul class="space-y-1">${detailLines.map(line => `<li class="text-sm text-gray-300">• ${escHtml(line)}</li>`).join('')}</ul>
      </div>
      <div>
        <div class="mb-2 flex items-center gap-2">
          <p class="text-xs text-gray-500 uppercase tracking-wide">Invoice PDF Preview</p>
          <button onclick="openInvoiceDocument('${escAttr(item.invoice_id)}')" class="ml-auto text-xs text-brand-300 hover:text-brand-200">Open PDF</button>
        </div>
        <iframe class="invoice-preview-frame" title="Invoice preview ${escAttr(item.invoice_id)}" srcdoc="${previewHtml}"></iframe>
        <p class="mt-1 text-[11px] text-gray-600">Preview generated from audit evidence. Attach source PDFs later to replace this document.</p>
      </div>
      <div class="grid grid-cols-2 gap-2">
        <button onclick="explainInvoiceDocument('${escAttr(item.invoice_id)}')" class="py-2 rounded-md bg-brand-500 hover:bg-brand-400 text-white text-sm font-semibold">Explain PDF with AI</button>
        <button onclick="openInvoiceDocument('${escAttr(item.invoice_id)}')" class="py-2 rounded-md bg-surface-700 border border-surface-500 hover:bg-surface-600 text-gray-200 text-sm font-semibold">Open in Tab</button>
      </div>
    </div>
  `;
}

function renderReportsView() {
  const reportEl = document.getElementById('reports-report-content');
  if (!reportEl) return;
  if (!state.report) {
    reportEl.innerHTML = '<p class="text-sm text-gray-600">Report will appear here when the audit completes.</p>';
  } else {
    reportEl.innerHTML = `
      <div class="mb-4 grid grid-cols-3 gap-3 p-3 bg-surface-700/40 rounded-lg border border-surface-600">
        <div><p class="text-xs text-gray-500">Flagged</p><p class="text-lg font-bold text-accent-red">${state.report.flagged_count || 0}</p></div>
        <div><p class="text-xs text-gray-500">At Risk</p><p class="text-lg font-bold text-accent-orange">${fmtCurrency(state.report.total_at_risk || 0)}</p></div>
        <div><p class="text-xs text-gray-500">Run</p><p class="text-xs font-mono text-gray-400 mt-1">${escHtml((state.runId || '').slice(0,8))}</p></div>
      </div>
      ${renderReportSummary(state.report)}
      ${renderReportItemsTable(state.report.items || [])}
    `;
  }
  renderApprovalLog();
}

function renderReportSummary(report) {
  const narrative = extractReportNarrative(report.markdown || '')
    || `Approved ${report.flagged_count || 0} flagged invoice${(report.flagged_count || 0) === 1 ? '' : 's'} totaling ${fmtCurrency(report.total_at_risk || 0)} at risk for the mission "${report.mission || 'audit mission'}". Review the table below for invoice-level evidence and use Export CSV for Excel.`;
  return `
    <div class="mb-4 rounded-lg border border-surface-600 bg-surface-700/30 p-4">
      <p class="text-xs text-gray-500 uppercase tracking-wide mb-2">Executive Summary</p>
      <p class="text-sm text-gray-300 leading-relaxed">${escHtml(narrative)}</p>
    </div>
  `;
}

function renderReportItemsTable(items) {
  if (!items.length) {
    return '<div class="rounded-lg border border-surface-600 bg-surface-700/30 p-4 text-sm text-gray-500">No flagged items were approved for this report.</div>';
  }
  const rows = items.map(item => {
    const reasons = (item.reasons || []).map(r =>
      `<span class="reason-chip ${escHtml(r)}">${escHtml(String(r).replace(/_/g, ' '))}</span>`
    ).join(' ');
    return `
      <tr>
        <td class="report-cell font-mono whitespace-nowrap">
          <button class="invoice-link" onclick="openInvoiceDocument('${escAttr(item.invoice_id)}')" title="Open invoice document">${escHtml(item.invoice_id)}</button>
        </td>
        <td class="report-cell min-w-[160px] text-gray-200">${escHtml(item.vendor_name)}</td>
        <td class="report-cell whitespace-nowrap text-gray-400">${escHtml(item.department)}</td>
        <td class="report-cell text-right font-mono text-accent-red whitespace-nowrap">${fmtCurrency(item.amount)}</td>
        <td class="report-cell min-w-[180px]"><div class="flex flex-wrap gap-1">${reasons}</div></td>
        <td class="report-cell min-w-[280px] text-gray-300 leading-relaxed">${escHtml(item.detail || '')}</td>
      </tr>
    `;
  }).join('');
  return `
    <div class="rounded-lg border border-surface-600 bg-surface-800 overflow-hidden">
      <div class="px-4 py-3 border-b border-surface-600 bg-surface-700/50 flex items-center gap-2">
        <span class="text-xs font-medium text-gray-400 uppercase tracking-wide">Flagged Items</span>
        <span class="ml-auto text-xs text-gray-500 font-mono">${items.length} rows · export CSV for Excel</span>
      </div>
      <div class="report-table-wrap">
        <table class="report-table">
          <thead>
            <tr>
              <th>Invoice ID</th>
              <th>Vendor</th>
              <th>Dept</th>
              <th class="text-right">Amount</th>
              <th>Reasons</th>
              <th>Evidence Detail</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  `;
}

function extractReportNarrative(md) {
  const lines = String(md || '').split('\n').map(line => line.trim()).filter(Boolean);
  const skip = /^(#|\\||-{3,}|\\*\\*Mission:|\\*\\*Run ID:|\\*\\*Flagged invoices:|\\*\\*Total at risk:|- \\*\\*)/;
  return lines.find(line => !skip.test(line)) || '';
}

function renderApprovalLog() {
  const el = document.getElementById('approval-log');
  if (!el) return;
  if (!state.approvalLog.length) {
    el.innerHTML = 'No approvals recorded yet.';
    return;
  }
  el.innerHTML = state.approvalLog.map(entry => `
    <div class="rounded-md border border-surface-600 bg-surface-700/40 p-3">
      <div class="flex items-center gap-2">
        <span class="status-pill ${entry.decision === 'approved' ? 'approved' : 'rejected'}">${escHtml(entry.gate)}</span>
        <span class="text-xs text-gray-500 font-mono ml-auto">${fmtTs(entry.ts)}</span>
      </div>
      <p class="text-sm text-gray-300 mt-2">${escHtml(entry.detail)}</p>
    </div>
  `).join('');
}

// ─────────────────────────────────────────────────────────────────────────────
// Download report
// ─────────────────────────────────────────────────────────────────────────────
function downloadReport() {
  if (!state.report) return;
  const md = state.report.markdown || '';
  const blob = new Blob([md], { type: 'text/markdown' });
  triggerDownload(blob, `audit-report-${state.runId?.slice(0,8) || 'export'}.md`);
}

function downloadReportExcel() {
  if (!state.report) return;
  const items = reportItems();
  const rows = items.map(item => `
    <tr>
      <td>${escHtml(item.invoice_id)}</td>
      <td>${escHtml(item.vendor_name)}</td>
      <td>${escHtml(item.department)}</td>
      <td style="mso-number-format:'\\$#,##0.00';">${Number(item.amount || 0).toFixed(2)}</td>
      <td>${escHtml((item.reasons || []).map(r => String(r).replace(/_/g, ' ')).join(', '))}</td>
      <td>${escHtml(item.detail || '')}</td>
    </tr>
  `).join('');
  const html = `<!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <style>
          table { border-collapse: collapse; font-family: Arial, sans-serif; font-size: 12px; }
          th { background: #d9eaf7; font-weight: bold; }
          th, td { border: 1px solid #9aa7b2; padding: 6px 8px; vertical-align: top; }
          .summary td:first-child { font-weight: bold; background: #f2f4f7; }
        </style>
      </head>
      <body>
        <h2>FaultAuditAI Audit Report</h2>
        <table class="summary">
          <tr><td>Mission</td><td>${escHtml(state.report.mission || '')}</td></tr>
          <tr><td>Run ID</td><td>${escHtml(state.report.run_id || state.runId || '')}</td></tr>
          <tr><td>Flagged invoices</td><td>${state.report.flagged_count || 0}</td></tr>
          <tr><td>Total at risk</td><td>${Number(state.report.total_at_risk || 0).toFixed(2)}</td></tr>
        </table>
        <br />
        <table>
          <thead>
            <tr>
              <th>Invoice ID</th><th>Vendor</th><th>Department</th><th>Amount</th><th>Reasons</th><th>Evidence Detail</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </body>
    </html>`;
  const blob = new Blob([html], { type: 'application/vnd.ms-excel;charset=utf-8' });
  triggerDownload(blob, `audit-report-${state.runId?.slice(0,8) || 'export'}.xls`);
}

function downloadReportPdf() {
  if (!state.report) return;
  const items = reportItems();
  const printWindow = window.open('', '_blank', 'width=1180,height=860');
  if (!printWindow) {
    alert('Allow pop-ups to generate the PDF report.');
    return;
  }
  printWindow.opener = null;
  printWindow.document.open();
  printWindow.document.write(buildPrintableReportHtml(state.report, items));
  printWindow.document.close();
  printWindow.focus();
  setTimeout(() => printWindow.print(), 450);
}

function buildPrintableReportHtml(report, items) {
  const status = state.appStatus || {};
  const runId = report.run_id || state.runId || '';
  const generatedAt = new Date().toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
  const runtime = status.agent_runtime_label || status.agent_runtime || 'Google ADK multi-agent';
  const model = status.gemini_model || 'Gemini 3.x';
  const mcp = status.mcp_enabled ? 'MongoDB MCP' : 'MongoDB evidence layer';
  const narrative = extractReportNarrative(report.markdown) || 'Human-approved suspicious invoices are listed below for remediation, recovery, and audit follow-up.';
  const approvalSummary = state.approvalLog.length
    ? state.approvalLog.map(entry => `${entry.gate}: ${entry.detail}`).join(' | ')
    : 'No approval entries captured in this browser session.';
  const rows = items.map((item, idx) => {
    const reasons = (item.reasons || []).map(reason => `
      <span class="reason-pill">${escHtml(String(reason).replace(/_/g, ' '))}</span>
    `).join('');
    return `
      <tr>
        <td class="row-num">${idx + 1}</td>
        <td class="mono">${escHtml(item.invoice_id)}</td>
        <td>${escHtml(item.vendor_name)}</td>
        <td>${escHtml(item.department)}</td>
        <td class="amount">${fmtCurrency(item.amount || 0)}</td>
        <td class="reasons">${reasons || '<span class="muted">No reason supplied</span>'}</td>
        <td>${escHtml(item.detail || 'Evidence detail unavailable')}</td>
      </tr>
    `;
  }).join('');

  return `<!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <title>FaultAuditAI Audit Report ${escHtml(runId ? `- ${runId}` : '')}</title>
        <style>${printReportStyles()}</style>
      </head>
      <body>
        <main class="report-shell">
          <section class="brand-hero">
            <div class="brand-mark">FA</div>
            <div>
              <p class="eyebrow">FaultAuditAI</p>
              <h1>AI Corporate-Finance Audit Report</h1>
              <p class="subtitle">${escHtml(report.mission || 'Vendor payments audit')}</p>
            </div>
          </section>

          <section class="meta-grid">
            <div><span>Run ID</span><strong>${escHtml(runId || 'Unavailable')}</strong></div>
            <div><span>Generated</span><strong>${escHtml(generatedAt)}</strong></div>
            <div><span>Runtime</span><strong>${escHtml(runtime)}</strong></div>
            <div><span>Model</span><strong>${escHtml(model)}</strong></div>
            <div><span>Evidence</span><strong>${escHtml(mcp)}</strong></div>
            <div><span>Approval</span><strong>Human reviewed</strong></div>
          </section>

          <section class="kpi-grid">
            <div class="kpi-card">
              <span>Flagged invoices</span>
              <strong>${Number(report.flagged_count || items.length || 0).toLocaleString()}</strong>
            </div>
            <div class="kpi-card risk">
              <span>Total at risk</span>
              <strong>${fmtCurrency(report.total_at_risk || 0)}</strong>
            </div>
            <div class="kpi-card">
              <span>Approved gates</span>
              <strong>${state.approvalLog.length || 2}</strong>
            </div>
            <div class="kpi-card">
              <span>Audit trail</span>
              <strong>Committed</strong>
            </div>
          </section>

          <section class="summary-panel">
            <div>
              <p class="section-label">Executive summary</p>
              <p>${escHtml(narrative)}</p>
            </div>
            <div>
              <p class="section-label">Approval log</p>
              <p>${escHtml(approvalSummary)}</p>
            </div>
          </section>

          <section class="findings-section">
            <div class="section-heading">
              <div>
                <p class="section-label">Flagged items</p>
                <h2>Evidence table</h2>
              </div>
              <p>${Number(items.length || 0).toLocaleString()} records</p>
            </div>
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Invoice ID</th>
                  <th>Vendor</th>
                  <th>Department</th>
                  <th>Amount</th>
                  <th>Reasons</th>
                  <th>Evidence detail</th>
                </tr>
              </thead>
              <tbody>${rows || '<tr><td colspan="7" class="empty">No flagged items were included in this report.</td></tr>'}</tbody>
            </table>
          </section>

          <footer>
            <strong>FaultAuditAI</strong>
            <span>AI-generated audit support. Final decisions require human review and source-system verification.</span>
          </footer>
        </main>
      </body>
    </html>`;
}

function buildInvoiceDocumentHtml(item, opts = {}) {
  const embedded = Boolean(opts.embedded);
  const seed = Math.abs(hashText(String(item.invoice_id || item.vendor_name || 'invoice')));
  const poNumber = `PO-${String(seed % 900000 + 100000)}`;
  const invoiceDate = new Date(Date.now() - (seed % 28) * 86400000).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
  const dueDate = new Date(Date.now() + ((seed % 21) + 7) * 86400000).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
  const reasons = (item.reasons || []).map(r => String(r).replace(/_/g, ' '));
  const reasonHtml = reasons.map(r => `<span class="pill">${escHtml(r)}</span>`).join('');
  const detailLines = String(item.detail || 'No evidence detail supplied.')
    .split(';')
    .map(s => s.trim())
    .filter(Boolean);
  const runId = state.runId || state.report?.run_id || 'pending';
  const docLabel = embedded ? 'Invoice document preview' : 'Invoice PDF Preview';
  const toolbar = embedded ? '' : `
    <div class="toolbar">
      <strong>${docLabel}</strong>
      <button onclick="window.print()">Print / Save PDF</button>
    </div>
  `;

  return `<!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <title>${escHtml(item.invoice_id)} - Invoice PDF Preview</title>
        <style>
          @page { size: letter; margin: 0.45in; }
          * { box-sizing: border-box; }
          body {
            margin: 0;
            background: ${embedded ? '#ffffff' : '#eef3f8'};
            color: #172033;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
            font-size: ${embedded ? '10px' : '12px'};
            line-height: 1.45;
          }
          .toolbar {
            position: sticky;
            top: 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 14px;
            background: #111827;
            color: #e5e7eb;
            box-shadow: 0 8px 24px rgba(15,23,42,.2);
          }
          .toolbar button {
            border: 1px solid #3b82f6;
            border-radius: 7px;
            background: #2563eb;
            color: white;
            padding: 7px 11px;
            font-weight: 800;
            cursor: pointer;
          }
          .page {
            max-width: ${embedded ? '720px' : '820px'};
            min-height: ${embedded ? 'auto' : '980px'};
            margin: ${embedded ? '0' : '22px auto'};
            padding: ${embedded ? '18px' : '34px'};
            background: #ffffff;
            border: ${embedded ? '0' : '1px solid #d8e1ee'};
            box-shadow: ${embedded ? 'none' : '0 22px 70px rgba(15,23,42,.16)'};
          }
          .doc-head {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 18px;
            border-bottom: 3px solid #2563eb;
            padding-bottom: 16px;
          }
          .brand {
            color: #174ea6;
            font-size: ${embedded ? '17px' : '22px'};
            font-weight: 900;
            letter-spacing: 0;
          }
          .subtle {
            color: #64748b;
            font-size: ${embedded ? '9px' : '11px'};
          }
          h1 {
            margin: 0;
            text-align: right;
            font-size: ${embedded ? '20px' : '30px'};
            line-height: 1;
            letter-spacing: 0;
          }
          .status {
            display: inline-block;
            margin-top: 8px;
            padding: 4px 8px;
            border-radius: 999px;
            background: #fff7ed;
            color: #b45309;
            border: 1px solid #fed7aa;
            font-weight: 800;
            font-size: 10px;
          }
          .meta {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            margin: 18px 0;
          }
          .box {
            border: 1px solid #dbe4f0;
            border-radius: 10px;
            padding: 10px;
            background: #f8fbff;
            overflow-wrap: anywhere;
          }
          .box span, th {
            color: #64748b;
            font-size: 9px;
            text-transform: uppercase;
            letter-spacing: .07em;
            font-weight: 900;
          }
          .box strong {
            display: block;
            margin-top: 4px;
            color: #172033;
          }
          .parties {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
            margin-bottom: 18px;
          }
          table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            border: 1px solid #dbe4f0;
            border-radius: 10px;
            overflow: hidden;
          }
          th {
            background: #edf4ff;
            text-align: left;
            padding: 9px;
          }
          td {
            padding: 10px 9px;
            border-top: 1px solid #e6edf6;
            vertical-align: top;
          }
          .right { text-align: right; }
          .total-row td {
            background: #f8fbff;
            font-weight: 900;
            font-size: ${embedded ? '12px' : '15px'};
          }
          .audit-panel {
            margin-top: 16px;
            border: 1px solid #fed7aa;
            border-radius: 12px;
            background: #fff7ed;
            padding: 12px;
          }
          .audit-panel h2 {
            margin: 0 0 8px;
            color: #9a3412;
            font-size: ${embedded ? '12px' : '15px'};
            letter-spacing: 0;
          }
          .pill {
            display: inline-block;
            margin: 0 4px 5px 0;
            padding: 3px 7px;
            border-radius: 999px;
            border: 1px solid #fdba74;
            background: #ffedd5;
            color: #9a3412;
            font-size: 10px;
            font-weight: 900;
            text-transform: capitalize;
          }
          ul { margin: 8px 0 0 18px; padding: 0; }
          li { margin-bottom: 4px; }
          footer {
            margin-top: 18px;
            padding-top: 10px;
            border-top: 1px solid #dbe4f0;
            color: #64748b;
            font-size: 10px;
          }
          @media print {
            body { background: white; }
            .toolbar { display: none; }
            .page {
              margin: 0;
              max-width: none;
              min-height: auto;
              padding: 0;
              border: 0;
              box-shadow: none;
            }
            .status, .box, th, .audit-panel {
              print-color-adjust: exact;
              -webkit-print-color-adjust: exact;
            }
          }
        </style>
      </head>
      <body>
        ${toolbar}
        <main class="page">
          <section class="doc-head">
            <div>
              <div class="brand">FaultAuditAI</div>
              <div class="subtle">Audit-generated invoice evidence preview</div>
              <span class="status">Flagged for review</span>
            </div>
            <div>
              <h1>Invoice</h1>
              <div class="subtle">${escHtml(item.invoice_id)}</div>
            </div>
          </section>

          <section class="meta">
            <div class="box"><span>Invoice ID</span><strong>${escHtml(item.invoice_id)}</strong></div>
            <div class="box"><span>PO Number</span><strong>${escHtml(poNumber)}</strong></div>
            <div class="box"><span>Invoice Date</span><strong>${escHtml(invoiceDate)}</strong></div>
            <div class="box"><span>Due Date</span><strong>${escHtml(dueDate)}</strong></div>
          </section>

          <section class="parties">
            <div class="box">
              <span>Vendor</span>
              <strong>${escHtml(item.vendor_name)}</strong>
              <div class="subtle">Department: ${escHtml(item.department || 'Unassigned')}</div>
            </div>
            <div class="box">
              <span>Audit run</span>
              <strong>${escHtml(String(runId).slice(0, 18))}${String(runId).length > 18 ? '...' : ''}</strong>
              <div class="subtle">Generated by ${escHtml(state.appStatus?.gemini_model || 'Gemini 3.x')}</div>
            </div>
          </section>

          <table>
            <thead>
              <tr>
                <th>Description</th>
                <th class="right">Amount</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  Vendor payment under audit review
                  <div class="subtle">Evidence: ${escHtml(item.detail || 'No detail supplied.')}</div>
                </td>
                <td class="right">${fmtCurrency(item.amount || 0)}</td>
              </tr>
              <tr class="total-row">
                <td>Total invoice amount</td>
                <td class="right">${fmtCurrency(item.amount || 0)}</td>
              </tr>
            </tbody>
          </table>

          <section class="audit-panel">
            <h2>AI Audit Explanation Context</h2>
            <div>${reasonHtml || '<span class="pill">audit review</span>'}</div>
            <ul>${detailLines.map(line => `<li>${escHtml(line)}</li>`).join('')}</ul>
          </section>

          <footer>
            This is a FaultAuditAI evidence preview generated from the audit dataset. It is not a substitute for the original vendor-submitted PDF stored in the source system.
          </footer>
        </main>
      </body>
    </html>`;
}

function exportFindingsCsv() {
  const rows = [['Vendor','Invoice ID','Department','Amount','Reasons','Agent','Tool','Status']];
  const items = state.flaggedItems.length ? state.flaggedItems : reportItems();
  items.forEach(item => {
    rows.push([
      item.vendor_name,
      item.invoice_id,
      item.department,
      item.amount,
      (item.reasons || []).join('|'),
      item._agent || 'Risk Triage Agent',
      item._tool_label || 'Internal detector fallback',
      state.itemStatuses[item.invoice_id] || 'pending',
    ]);
  });
  const csv = rows.map(row => row.map(v => `"${String(v ?? '').replace(/"/g,'""')}"`).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  triggerDownload(blob, `audit-findings-${state.runId?.slice(0,8) || 'export'}.csv`);
}

async function copyCfoSummary() {
  if (!state.report?.markdown) return;
  const text = state.report.markdown
    .split('\n')
    .map(line => line.trim())
    .filter(line => line && !line.startsWith('#') && !line.startsWith('|'))[0] || '';
  try { await navigator.clipboard.writeText(text); } catch {}
}

function openAskDrawer() {
  document.getElementById('ask-backdrop').classList.remove('hidden');
  document.getElementById('ask-drawer').classList.add('open');
  setTimeout(() => document.getElementById('ask-input')?.focus(), 50);
}

function closeAskDrawer() {
  document.getElementById('ask-backdrop').classList.add('hidden');
  document.getElementById('ask-drawer').classList.remove('open');
}

function askPrompt(text) {
  document.getElementById('ask-input').value = text;
  submitAsk();
}

async function explainFinding(invoiceId) {
  const item = state.flaggedItems.find(i => i.invoice_id === invoiceId);
  if (!item) return;
  openAskDrawer();
  document.getElementById('ask-input').value = `Why was invoice ${item.invoice_id} from ${item.vendor_name} flagged?`;
  await submitAsk();
}

async function explainInvoiceDocument(invoiceId) {
  const item = findInvoiceItem(invoiceId);
  if (!item) return;
  openAskDrawer();
  const reasons = (item.reasons || []).map(r => String(r).replace(/_/g, ' ')).join(', ') || 'audit risk';
  document.getElementById('ask-input').value =
    `Review invoice document ${item.invoice_id} from ${item.vendor_name} for ${fmtCurrency(item.amount)}. Explain the PDF evidence, why it was flagged for ${reasons}, and what the auditor should verify next. Evidence: ${item.detail || 'No detail supplied.'}`;
  await submitAsk();
}

function openInvoiceDocument(invoiceId) {
  const item = findInvoiceItem(invoiceId);
  if (!item) return;
  const win = window.open('', '_blank', 'width=920,height=900');
  if (!win) {
    alert('Allow pop-ups to open the invoice PDF preview.');
    return;
  }
  win.opener = null;
  win.document.open();
  win.document.write(buildInvoiceDocumentHtml(item));
  win.document.close();
  win.focus();
}

function findInvoiceItem(invoiceId) {
  const allItems = [
    ...state.flaggedItems,
    ...(state.report?.items || []),
  ];
  return allItems.find(item => String(item.invoice_id) === String(invoiceId));
}

async function submitAsk() {
  const input = document.getElementById('ask-input');
  const question = input.value.trim();
  if (!question) return;
  input.value = '';
  appendAskMessage('user', question);
  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, run_id: state.runId }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const answer = await res.json();
    appendAskMessage('agent', answer.answer, answer.model);
  } catch (err) {
    appendAskMessage('agent', `I could not answer that request (${err.message}).`, 'error');
  }
}

function appendAskMessage(role, text, model) {
  const el = document.getElementById('ask-messages');
  const div = document.createElement('div');
  div.className = role === 'user'
    ? 'ml-8 rounded-lg bg-brand-500 text-white p-3'
    : 'mr-8 rounded-lg bg-surface-700 border border-surface-600 text-gray-200 p-3';
  div.innerHTML = `
    <p>${escHtml(text)}</p>
    ${role === 'agent' ? `<p class="text-[11px] text-gray-500 mt-2">AI-generated — requires human review · ${escHtml(model || state.appStatus?.gemini_model || 'Gemini 3.x')}</p>` : ''}
  `;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}

// ─────────────────────────────────────────────────────────────────────────────
// Utility helpers
// ─────────────────────────────────────────────────────────────────────────────
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
  const tl = document.getElementById('timeline');
  if (tl) tl.scrollTop = tl.scrollHeight;
}

function resetUI() {
  // Reset state
  state.runId = null;
  state.stepCount = 0;
  state.flaggedItems = [];
  state.atRisk = 0;
  state.rowDecisions = {};
  state.itemStatuses = {};
  state.report = null;
  state.deptCounts = {};
  state.vendorFlags = {};
  state.approvalLog = [];
  state.selectedFindingId = null;
  state._lastPlan = '';
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

  // Reset KPIs
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
