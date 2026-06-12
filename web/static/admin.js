const state = {
  overview: null,
  records: [],
  selectedId: "",
  activeTag: "",
  runs: [],
  datasets: [],
  selectedDataset: "",
  config: null
};

const $ = (id) => document.getElementById(id);

function init() {
  $("refreshAdminButton").addEventListener("click", () => refreshAll());
  $("reindexButton").addEventListener("click", () => rebuildIndex());
  $("reloadEvalButton").addEventListener("click", () => reloadEvaluations());
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
  $("runSearch").addEventListener("input", debounce(() => loadRuns(), 200));
  $("runStatus").addEventListener("change", () => loadRuns());
  void refreshAll();
}

async function refreshAll() {
  setStatus("加载中", true);
  clearError();
  await Promise.all([loadOverview(), loadKnowledge(), loadRuns(), loadEvaluationDatasets(), loadConfigView()]);
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
  const payload = await fetchJson(`/api/admin/knowledge?query=${encodeURIComponent(query)}&tag=${encodeURIComponent(tag)}`);
  state.records = payload.records || [];
  renderKnowledgeSummary(payload.summary || {});
  renderKnowledgeList(state.records);
  renderTagFilters(payload.summary?.top_tags || []);
  if (!state.selectedId && state.records.length) {
    void selectRecord(state.records[0].id);
  }
}

async function loadRuns() {
  const query = $("runSearch").value.trim();
  const status = $("runStatus").value;
  const payload = await fetchJson(
    `/api/admin/runs?query=${encodeURIComponent(query)}&status=${encodeURIComponent(status)}&limit=20`
  );
  state.runs = payload.runs || [];
  renderRuns(payload.stats || {}, state.runs);
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

function renderOverview(payload) {
  const knowledge = payload.knowledge || {};
  const audit = payload.audit || {};
  const evaluation = payload.evaluation || {};
  const multiturn = evaluation.multiturn || {};
  const latency = evaluation.latency || {};
  const realChain = evaluation.real_chain || {};
  const asr = evaluation.asr || {};
  const config = payload.config || {};
  const providerHealth = payload.provider_health || {};

  $("knowledgeCountMetric").textContent = String(knowledge.record_count ?? "--");
  $("runCountMetric").textContent = String(audit.total_runs ?? "--");
  $("gateAccuracyMetric").textContent = formatPercent(multiturn.gate_accuracy);
  $("realLatencyMetric").textContent = realChain.avg_first_audio_ms ? `${Math.round(realChain.avg_first_audio_ms)} ms` : "--";

  $("evaluationSummary").innerHTML = [
    summaryCard("ASR 评测", `样本 ${asr.evaluated_rows ?? 0}`, `CER ${formatPercent(asr.avg_cer)} · 术语召回 ${formatPercent(asr.term_recall)}`),
    summaryCard(
      "多轮问答",
      `dialogs ${multiturn.dialogs ?? 0}`,
      `gate ${formatPercent(multiturn.gate_accuracy)} · grounding ${formatPercent(multiturn.followup_grounding_accuracy)}`
    ),
    summaryCard(
      "延迟评测",
      `rows ${latency.rows ?? 0}`,
      `first audio ${Math.round(latency.avg_first_audio_ms ?? 0)} ms · total ${Math.round(latency.avg_total_ms ?? 0)} ms`
    ),
    summaryCard(
      "真实链路",
      `samples ${realChain.num_samples ?? 0}`,
      `ASR ${Math.round(realChain.avg_asr_ms ?? 0)} ms · 首音 ${Math.round(realChain.avg_first_audio_ms ?? 0)} ms`
    ),
    summaryCard("审计状态", `ok ${audit.ok_runs ?? 0}`, `error ${audit.error_runs ?? 0} · blocked ${audit.blocked_runs ?? 0}`),
    summaryCard("当前配置", `LLM ${config.llm_provider || "--"}`, `ASR ${config.asr_provider || "--"} · TTS ${config.tts_provider || "--"}`)
  ].join("");
  renderProviderHealth(providerHealth);
}

function renderKnowledgeSummary(summary) {
  $("knowledgeListState").textContent = `${summary.record_count ?? 0} 条`;
}

function renderKnowledgeList(records) {
  if (!records.length) {
    $("knowledgeList").innerHTML = '<div class="log-item">没有匹配的知识条目。</div>';
    prepareNewRecord(false);
    return;
  }
  $("knowledgeList").innerHTML = records
    .map(
      (record) => `
        <button class="log-item admin-item ${record.id === state.selectedId ? "is-selected" : ""}" data-record-id="${escapeHtml(
          record.id
        )}">
          <strong>${escapeHtml(record.title)}</strong>
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

async function selectRecord(recordId) {
  if (!recordId) {
    return;
  }
  const payload = await fetchJson(`/api/admin/knowledge/${encodeURIComponent(recordId)}`);
  const record = payload.record || {};
  state.selectedId = record.id || "";
  $("recordId").value = record.id || "";
  $("recordTitle").value = record.title || "";
  $("recordTags").value = Array.isArray(record.tags) ? record.tags.join(", ") : "";
  $("recordText").value = record.text || "";
  $("editorState").textContent = state.selectedId || "未选择";
  renderKnowledgeList(state.records);
}

function prepareNewRecord(resetId = true) {
  state.selectedId = "";
  $("recordId").value = resetId ? state.overview?.knowledge?.next_id || "" : "";
  $("recordTitle").value = "";
  $("recordTags").value = "";
  $("recordText").value = "";
  $("editorState").textContent = "新建条目";
  renderKnowledgeList(state.records);
}

function renderTagFilters(tagRows) {
  const chips = [
    `<button class="tag-chip ${state.activeTag ? "" : "is-active"}" data-tag="">全部</button>`,
    ...tagRows.map(
      (item) =>
        `<button class="tag-chip ${state.activeTag === item.tag ? "is-active" : ""}" data-tag="${escapeHtml(item.tag)}">${escapeHtml(
          item.tag
        )} (${item.count})</button>`
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

async function saveRecord() {
  const recordId = $("recordId").value.trim();
  const payload = {
    id: recordId,
    title: $("recordTitle").value.trim(),
    tags: $("recordTags")
      .value.split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    text: $("recordText").value.trim()
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
  setStatus("已保存", false);
}

async function deleteRecord() {
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
  setStatus("已删除", false);
}

async function rebuildIndex() {
  await fetchJson("/api/admin/reindex", { method: "POST", body: "{}" });
  await loadOverview();
  setStatus("索引已重建", false);
}

async function reloadEvaluations() {
  await fetchJson("/api/admin/evaluations/reload", { method: "POST", body: "{}" });
  state.selectedDataset = "";
  await Promise.all([loadOverview(), loadEvaluationDatasets()]);
  setStatus("评测已重载", false);
}

async function cleanupRuns() {
  const confirmed = window.confirm("确认清理测试日志和乱码审计记录吗？这会删除后台中的 smoke 记录。");
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

async function saveConfig() {
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
        <div class="log-item ${run.status === "error" ? "is-error" : ""}">
          <strong>${escapeHtml(run.question || run.transcript || "未命名请求")}</strong>
          <p>${escapeHtml(run.session_id || "--")} · ${escapeHtml(run.mode || "--")} · ${escapeHtml(run.gate_label || "--")}</p>
          <p>${escapeHtml(trimText(detail, 140))}</p>
          <p class="muted-line">${escapeHtml(run.run_id || "--")} · ${escapeHtml(formatTimestamp(run.created_at || ""))}</p>
        </div>`;
    })
    .join("");
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
        <button class="log-item admin-item ${dataset.dataset_name === state.selectedDataset ? "is-selected" : ""}" data-dataset-name="${escapeHtml(
          dataset.dataset_name
        )}">
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
    : '<div><dt>summary</dt><dd>--</dd></div>';

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
    `TTS env: ${env.SHIPVOICE_TTS_PROVIDER || "(none)"}`
  ];
  $("configMeta").innerHTML = rows.map((item) => `<span class="provider-chip">${escapeHtml(item)}</span>`).join("");
}

