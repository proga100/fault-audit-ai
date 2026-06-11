// ─────────────────────────────────────────────────────────────────────────────
// Flagged items table (Gate 2)
// ─────────────────────────────────────────────────────────────────────────────
function renderFlaggedTable() {
  const tbody = document.getElementById('flagged-items-tbody');
  tbody.innerHTML = '';

  state.flaggedItems.forEach(item => {
    const tr = document.createElement('tr');
    const active = state.selectedGateInvoiceId === item.invoice_id ? 'active' : '';
    tr.className = `gate-review-row finding-row ${active} bg-surface-800 hover:bg-surface-700/50 transition-colors`;
    tr.dataset.invoiceId = item.invoice_id;
    tr.tabIndex = 0;
    tr.title = 'Open invoice review';
    tr.onclick = () => openMissionInvoiceReview(item.invoice_id);
    tr.onkeydown = (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openMissionInvoiceReview(item.invoice_id);
      }
    };

    const reasons = (item.reasons || []).map(r =>
      `<span class="reason-chip ${r}">${r.replace(/_/g,' ')}</span>`
    ).join(' ');
    const shortId = escHtml(String(item.invoice_id).slice(0, 8));
    const decision = state.rowDecisions[item.invoice_id] || 'approve';

    tr.innerHTML = `
      <td class="px-2 py-2">
        <input type="checkbox" class="item-cb rounded border-surface-500" data-id="${escAttr(item.invoice_id)}" ${decision === 'approve' ? 'checked' : ''} onclick="event.stopPropagation()" onchange="handleCbChange(this)" />
      </td>
      <td class="px-2 py-2 text-xs text-gray-200 max-w-[130px] truncate" title="${escHtml(item.vendor_name)}">
        ${escHtml(item.vendor_name)}
        <span class="block font-mono text-[10px] text-gray-500">${shortId} · ${escHtml(item.department)}</span>
      </td>
      <td class="px-2 py-2 text-xs text-right font-mono font-semibold text-accent-red whitespace-nowrap">${fmtCurrency(item.amount)}</td>
      <td class="px-2 py-2"><div class="flex flex-wrap gap-1 max-w-[150px]">${reasons}</div></td>
      <td class="px-2 py-2 text-center">
        <div class="flex gap-1 justify-center">
          <button class="row-decision-btn approve ${decision === 'approve' ? 'active' : ''}" data-id="${escAttr(item.invoice_id)}" data-action="approve" onclick="event.stopPropagation(); setRowDecision(this,'approve')">✓</button>
          <button class="row-decision-btn reject ${decision === 'reject' ? 'active' : ''}" data-id="${escAttr(item.invoice_id)}" data-action="reject" onclick="event.stopPropagation(); setRowDecision(this,'reject')">✕</button>
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
  if (state.selectedGateInvoiceId === id) renderMissionInvoiceReview(findInvoiceItem(id));
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
  if (state.selectedGateInvoiceId === id) renderMissionInvoiceReview(findInvoiceItem(id));
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

function openMissionInvoiceReview(invoiceId) {
  const item = findInvoiceItem(invoiceId);
  if (!item) return;
  state.selectedGateInvoiceId = item.invoice_id;
  renderFlaggedTable();
  renderMissionInvoiceReview(item);
  document.getElementById('mission-dashboard-header')?.classList.add('hidden');
  document.getElementById('mission-dashboard-content')?.classList.add('hidden');
  const review = document.getElementById('mission-invoice-review');
  review?.classList.remove('hidden');
  review?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function closeMissionInvoiceReview() {
  state.selectedGateInvoiceId = null;
  document.getElementById('mission-invoice-review')?.classList.add('hidden');
  document.getElementById('mission-dashboard-header')?.classList.remove('hidden');
  document.getElementById('mission-dashboard-content')?.classList.remove('hidden');
  renderFlaggedTable();
}

function renderMissionInvoiceReview(item) {
  const el = document.getElementById('mission-invoice-review');
  if (!el || !item) return;
  const reasons = (item.reasons || []).map(r => `<span class="reason-chip ${escHtml(r)}">${escHtml(String(r).replace(/_/g,' '))}</span>`).join(' ');
  const detailLines = String(item.detail || 'No detail supplied.').split(';').map(s => s.trim()).filter(Boolean);
  const decision = state.rowDecisions[item.invoice_id] || 'approve';
  const previewHtml = escAttr(buildInvoiceDocumentHtml(item, { embedded: true }));
  const explanation = renderInvoiceExplanationBlock(item);
  el.innerHTML = `
    <div class="rounded-xl bg-surface-800 border border-surface-600 overflow-hidden fade-in">
      <div class="px-4 py-3 border-b border-surface-600 bg-surface-700/50 flex items-center gap-3">
        <button onclick="closeMissionInvoiceReview()" class="w-8 h-8 rounded-md border border-surface-500 bg-surface-800 text-gray-300 hover:text-white hover:border-brand-400 transition-colors" title="Back to dashboard" aria-label="Back to dashboard">←</button>
        <div>
          <p class="text-xs text-gray-500 uppercase tracking-wide">Invoice Review</p>
          <p class="text-sm text-gray-200 font-mono">${escHtml(item.invoice_id)}</p>
        </div>
        <span class="ml-auto status-pill ${decision === 'approve' ? 'approved' : 'rejected'}">${decision === 'approve' ? 'Queued to approve' : 'Queued to reject'}</span>
      </div>
      <div class="p-4 space-y-4">
        <div class="grid grid-cols-2 gap-3">
          <div class="rounded-lg bg-surface-700/40 border border-surface-600 p-3">
            <p class="text-xs text-gray-500 uppercase tracking-wide">Vendor</p>
            <p class="text-sm text-gray-200 mt-1">${escHtml(item.vendor_name)}</p>
          </div>
          <div class="rounded-lg bg-surface-700/40 border border-surface-600 p-3">
            <p class="text-xs text-gray-500 uppercase tracking-wide">Amount</p>
            <p class="text-sm font-mono text-accent-red mt-1">${fmtCurrency(item.amount)}</p>
          </div>
          <div class="rounded-lg bg-surface-700/40 border border-surface-600 p-3">
            <p class="text-xs text-gray-500 uppercase tracking-wide">Department</p>
            <p class="text-sm text-gray-200 mt-1">${escHtml(item.department)}</p>
          </div>
          <div class="rounded-lg bg-surface-700/40 border border-surface-600 p-3">
            <p class="text-xs text-gray-500 uppercase tracking-wide">Decision</p>
            <div class="mt-2 flex gap-2">
              <button class="row-decision-btn approve ${decision === 'approve' ? 'active' : ''}" onclick="setMissionInvoiceDecision('${escAttr(item.invoice_id)}','approve')">✓ Approve</button>
              <button class="row-decision-btn reject ${decision === 'reject' ? 'active' : ''}" onclick="setMissionInvoiceDecision('${escAttr(item.invoice_id)}','reject')">✕ Reject</button>
            </div>
          </div>
        </div>
        <div class="flex flex-wrap gap-1">${reasons}</div>
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
        </div>
        <div class="grid grid-cols-2 gap-2">
          <button onclick="explainInvoiceDocument('${escAttr(item.invoice_id)}')" ${state.invoiceExplainLoading[item.invoice_id] ? 'disabled' : ''} class="py-2 rounded-md bg-brand-500 hover:bg-brand-400 disabled:opacity-60 disabled:cursor-wait text-white text-sm font-semibold">
            ${state.invoiceExplainLoading[item.invoice_id] ? 'Explaining…' : 'Explain with AI'}
          </button>
          <button onclick="openInvoiceDocument('${escAttr(item.invoice_id)}')" class="py-2 rounded-md bg-surface-700 border border-surface-500 hover:bg-surface-600 text-gray-200 text-sm font-semibold">Open in Tab</button>
        </div>
        ${explanation}
      </div>
    </div>
  `;
}

function renderInvoiceExplanationBlock(item) {
  const loading = state.invoiceExplainLoading[item.invoice_id];
  const explanation = state.invoiceExplanations[item.invoice_id];
  if (loading) {
    return `
      <div class="rounded-lg border border-brand-500/40 bg-brand-900/20 p-4">
        <div class="flex items-center gap-2 text-sm font-semibold text-brand-200">
          <span class="pending-step step-badge bg-brand-500/15"></span>
          AuditAssistantAgent
          <span class="tool-chip text-[10px]">${escHtml(state.appStatus?.gemini_model || 'Gemini 3.x')}</span>
        </div>
        <p class="mt-2 text-sm text-gray-300">
          Reading invoice evidence and preparing auditor guidance<span class="typing-dots" aria-hidden="true"><span></span><span></span><span></span></span>
        </p>
      </div>
    `;
  }
  if (!explanation) {
    return `
      <div class="rounded-lg border border-surface-600 bg-surface-700/30 p-4">
        <p class="text-xs text-gray-500 uppercase tracking-wide">AI Explanation</p>
        <p class="mt-2 text-sm text-gray-400">Use Explain with AI to generate a grounded invoice review from the evidence above.</p>
      </div>
    `;
  }
  return `
    <div class="rounded-lg border border-brand-500/40 bg-brand-900/20 p-4">
      <div class="flex items-center gap-2">
        <p class="text-xs text-brand-200 uppercase tracking-wide font-semibold">AI Explanation</p>
        <span class="ml-auto text-[11px] text-gray-500">${escHtml(explanation.model || state.appStatus?.gemini_model || 'Gemini 3.x')}</span>
      </div>
      <p class="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-200">${escHtml(explanation.answer)}</p>
      <p class="mt-3 text-[11px] text-gray-500">AI-generated — requires human review before approval.</p>
    </div>
  `;
}

function setMissionInvoiceDecision(invoiceId, decision) {
  state.rowDecisions[invoiceId] = decision;
  const row = Array.from(document.querySelectorAll('#flagged-items-tbody tr'))
    .find(tr => tr.dataset.invoiceId === String(invoiceId));
  if (row) {
    const cb = row.querySelector('.item-cb');
    if (cb) cb.checked = decision === 'approve';
    row.querySelectorAll('.row-decision-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.action === decision);
    });
  }
  renderMissionInvoiceReview(findInvoiceItem(invoiceId));
}

// ─────────────────────────────────────────────────────────────────────────────
// Approval submissions
// ─────────────────────────────────────────────────────────────────────────────
async function approvePlan() {
  const edited = document.getElementById('plan-edit-input')?.value.trim() || '';
  const original = state._lastPlan || '';
  const changed = edited && edited !== original;
  recordApproval('plan', 'approved', changed ? 'Edited plan approved' : 'Plan approved');
  setStatusBadge('executing', 'Continuing…');
  document.getElementById('gate-plan').classList.add('hidden');
  showPendingTimelineCard('plan-approved', {
    label: 'Continuing',
    agent: 'MissionPlanningAgent',
    toolLabel: state.appStatus?.gemini_model || 'Gemini 3.x',
    message: 'Plan approved. Agents are preparing evidence queries',
  });
  await postApproval({ gate: 'plan', approved: true, ...(changed ? { edited_plan: edited } : {}) });
}
async function rejectPlan() {
  recordApproval('plan', 'rejected', 'Plan rejected');
  showPendingTimelineCard('plan-rejected', {
    label: 'Sending',
    agent: 'HumanApprovalAgent',
    toolLabel: 'Approval gate',
    message: 'Submitting plan rejection',
  });
  await postApproval({ gate: 'plan', approved: false });
  removePendingTimelineCard('plan-rejected');
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
  document.getElementById('gate-action').classList.add('hidden');
  showPendingTimelineCard('action-approved', {
    label: 'Writing',
    agent: 'AuditTrailAgent',
    toolLabel: 'MongoDB Atlas · gated write',
    message: 'Writing approved findings and preparing the report',
  });
  await postApproval({ gate: 'action', approved: true, approved_ids: approvedIds, rejected_ids: rejectedIds });
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
