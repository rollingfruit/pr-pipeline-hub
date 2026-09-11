const state = {
  runs: [],
  selectedRunId: null,
  selectedStageId: null,
  accessToken: new URLSearchParams(window.location.search).get("access_token") || "",
  timer: null,
};

const pipelineGroups = [
  { id: "prepare", name: "代码准备", stageIds: ["prepare"] },
  { id: "change", name: "变更校验", stageIds: ["merge", "format"] },
  { id: "quality", name: "质量门禁", stageIds: ["vet", "unit", "docs"] },
];

const elements = Object.fromEntries([
  "runner-status", "health-dot", "run-form", "pr-url", "requested-by", "form-error",
  "refresh-button", "run-list", "empty-state", "detail-content", "run-repo", "run-title",
  "run-pr-link", "run-badge", "run-duration", "run-id", "run-sha", "run-branch",
  "run-requested-by", "run-summary", "stage-flow", "log-title", "log-state", "log-output",
  "auto-scroll", "runner-location",
  "profile", "source-mode", "suite-picker", "suite-selection", "diagnostic", "e2e-links", "e2e-status", "e2e-steps",
].map((id) => [id, document.getElementById(id)]));

function apiHeaders(extra = {}) {
  const headers = { ...extra };
  if (state.accessToken) headers["X-Pipeline-View-Token"] = state.accessToken;
  return headers;
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: apiHeaders(options.headers || {}) });
  const payload = response.headers.get("content-type")?.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function statusInfo(item) {
  if (item.status === "running") return ["运行中", "running"];
  if (item.status === "queued") return ["排队中", "queued"];
  if (item.status === "interrupted") return ["已中断", "failure"];
  if (item.failure_kind === "error") return ["环境阻塞", "failure"];
  if (item.conclusion === "success") return ["通过", "success"];
  if (item.conclusion === "failure") return ["失败", "failure"];
  if (item.conclusion === "skipped") return ["已跳过", "skipped"];
  return ["等待", "queued"];
}

function duration(value) {
  if (value === null || value === undefined) return "--";
  if (value < 60) return `${value}s`;
  return `${Math.floor(value / 60)}m ${value % 60}s`;
}

function shortSha(value) { return value ? value.slice(0, 8) : "--"; }

function groupStatus(stages) {
  if (stages.some((stage) => stage.conclusion === "failure" || stage.status === "interrupted")) return ["失败", "failure"];
  if (stages.some((stage) => stage.status === "running")) return ["运行中", "running"];
  if (stages.every((stage) => stage.conclusion === "success")) return ["通过", "success"];
  if (stages.every((stage) => stage.conclusion === "skipped")) return ["未执行", "skipped"];
  return ["等待", "queued"];
}

function groupDuration(stages) {
  const values = stages.map((stage) => stage.duration_seconds).filter((value) => value !== null && value !== undefined);
  return values.length ? duration(values.reduce((total, value) => total + value, 0)) : "--";
}

function selectStage(run, stageId) {
  state.selectedStageId = stageId;
  renderDetail(run);
  loadLog(run);
}

function renderRunList() {
  elements["run-list"].replaceChildren();
  for (const run of state.runs) {
    const [label, className] = statusInfo(run);
    const button = document.createElement("button");
    button.type = "button";
    button.className = `run-item${run.id === state.selectedRunId ? " selected" : ""}`;
    button.innerHTML = `
      <span class="run-item-top"><strong>${escapeHtml(run.repo)} #${run.pr_number}</strong><span class="mini-badge ${className}">${label}</span></span>
      <span class="run-item-title">${escapeHtml(run.title)}</span>
      <span class="run-item-meta">${escapeHtml(run.id)} · ${duration(run.duration_seconds)}</span>`;
    button.addEventListener("click", () => selectRun(run.id));
    elements["run-list"].append(button);
  }
}