function renderProviderHealth(payload) {
  const items = [payload.asr, payload.llm, payload.tts].filter(Boolean);
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
        item.endpoint ? trimText(item.endpoint, 80) : "endpoint=(none)"
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

async function fetchJson(url, options = {}) {
  try {
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...options
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `request failed: ${response.status}`);
    }
    return payload;
  } catch (error) {
    showError(error.message || String(error));
    throw error;
  }
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

function datasetHeadline(datasetName, row, fallbackKey) {
  if (datasetName === "asr_eval") {
    return `${row.id || fallbackKey} · ${row.transcript || "ASR row"}`;
  }
  if (datasetName === "multiturn_eval") {
    return `${row.turn_id || fallbackKey} · ${row.question || "Multi-turn row"}`;
  }
  if (datasetName === "latency_metrics") {
    return `${row.question_id || fallbackKey} · ${row.mode || "mode"}`;
  }
  if (datasetName === "real_chain_samples") {
    return `${row.sample_id || fallbackKey} · ${row.transcript || "Real chain sample"}`;
  }
  return fallbackKey;
}

function datasetDetail(datasetName, row) {
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
      meta: `${row.category || "--"} · first audio ${row.first_audio_ms || "--"} ms · total ${row.total_ms || "--"} ms`,
      body: trimText(row.question || "", 180)
    };
  }
  if (datasetName === "real_chain_samples") {
    return {
      meta: `ASR ${row.asr_ms || "--"} ms · retrieval ${row.retrieval_ms || "--"} ms · first audio ${row.first_audio_ms || "--"} ms`,
      body: trimText(row.transcript || "", 180)
    };
  }
  return { meta: "", body: trimText(JSON.stringify(row), 180) };
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
