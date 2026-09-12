import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  GitPullRequest,
  LayoutDashboard,
  ListChecks,
  ShieldCheck,
  Server,
  ChevronRight,
  ExternalLink,
  RefreshCw,
  Check,
  X,
  Clock,
  AlertCircle,
  FileText,
  Download,
  MessageSquare,
  GitBranch,
  Search,
  Activity,
  Plus,
} from "lucide-react";
import "./style.css";
import { IncrementalBoard } from './IncrementalBoard';

type Stage = {
  id: string;
  name: string;
  status: string;
  conclusion?: string;
  duration_seconds?: number;
};
type Attachment = { name: string; url: string; type: string };
type Case = {
  id: string;
  suite: string;
  phase: string;
  status: string;
  duration: number;
  title: string;
  errors: string[];
  attachments: Attachment[];
};
export type Run = {
  frozen_environment?: {fingerprint:string;images:Record<string,string[]>};
  current_round?: number;
  target_rounds?: number;
  active_run_id?: string;
  environment_health?: string;
  cleanup?: {status:string;active_residuals?:unknown[]};
  statistics?: {planned:number;started:number;completed:number;interrupted:number;first_pass_count:number;first_pass_rate:number|null;failure_types:Record<string,number>};
  rounds?: {index:number;run_id:string;first_pass:boolean;summary:string;failure_kind:string;archive_verified:boolean;cleanup?:{status:string;active_residuals?:unknown[]}}[];
  full_acceptance?: boolean;
  kind?: string;
  source_mode?: string;
  build_result?: {build_id:string;source_sha:string;image:string;image_id:string};
  rollback?: string;
  image_manifest?: {name:string;generation:number;images:string[]}[];
  evidence_notice?: string;
  provider_scope?: string;
  build_url?: string;
  members?: {repo:string;repo_id?:number;pr_number:number|null;pr_url:string;head_ref?:string;base_ref?:string;head_sha:string;base_sha:string}[];
  options?: {codex_review:boolean;baseline_enabled:boolean;github_write:boolean};
  version_checks?: {repo:string;expected_head:string;actual_head:string;expected_base:string;actual_base:string;state:string}[];
  id: string;
  repo: string;
  pr_number: number;
  title: string;
  pr_url: string;
  head_sha?: string;
  base_sha?: string;
  head_ref?: string;
  status: string;
  conclusion?: string;
  summary?: string;
  created_at: string;
  duration_seconds?: number;
  stale?: boolean;
  failure_kind?: string;
  queue_position?: number;
  stages: Stage[];
  suites: { id: string; name: string; reason: string }[];
  evidence_cases: Case[];
  test_reports?: { phase: string; suite: string; url: string }[];
  trace_downloads?: { phase: string; suite: string; url: string }[];
  review?: {
    status: string;
    summary?: string;
    findings: {
      severity: string;
      title: string;
      body?: string;
      file?: string;
      line?: number;
    }[];
  };
  github?: { state: string; ok?: boolean };
  deliveries?: {
    channel: string;
    state?: string;
    ok?: boolean;
    error?: string;
    url?: string;
    phase?: string;
  }[];
  policy?: { coverage_gaps: string[] };
  archive?: { synced_at: string };
  report_url?: string;
};
type Suite = { id: string; name: string; kind: string; implemented: boolean };
const token = new URLSearchParams(location.search).get("access_token");
const headers = token ? { "X-Pipeline-View-Token": token } : undefined;
const basePath = location.pathname.startsWith('/pipeline') ? '/pipeline' : '';
const currentPath = () => location.pathname.slice(basePath.length) || '/';
const sitePath = (path: string) => basePath + path;
async function api<T>(url: string): Promise<T> {
  const r = await fetch(sitePath(url), { headers });
  if (r.status === 401 && basePath) location.assign('/?return_to='+encodeURIComponent(location.pathname));
  if (!r.ok)
    throw Error(
      r.status === 401
        ? "请使用群内授权分享链接打开看板"
        : `接口返回 ${r.status}`,
    );
  return r.json();
}
function safeUrl(value?: string) {
  if (!value) return "#";
  try {
    const u = new URL(value, location.origin);
    if (basePath && u.hostname === location.hostname && /^\/(runs|batches|artifacts|api|history|capabilities|runners)(\/|$)/.test(u.pathname)) {
      u.host=location.host;u.protocol=location.protocol;u.pathname=sitePath(u.pathname);u.searchParams.delete('access_token');
    }
    return ["http:", "https:"].includes(u.protocol) ? u.href : "#";
  } catch {
    return "#";
  }
}
function time(s?: number) {
  return s == null
    ? "—"
    : s < 60
      ? `${s}s`
      : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}