function renderDetail(run) {
  elements["empty-state"].hidden = true;
  elements["detail-content"].hidden = false;
  const [label, className] = statusInfo(run);
  elements["run-repo"].textContent = `${run.repo} · PR #${run.pr_number}`;
  elements["run-title"].textContent = run.title;
  elements["run-pr-link"].href = run.pr_url;
  elements["run-pr-link"].textContent = run.pr_url;
  elements["run-badge"].className = `badge ${className}`;
  elements["run-badge"].textContent = label;
  elements["run-duration"].textContent = `总耗时 ${duration(run.duration_seconds)}`;
  elements["run-id"].textContent = run.id;
  elements["run-sha"].textContent = shortSha(run.head_sha);
  elements["run-branch"].textContent = run.head_ref || "--";
  elements["run-requested-by"].textContent = run.requested_by;
  elements["run-summary"].textContent = run.summary + (run.archive
    ? ` · ECS 同步于 ${run.archive.synced_at || "--"}`
    : run.publication ? ` · ECS 上传：${run.publication.status}${run.publication.error ? "（" + run.publication.error + "）" : ""}` : "");
  elements["e2e-links"].replaceChildren();
  const reports = (run.test_reports || []).map(report => [
    `${report.phase === "baseline" ? "基线" : "候选"} ${report.suite} 回放`, report.url]);
  const traces = (run.trace_downloads || []).map(report => [
    `${report.phase === "baseline" ? "基线" : "候选"} ${report.suite} Trace 下载`, report.url]);
  for (const [label, value] of [["本地测试项目", run.archive ? null : run.app_url],
    ["服务器分享", run.archive ? null : run.web_url], ["验收报告", run.report_url], ...reports, ...traces]) {
    if (!value) continue;
    const link = document.createElement("a");
    const url = new URL(value, location.origin);
    if (!["http:", "https:"].includes(url.protocol)) continue;
    if (state.accessToken && url.origin === location.origin) url.searchParams.set("access_token", state.accessToken);
    link.href = url.href; link.textContent = label; link.target = url.origin === location.origin ? "_self" : "_blank"; link.rel = "noopener";
    elements["e2e-links"].append(link);
  }
  elements["e2e-status"].textContent = run.profile === "browser-e2e"
    ? `${run.full_acceptance ? "完整执行集合" : "单项调试"} · 实际通过 ${(run.test_results || []).filter(t => t.status === "passed").length} 个用例 · GitHub: ${run.github?.state || "未回写"}${run.github?.ok === false ? "（回写失败）" : ""}${run.stale ? " · 版本已过期" : ""}` : "";
  elements["e2e-steps"].replaceChildren();
  for (const step of (run.steps || []).slice(-30)) {
    const item = document.createElement("li");
    item.textContent = `${step.phase === "baseline" ? "基线" : "候选"} ${step.suite || ""} · ${step.title} · ${step.status}`;
    elements["e2e-steps"].append(item);
  }

  if (!state.selectedStageId || !run.stages.some((stage) => stage.id === state.selectedStageId)) {
    state.selectedStageId = run.stages.find((stage) => stage.status === "running")?.id ||
      [...run.stages].reverse().find((stage) => stage.conclusion === "failure")?.id ||
      run.stages[0].id;
  }
  elements["stage-flow"].replaceChildren();
  const track = document.createElement("div");
  track.className = `pipeline-track track-${statusInfo(run)[1]}`;
  track.innerHTML = '<div class="pipeline-rail" aria-hidden="true"></div><div class="terminal-node terminal-start"><span>Start</span><i></i></div>';

  const groups = run.profile === "browser-e2e" ? [
    {id: "source", name: "准备与构建", stageIds: ["resolve", "agent", "preflight", "snapshot", "build"]},
    {id: "environment", name: "部署验证", stageIds: ["baseline", "deploy"]},
    {id: "browser", name: "浏览器全链路", stageIds: ["E01", "E02", "E03", "DR"]},
    {id: "contract", name: "跨服务契约", stageIds: ["DR-contract"]},
    {id: "results", name: "证据与回写", stageIds: ["report", "github"]},
  ] : pipelineGroups;
  const groupCount = groups.filter(g => g.stageIds.some(id => run.stages.some(s => s.id === id))).length;
  track.style.gridTemplateColumns = `70px repeat(${groupCount}, minmax(190px, 1fr)) 70px`;
  track.style.minWidth = `${140 + groupCount * 190}px`;
  for (const definition of groups) {
    const stages = definition.stageIds.map((id) => run.stages.find((stage) => stage.id === id)).filter(Boolean);
    if (!stages.length) continue;
    const [groupLabel, groupClass] = groupStatus(stages);
    const group = document.createElement("section");
    group.className = `pipeline-group group-${groupClass}`;
    group.setAttribute("aria-label", `${definition.name}：${groupLabel}`);

    const milestone = document.createElement("button");
    milestone.type = "button";
    milestone.className = `milestone${stages.some((stage) => stage.id === state.selectedStageId) ? " selected" : ""}`;
    milestone.innerHTML = `<span class="milestone-name">${escapeHtml(definition.name)}</span><span class="milestone-time">${groupDuration(stages)}</span><i aria-hidden="true"></i><span class="sr-only">${groupLabel}</span>`;
    milestone.addEventListener("click", () => selectStage(run, stages.find((stage) => stage.conclusion === "failure" || stage.status === "running")?.id || stages[0].id));
    group.append(milestone);

    const tasks = document.createElement("div");
    tasks.className = "pipeline-tasks";
    for (const stage of stages) {
      const [stageLabel, stageClass] = statusInfo(stage);
      const task = document.createElement("button");
      task.type = "button";
      task.className = `task-node task-${stageClass}${stage.id === state.selectedStageId ? " selected" : ""}`;
      task.innerHTML = `<i aria-hidden="true"></i><span><strong>${escapeHtml(stage.name)}</strong><small>${stageLabel} · ${duration(stage.duration_seconds)}</small></span>`;
      task.addEventListener("click", () => selectStage(run, stage.id));
      tasks.append(task);
    }
    group.append(tasks);
    track.append(group);
  }

  const end = document.createElement("div");
  end.className = `terminal-node terminal-end terminal-${statusInfo(run)[1]}`;
  end.innerHTML = "<span>End</span><i></i>";
  track.append(end);
  elements["stage-flow"].append(track);
}

