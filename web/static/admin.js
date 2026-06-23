const ADMIN_TOKEN_KEY = "shipvoice.admin_token";

const state = {
  overview: null,
  records: [],
  history: [],
  selectedId: "",
  activeTag: "",
  runs: [],
  selectedRunId: "",
  jobs: [],
  currentJobId: "",
  currentJobStatus: "",
  datasets: [],
  selectedDataset: "",
  config: null,
  authStatus: null,
  session: null
};

let jobPollTimer = 0;

const $ = (id) => document.getElementById(id);

function init() {
  $("adminLoginButton").addEventListener("click", () => {
    void loginAdmin();
  });
  $("adminLogoutButton").addEventListener("click", () => logoutAdmin());
  $("refreshAdminButton").addEventListener("click", () => {
    void refreshAll();
  });
  $("reindexButton").addEventListener("click", () => {
    void rebuildIndex();
  });
  $("reloadEvalButton").addEventListener("click", () => {
    void reloadEvaluations();
  });
  $("runEvalButton").addEventListener("click", () => {
    void runEvaluations();
  });
  $("exportRunsJsonlButton").addEventListener("click", () => {
    void exportRuns("jsonl");
  });
  $("exportRunsCsvButton").addEventListener("click", () => {
    void exportRuns("csv");
  });
  $("cleanupRunsButton").addEventListener("click", () => {
    void cleanupRuns();
  });
  $("newRecordButton").addEventListener("click", () => prepareNewRecord());
  $("knowledgeForm").addEventListener("submit", (event) => {
    event.preventDefault();
    void saveRecord();
  });
  $("deleteRecordButton").addEventListener("click", () => {
    void deleteRecord();
  });
  $("configForm").addEventListener("submit", (event) => {
    event.preventDefault();
    void saveConfig();
  });
  $("reloadConfigButton").addEventListener("click", () => {
    void loadConfigView();
  });
  $("knowledgeSearch").addEventListener("input", debounce(() => loadKnowledge(), 200));
  $("knowledgeStatusFilter").addEventListener("change", () => {
    void loadKnowledge();
  });
  $("runSearch").addEventListener("input", debounce(() => loadRuns(), 200));
  $("runStatus").addEventListener("change", () => {
    void loadRuns();
  });
  $("runCaseStatus").addEventListener("change", () => {
    void loadRuns();
  });
  $("runCaseSeverity").addEventListener("change", () => {
    void loadRuns();
  });
  $("runCaseForm").addEventListener("submit", (event) => {
    event.preventDefault();
    void saveRunCase();
  });
  $("adminPassword").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void loginAdmin();
    }
  });
  void boot();
}

async function boot() {
  setStatus("初始化中", true);
  clearError();
  await loadAuthStatus();
  if (getAdminToken()) {
    const ok = await restoreSession();
    if (ok) {
      await refreshAll();
      return;
    }
  }
  setStatus("未登录", false);
}

async function loadAuthStatus() {
  try {
    const payload = await fetchJson("/api/admin/auth/status", {}, false);
    state.authStatus = payload.auth || null;
    renderAuthState();
  } catch (_error) {
    state.authStatus = null;
    renderAuthState();
  }
}

async function restoreSession() {
  try {
    const payload = await fetchJson("/api/admin/auth/session");
    state.session = payload.session || null;
    renderAuthState();
    return true;
  } catch (_error) {
    logoutAdmin(false);
    return false;
  }
}

async function loginAdmin() {
  const password = $("adminPassword").value;
  if (!password) {
    showError("请输入后台口令。");
    return;
  }
  setStatus("登录中", true);
  clearError();
  const payload = await fetchJson(
    "/api/admin/auth/login",
    {
      method: "POST",
      body: JSON.stringify({ password })
    },
    false
  );
  window.sessionStorage.setItem(ADMIN_TOKEN_KEY, payload.token || "");
  $("adminPassword").value = "";
  await restoreSession();
  await refreshAll();
}

function logoutAdmin(showMessage = true) {
  window.sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  stopJobPolling();
  state.session = null;
  state.overview = null;
  state.records = [];
  state.history = [];
  state.runs = [];
  state.selectedRunId = "";
  state.jobs = [];
  state.datasets = [];
  state.selectedId = "";
  state.currentJobId = "";
  state.currentJobStatus = "";
  state.selectedDataset = "";
  renderAuthState();
  resetAdminView();
  clearError();
  setStatus("未登录", false);
  if (showMessage) {
    $("adminAuthMeta").textContent = "已退出后台会话。";
  }
}

function renderAuthState() {
  const authMode = state.authStatus?.mode || "--";
  const badge = $("adminAuthState");
  if (state.session) {
    badge.textContent = "已登录";
    badge.className = "status-badge";
    $("adminAuthMeta").textContent = `认证模式：${authMode}，会话将在 ${formatUnixTimestamp(state.session.expires_at)} 过期。`;
    return;
  }
  badge.textContent = "未登录";
  badge.className = "status-badge is-blocked";
  $("adminAuthMeta").textContent = `认证模式：${authMode}。未登录时禁止访问后台数据和管理动作。`;
}

