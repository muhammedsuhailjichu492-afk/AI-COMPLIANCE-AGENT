/* ==========================================================================
   Ledger — frontend application logic (vanilla JS, no framework/build step)
   Talks to the FastAPI backend mounted at the same origin under /api/*.
   ========================================================================== */

const API_BASE = "/api";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  policies: [],
  documents: [],
  reports: [],
  analyzeTargetId: null,
  activeReportId: null,
};

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
function $(sel, root = document) { return root.querySelector(sel); }
function $all(sel, root = document) { return [...root.querySelectorAll(sel)]; }

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("is-error", isError);
  toast.classList.add("is-visible");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.remove("is-visible"), 3200);
}

function fmtDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) +
    " · " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function riskBadgeClass(level) {
  return { low: "badge--low", medium: "badge--medium", high: "badge--high", critical: "badge--critical" }[level] || "badge--medium";
}

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  const contentType = res.headers.get("content-type") || "";
  return contentType.includes("application/json") ? res.json() : res.text();
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
function initNav() {
  $all(".nav-item").forEach(btn => {
    btn.addEventListener("click", () => setActiveView(btn.dataset.view));
  });
}

function setActiveView(view) {
  $all(".nav-item").forEach(b => b.classList.toggle("is-active", b.dataset.view === view));
  $all(".view").forEach(v => v.classList.toggle("is-active", v.id === `view-${view}`));
}

// ---------------------------------------------------------------------------
// Health check
// ---------------------------------------------------------------------------
async function checkHealth() {
  const dot = $("#apiStatusDot");
  const text = $("#apiStatusText");
  try {
    const health = await api("/health");
    dot.classList.add("online");
    dot.classList.remove("offline");
    text.textContent = health.llm_configured
      ? "Backend connected · LLM reasoning enabled"
      : "Backend connected · local heuristics mode (no API key)";
  } catch (e) {
    dot.classList.add("offline");
    text.textContent = "Backend unreachable";
  }
}

// ---------------------------------------------------------------------------
// Uploaders (policy + document) — shared drag/drop + click-to-browse wiring
// ---------------------------------------------------------------------------
function initUploader(containerId, inputId, kind, onDone) {
  const container = $(`#${containerId}`);
  const input = $(`#${inputId}`);

  container.addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    if (input.files.length) uploadFile(input.files[0], kind, onDone);
    input.value = "";
  });

  ["dragenter", "dragover"].forEach(evt =>
    container.addEventListener(evt, e => { e.preventDefault(); container.classList.add("is-dragover"); })
  );
  ["dragleave", "drop"].forEach(evt =>
    container.addEventListener(evt, e => { e.preventDefault(); container.classList.remove("is-dragover"); })
  );
  container.addEventListener("drop", e => {
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file, kind, onDone);
  });
}

async function uploadFile(file, kind, onDone) {
  const formData = new FormData();
  formData.append("file", file);
  showToast(`Processing ${file.name}…`);
  try {
    await api(`/upload/${kind}`, { method: "POST", body: formData });
    showToast(`${file.name} indexed successfully.`);
    await refreshAll();
    if (onDone) onDone();
  } catch (e) {
    showToast(`Upload failed: ${e.message}`, true);
  }
}

// ---------------------------------------------------------------------------
// Loading data
// ---------------------------------------------------------------------------
async function loadPolicies() {
  state.policies = await api("/files/policy");
  renderPolicyTable();
}

async function loadDocuments() {
  state.documents = await api("/files/document");
  renderDocumentTable();
  renderAskDocSelect();
}

async function loadReports() {
  state.reports = await api("/reports");
  renderReportsList();
  renderDashboardReports();
}

async function refreshAll() {
  await Promise.all([loadPolicies(), loadDocuments(), loadReports()]);
  renderStats();
}

