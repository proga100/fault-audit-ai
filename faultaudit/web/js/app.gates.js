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
