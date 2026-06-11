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
  card.className = `timeline-card type-${type} timeline-card-enter rounded-lg bg-surface-800 border border-surface-600 p-3 pl-4`;

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

  document.querySelectorAll('.timeline-card.is-latest').forEach(el => el.classList.remove('is-latest'));
  card.classList.add('is-latest');
  document.getElementById('timeline').appendChild(card);
  requestAnimationFrame(() => focusTimelineElement(card, { force: true, block: 'center' }));
  setTimeout(() => focusTimelineElement(card, { force: true, block: 'center' }), 180);
}