// ---------------------------------------------------------------------------
// Rendering: Policy table
// ---------------------------------------------------------------------------
function renderPolicyTable() {
  const tbody = $("#policyTable tbody");
  tbody.innerHTML = "";
  $("#policyEmptyNote").style.display = state.policies.length ? "none" : "block";

  state.policies.forEach(p => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="file-name">${escapeHtml(p.filename)}</td>
      <td>${p.chunks}</td>
      <td>${fmtDate(p.uploaded_at)}</td>
      <td><button class="link-btn danger" data-id="${p.id}">Remove</button></td>
    `;
    tr.querySelector(".link-btn").addEventListener("click", () => deleteFile("policy", p.id));
    tbody.appendChild(tr);
  });
}

// ---------------------------------------------------------------------------
// Rendering: Document table
// ---------------------------------------------------------------------------
function renderDocumentTable() {
  const tbody = $("#documentTable tbody");
  tbody.innerHTML = "";
  $("#documentEmptyNote").style.display = state.documents.length ? "none" : "block";

  state.documents.forEach(d => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="file-name">${escapeHtml(d.filename)}</td>
      <td>${d.chunks}</td>
      <td>${fmtDate(d.uploaded_at)}</td>
      <td><button class="link-btn analyze-btn" data-id="${d.id}" data-name="${escapeHtml(d.filename)}">Analyze</button></td>
      <td><button class="link-btn danger" data-id="${d.id}">Remove</button></td>
    `;
    tr.querySelector(".analyze-btn").addEventListener("click", () => openAnalyzeModal(d.id, d.filename));
    tr.querySelector(".danger").addEventListener("click", () => deleteFile("document", d.id));
    tbody.appendChild(tr);
  });
}

async function deleteFile(kind, id) {
  if (!confirm("Remove this file and its indexed chunks?")) return;
  try {
    await api(`/files/${kind}/${id}`, { method: "DELETE" });
    showToast("Removed.");
    await refreshAll();
  } catch (e) {
    showToast(`Could not remove file: ${e.message}`, true);
  }
}

// ---------------------------------------------------------------------------
// Analyze modal
// ---------------------------------------------------------------------------
function openAnalyzeModal(docId, docName) {
  state.analyzeTargetId = docId;
  $("#analyzeModalDocName").textContent = docName;
  $("#focusQueryInput").value = "";
  $("#analyzeModalBackdrop").classList.add("is-open");
}

function closeAnalyzeModal() {
  $("#analyzeModalBackdrop").classList.remove("is-open");
  state.analyzeTargetId = null;
}