function resetAdminView() {
  $("knowledgeCountMetric").textContent = "--";
  $("runCountMetric").textContent = "--";
  $("gateAccuracyMetric").textContent = "--";
  $("realLatencyMetric").textContent = "--";
  $("evaluationSummary").innerHTML = "";
  $("knowledgeSummary").innerHTML = "";
  $("jobSummary").innerHTML = "";
  $("jobList").innerHTML = '<div class="log-item">登录后加载。</div>';
  $("jobListState").textContent = "0 个";
  $("knowledgeList").innerHTML = '<div class="log-item">登录后加载。</div>';
  $("knowledgeListState").textContent = "0 条";
  $("historyList").innerHTML = '<div class="log-item">登录后加载。</div>';
  $("historyState").textContent = "未选择";
  $("providerHealthList").innerHTML = '<div class="log-item">登录后加载。</div>';
  $("runList").innerHTML = '<div class="log-item">登录后加载。</div>';
  $("runCaseState").textContent = "未选择";
  $("runCaseForm").reset();
  $("datasetList").innerHTML = '<div class="log-item">登录后加载。</div>';
  $("datasetRows").innerHTML = '<div class="log-item">登录后加载。</div>';
  $("datasetSummary").innerHTML = "";
  $("configEditor").value = "";
  $("configMeta").innerHTML = "";
  $("configState").textContent = "未加载";
  $("knowledgeStatusFilter").value = "";
  $("runCaseStatus").value = "";
  $("runCaseSeverity").value = "";
  prepareNewRecord();
}

async function refreshAll() {
  ensureLoggedIn();
  setStatus("加载中", true);
  clearError();
  await Promise.all([loadOverview(), loadKnowledge(), loadRuns(), loadJobs(), loadEvaluationDatasets(), loadConfigView()]);
  setStatus("就绪", false);
}

async function loadOverview() {
  const payload = await fetchJson("/api/admin/overview");
  state.overview = payload;
  renderOverview(payload);
}

async function loadKnowledge() {
  const query = $("knowledgeSearch").value.trim();
  const tag = state.activeTag;
  const status = $("knowledgeStatusFilter").value;
  const payload = await fetchJson(
    `/api/admin/knowledge?query=${encodeURIComponent(query)}&tag=${encodeURIComponent(tag)}&status=${encodeURIComponent(status)}`
  );
  state.records = payload.records || [];
  renderKnowledgeSummary(payload.summary || {});
  renderKnowledgeList(state.records);
  renderTagFilters(payload.summary?.top_tags || []);
  if (state.selectedId && !state.records.some((item) => item.id === state.selectedId)) {
    prepareNewRecord(false);
  }
  if (!state.selectedId && state.records.length) {
    await selectRecord(state.records[0].id);
  }
}

async function loadRuns() {
  const query = $("runSearch").value.trim();
  const status = $("runStatus").value;
  const caseStatus = $("runCaseStatus").value;
  const caseSeverity = $("runCaseSeverity").value;
  const payload = await fetchJson(
    `/api/admin/runs?query=${encodeURIComponent(query)}&status=${encodeURIComponent(status)}&case_status=${encodeURIComponent(caseStatus)}&case_severity=${encodeURIComponent(caseSeverity)}&limit=50`
  );
  state.runs = payload.runs || [];
  renderRuns(payload.stats || {}, state.runs);
  if (state.selectedRunId && !state.runs.some((item) => item.run_id === state.selectedRunId)) {
    prepareRunCase();
  }
  if (!state.selectedRunId && state.runs.length) {
    selectRun(state.runs[0].run_id);
  }
}

async function loadJobs() {
  const payload = await fetchJson("/api/admin/jobs?job_type=evaluation&limit=8");
  state.jobs = payload.jobs || [];
  renderJobs(payload.summary || {}, state.jobs);
  if (state.currentJobId) {
    const current = state.jobs.find((item) => item.job_id === state.currentJobId);
    const nextStatus = current?.status || "";
    if (nextStatus && nextStatus !== state.currentJobStatus) {
      state.currentJobStatus = nextStatus;
      if (nextStatus === "completed") {
        state.selectedDataset = "";
        await Promise.all([loadOverview(), loadEvaluationDatasets()]);
        const okCount = (current?.result?.reports || []).filter((item) => item.ok).length;
        const totalCount = (current?.result?.reports || []).length;
        setStatus(`评测完成 ${okCount}/${totalCount}`, false);
      } else if (nextStatus === "failed") {
        setStatus(`评测失败：${current?.error || "unknown error"}`, false);
      }
    }
  }
  updateJobPolling();
}

function hasActiveJobs() {
  return state.jobs.some((item) => ["queued", "running"].includes(item.status));
}