async function loadRuns() {
  const payload = await api("/api/runs");
  state.runs = payload.runs;
  if (!state.selectedRunId) {
    const pathMatch = window.location.pathname.match(/^\/runs\/([A-Za-z0-9-]+)$/);
    state.selectedRunId = pathMatch?.[1] || state.runs[0]?.id || null;
  }
  renderRunList();
  if (state.selectedRunId) await refreshSelectedRun();
}

async function refreshSelectedRun() {
  if (!state.selectedRunId) return;
  const run = await api(`/api/runs/${state.selectedRunId}`);
  const index = state.runs.findIndex((item) => item.id === run.id);
  if (index >= 0) state.runs[index] = run;
  renderRunList();
  renderDetail(run);
  await loadLog(run);
}

async function loadLog(run) {
  const stage = run.stages.find((item) => item.id === state.selectedStageId);
  if (!stage) return;
  const content = await api(`/api/runs/${run.id}/stages/${stage.id}/log`);
  elements["log-title"].textContent = `${stage.name}日志`;
  elements["log-state"].textContent = statusInfo(stage)[0];
  elements["log-output"].textContent = content || "等待阶段输出...";
  if (elements["auto-scroll"].checked) elements["log-output"].scrollTop = elements["log-output"].scrollHeight;
}

async function selectRun(runId) {
  state.selectedRunId = runId;
  state.selectedStageId = null;
  const suffix = state.accessToken ? `?access_token=${encodeURIComponent(state.accessToken)}` : "";
  history.replaceState(null, "", `/runs/${runId}${suffix}`);
  await refreshSelectedRun();
}

async function checkHealth() {
  try {
    const health = await api("/api/health");
    elements["health-dot"].classList.add("online");
    elements["runner-status"].textContent = `${health.runner} Runner 在线`;
    elements["runner-location"].textContent = health.runner;
    if (health.read_only) {
      elements["run-form"].hidden = true;
      elements["runner-status"].textContent = "ECS 报告归档 · 本地 WSL 执行";
    }
  } catch (error) {
    elements["health-dot"].classList.remove("online");
    elements["runner-status"].textContent = `Runner 不可用：${error.message}`;
  }
}

elements["run-form"].addEventListener("submit", async (event) => {
  event.preventDefault();
  elements["form-error"].textContent = "";
  const button = elements["run-form"].querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const run = await api("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pr_url: elements["pr-url"].value,
        requested_by: elements["requested-by"].value || "web-console",
        profile: elements["profile"].value,
        suites: selectedSuites(),
        diagnostic: elements["diagnostic"].checked,
        source_mode: elements["source-mode"].value,
      }),
    });
    state.runs.unshift(run);
    await selectRun(run.id);
  } catch (error) {
    elements["form-error"].textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

elements["refresh-button"].addEventListener("click", loadRuns);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);
}

async function tick() {
  try {
    await loadRuns();
  } catch (error) {
    elements["form-error"].textContent = error.message;
  }
  state.timer = window.setTimeout(tick, 1500);
}

checkHealth();
async function loadSuites() {
  const {suites} = await api("/api/e2e/suites");
  for (const suite of suites) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox"; input.value = suite.id; input.disabled = !suite.implemented;
    input.checked = ["E01", "E02", "E03"].includes(suite.id);
    input.addEventListener("change", selectionPreview);
    label.append(input, document.createTextNode(`${suite.id} ${suite.name}${suite.implemented ? "" : "（未接入）"}`));
    elements["suite-picker"].append(label);
  }
  selectionPreview();
}
function selectedSuites() {
  return [...elements["suite-picker"].querySelectorAll("input:checked")].map(input => input.value);
}
function selectionPreview() {
  const isE2e = elements["profile"].value === "browser-e2e";
  elements["source-mode"].disabled = !isE2e;
  if (!isE2e) elements["source-mode"].value = "merge";
  const headOnly = elements["source-mode"].value === "pr-head";
  if (headOnly) elements["diagnostic"].checked = true;
  elements["diagnostic"].disabled = headOnly;
  elements["suite-picker"].hidden = !isE2e;
  const chosen = selectedSuites();
  const full = ["E01", "E02", "E03"].every(id => chosen.includes(id));
  if (full && /github\.com\/rollingfruit\/agent-governance-gw\/pull\/96\/?$/.test(elements["pr-url"].value)) {
    chosen.push(...["DR", "DR-contract"].filter(id => !chosen.includes(id)));
  }
  elements["suite-selection"].textContent = isE2e ? `${headOnly ? "PR head 诊断" : full ? "完整验收" : "单项调试"}：${chosen.join("、") || "未选择"}` : "";
}
elements["source-mode"].addEventListener("change", selectionPreview);
elements["profile"].addEventListener("change", selectionPreview);
elements["pr-url"].addEventListener("input", selectionPreview);
loadSuites().catch(error => {elements["form-error"].textContent = error.message;});
tick();
