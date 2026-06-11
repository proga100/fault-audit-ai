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