function stopJobPolling() {
  if (jobPollTimer) {
    window.clearInterval(jobPollTimer);
    jobPollTimer = 0;
  }
}

function updateJobPolling() {
  if (hasActiveJobs()) {
    if (!jobPollTimer) {
      jobPollTimer = window.setInterval(() => {
        if (!state.session) {
          stopJobPolling();
          return;
        }
        void loadJobs();
      }, 2500);
    }
    return;
  }
  stopJobPolling();
}

async function loadEvaluationDatasets() {
  const payload = await fetchJson("/api/admin/evaluations");
  state.datasets = payload.datasets || [];
  renderDatasetList(state.datasets);
  if (!state.selectedDataset && state.datasets.length) {
    await selectDataset(state.datasets[0].dataset_name);
  }
}

async function loadConfigView() {
  const payload = await fetchJson("/api/admin/config");
  state.config = payload;
  renderConfig(payload);
}

async function rebuildIndex() {
  ensureLoggedIn();
  setStatus("重建索引中", true);
  await fetchJson("/api/admin/reindex", { method: "POST", body: "{}" });
  await loadOverview();
  setStatus("索引已重建", false);
}

async function reloadEvaluations() {
  ensureLoggedIn();
  setStatus("重载评测中", true);
  await fetchJson("/api/admin/evaluations/reload", { method: "POST", body: "{}" });
  state.selectedDataset = "";
  await Promise.all([loadOverview(), loadEvaluationDatasets()]);
  setStatus("评测已重载", false);
}

async function runEvaluations() {
  ensureLoggedIn();
  const confirmed = window.confirm("执行离线批量评测（安全门控、ASR、多轮、仪表板）？");
  if (!confirmed) {
    return;
  }
  setStatus("评测任务排队中", true);
  const payload = await fetchJson("/api/admin/evaluations/run", {
    method: "POST",
    body: JSON.stringify({
      targets: ["safety_gate", "asr", "multiturn", "dashboard"],
      reload_after: true,
      async_mode: true
    })
  });
  state.currentJobId = payload.job?.job_id || "";
  state.currentJobStatus = payload.job?.status || "";
  await Promise.all([loadOverview(), loadJobs()]);
  setStatus(`评测任务已启动 ${state.currentJobId || ""}`.trim(), false);
}

async function exportRuns(format) {
  ensureLoggedIn();
  setStatus(`导出 ${format.toUpperCase()} 中`, true);
  const query = $("runSearch").value.trim();
  const status = $("runStatus").value;
  const caseStatus = $("runCaseStatus").value;
  const caseSeverity = $("runCaseSeverity").value;
  const token = getAdminToken();
  const response = await fetch(
    `/api/admin/runs/export?format=${encodeURIComponent(format)}&query=${encodeURIComponent(query)}&status=${encodeURIComponent(status)}&case_status=${encodeURIComponent(caseStatus)}&case_severity=${encodeURIComponent(caseSeverity)}&limit=500`,
    {
      headers: buildHeaders(token, false)
    }
  );
  if (!response.ok) {
    let message = `request failed: ${response.status}`;
    try {
      const payload = await response.json();
      message = payload.error || message;
    } catch (_error) {
      // ignore
    }
    showError(message);
    throw new Error(message);
  }
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `shipvoice-runs.${format === "csv" ? "csv" : "jsonl"}`;
  link.click();
  window.URL.revokeObjectURL(url);
  setStatus(`已导出 ${format.toUpperCase()}`, false);
}

async function cleanupRuns() {
  ensureLoggedIn();
  const confirmed = window.confirm("确认清理 smoke 日志和乱码测试记录吗？");
  if (!confirmed) {
    return;
  }
  const payload = await fetchJson("/api/admin/runs/cleanup", {
    method: "POST",
    body: JSON.stringify({
      delete_smoke: true,
      delete_mojibake: true,
      query: ""
    })
  });
  await Promise.all([loadOverview(), loadRuns()]);
  const deletedCount = payload.cleanup?.deleted_count ?? 0;
  setStatus(`已清理 ${deletedCount} 条`, false);
}

async function saveRecord() {
  ensureLoggedIn();
  const recordId = $("recordId").value.trim();
  const payload = {
    id: recordId,
    title: $("recordTitle").value.trim(),
    status: $("recordStatus").value,
    owner: $("recordOwner").value.trim(),
    source: $("recordSource").value.trim(),
    tags: $("recordTags")
      .value.split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    text: $("recordText").value.trim(),
    reviewer: $("recordReviewer").value.trim(),
    review_notes: $("recordReviewNotes").value.trim(),
    change_note: $("recordChangeNote").value.trim()
  };
  if (!payload.title || !payload.text) {
    showError("标题和正文不能为空。");
    return;
  }
  const url = state.selectedId ? `/api/admin/knowledge/${encodeURIComponent(state.selectedId)}` : "/api/admin/knowledge";
  const method = state.selectedId ? "PUT" : "POST";
  const result = await fetchJson(url, { method, body: JSON.stringify(payload) });
  await Promise.all([loadOverview(), loadKnowledge()]);
  state.selectedId = result.record?.id || payload.id;
  await selectRecord(state.selectedId);
  setStatus("条目已保存", false);
}