async function runAnalysis() {
  if (!state.analyzeTargetId) return;
  const btn = $("#runAnalysisBtn");
  const btnText = $("#runAnalysisBtnText");
  btn.disabled = true;
  btnText.textContent = "Analyzing…";

  try {
    const report = await api("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: state.analyzeTargetId,
        focus_query: $("#focusQueryInput").value.trim() || null,
      }),
    });
    showToast("Risk report generated.");
    closeAnalyzeModal();
    await loadReports();
    setActiveView("reports");
    selectReport(report.id);
  } catch (e) {
    showToast(`Analysis failed: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btnText.textContent = "Run analysis";
  }
}

// ---------------------------------------------------------------------------
// Rendering: Reports list + detail
// ---------------------------------------------------------------------------
function renderReportsList() {
  const container = $("#reportsList");
  container.innerHTML = "";
  $("#reportsEmptyNote").style.display = state.reports.length ? "none" : "block";

  state.reports.forEach(r => {
    const row = document.createElement("div");
    row.className = "report-row" + (r.id === state.activeReportId ? " is-active" : "");
    row.innerHTML = `
      <div class="report-row-top">
        <span class="report-row-name">${escapeHtml(r.document_name)}</span>
        <span class="badge ${riskBadgeClass(r.risk_level)}">${r.risk_level}</span>
      </div>
      <span class="report-row-date">${fmtDate(r.generated_at)} · score ${r.overall_compliance_score}</span>
    `;
    row.addEventListener("click", () => selectReport(r.id));
    container.appendChild(row);
  });
}

function renderDashboardReports() {
  const container = $("#dashboardReports");
  const recent = state.reports.slice(0, 5);
  if (!recent.length) {
    container.innerHTML = `<p class="empty-note">No reports yet. Upload a policy set and a document, then run an analysis.</p>`;
    return;
  }
  container.innerHTML = "";
  recent.forEach(r => {
    const row = document.createElement("div");
    row.className = "report-row";
    row.innerHTML = `
      <div class="report-row-top">
        <span class="report-row-name">${escapeHtml(r.document_name)}</span>
        <span class="badge ${riskBadgeClass(r.risk_level)}">${r.risk_level}</span>
      </div>
      <span class="report-row-date">${fmtDate(r.generated_at)} · score ${r.overall_compliance_score}</span>
    `;
    row.addEventListener("click", () => { setActiveView("reports"); selectReport(r.id); });
    container.appendChild(row);
  });
}

function selectReport(id) {
  state.activeReportId = id;
  renderReportsList();
  const report = state.reports.find(r => r.id === id);
  if (!report) return;
  renderReportDetail(report);
}

function renderReportDetail(r) {
  const panel = $("#reportDetailPanel");

  const gapsHtml = r.gaps.length
    ? r.gaps.map((g, i) => `
      <div class="gap-item">
        <span class="gap-index">${String(i + 1).padStart(2, "0")}</span>
        <div>
          <div class="gap-issue">${escapeHtml(g.issue)}</div>
          <div class="gap-meta"><strong>Severity:</strong> ${escapeHtml(g.severity)} &nbsp;·&nbsp;
            <strong>Related policy:</strong> ${escapeHtml(g.related_policy_snippet)}</div>
          <div class="gap-recommendation">${escapeHtml(g.recommendation)}</div>
        </div>
      </div>
    `).join("")
    : `<p class="empty-note" style="padding:0;">No gaps identified.</p>`;

  const strengthsHtml = r.strengths.length
    ? `<ul class="strength-list">${r.strengths.map(s => `<li>${escapeHtml(s)}</li>`).join("")}</ul>`
    : `<p class="empty-note" style="padding:0;">No strengths noted.</p>`;

  panel.innerHTML = `
    <div class="report-detail">
      <div class="report-detail-head">
        <div class="report-detail-title">
          <h3>${escapeHtml(r.document_name)}</h3>
          <p>${fmtDate(r.generated_at)}</p>
        </div>
        <div class="score-block">
          <div class="score-value">${r.overall_compliance_score}</div>
          <div class="score-caption">/ 100 · <span class="badge ${riskBadgeClass(r.risk_level)}">${r.risk_level}</span></div>
        </div>
      </div>

      <p class="report-summary">${escapeHtml(r.summary)}</p>

      <div class="report-block">
        <h4 class="report-section-title">Compliance gaps (${r.gaps.length})</h4>
        ${gapsHtml}
      </div>

      <div class="report-block">
        <h4 class="report-section-title">Strengths</h4>
        ${strengthsHtml}
      </div>

      <div class="report-refs">
        Policies referenced: ${r.policies_referenced.length ? escapeHtml(r.policies_referenced.join(", ")) : "none matched"}
      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------
function renderStats() {
  $("#statPolicyCount").textContent = state.policies.length;
  $("#statDocCount").textContent = state.documents.length;
  $("#statReportCount").textContent = state.reports.length;

  if (state.reports.length) {
    const latest = state.reports[0];
    $("#statLatestRisk").textContent = latest.risk_level;
    $("#statLatestDoc").textContent = latest.document_name;
  } else {
    $("#statLatestRisk").textContent = "—";
    $("#statLatestDoc").textContent = "no reports yet";
  }
}

// ---------------------------------------------------------------------------
// Ask
// ---------------------------------------------------------------------------
function renderAskDocSelect() {
  const select = $("#askDocSelect");
  const current = select.value;
  select.innerHTML = `<option value="">Policy library only</option>` +
    state.documents.map(d => `<option value="${d.id}">${escapeHtml(d.filename)}</option>`).join("");
  select.value = current;
}

async function askQuestion() {
  const question = $("#askQuestionInput").value.trim();
  if (!question) return;
  const btn = $("#askBtn");
  const btnText = $("#askBtnText");
  btn.disabled = true;
  btnText.textContent = "Thinking…";
  $("#askAnswer").textContent = "";

  try {
    const result = await api("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        document_id: $("#askDocSelect").value || null,
      }),
    });
    $("#askAnswer").textContent = result.answer;
  } catch (e) {
    showToast(`Could not answer: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btnText.textContent = "Ask";
  }
}

// ---------------------------------------------------------------------------
// Misc
// ---------------------------------------------------------------------------
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  initNav();
  initUploader("policyUploader", "policyFileInput", "policy");
  initUploader("documentUploader", "documentFileInput", "document");

  $("#analyzeModalClose").addEventListener("click", closeAnalyzeModal);
  $("#analyzeModalBackdrop").addEventListener("click", e => {
    if (e.target.id === "analyzeModalBackdrop") closeAnalyzeModal();
  });
  $("#runAnalysisBtn").addEventListener("click", runAnalysis);
  $("#askBtn").addEventListener("click", askQuestion);

  await checkHealth();
  await refreshAll();
});
