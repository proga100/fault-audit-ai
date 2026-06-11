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