async function deleteRecord() {
  ensureLoggedIn();
  const recordId = state.selectedId || $("recordId").value.trim();
  if (!recordId) {
    showError("当前没有可删除的条目。");
    return;
  }
  if (!window.confirm(`确认删除知识条目 ${recordId} 吗？`)) {
    return;
  }
  await fetchJson(`/api/admin/knowledge/${encodeURIComponent(recordId)}`, { method: "DELETE" });
  await Promise.all([loadOverview(), loadKnowledge()]);
  prepareNewRecord();
  setStatus("条目已删除", false);
}

async function selectRecord(recordId) {
  if (!recordId) {
    return;
  }
  const payload = await fetchJson(`/api/admin/knowledge/${encodeURIComponent(recordId)}`);
  const record = payload.record || {};
  state.history = payload.history || [];
  state.selectedId = record.id || "";
  $("recordId").value = record.id || "";
  $("recordTitle").value = record.title || "";
  $("recordStatus").value = record.status || "draft";
  $("recordOwner").value = record.owner || "";
  $("recordSource").value = record.source || "";
  $("recordTags").value = Array.isArray(record.tags) ? record.tags.join(", ") : "";
  $("recordText").value = record.text || "";
  $("recordReviewer").value = record.last_reviewer || "";
  $("recordReviewNotes").value = record.review_notes || "";
  $("recordChangeNote").value = "";
  $("editorState").textContent = state.selectedId ? `${state.selectedId} · ${knowledgeStatusLabel(record.status)}` : "未选择";
  renderHistory(state.history);
  renderKnowledgeList(state.records);
}

function prepareNewRecord(resetId = true) {
  state.history = [];
  state.selectedId = "";
  $("recordId").value = resetId ? state.overview?.knowledge?.next_id || "" : "";
  $("recordTitle").value = "";
  $("recordStatus").value = "draft";
  $("recordOwner").value = "";
  $("recordSource").value = "";
  $("recordTags").value = "";
  $("recordText").value = "";
  $("recordReviewer").value = "";
  $("recordReviewNotes").value = "";
  $("recordChangeNote").value = "";
  $("editorState").textContent = "新建条目";
  $("historyState").textContent = "未选择";
  $("historyList").innerHTML = '<div class="log-item">保存后自动生成版本历史。</div>';
  renderKnowledgeList(state.records);
}

async function saveConfig() {
  ensureLoggedIn();
  const rawText = $("configEditor").value;
  const payload = await fetchJson("/api/admin/config", {
    method: "POST",
    body: JSON.stringify({ raw_text: rawText })
  });
  renderConfig({
    ...state.config,
    config: payload.config,
    raw_text: JSON.stringify(payload.config, null, 2)
  });
  await loadOverview();
  setStatus("配置已重载", false);
}

function renderOverview(payload) {
  const knowledge = payload.knowledge || {};
  const audit = payload.audit || {};
  const evaluation = payload.evaluation || {};
  const jobs = payload.jobs || {};
  const safety = evaluation.safety || {};
  const multiturn = evaluation.multiturn || {};
  const latency = evaluation.latency || {};
  const realChain = evaluation.real_chain || {};
  const asr = evaluation.asr || {};
  const config = payload.config || {};
  const providerHealth = payload.provider_health || {};

  $("knowledgeCountMetric").textContent = String(knowledge.record_count ?? "--");
  $("runCountMetric").textContent = String(audit.total_runs ?? "--");
  $("gateAccuracyMetric").textContent = formatPercent(multiturn.gate_accuracy ?? safety.accuracy);
  $("realLatencyMetric").textContent = realChain.avg_first_audio_ms ? `${Math.round(realChain.avg_first_audio_ms)} ms` : "--";

  $("evaluationSummary").innerHTML = [
    summaryCard("安全门控", `rows ${safety.evaluated_rows ?? safety.rows ?? 0}`, `accuracy ${formatPercent(safety.accuracy)} · critical ${safety.critical_failures ?? 0}`),
    summaryCard("ASR 评测", `rows ${asr.evaluated_rows ?? asr.rows ?? 0}`, `CER ${formatPercent(asr.avg_cer)} · 术语召回 ${formatPercent(asr.term_recall)}`),
    summaryCard("多轮问答", `dialogs ${multiturn.dialogs ?? multiturn.rows ?? 0}`, `gate ${formatPercent(multiturn.gate_accuracy)} · grounding ${formatPercent(multiturn.followup_grounding_accuracy)}`),
    summaryCard("延迟评测", `rows ${latency.rows ?? 0}`, `audio ready ${roundMetric(latency.avg_first_audio_ms)} ms · total ${roundMetric(latency.avg_total_ms)} ms`),
    summaryCard("真实链路", `samples ${realChain.num_samples ?? realChain.rows ?? 0}`, `ASR ${roundMetric(realChain.avg_asr_ms)} ms · 载荷就绪 ${roundMetric(realChain.avg_first_audio_ms)} ms`),
    summaryCard("当前配置", `LLM ${config.llm_provider || "--"}`, `ASR ${config.asr_provider || "--"} · TTS ${config.tts_provider || "--"}`),
    summaryCard("复盘台账", `open ${audit.open_cases ?? 0}`, `high ${audit.high_priority_cases ?? 0} · total ${audit.total_runs ?? 0}`),
    summaryCard("后台作业", `active ${jobs.active_jobs ?? 0}`, `latest ${jobs.latest_job?.status || "--"} · total ${jobs.total_jobs ?? 0}`)
  ].join("");
  renderProviderHealth(providerHealth);
}

