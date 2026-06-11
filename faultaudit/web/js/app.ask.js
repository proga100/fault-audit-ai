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
  const reasons = (item.reasons || []).map(r => String(r).replace(/_/g, ' ')).join(', ') || 'audit risk';
  const question = `Explain invoice ${item.invoice_id}: why it was flagged for ${reasons}, what evidence supports it, and what the auditor should verify next.`;
  const context = {
    invoice_id: item.invoice_id,
    vendor_name: item.vendor_name,
    department: item.department,
    amount: item.amount,
    reasons: item.reasons || [],
    detail: item.detail || '',
  };
  const pendingId = `invoice-explain-${item.invoice_id}`;
  const toolData = {
    tool: 'invoice_explanation',
    agent: 'AuditAssistantAgent',
    tool_label: state.appStatus?.gemini_model || 'Gemini 3.x',
    args: {
      invoice_id: item.invoice_id,
      vendor_name: item.vendor_name,
      reasons: context.reasons,
    },
  };

  state.invoiceExplainLoading[item.invoice_id] = true;
  delete state.invoiceExplanations[item.invoice_id];
  renderMissionInvoiceReview(item);
  showPendingTimelineCard(pendingId, {
    label: 'Analyzing',
    agent: 'AuditAssistantAgent',
    toolLabel: state.appStatus?.gemini_model || 'Gemini 3.x',
    message: `Reading invoice ${item.invoice_id} evidence`,
  });
  const card = appendTimelineCard('tool_call', toolData);
  markToolCallRunning(toolData, card);

  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, run_id: state.runId, invoice_context: context }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const answer = await res.json();
    state.invoiceExplanations[item.invoice_id] = {
      answer: answer.answer,
      model: answer.model,
    };
    removePendingTimelineCard(pendingId);
    markToolCallComplete(toolData);
    appendTimelineCard('tool_result', {
      tool: 'invoice_explanation',
      agent: 'AuditAssistantAgent',
      tool_label: answer.model || state.appStatus?.gemini_model || 'Gemini 3.x',
      count: 1,
    });
  } catch (err) {
    const activeKey = toolRunKey(toolData);
    const activeCard = state.activeToolCards?.[activeKey];
    if (activeCard) {
      delete state.activeToolCards[activeKey];
      activeCard.classList.remove('tool-call-running');
      const status = activeCard.querySelector('[data-tool-call-status]');
      if (status) status.textContent = 'Failed';
    }
    state.invoiceExplanations[item.invoice_id] = {
      answer: `I could not explain this invoice right now (${err.message}).`,
      model: 'error',
    };
    removePendingTimelineCard(pendingId);
    appendTimelineCard('error', {
      agent: 'AuditAssistantAgent',
      tool_label: 'Invoice explanation',
      error: err.message,
    });
  } finally {
    state.invoiceExplainLoading[item.invoice_id] = false;
    renderMissionInvoiceReview(findInvoiceItem(invoiceId));
    if (state.selectedFindingId === item.invoice_id) renderFindingDetail(item);
  }
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