function deliveryLabel(run: Run, channel: string) {
  if (channel.startsWith('batch_')) {
    const member=run.members?.find(m=>String(m.repo_id)===channel.split(':')[1]);
    return `${member?.repo.split('/').pop() || 'PR'} #${member?.pr_number || ''} ${channel.startsWith('batch_status:')?'检查状态':'摘要评论'}`;
  }
  return ({github_status:'GitHub 状态',github_comment:'PR 摘要评论',newlink:'蓝区编码演示'} as Record<string,string>)[channel] || channel;
}
function state(r: {
  status?: string;
  conclusion?: string;
  failure_kind?: string;
  stale?: boolean;
}): [string, string] {
  if (r.stale) return ["版本已过期", "warn"];
  if (r.status === "running") return ["执行中", "active"];
  if (r.status === "queued") return ["排队中", "wait"];
  if (r.status === "draft") return ["草稿", "wait"];
  if (
    r.failure_kind === "error" ||
    ["blocked", "interrupted"].includes(r.status || "")
  )
    return ["环境阻塞", "warn"];
  if (r.conclusion === "success") return ["通过", "pass"];
  if (r.conclusion === "failure") return ["未通过", "fail"];
  if (r.conclusion === "skipped") return ["未执行", "wait"];
  if (r.status === "superseded") return ["旧版本", "wait"];
  if (r.status === "closed") return ["已关闭", "wait"];
  return ["待执行", "wait"];
}
function Badge({ item }: { item: Parameters<typeof state>[0] }) {
  const [label, color] = state(item);
  return <span className={`badge ${color}`}>{label}</span>;
}
function Result({ value }: { value?: string }) {
  return (
    <span
      className={`result ${value === "passed" ? "pass" : value === "failed" || value === "timedOut" ? "fail" : "wait"}`}
    >
      {value === "passed" ? (
        <Check size={14} />
      ) : value === "failed" || value === "timedOut" ? (
        <X size={14} />
      ) : (
        <Clock size={14} />
      )}{" "}
      {value === "passed"
        ? "通过"
        : value === "failed" || value === "timedOut"
          ? "失败"
          : "未执行"}
    </span>
  );
}
const stagesets = [
  ["接收与准备", ["resolve", "agent", "preflight", "prepare", "bootstrap"]],
  ["固定版本与构建", ["snapshot", "build", "merge", "format"]],
  ["部署与基线", ["baseline", "deploy"]],
  ["关键链路", ["E01", "E02", "E03", "E04", "DR", "DR-contract", "unit", "vet"]],
  ["韧性与幂等", ["E05", "E06"]],
  ["报告与回写", ["report", "github", "docs"]],
] as [string, string[]][];
function App() {
  const [monitors,setMonitors]=useState<{id:string;repo:string;status:string;checked_at?:string;server_received_at?:string;latest?:{number:number;title:string;html_url:string;head:{sha:string}};pull_requests?:{number:number;title:string;html_url:string;state:string;draft:boolean;merged_at?:string;head:{sha:string}}[];pending_events:number;execution_status:string;error?:string}[]>([]);
  const [runs, setRuns] = useState<Run[]>([]),
    [catalog, setCatalog] = useState<Suite[]>([]),
    [current, setCurrent] = useState<Run>(),
    [page, setPage] = useState(
      /^\/(runs|batches)\//.test(currentPath()) ? "detail" : currentPath()==='/history'?'overview':currentPath()==='/runners'?'runners':currentPath()==='/capabilities'?'capabilities':"batches",
    ),
    [tab, setTab] = useState("总览"),
    [selected, setSelected] = useState(""),
    [log, setLog] = useState(""),
    [error, setError] = useState(""),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("全部"),
    [health, setHealth] = useState<{ runner?: string; read_only?: boolean; editor_url?:string; cloud_profile?:boolean }>(
      {},
    ),
    [caseKey, setCaseKey] = useState("");
  async function refresh() {
    try {
      const [data, c, h, m] = await Promise.all([
        api<{ runs: Run[] }>("/api/runs"),
        api<{ suites: Suite[] }>("/api/e2e/suites"),
        api<typeof health>("/api/health"),
        Promise.resolve({monitors: [] as typeof monitors}),
      ]);
      setRuns(data.runs);
      setCatalog(c.suites);
      setHealth(h);
      setMonitors(m.monitors);
      const id = /^\/(runs|batches)\//.test(currentPath())
        ? currentPath().split("/")[2]
        : current?.id;
      if (id) setCurrent(await api<Run>(`/api/runs/${id}`));
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!current) return;
    const chosen =
      current.evidence_cases?.find(
        (c) => `${c.phase}:${c.suite}:${c.id}` === caseKey,
      ) ||
      current.evidence_cases?.find(
        (c) => c.phase === (current.source_mode === 'environment' ? 'current' : 'candidate') && c.status !== "passed",
      ) ||
      current.evidence_cases?.find((c) => c.phase === (current.source_mode === 'environment' ? 'current' : 'candidate'));
    const id =
      selected ||
      chosen?.suite ||
      current.stages.find((s) => s.conclusion === "failure")?.id ||
      current.stages[0]?.id;
    if (!id) {
      setLog("尚未产生执行日志");
      return;
    }
    let active = true;
    fetch(sitePath(`/api/runs/${current.id}/stages/${id}/log`), { headers })
      .then((r) =>
        r.ok ? r.text() : Promise.reject(Error(`日志暂不可用 (${r.status})`)),
      )
      .then((value) => {
        if (active) setLog(value.replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, ''));
      })
      .catch((e) => {
        if (active) setLog(String(e));
      });
    return () => {
      active = false;
    };
  }, [current, selected, caseKey]);
  useEffect(() => {
    const back = () => {
      const p = currentPath();
      setPage(
        /^\/(runs|batches)\//.test(p)
          ? "detail"
          : p === "/history" ? "overview" : p === "/reviews" ? "reviews" : p === "/capabilities"
            ? "capabilities"
            : p === "/runners"
              ? "runners"
              : "batches",
      );
      refresh();
    };
    addEventListener("popstate", back);
    return () => removeEventListener("popstate", back);
  }, []);
  function open(r: Run) {
    history.pushState({}, "", sitePath(`/${r.kind==='batch'?'batches':'runs'}/${r.id}`));
    setCurrent(r);
    setPage("detail");
    setTab("总览");
    setSelected("");
    setCaseKey("");
    api<Run>(`/api/runs/${r.id}`)
      .then(setCurrent)
      .catch((e) => setError(String(e)));
  }
  function nav(p: string) {
    setPage(p);
    history.pushState({}, "", sitePath(p === "overview" ? "/history" : `/${p}`));
  }
  const cases = current?.evidence_cases || [],
    picked =
      cases.find((c) => `${c.phase}:${c.suite}:${c.id}` === caseKey) ||
      cases.find((c) => c.phase === (current?.source_mode === 'environment' ? 'current' : 'candidate') && c.status !== "passed") ||
      cases.find((c) => c.phase === "candidate") ||
      cases[0];
  const activeStage =
    current?.stages.find((s) => s.id === (selected || picked?.suite)) ||
    current?.stages.find((s) => s.conclusion === "failure") ||
    current?.stages[0];
  const review = current?.review,
    findings = review?.findings || [],
    reviewDone = review?.status === "completed";
  const visible = runs.filter(
    (r) =>
      `${r.repo} ${r.title} ${r.pr_number}`
        .toLowerCase()
        .includes(query.toLowerCase()) &&
      (filter === "全部" ||
        (filter === "排队中"
          ? r.status === "queued"
          : filter === "执行中"
            ? r.status === "running"
            : filter === "已完成"
              ? r.status === "completed"
              : state(r)[1] === "fail" || state(r)[1] === "warn")),
  );
  const links = (label: string, url: string) => (
    <a href={safeUrl(url)} target="_blank" rel="noreferrer">
      {label}
      <ExternalLink size={13} />
    </a>
  );
  const table = (
    <div className="table-wrap">
      <table className="suite-table">
        <thead>
          <tr>
            <th>用例</th>
            <th>选择依据</th>
            {current?.source_mode !== 'environment' && <th>基线</th>}
            <th>{current?.source_mode === 'environment' ? '当前环境' : '候选'}</th>
            <th>耗时</th>
          </tr>
        </thead>
        <tbody>
          {(current?.suites || []).map((s) => {
            const b = cases.filter(
                (c) => c.phase === "baseline" && c.suite === s.id,
              ),
              c = cases.filter(
                (c) => c.phase === (current?.source_mode === 'environment' ? 'current' : 'candidate') && c.suite === s.id,
              );
            const result = (values: Case[]) =>
              !values.length
                ? undefined
                : values.every((x) => x.status === "passed")
                  ? "passed"
                  : "failed";
            return (
              <tr
                key={s.id}
                className={picked?.suite === s.id ? "chosen" : ""}
                onClick={() => {
                  if (c[0] || b[0]) {
                    const p = c[0] || b[0];
                    setCaseKey(`${p.phase}:${p.suite}:${p.id}`);
                    setSelected(p.phase === 'baseline' ? 'baseline' : p.suite);
                  }
                }}
              >
                <td>
                  <button className="text-button">
                    {s.id} {s.name}
                  </button>
                </td>
                <td>{s.reason || (current?.source_mode === 'environment' ? '手动选择的当前环境诊断' : '历史记录未保存')}</td>
                {current?.source_mode !== 'environment' && <td>
                  <Result value={result(b)} />
                </td>}
                <td>
                  <Result value={result(c)} />
                </td>
                <td>
                  {c.length
                    ? time(
                        Math.round(
                          c.reduce((sum, x) => sum + x.duration, 0) / 1000,
                        ),
                      )
                    : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!current?.suites.length && <div className="empty">尚未生成执行集合</div>}
    </div>
  );
  const evidence = picked ? (
    <section className="evidence-tool">
      <div className="section-head">
        <h3>
          <FileText size={18} /> {picked.suite} ·{" "}
          {picked.phase === 'current' ? '当前环境' : picked.phase === "baseline" ? "基线" : "候选"}证据
        </h3>
        <Result value={picked.status} />
      </div>
      <select
        aria-label="选择用例证据"
        value={`${picked.phase}:${picked.suite}:${picked.id}`}
        onChange={(e) => {setCaseKey(e.target.value);setSelected('');}}
      >
        {cases.map((c) => (
          <option
            key={`${c.phase}:${c.suite}:${c.id}`}
            value={`${c.phase}:${c.suite}:${c.id}`}
          >
            {c.phase === 'current' ? '当前环境' : c.phase === "baseline" ? "基线" : "候选"} {c.suite} · {c.title}
          </option>
        ))}
      </select>
      {picked.errors?.length > 0 && (
        <pre className="assertion">{picked.errors.join("\n").replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, '')}</pre>
      )}
      <div className="evidence-grid">
        <div>
          {picked.attachments.find((a) => a.type === "image") ? (
            <img
              src={safeUrl(
                picked.attachments.find((a) => a.type === "image")!.url,
              )}
              alt="实际用例截图"
            />
          ) : picked.attachments.find((a) => a.type === "video") ? (
            <video
              controls
              preload="metadata"
              src={safeUrl(
                picked.attachments.find((a) => a.type === "video")!.url,
              )}
            />
          ) : (
            <div className="empty">此用例没有截图或视频附件</div>
          )}
          <div className="attachments">
            {picked.attachments.map((a, i) => (
              <a key={i} href={safeUrl(a.url)} target="_blank" rel="noreferrer">
                <Download size={13} />
                {a.name}
              </a>
            ))}
          </div>
        </div>
        <div className="console">
          <div className="console-head">{activeStage?.name || "运行"}日志</div>
          <pre>{log || "等待日志"}</pre>
        </div>
      </div>
    </section>
  ) : (
    <div className="empty evidence-tool">尚无浏览器执行证据</div>
  );
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <GitBranch size={29} />
          <div>
            <b>PR Pipeline Hub</b>
            <small>代码检视与能力回归</small>
          </div>
        </div>
        <nav>
          {[
            [LayoutDashboard, "batches", "联合验证"],
            [ListChecks, "overview", "执行记录"],
            [ShieldCheck, "capabilities", "关键能力"],
            [Server, "runners", "运行环境"],
          ].map(([Icon, id, name]) => {
            const I = Icon as typeof Server;
            return (
              <button
                key={String(id)}
                className={page === id || (page === 'detail' && id === (current?.kind==='batch'?'batches':'overview')) ? "nav active" : "nav"}
                onClick={() => nav(String(id))}
              >
                <I size={19} />
                {String(name)}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <span className="avatar">N</span>
          <div>
            NewLink<small>观察模式 · 只读看板</small>
          </div>
        </div>
      </aside>
      <main>
        <header className="top">
          <span>
            PR Pipeline Hub <ChevronRight size={14} />{" "}
            {page === 'detail' && current?.source_mode === 'environment' ? '环境诊断' : page === 'batches' || (page==='detail'&&current?.kind==='batch') ? '联合验证' : page === "detail" || page === 'reviews'
              ? "PR 动态"
              : page === "capabilities"
                ? "关键能力"
                : page === "runners"
                  ? "运行环境"
                  : "执行记录"}
          </span>
          <div>
            <a className="create-validation" href={safeUrl(health?.editor_url || 'http://127.0.0.1:8793/')}>
              <Plus size={16} />新建 PR 验证
            </a>
            <span className="observation">观察模式</span>
            <button className="icon" title="刷新" onClick={refresh}>
              <RefreshCw size={18} />
            </button>
          </div>
        </header>
        {error && (
          <div className="error">
            <AlertCircle size={16} />
            {error}
          </div>
        )}
        {page === "detail" && current ? (
          <>
            <div className="pr-heading">
              <div className="pr-title">
                <GitPullRequest size={26} />
                <div>
                  <h1>
                    {current.source_mode==='environment'?(current.build_result?'Gamma 验证':'环境诊断'):current.kind==='batch'?'联合验证':`#${current.pr_number}`} {current.title}
                  </h1>
                  {current.source_mode==='environment' ? <p>dev-gamma · CI 专用测试身份 · {current.build_result?'本次构建产物验证':'未构建或更新集群镜像'}</p> : <p>
                    {current.repo} · head{" "}
                    <code>{current.head_sha?.slice(0, 8) || "待解析"}</code> ·
                    base{" "}
                    <code>{current.base_sha?.slice(0, 8) || "待解析"}</code> ·{" "}
                    {current.head_ref || "—"}
                  </p>}
                </div>
              </div>
              <div className="pr-actions">
                <Badge item={current} />
                {current.pr_url && links("GitHub PR", current.pr_url)}
                {current.build_url && links("来源构建", current.build_url)}
              </div>
            </div>
            {current.kind==='gamma'&&<section className="page-content">
              <div className="section-head"><h2>环境队列与稳定性验收</h2><span>dev-gamma · 串行执行</span></div>
              <p>{current.summary}</p>
              <p>队列位置：{current.queue_position || '—'} · 当前轮次：{current.current_round || 0}/{current.target_rounds || 1} · 环境：{current.environment_health || '等待'}</p>
              {current.active_run_id&&links('查看当前轮次', '/pipeline/runs/'+current.active_run_id)}
              {current.statistics&&<p>计划 {current.statistics.planned} · 已启动 {current.statistics.started} · 已完成 {current.statistics.completed} · 中断 {current.statistics.interrupted} · 首次通过 {current.statistics.first_pass_count}/{current.statistics.started}（{current.statistics.first_pass_rate==null?'未执行':(current.statistics.first_pass_rate*100).toFixed(1)+'%'}）</p>}
              <p>清理状态：{current.cleanup?.status || 'pending'} · 活动残留：{current.cleanup?.active_residuals?.length ?? '未核验'}</p>
              <div style={{overflowX:'auto'}}><table><thead><tr><th>轮次</th><th>首次结果</th><th>失败分类</th><th>证据</th><th>清理</th></tr></thead><tbody>
                {current.rounds?.map(row=><tr key={row.index}><td>{links('第 '+row.index+' 轮','/pipeline/runs/'+row.run_id)}</td><td>{row.first_pass?'通过':'未通过'}</td><td>{row.first_pass?'—':row.failure_kind}</td><td>{row.archive_verified?'已校验':'未确认'}</td><td>{row.cleanup?.status || 'unknown'}</td></tr>)}
              </tbody></table></div>
            </section>}
            {current.source_mode==='environment'&&<section className="page-content" style={{paddingTop:12,paddingBottom:12}}>
              <div className="section-head"><h2>实测环境镜像</h2><span>仅适用于本次环境快照，不代表分支或 PR 合入验收</span></div>
              {current.build_result&&<p>来源构建：{current.build_result.build_id}<br/>源码：<code style={{overflowWrap:'anywhere'}}>{current.build_result.source_sha}</code><br/>交付镜像：<code style={{overflowWrap:'anywhere'}}>{current.build_result.image}</code></p>}
              {current.rollback&&<p>失败恢复：{current.rollback==='restored'?'已恢复部署前镜像':current.rollback==='unchanged'?'镜像未改变':'需要人工处理，未覆盖外部更新'}</p>}
              {current.provider_scope && <p>OpenCode 专用测试 Runtime · 不覆盖多 Provider 切换</p>}
              {current.image_manifest?.map(item=><p key={item.name}><strong>{item.name}</strong> · generation {item.generation}<br/>{item.images.map(image=><code key={image} style={{overflowWrap:'anywhere'}}>{image}</code>)}</p>)}
              {current.frozen_environment&&<details><summary>冻结版本清单</summary><p><code style={{overflowWrap:'anywhere'}}>{current.frozen_environment.fingerprint}</code></p>{Object.entries(current.frozen_environment.images).map(([name,images])=><p key={name}><strong>{name}</strong><br/>{images.map(image=><code key={image} style={{overflowWrap:'anywhere'}}>{image}</code>)}</p>)}</details>}
              {current.evidence_notice&&<p className="muted">{current.evidence_notice}</p>}
            </section>}
            {current.kind==='batch'&&<section className="page-content" style={{paddingTop:12,paddingBottom:12}}>
              <div className="section-head"><h2>联合版本清单</h2><span>{current.full_acceptance?'核心集合验证':'局部验证'} · 不证明单个 PR 独立合入安全</span></div>
              {current.source_mode==='artifact' && <p>构建产物验证：运行已交付的确切镜像；不代表 PR 合入验收，不修改 CCE 环境。</p>}
              {current.members?.map(m=><p key={m.repo}>{m.pr_url ? links(`${m.repo} #${m.pr_number}`,m.pr_url) : m.repo} · {m.head_ref || 'head'} <code>{m.head_sha.slice(0,8)}</code> / {m.base_ref || 'base'} <code>{m.base_sha.slice(0,8)}</code></p>)}
              <p className="muted">Codex 代码检视：{current.options?.codex_review?'启用':'未启用'} · 基线对照：{current.options?.baseline_enabled?'启用':'未启用'} · GitHub 回写：{current.options?.github_write?'启用':'未启用'}</p>
              {current.version_checks?.filter(v=>v.expected_head!==v.actual_head||v.expected_base!==v.actual_base||v.state!=='open').map(v=><p className="error" key={v.repo}>{v.repo} 版本已过期 · head {v.expected_head.slice(0,8)} → {v.actual_head.slice(0,8)} · base {v.expected_base.slice(0,8)} → {v.actual_base.slice(0,8)} · {v.state}</p>)}
            </section>}
            <div className="tabs">
              {["总览", "代码发现", "E2E 证据", "运行日志", "交付记录"].map(
                (t) => (
                  <button
                    className={tab === t ? "selected" : ""}
                    onClick={() => setTab(t)}
                    key={t}
                  >
                    {t}
                  </button>
                ),
              )}
            </div>
            <div className="detail-layout">
              <article className="workspace">
                {tab === "总览" && (
                  <>
                    {current.kind!=='gamma'&&<section className="pipeline">
                      <div className="section-head">
                        <h2>CI / E2E 流水线</h2>
                        <span>{time(current.duration_seconds)}</span>
                      </div>
                      <div className="dag">
                        {stagesets.map(([name, ids]) => {
                          const stages = current.stages.filter((s) =>
                            ids.includes(s.id),
                          );
                          const status = stages.some(
                            (s) => s.conclusion === "failure",
                          )
                            ? "fail"
                            : stages.some((s) => s.status === "running")
                              ? "active"
                              : stages.length &&
                                  stages.every(
                                    (s) => s.conclusion === "success",
                                  )
                                ? "pass"
                                : "wait";
                          return (
                            <div className="dag-group" key={name}>
                              <div className={`node ${status}`}>
                                {status === "pass" ? (
                                  <Check />
                                ) : status === "fail" ? (
                                  <X />
                                ) : status === "active" ? (
                                  <Activity />
                                ) : (
                                  <Clock />
                                )}
                              </div>
                              <b>{name}</b>
                              <small>
                                {stages.length
                                  ? time(
                                      stages.reduce(
                                        (n, s) => n + (s.duration_seconds || 0),
                                        0,
                                      ),
                                    )
                                  : "未开始"}
                              </small>
                              <div className="children">
                                {stages.map((s) => (
                                  <button
                                    title={`查看${s.name}日志`}
                                    key={s.id}
                                    onClick={() => {setSelected(s.id);const evidence=cases.find(c=>c.phase==='candidate'&&c.suite===s.id);if(evidence)setCaseKey(`${evidence.phase}:${evidence.suite}:${evidence.id}`);}}
                                    className={
                                      selected === s.id
                                        ? "child chosen"
                                        : "child"
                                    }
                                  >
                                    <i className={state(s)[1]}>
                                      {s.conclusion === "success" ? (
                                        <Check size={12} />
                                      ) : s.conclusion === "failure" ? (
                                        <X size={12} />
                                      ) : (
                                        <Clock size={12} />
                                      )}
                                    </i>
                                    <span>
                                      {s.name}
                                      <small>
                                        {state(s)[0]} ·{" "}
                                        {time(s.duration_seconds)}
                                      </small>
                                    </span>
                                  </button>
                                ))}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </section>}
                    <section>
                      <h2>E2E 用例集</h2>
                      {table}
                    </section>
                    {evidence}
                  </>
                )}
                {tab === "E2E 证据" && (
                  <>
                    <h2>{current.source_mode === 'environment' ? '当前环境执行证据' : '基线与候选对比'}</h2>
                    {table}
                    {evidence}
                    <div className="report-links">
                      {current.test_reports?.map((r) => (
                        <React.Fragment key={r.url}>
                          {links(
                            `${r.phase === "baseline" ? "基线" : "候选"} ${r.suite} 完整报告`,
                            r.url,
                          )}
                        </React.Fragment>
                      ))}
                      {current.trace_downloads?.map((r) => (
                        <React.Fragment key={r.url}>
                          {links(`${r.phase} ${r.suite} Trace`, r.url)}
                        </React.Fragment>
                      ))}
                    </div>
                  </>
                )}
                {tab === "运行日志" && (
                  <>
                    <h2>阶段日志</h2>
                    <select
                      aria-label="日志阶段"
                      value={activeStage?.id || ""}
                      onChange={(e) => setSelected(e.target.value)}
                    >
                      {current.stages.map((s) => (
                        <option value={s.id} key={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                    <div className="console full">
                      <pre>{log}</pre>
                    </div>
                  </>
                )}
                {tab === "代码发现" && (
                  <>
                    <h2>Agent 代码发现</h2>
                    {!reviewDone && (
                      <div className="empty">
                        {review?.summary ||
                          "尚未收到结构化检视结果；不能据此判断没有风险。"}
                      </div>
                    )}
                    {reviewDone && !findings.length && (
                      <p>本次检视未记录可确认的问题。</p>
                    )}
                    {findings.map((f, i) => (
                      <section className="finding" key={i}>
                        <h3>
                          {f.severity} · {f.title}
                        </h3>
                        <p>{f.body}</p>
                        <code>
                          {f.file}
                          {f.line ? `:${f.line}` : ""}
                        </code>
                      </section>
                    ))}
                  </>
                )}
                {tab === "交付记录" && (
                  <>
                    <h2>交付与回写</h2>
                    {current.deliveries?.map((d, i) => (
                      <div className="delivery" key={i}>
                        <span>{deliveryLabel(current,d.channel)} · {d.phase==='queued'?'开始':'结果'}</span>
                        <b>{d.ok ? "已确认" : d.state || "尚无记录"}</b>
                        {d.url&&<a href={safeUrl(d.url)} target="_blank" rel="noreferrer">查看评论 <ExternalLink size={12}/></a>}
                        {d.error && <p>{d.error}</p>}
                      </div>
                    ))}
                    <p className="muted">
                      报告同步：{current.archive?.synced_at || "本地记录"}
                    </p>
                  </>
                )}
              </article>
              <aside className="inspector">
                <section>
                  <h2>
                    <FileText size={19} /> Agent 检视摘要
                  </h2>
                  <div className="risk-counts">
                    {[
                      ["high", "高风险"],
                      ["medium", "中风险"],
                      ["low", "低风险"],
                    ].map(([key, label]) => (
                      <div key={key}>
                        <small>{label}</small>
                        <strong className={key}>
                          {reviewDone
                            ? findings.filter((f) => f.severity === key).length
                            : "—"}
                        </strong>
                      </div>
                    ))}
                  </div>
                  <h3>
                    <AlertCircle size={17} /> 主要发现
                  </h3>
                  <p>
                    {(current.options?.codex_review===false?'未启用代码检视，代码风险未评估。':review?.summary) ||
                      "尚未完成 Agent 代码检视。E2E 通过不等于代码审阅通过。"}
                  </p>
                  <h3>
                    <ShieldCheck size={17} /> 测试结论
                  </h3>
                  <Badge item={current} />
                  <p>{current.summary}</p>
                  <small>观察模式，不自动阻止或执行合入。</small>
                </section>
                <section>
                  <h2>
                    <MessageSquare size={19} /> 交付与回写
                  </h2>
                  {current.deliveries?.map((d, i) => (
                    <div className="delivery compact" key={i}>
                      <span>
                        {deliveryLabel(current,d.channel)}
                      </span>
                      <b className={d.ok ? "pass" : "wait"}>
                        {d.ok
                          ? "已确认"
                          : d.state === "pending"
                            ? "待完成"
                            : "尚无成功回执"}
                      </b>
                    </div>
                  ))}
                  <div className="agent">
                    <span className="avatar">X</span>
                    <div>
                      {current.source_mode==='environment'?'CI 专用 E2E Runtime':current.kind==='batch'?(health.cloud_profile?'Linux Worker':'本机 WSL Worker'):'xiao-commitor'}<small>{current.source_mode==='environment'?'未触发 NewLink 机器人或代码检视':current.kind==='batch'?'本轮不包含 NewLink 投递验收':'消息与任务回执独立核对'}</small>
                    </div>
                  </div>
                </section>
                {current.policy?.coverage_gaps?.length ? (
                  <section>
                    <h3>覆盖边界</h3>
                    {current.policy.coverage_gaps.map((g) => (
                      <p key={g}>{g}</p>
                    ))}
                  </section>
                ) : null}
              </aside>
            </div>
          </>
        ) : page === 'batches' ? (
          <section className="page-content"><div className="section-head"><h1>联合验证</h1><a href={safeUrl(health?.editor_url||'http://127.0.0.1:8793/')} target="_blank" rel="noreferrer">新建批次 <ExternalLink size={14}/></a></div>
            <p className="muted">{health.cloud_profile?'云端提交 · 专用 Linux Worker · 单执行槽':'本机提交 · ECS 只读报告 · 单执行槽'}</p>
            <h2 style={{marginTop:24}}>当前执行 / 等待队列</h2>
            {runs.filter(r=>['running','queued'].includes(r.status)).map(r=><div className="delivery" key={r.id}><button className="text-button" onClick={()=>open(r)}>{r.title}</button><Badge item={r}/><span>队列 {r.queue_position||'—'}</span></div>)}
            {!runs.some(r=>['running','queued'].includes(r.status))&&<p className="empty">当前没有执行或排队任务</p>}
            <h2>批次记录</h2><div className="table-wrap"><table><thead><tr><th>批次</th><th>跨仓组合</th><th>用例 / 配置</th><th>结果</th></tr></thead><tbody>{runs.filter(r=>r.kind==='batch').map(r=><tr key={r.id}><td><button className="text-button" onClick={()=>open(r)}>{r.title}</button><small>{r.id}</small></td><td>{r.members?.map(m=><div key={m.repo}>{m.repo.split('/').pop()} {m.pr_number ? '#'+m.pr_number : m.head_ref || '构建产物'}</div>)}</td><td>{r.suites?.map(s=>s.id).join(' / ')}<small>代码检视 {r.options?.codex_review?'开启':'关闭'} · 基线 {r.options?.baseline_enabled?'开启':'关闭'}</small></td><td><Badge item={r}/></td></tr>)}</tbody></table></div>
            {!runs.some(r=>r.kind==='batch')&&<p className="empty">暂无联合验证批次</p>}
          </section>
        ) : page === 'reviews' ? (
          <IncrementalBoard runs={runs} monitors={monitors} open={open} />
        ) : page === "capabilities" ? (
          <section className="page-content">
            <h1>关键能力与门禁</h1>
            <p className="muted">当前登记的用例与覆盖缺口</p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>用例</th>
                    <th>关键能力</th>
                    <th>类型</th>
                    <th>实现状态</th>
                  </tr>
                </thead>
                <tbody>
                  {catalog.map((s) => (
                    <tr key={s.id}>
                      <td>{s.id}</td>
                      <td>{s.name}</td>
                      <td>
                        {s.kind === "browser" ? "浏览器链路" : "集成契约"}
                      </td>
                      <td>
                        <span
                          className={`badge ${s.implemented ? "pass" : "warn"}`}
                        >
                          {s.implemented ? "已实现，按运行验证" : "覆盖缺口"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : page === "reviews" ? (
          <section className="page-content">
            <h1>PR 检视</h1>
            <div className="list-tools">
              <span>监听仓库 {monitors.length} · PR {monitors.reduce((n,m)=>n+(m.pull_requests?.length||0),0)} · 执行记录 {runs.length}</span>
              <label className="search"><Search size={16}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索仓库、PR 或标题"/></label>
            </div>
            {monitors.map(m=><section key={m.id}>
              <div className="section-head"><h2>{m.repo}</h2><span className="muted">最近同步 {m.checked_at?new Date(m.checked_at).toLocaleString():'尚未同步'}</span></div>
              {(m.status!=='watching'||Date.now()-Date.parse(m.server_received_at||'')>=180000)&&<p className="error">监听异常或离线，以下为最近一次快照。{m.error||''}</p>}
              <div className="table-wrap"><table><thead><tr><th>PR</th><th>状态 / 版本</th><th>执行记录</th></tr></thead><tbody>
                {(m.pull_requests||[]).filter(p=>`${m.repo} ${p.number} ${p.title}`.toLowerCase().includes(query.toLowerCase())).map(p=>{
                  const attempts=runs.filter(r=>r.repo===m.repo&&r.pr_number===p.number);
                  return <tr key={p.number}><td>{links(`#${p.number} ${p.title}`,p.html_url)}</td>
                    <td>{p.merged_at?'已合入':p.state==='closed'?'已关闭':p.draft?'草稿':'待合入'}<br/><code>{p.head.sha.slice(0,8)}</code></td>
                    <td>{attempts.length?<details><summary>{attempts.length} 次执行</summary>{attempts.map(r=><div key={r.id}><button className="text-button" onClick={()=>open(r)}>{r.id}</button> <Badge item={r}/></div>)}</details>:<span className="muted">尚未执行</span>}</td>
                  </tr>;
                })}
              </tbody></table></div>
              {!m.pull_requests?.length&&<div className="empty">尚未同步 PR 清单</div>}
            </section>)}
            {!monitors.length&&<div className="empty">尚未收到本地监听快照</div>}
          </section>
        ) : page === "runners" ? (
          <section className="page-content">
            <h1>运行环境</h1>
            <h2 style={{marginTop:24}}>GitHub PR 发现</h2>
            <p><a href={safeUrl(health?.editor_url||'http://127.0.0.1:8793/')} target="_blank" rel="noreferrer">PR 选择与入队</a></p>
            {monitors.map(m=><section key={m.id} className="monitor-status">
              <div className="section-head"><h3>{m.repo}</h3><span className={`badge ${m.status==='watching'&&Date.now()-Date.parse(m.server_received_at||'')<180000?'pass':'warn'}`}>{m.status==='watching'&&Date.now()-Date.parse(m.server_received_at||'')<180000?'监听中':'监听异常或离线'}</span></div>
              <p>最近检查：{m.checked_at?new Date(m.checked_at).toLocaleString():'尚未检查'} · 每 60 秒 · 待同步事件 {m.pending_events}</p>
              {m.latest&&<p>{links(`最新未合入 PR #${m.latest.number} ${m.latest.title}`,m.latest.html_url)} · <code>{m.latest.head.sha.slice(0,8)}</code></p>}
              <p className="muted">{m.execution_status}</p>{m.error&&<p className="error">{m.error}</p>}
            </section>)}
            <div className="environment">
              <Server size={32} />
              <div>
                <h2>{health.runner || "尚未连接"}</h2>
                <p>{health.cloud_profile?'Linux Worker · 单执行槽':'本机 WSL · 单执行槽'}</p>
                <p>{health.cloud_profile?'云端控制面与专用构建机':'ECS 负责看板与报告；业务构建留在 WSL。'}</p>
              </div>
            </div>
            <h2>当前任务</h2>
            {runs
              .filter((r) => r.status === "running")
              .map((r) => (
                <button
                  className="text-button"
                  onClick={() => open(r)}
                  key={r.id}
                >
                  {r.source_mode==='environment'?r.title:`${r.repo} #${r.pr_number}`}
                </button>
              ))}
          </section>
        ) : (
          <section className="page-content">
            <h1>执行记录</h1>
            <div className="metrics">
              {[
                ["排队中", runs.filter((r) => r.status === "queued").length],
                ["执行中", runs.filter((r) => r.status === "running").length],
                [
                  "需关注",
                  runs.filter((r) => ["warn", "fail"].includes(state(r)[1]))
                    .length,
                ],
                ["已完成", runs.filter((r) => r.status === "completed").length],
              ].map(([name, n]) => (
                <div key={name}>
                  <small>{name}</small>
                  <strong>{n}</strong>
                </div>
              ))}
            </div>
            <div className="list-tools">
              <div className="tabs">
                {["全部", "排队中", "执行中", "已完成", "需关注"].map((f) => (
                  <button
                    className={filter === f ? "selected" : ""}
                    onClick={() => setFilter(f)}
                    key={f}
                  >
                    {f}
                  </button>
                ))}
              </div>
              <label className="search">
                <Search size={16} />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="搜索仓库、PR 或标题"
                />
              </label>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>PR</th>
                    <th>仓库</th>
                    <th>检视状态</th>
                    <th>队列</th>
                    <th>创建时间</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <button className="text-button" onClick={() => open(r)}>
                          {r.pr_number ? `#${r.pr_number} ` : ''}{r.title}
                        </button>
                      </td>
                      <td>{r.repo}</td>
                      <td>
                        <Badge item={r} />
                      </td>
                      <td>{r.queue_position || "—"}</td>
                      <td>{r.created_at?.replace("T", " ").slice(0, 19)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!visible.length && (
                <div className="empty">暂无匹配的检视记录</div>
              )}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