function renderJobs(summary, jobs) {
  $("jobListState").textContent = `${jobs.length} 个`;
  const latest = summary.latest_job || null;
  const active = summary.active_job || null;
  $("jobSummary").innerHTML = [
    summaryCard("活跃作业", String(summary.active_jobs ?? 0), active ? `${active.label || active.job_id} · ${active.status} · ${active.progress}%` : "当前无排队/执行中的任务"),
    summaryCard("最近一次", latest ? latest.status : "--", latest ? `${latest.progress}% · ${formatTimestamp(latest.updated_at)}` : "尚未执行离线批量评测")
  ].join("");
  if (!jobs.length) {
    $("jobList").innerHTML = '<div class="log-item">当前没有后台作业记录。</div>';
    return;
  }
  $("jobList").innerHTML = jobs
    .map((job) => {
      const reports = job.result?.reports || [];
      const okCount = reports.filter((item) => item.ok).length;
      const totalCount = reports.length;
      const detail = [
        `status=${job.status}`,
        `progress=${job.progress}%`,
        totalCount ? `reports=${okCount}/${totalCount}` : "",
        job.payload?.targets?.length ? `targets=${job.payload.targets.join(",")}` : "",
        job.completed_at ? `completed=${formatTimestamp(job.completed_at)}` : `updated=${formatTimestamp(job.updated_at)}`
      ]
        .filter(Boolean)
        .join(" · ");
      const summaryText =
        job.error ||
        job.result?.failure?.error ||
        (totalCount ? `执行完成，共 ${okCount}/${totalCount} 个脚本成功` : "等待执行结果");
      return `
        <div class="log-item ${job.status === "failed" ? "is-error" : ""}">
          <strong>${escapeHtml(job.label || "后台作业")} · ${escapeHtml(job.job_id)}</strong>
          <p>${escapeHtml(detail)}</p>
          <p>${escapeHtml(trimText(summaryText, 180))}</p>
        </div>`;
    })
    .join("");
}

function renderKnowledgeSummary(summary) {
  $("knowledgeListState").textContent = `${summary.record_count ?? 0} 条`;
  $("knowledgeSummary").innerHTML = [
    summaryCard("已批准", String(summary.approved_count ?? 0), `索引上线 ${summary.approved_count ?? 0}`),
    summaryCard("待审核", String(summary.pending_review_count ?? 0), `草稿 ${summary.draft_count ?? 0} · 归档 ${summary.archived_count ?? 0}`)
  ].join("");
}

function renderKnowledgeList(records) {
  if (!records.length) {
    $("knowledgeList").innerHTML = '<div class="log-item">没有匹配的知识条目。</div>';
    return;
  }
  $("knowledgeList").innerHTML = records
    .map(
      (record) => `
        <button class="log-item admin-item ${record.id === state.selectedId ? "is-selected" : ""}" data-record-id="${escapeHtml(record.id)}">
          <strong>${escapeHtml(record.title)}</strong>
          <p>${escapeHtml(knowledgeStatusLabel(record.status))} · v${escapeHtml(String(record.current_version || 1))} · ${escapeHtml(record.owner || "未指派")}</p>
          <p>${escapeHtml((record.tags || []).join(" · "))}</p>
          <p>${escapeHtml(record.text_preview || "")}</p>
        </button>`
    )
    .join("");
  document.querySelectorAll("[data-record-id]").forEach((button) => {
    button.addEventListener("click", () => {
      void selectRecord(button.dataset.recordId || "");
    });
  });
}

function renderHistory(history) {
  $("historyState").textContent = history.length ? `${history.length} 条` : "未选择";
  if (!history.length) {
    $("historyList").innerHTML = '<div class="log-item">当前条目还没有历史记录。</div>';
    return;
  }
  $("historyList").innerHTML = history
    .map((item) => {
      const snapshot = item.snapshot || {};
      const detail = [
        `v${item.version_no}`,
        knowledgeStatusLabel(snapshot.status),
        item.actor || "--",
        formatTimestamp(item.created_at)
      ]
        .filter(Boolean)
        .join(" · ");
      return `
        <div class="log-item">
          <strong>${escapeHtml(item.action || "updated")}</strong>
          <p>${escapeHtml(detail)}</p>
          <p>${escapeHtml(item.change_note || "--")}</p>
        </div>`;
    })
    .join("");
}

