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
  invoiceExplanations: {},
  invoiceExplainLoading: {},
  reportGenerating: false,
  report: null,
  deptCounts: {},
  vendorFlags: {},
  approvalLog: [],
  appStatus: null,
  baselineStats: null,
  currentTab: 'mission',
  selectedFindingId: null,
  selectedGateInvoiceId: null,
  pendingTimelineCards: {},
  activeToolCards: {},
};

// ─────────────────────────────────────────────────────────────────────────────
// Boot / shell
// ─────────────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadStatus();
  loadStats();
  renderFindingsView();
  renderApprovalLog();
  document.getElementById('launch-btn')?.classList.add('timeline-button-attention');
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
  setKpiBaselineMode();
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

  document.getElementById('onboarding-hint')?.remove();
  resetUI();
  showPendingTimelineCard('mission-start', {
    label: 'Starting',
    agent: 'FaultAuditCoordinatorAgent',
    toolLabel: 'Google ADK multi-agent',
    message: 'Connecting to the multi-agent runtime',
  });

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
    updatePendingTimelineCard('mission-start', {
      label: 'Planning',
      agent: 'MissionPlanningAgent',
      toolLabel: state.appStatus?.gemini_model || 'Gemini 3.x',
      message: 'Gemini is drafting the first audit plan',
    });
    startSSE(run_id);
  } catch (err) {
    removePendingTimelineCard('mission-start');
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
