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
  if (state.selectedFindingId === item.invoice_id) renderFindingDetail(item);
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
  const pendingId = `ask-agent-${Date.now()}`;
  const toolData = {
    tool: 'ask_audit_agent',
    agent: 'AuditAssistantAgent',
    tool_label: state.appStatus?.gemini_model || 'Gemini 3.x',
    args: {
      question: question.slice(0, 140),
      run_id: state.runId || 'none',
    },
  };
  const pendingMessage = appendAskPendingMessage();
  showPendingTimelineCard(pendingId, {
    label: 'Thinking',
    agent: 'AuditAssistantAgent',
    toolLabel: state.appStatus?.gemini_model || 'Gemini 3.x',
    message: 'Interpreting the audit question and loading available context',
  });
  const card = appendTimelineCard('tool_call', toolData);
  markToolCallRunning(toolData, card);
  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, run_id: state.runId }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const answer = await res.json();
    removePendingTimelineCard(pendingId);
    markToolCallComplete(toolData);
    appendTimelineCard('tool_result', {
      tool: 'ask_audit_agent',
      agent: 'AuditAssistantAgent',
      tool_label: answer.model || state.appStatus?.gemini_model || 'Gemini 3.x',
      count: 1,
    });
    pendingMessage?.remove();
    appendAskMessage('agent', answer.answer, answer.model);
  } catch (err) {
    markAskToolFailed(toolData);
    removePendingTimelineCard(pendingId);
    appendTimelineCard('error', {
      agent: 'AuditAssistantAgent',
      tool_label: 'Ask Audit Agent',
      error: err.message,
    });
    pendingMessage?.remove();
    appendAskMessage('agent', `I could not answer that request (${err.message}).`, 'error');
  }
}

function appendAskMessage(role, text, model) {
  const el = document.getElementById('ask-messages');
  const div = document.createElement('div');
  div.className = role === 'user'
    ? 'ml-8 rounded-lg bg-brand-500 text-white p-3 ask-user-message'
    : 'mr-8 rounded-lg bg-surface-700 border border-surface-600 text-gray-200 p-4 ask-agent-message';
  if (role === 'agent') {
    div.innerHTML = `
      <div class="flex items-center gap-2 mb-3">
        <span class="agent-chip text-[10px]">AuditAssistantAgent</span>
        <span class="tool-chip text-[10px]">${escHtml(model || state.appStatus?.gemini_model || 'Gemini 3.x')}</span>
      </div>
      <div class="ask-answer space-y-3">${formatAskAnswer(text)}</div>
      <p class="text-[11px] text-gray-500 mt-3">AI-generated — requires human review</p>
    `;
  } else {
    div.innerHTML = `<p class="leading-6">${escHtml(text)}</p>`;
  }
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}

function appendAskPendingMessage() {
  const el = document.getElementById('ask-messages');
  const div = document.createElement('div');
  div.className = 'mr-8 rounded-lg border border-brand-500/40 bg-brand-900/20 text-gray-200 p-4 ask-agent-message';
  div.innerHTML = `
    <div class="flex items-center gap-2">
      <span class="pending-step step-badge bg-brand-500/15"></span>
      <span class="agent-chip text-[10px]">AuditAssistantAgent</span>
      <span class="tool-chip text-[10px]">${escHtml(state.appStatus?.gemini_model || 'Gemini 3.x')}</span>
    </div>
    <p class="mt-3 text-sm text-gray-300">
      Analyzing audit context<span class="typing-dots" aria-hidden="true"><span></span><span></span><span></span></span>
    </p>
  `;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
  return div;
}

function markAskToolFailed(toolData) {
  const activeKey = toolRunKey(toolData);
  const activeCard = state.activeToolCards?.[activeKey];
  if (!activeCard) return;
  delete state.activeToolCards[activeKey];
  activeCard.classList.remove('tool-call-running');
  const status = activeCard.querySelector('[data-tool-call-status]');
  if (status) status.textContent = 'Failed';
}

function formatAskAnswer(text) {
  const raw = String(text || '').trim();
  if (!raw) return '<p class="text-sm text-gray-400">No answer returned.</p>';

  const parts = raw.split(/(\*\*[^*]+?\*\*)/g).filter(Boolean);
  if (parts.some(part => part.startsWith('**') && part.endsWith('**'))) {
    let html = '';
    let intro = '';
    for (let i = 0; i < parts.length; i += 1) {
      const part = parts[i];
      if (part.startsWith('**') && part.endsWith('**')) {
        if (intro.trim()) {
          html += formatAskParagraphs(intro);
          intro = '';
        }
        const title = part.slice(2, -2).replace(/:$/, '').trim();
        const body = parts[i + 1] && !parts[i + 1].startsWith('**') ? parts[++i] : '';
        html += `
          <section class="ask-answer-section">
            <h3>${escHtml(title)}</h3>
            ${formatAskParagraphs(body)}
          </section>
        `;
      } else {
        intro += part;
      }
    }
    if (intro.trim()) html += formatAskParagraphs(intro);
    return html;
  }
  return formatAskParagraphs(raw);
}

function formatAskParagraphs(text) {
  const blocks = String(text || '')
    .replace(/\r/g, '')
    .split(/\n{2,}/)
    .map(block => block.trim())
    .filter(Boolean);
  if (!blocks.length) return '';
  return blocks.map(block => {
    const lines = block.split('\n').map(line => line.trim()).filter(Boolean);
    const bulletLines = lines.filter(line => /^[-•*]\s+/.test(line));
    if (bulletLines.length === lines.length) {
      return `<ul>${bulletLines.map(line => `<li>${escHtml(line.replace(/^[-•*]\s+/, ''))}</li>`).join('')}</ul>`;
    }
    return `<p>${escHtml(lines.join(' '))}</p>`;
  }).join('');
}

// ─────────────────────────────────────────────────────────────────────────────
// Utility helpers