function renderTagFilters(tagRows) {
  const chips = [
    `<button class="tag-chip ${state.activeTag ? "" : "is-active"}" data-tag="">全部</button>`,
    ...tagRows.map(
      (item) =>
        `<button class="tag-chip ${state.activeTag === item.tag ? "is-active" : ""}" data-tag="${escapeHtml(item.tag)}">${escapeHtml(item.tag)} (${item.count})</button>`
    )
  ];
  $("tagFilters").innerHTML = chips.join("");
  document.querySelectorAll("[data-tag]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeTag = button.dataset.tag || "";
      void loadKnowledge();
    });
  });
}

function renderRuns(stats, runs) {
  $("runListState").textContent = `${runs.length} 条`;
  $("runCountMetric").textContent = String(stats.total_runs ?? "--");
  if (!runs.length) {
    $("runList").innerHTML = '<div class="log-item">没有匹配的运行记录。</div>';
    return;
  }
  $("runList").innerHTML = runs
    .map((run) => {
      const detail = run.error || run.answer_preview || run.question || "";
      return `
        <button class="log-item admin-item ${run.run_id === state.selectedRunId ? "is-selected" : ""} ${run.status === "error" ? "is-error" : ""}" data-run-id="${escapeHtml(run.run_id || "")}">
          <strong>${escapeHtml(run.question || run.transcript || "未命名请求")}</strong>
          <p>${escapeHtml(run.session_id || "--")} · ${escapeHtml(run.mode || "--")} · ${escapeHtml(run.gate_label || "--")}</p>
          <p>${escapeHtml(caseStatusLabel(run.case_status))} · ${escapeHtml(caseSeverityLabel(run.case_severity))} · ${escapeHtml(caseTypeLabel(run.case_type))} · ${escapeHtml(run.case_owner || "未指派")}</p>
          <p>${escapeHtml(trimText(detail, 180))}</p>
          <p class="muted-line">${escapeHtml(run.run_id || "--")} · ${escapeHtml(formatTimestamp(run.created_at || ""))}</p>
        </button>`;
    })
    .join("");
  document.querySelectorAll("[data-run-id]").forEach((button) => {
    button.addEventListener("click", () => {
      selectRun(button.dataset.runId || "");
    });
  });
}

function selectRun(runId) {
  const run = state.runs.find((item) => item.run_id === runId);
  if (!run) {
    return;
  }
  state.selectedRunId = runId;
  $("runCaseState").textContent = `${run.run_id} · ${caseStatusLabel(run.case_status)}`;
  $("caseStatus").value = run.case_status || "open";
  $("caseSeverity").value = run.case_severity || "medium";
  $("caseType").value = run.case_type || "quality";
  $("caseOwner").value = run.case_owner || "";
  $("caseReviewer").value = run.case_reviewer || "";
  $("caseNote").value = run.case_note || "";
  renderRuns(state.overview?.audit || {}, state.runs);
}

function prepareRunCase() {
  state.selectedRunId = "";
  $("runCaseState").textContent = "未选择";
  $("runCaseForm").reset();
  renderRuns(state.overview?.audit || {}, state.runs);
}

