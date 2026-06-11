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
  removePendingTimelineCard('mission-start');
  setStatusBadge('planning', 'Plan received');
  const plan = evt.data?.plan || evt.data?.text || JSON.stringify(evt.data);
  appendTimelineCard('plan', { plan });
}

function handleToolCall(evt) {
  removePendingTimelineCard('plan-approved');
  setStatusBadge('executing', 'Executing…');
  const card = appendTimelineCard('tool_call', evt.data);
  markToolCallRunning(evt.data, card);
}

function handleToolResult(evt) {
  markToolCallComplete(evt.data);
  appendTimelineCard('tool_result', evt.data);
}

function handleProposal(evt) {
  removePendingTimelineCard('plan-approved');
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

  setKpiAuditMode();
  animateKPICurrency('kpi-at-risk', state.atRisk);
  animateKPI('kpi-flags', total);
  const vendorsChecked = evt.data?.vendors_checked
    ?? evt.data?.vendor_count
    ?? state.baselineStats?.vendors
    ?? Object.keys(state.vendorFlags).length
    ?? 0;
  animateKPI('kpi-vendors', vendorsChecked);
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
  if (gate === 'plan') removePendingTimelineCard('mission-start');
  if (gate === 'action') removePendingTimelineCard('plan-approved');
  setStatusBadge('awaiting', `Awaiting ${gate} approval`);
  appendTimelineCard('awaiting_approval', evt.data);

  if (gate === 'plan') {
    const plan = evt.data?.plan || state._lastPlan || '';
    document.getElementById('plan-edit-input').value = plan;
    document.getElementById('plan-edit-area').classList.remove('hidden');
    const gateEl = document.getElementById('gate-plan');
    gateEl.classList.remove('hidden');
    focusTimelineGate(gateEl);
  } else if (gate === 'action') {
    renderFlaggedTable();
    const gateEl = document.getElementById('gate-action');
    gateEl.classList.remove('hidden');
    focusTimelineGate(gateEl);
  }
}

function handleWritten(evt) {
  removePendingTimelineCard('action-approved');
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
  removePendingTimelineCard('action-approved');
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
  clearPendingTimelineCards();
  setStatusBadge('error', 'Error');
  appendTimelineCard('error', evt.data);
  const btn = document.getElementById('launch-btn');
  btn.disabled = false;
  btn.innerHTML = 'Run Audit Mission';
}

function handleDone(evt) {
  clearPendingTimelineCards();
  setStatusBadge('done', 'Done');
  appendTimelineCard('done', evt.data);
  if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
  const btn = document.getElementById('launch-btn');
  btn.disabled = false;
  btn.innerHTML = 'Run Audit Mission';
}