async function saveRunCase() {
  ensureLoggedIn();
  if (!state.selectedRunId) {
    showError("请先选择一条运行记录。");
    return;
  }
  const payload = {
    case_status: $("caseStatus").value,
    case_severity: $("caseSeverity").value,
    case_type: $("caseType").value,
    case_owner: $("caseOwner").value.trim(),
    case_reviewer: $("caseReviewer").value.trim(),
    case_note: $("caseNote").value.trim()
  };
  const result = await fetchJson(`/api/admin/runs/${encodeURIComponent(state.selectedRunId)}/case`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
  const updated = result.run || null;
  if (updated) {
    state.runs = state.runs.map((item) => (item.run_id === updated.run_id ? updated : item));
    renderRuns(result.stats || state.overview?.audit || {}, state.runs);
    selectRun(updated.run_id);
  }
  await loadOverview();
  setStatus("处置已保存", false);
}

function renderDatasetList(datasets) {
  $("datasetListState").textContent = `${datasets.length} 个`;
  if (!datasets.length) {
    $("datasetList").innerHTML = '<div class="log-item">当前没有已入库评测数据。</div>';
    $("datasetSummary").innerHTML = "";
    $("datasetRows").innerHTML = "";
    $("datasetDetailState").textContent = "未选择";
    return;
  }
  $("datasetList").innerHTML = datasets
    .map(
      (dataset) => `
        <button class="log-item admin-item ${dataset.dataset_name === state.selectedDataset ? "is-selected" : ""}" data-dataset-name="${escapeHtml(dataset.dataset_name)}">
          <strong>${escapeHtml(dataset.display_name)}</strong>
          <p>${escapeHtml(dataset.dataset_name)} · ${dataset.row_count} rows</p>
          <p>${escapeHtml(trimText(dataset.source_path || "", 100))}</p>
        </button>`
    )
    .join("");
  document.querySelectorAll("[data-dataset-name]").forEach((button) => {
    button.addEventListener("click", () => {
      void selectDataset(button.dataset.datasetName || "");
    });
  });
}

async function selectDataset(datasetName) {
  if (!datasetName) {
    return;
  }
  state.selectedDataset = datasetName;
  const payload = await fetchJson(`/api/admin/evaluations/${encodeURIComponent(datasetName)}?limit=12`);
  renderDatasetList(state.datasets);
  renderDatasetDetail(payload);
}

function renderDatasetDetail(payload) {
  $("datasetDetailState").textContent = payload.display_name || payload.dataset_name || "未选择";
  const summary = payload.summary || {};
  const summaryPairs = Object.entries(summary)
    .filter(([, value]) => value === null || ["string", "number", "boolean"].includes(typeof value))
    .slice(0, 8);
  $("datasetSummary").innerHTML = summaryPairs.length
    ? summaryPairs
        .map(
          ([key, value]) => `
            <div>
              <dt>${escapeHtml(key)}</dt>
              <dd>${escapeHtml(formatSummaryValue(value))}</dd>
            </div>`
        )
        .join("")
    : "<div><dt>summary</dt><dd>--</dd></div>";

  const rows = payload.rows || [];
  if (!rows.length) {
    $("datasetRows").innerHTML = '<div class="log-item">当前数据集没有可展示的行。</div>';
    return;
  }
  $("datasetRows").innerHTML = rows
    .map((item) => {
      const row = item.payload || {};
      const headline = datasetHeadline(payload.dataset_name, row, item.row_key);
      const detail = datasetDetail(payload.dataset_name, row);
      return `
        <div class="log-item">
          <strong>${escapeHtml(headline)}</strong>
          <p>${escapeHtml(detail.meta)}</p>
          <p>${escapeHtml(detail.body)}</p>
        </div>`;
    })
    .join("");
}

function renderConfig(payload) {
  $("configEditor").value = payload.raw_text || "";
  $("configState").textContent = "已加载";
  const env = payload.env_overrides || {};
  const rows = [
    `config: ${payload.config_path || "--"}`,
    `ASR env: ${env.SHIPVOICE_ASR_PROVIDER || "(none)"}`,
    `LLM env: ${env.SHIPVOICE_LLM_PROVIDER || "(none)"}`,
    `TTS env: ${env.SHIPVOICE_TTS_PROVIDER || "(none)"}`,
    `Admin auth: ${env.SHIPVOICE_ADMIN_AUTH_MODE || "--"}`
  ];
  $("configMeta").innerHTML = rows.map((item) => `<span class="provider-chip">${escapeHtml(item)}</span>`).join("");
}

function renderProviderHealth(payload) {
  const providers = payload.providers || payload;
  const items = [providers.asr, providers.llm, providers.tts].filter(Boolean);
  $("providerHealthState").textContent = items.length ? "已更新" : "未加载";
  if (!items.length) {
    $("providerHealthList").innerHTML = '<div class="log-item">当前没有 provider 健康信息。</div>';
    return;
  }
  $("providerHealthList").innerHTML = items
    .map((item) => {
      const status = item.reachable === null ? item.mode : item.reachable ? "reachable" : "unreachable";
      const detail = [
        `provider=${item.provider || "--"}`,
        `mode=${item.mode || "--"}`,
        item.model ? `model=${item.model}` : "",
        item.http_status ? `http=${item.http_status}` : "",
        item.endpoint ? trimText(item.endpoint, 90) : "endpoint=(none)"
      ]
        .filter(Boolean)
        .join(" · ");
      return `
        <div class="log-item ${item.reachable === false ? "is-error" : ""}">
          <strong>${escapeHtml(item.component || "Provider")} · ${escapeHtml(status)}</strong>
          <p>${escapeHtml(detail)}</p>
          <p>${escapeHtml(item.detail || "--")}</p>
        </div>`;
    })
    .join("");
}

async function fetchJson(url, options = {}, requireAuth = true) {
  try {
    const token = requireAuth ? getAdminToken() : "";
    const response = await fetch(url, {
      headers: buildHeaders(token, true),
      ...options
    });
    const payload = await response.json();
    if (!response.ok) {
      if (response.status === 401 && requireAuth) {
        logoutAdmin(false);
      }
      throw new Error(payload.error || `request failed: ${response.status}`);
    }
    return payload;
  } catch (error) {
    showError(error.message || String(error));
    throw error;
  }
}

function buildHeaders(token, withJson) {
  const headers = {};
  if (withJson) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

function getAdminToken() {
  return window.sessionStorage.getItem(ADMIN_TOKEN_KEY) || "";
}

function ensureLoggedIn() {
  if (!state.session || !getAdminToken()) {
    throw new Error("请先登录后台。");
  }
}

function setStatus(text, isLoading) {
  $("adminStatus").textContent = text;
  $("adminStatus").className = isLoading ? "status-badge is-running" : "status-badge";
}

function showError(message) {
  $("adminError").hidden = false;
  $("adminError").textContent = message;
  $("adminStatus").textContent = "异常";
  $("adminStatus").className = "status-badge is-blocked";
}

function clearError() {
  $("adminError").hidden = true;
  $("adminError").textContent = "";
}

function summaryCard(title, value, detail) {
  return `
    <div>
      <dt>${escapeHtml(title)}</dt>
      <dd>${escapeHtml(value)}</dd>
      <div class="summary-detail">${escapeHtml(detail)}</div>
    </div>`;
}

function formatSummaryValue(value) {
  if (value === null || value === undefined || value === "") {
    return "--";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function datasetHeadline(datasetName, row, altKey) {
  if (datasetName === "safety_gate_eval") {
    return `${row.id || altKey} · ${row.question || "Safety row"}`;
  }
  if (datasetName === "asr_eval") {
    return `${row.id || altKey} · ${row.transcript || "ASR row"}`;
  }
  if (datasetName === "multiturn_eval") {
    return `${row.turn_id || altKey} · ${row.question || "Multi-turn row"}`;
  }
  if (datasetName === "latency_metrics") {
    return `${row.question_id || altKey} · ${row.mode || "mode"}`;
  }
  if (datasetName === "real_chain_samples") {
    return `${row.sample_id || altKey} · ${row.transcript || "Real chain sample"}`;
  }
  return altKey;
}

function datasetDetail(datasetName, row) {
  if (datasetName === "safety_gate_eval") {
    return {
      meta: `${row.expected_gate || "--"} · ${row.predicted_gate || "--"} · critical ${row.critical_issue || "--"}`,
      body: trimText(row.reason || row.question || "", 180)
    };
  }
  if (datasetName === "asr_eval") {
    return {
      meta: `${row.scenario || "--"} · CER ${row.cer || "--"} · recall ${row.term_recall || "--"}`,
      body: trimText(row.asr_transcript || row.transcript || "", 180)
    };
  }
  if (datasetName === "multiturn_eval") {
    return {
      meta: `${row.scenario || "--"} · gate ${row.predicted_gate || "--"} · total ${row.total_ms || "--"} ms`,
      body: trimText(row.answer || "", 180)
    };
  }
  if (datasetName === "latency_metrics") {
    return {
      meta: `${row.category || "--"} · audio ready ${row.first_audio_ms || "--"} ms · total ${row.total_ms || "--"} ms`,
      body: trimText(row.question || "", 180)
    };
  }
  if (datasetName === "real_chain_samples") {
    return {
      meta: `ASR ${row.asr_ms || "--"} ms · retrieval ${row.retrieval_ms || "--"} ms · audio ready ${row.first_audio_ms || "--"} ms`,
      body: trimText(row.transcript || "", 180)
    };
  }
  return { meta: "", body: trimText(JSON.stringify(row), 180) };
}

function knowledgeStatusLabel(status) {
  const labels = {
    draft: "草稿",
    in_review: "待审核",
    approved: "已批准",
    changes_requested: "待修改",
    archived: "已归档"
  };
  return labels[status] || status || "--";
}

function caseStatusLabel(status) {
  const labels = {
    open: "待处理",
    investigating: "调查中",
    resolved: "已关闭",
    accepted_risk: "接受风险",
    ignored: "忽略"
  };
  return labels[status] || status || "--";
}

function caseSeverityLabel(severity) {
  const labels = {
    critical: "严重",
    high: "高",
    medium: "中",
    low: "低"
  };
  return labels[severity] || severity || "--";
}

function caseTypeLabel(type) {
  const labels = {
    normal: "正常",
    safety_gate: "安全门控",
    error: "系统错误",
    latency: "时延瓶颈",
    quality: "回答质量",
    asr: "ASR",
    llm: "LLM",
    tts: "TTS"
  };
  return labels[type] || type || "--";
}

function formatPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "--";
  }
  return `${(numeric * 100).toFixed(1)}%`;
}

function formatTimestamp(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatUnixTimestamp(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return "--";
  }
  return new Date(numeric * 1000).toLocaleString("zh-CN", { hour12: false });
}

function roundMetric(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.round(numeric) : "--";
}

function trimText(value, maxLength) {
  const text = String(value || "");
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength)}...`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function debounce(fn, delayMs) {
  let timer = 0;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delayMs);
  };
}

init();
