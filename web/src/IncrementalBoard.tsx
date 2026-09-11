import { useEffect, useRef, useState } from 'react';
import { Activity, Check, Clock, GitPullRequest, Search, ChevronRight, ExternalLink, X } from 'lucide-react';
import type { Run } from './main';
import './incremental.css';

const repos = ['agent-governance-gw','multica-aiwelink','service_router','AgentLink','public-service','observability','skills-market','CellMem','semantic-schedule','semantic-gateway','aiwelink-temporal'];
type PR = {number:number;title:string;html_url:string;state:string;draft:boolean;updated_at?:string;created_at?:string;merged_at?:string;head:{sha:string}};
type Monitor = {repo:string;status:string;checked_at?:string;server_received_at?:string;pull_requests?:PR[]};
type Entry = {key:string;repo:string;number:number;title:string;url:string;date:string;pr?:PR;run?:Run;attempts:Run[]};
const stamp=(s?:string)=>Date.parse(s||'')||0;
const active=(r?:Run)=>!!r && ['running','queued'].includes(r.status);
function status(e:Entry) {
  const r=e.run;
  if (r?.status==='running') return ['执行中','active'];
  if (r?.status==='queued') return [`排队 ${r.queue_position || ''}`,'wait'];
  if (e.pr && r && e.pr.head.sha!==r.head_sha) return ['新版本未检视','wait'];
  if (r?.stale) return ['版本已过期','warn'];
  if (r?.failure_kind==='error'||['blocked','interrupted'].includes(r?.status||'')) return ['环境阻塞','warn'];
  if (r?.conclusion==='failure') return ['未通过','fail'];
  if (r?.conclusion==='success') return ['通过','pass'];
  if (e.pr?.merged_at) return ['已合入','wait'];
  if (e.pr?.state==='closed') return ['已关闭','wait'];
  if (e.pr?.draft) return ['草稿','wait'];
  return [r ? '未执行' : '待检视','wait'];
}
export function entries(runs:Run[],monitors:Monitor[]) {
  const map=new Map<string,Entry>();
  for (const m of monitors) for (const p of m.pull_requests||[]) {
    const key=`${m.repo}#${p.number}`;
    map.set(key,{key,repo:m.repo,number:p.number,title:p.title,url:p.html_url,date:p.updated_at||p.created_at||'',pr:p,attempts:[]});
  }
  for (const r of [...runs].sort((a,b)=>stamp(b.created_at)-stamp(a.created_at))) {
    const key=`${r.repo}#${r.pr_number}`;
    const e=map.get(key)||{key,repo:r.repo,number:r.pr_number,title:r.title,url:r.pr_url,date:r.created_at,attempts:[]};
    e.attempts.push(r);
    if (!e.run) e.run=r;
    if (stamp(r.created_at)>stamp(e.date)) e.date=r.created_at;
    map.set(key,e);
  }
  return [...map.values()].filter(e=>repos.includes(e.repo.split('/').pop()!)).sort((a,b)=>stamp(b.date)-stamp(a.date)||a.key.localeCompare(b.key));
}
export function IncrementalBoard({runs,monitors,open}:{runs:Run[];monitors:Monitor[];open:(r:Run)=>void}) {
  const [repo,setRepo]=useState('全部仓库'),[query,setQuery]=useState(''),[filter,setFilter]=useState('全部'),[limit,setLimit]=useState(30),[history,setHistory]=useState(false);
  const sentinel=useRef<HTMLDivElement>(null);
  const [preview,setPreview]=useState<Run>(),[previewError,setPreviewError]=useState(''),[stage,setStage]=useState(''),[logs,setLogs]=useState('');
  useEffect(()=>{
    if(!preview?.id)return;
    const controller=new AbortController();
    const read=async()=>{
      try{
        const r=await fetch(`/api/runs/${preview.id}`,{signal:controller.signal});
        if(!r.ok)throw Error(`详情暂不可用 (${r.status})`);
        const data:Run=await r.json();setPreview(data);setPreviewError('');
      }catch(e){if(!controller.signal.aborted)setPreviewError(String(e));}
    };
    read();const timer=setInterval(read,5000);
    return ()=>{controller.abort();clearInterval(timer);};
  },[preview?.id]);
  useEffect(()=>{
    const id=stage||preview?.stages?.find(s=>s.status==='running')?.id||preview?.stages?.[0]?.id;
    if(!preview||!id){setLogs('尚未产生执行日志');return;}
    const controller=new AbortController();
    fetch(`/api/runs/${preview.id}/stages/${encodeURIComponent(id)}/log`,{signal:controller.signal}).then(r=>r.ok?r.text():Promise.reject(Error(`日志暂不可用 (${r.status})`))).then(v=>setLogs(v.replace(/\u001b\[[0-?]*[ -/]*[@-~]/g,''))).catch(e=>{if(!controller.signal.aborted)setLogs(String(e));});
    return ()=>controller.abort();
  },[preview,stage]);
  function inspect(r:Run){setStage('');setLogs('加载中');setPreviewError('');setPreview(r);}
  const all=entries(runs,monitors), running=runs.filter(r=>r.status==='running'), queued=runs.filter(r=>r.status==='queued').sort((a,b)=>(a.queue_position||0)-(b.queue_position||0));
  const cut=Date.now()-86400000;
  const matches=all.filter(e=>(repo==='全部仓库'||e.repo.endsWith('/'+repo))&&`${e.repo} ${e.number} ${e.title}`.toLowerCase().includes(query.toLowerCase())&&(filter==='全部'||(filter==='待检视'?status(e)[0].includes('检视'):filter==='执行中'?e.run?.status==='running':filter==='排队中'?e.run?.status==='queued':filter==='需关注'?['warn','fail'].includes(status(e)[1]):e.run?.conclusion==='success')));
  const recent=matches.filter(e=>stamp(e.date)>=cut||e.attempts.some(active));
  const old=matches.filter(e=>stamp(e.date)<cut&&!e.attempts.some(active));
  const displayed=history?[...recent,...old]:recent;
  useEffect(()=>{setLimit(30);},[repo,query,filter,history]);
  useEffect(()=>{
    const observer=new IntersectionObserver(events=>{if(events.some(e=>e.isIntersecting))setLimit(n=>n+30);},{rootMargin:'150px'});
    if(sentinel.current)observer.observe(sentinel.current);
    return ()=>observer.disconnect();
  },[limit,displayed.length]);
  function row(e:Entry) {
    const [label,color]=status(e);
    return <div className="pr-event" key={e.key}>
      <time dateTime={e.date}>{stamp(e.date)?new Date(e.date).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'时间未知'}</time>
      <GitPullRequest size={17}/>
      <div className="event-main"><small>{e.repo.split('/').pop()}</small>
        {e.run?<button className="text-button" onClick={()=>open(e.run!)}>#{e.number} {e.title}</button>:<a href={e.url} target="_blank" rel="noreferrer">#{e.number} {e.title} <ExternalLink size={12}/></a>}
        <small>head {(e.pr?.head.sha||e.run?.head_sha||'').slice(0,8)||'待解析'} · {e.attempts.length} 次执行</small>
        {e.attempts.length>1&&<details><summary>历史执行</summary>{e.attempts.map(r=><button key={r.id} className="text-button attempt" onClick={()=>open(r)}>{r.id} · {r.status}</button>)}</details>}
      </div><span className={`badge ${color}`}>{label}</span>
      {e.run&&<button className="icon" title="查看执行详情" onClick={()=>open(e.run!)}><ChevronRight size={18}/></button>}
    </div>;
  }
  return <div className={`incremental-layout ${preview?'with-preview':''}`}>
    <aside className="repo-rail"><h3>仓库 <span>11</span></h3>
      {['全部仓库',...repos].map(name=>{
        const monitor=monitors.find(m=>m.repo.endsWith('/'+name));
        const watching=monitor?.status==='watching'&&Date.now()-stamp(monitor.server_received_at)<300000;
        return <button key={name} className={repo===name?'repo selected':'repo'} onClick={()=>setRepo(name)} title={name==='全部仓库'?name:watching?'监听中':'未同步或监听异常'}>
          <span className={`repo-dot ${watching?'pass':'wait'}`}/><span>{name}</span><small>{all.filter(e=>(name==='全部仓库'||e.repo.endsWith('/'+name))&&(stamp(e.date)>=cut||e.attempts.some(active))).length}</small>
        </button>;
      })}<small className="muted">最近同步 {monitors.length} 仓</small>
    </aside>
    <section className="incremental-main"><div className="section-head"><h1>PR 增量动态</h1><span className="muted">最近 24 小时 · 最新动态优先</span></div>
      <section className="live-execution" aria-label="当前 E2E 执行"><h2><Activity size={18}/> 当前执行 · {running.length} / 1</h2>
        {!running.length&&<p className="muted">当前没有正在执行的任务</p>}
        {running.map(r=><div key={r.id}><button className="text-button live-title" onClick={()=>inspect(r)}>{r.repo} #{r.pr_number} · {r.title} <ChevronRight size={18}/></button>
          <div className="live-stages">{(r.stages||[]).map(s=><button key={s.id} onClick={()=>{inspect(r);setStage(s.id);}} className={s.status==='running'?'active':s.conclusion==='success'?'pass':s.conclusion==='failure'?'fail':'wait'} title={`查看 ${s.name}`}>
            {s.conclusion==='success'?<Check size={16}/>:s.status==='running'?<Activity size={16}/>:<Clock size={16}/>}<span>{s.name}</span></button>)}</div>
          {!r.stages?.length&&<small>等待 Worker 上传阶段进度</small>}
        </div>)}
        <div className="queue-strip"><b>等待执行 {queued.length}</b>{queued.map((r,i)=><button key={r.id} className="text-button" onClick={()=>open(r)}>#{i+1} {r.repo.split('/').pop()} PR #{r.pr_number}</button>)}</div>
      </section>
      <div className="list-tools"><div className="tabs">{['全部','待检视','执行中','排队中','通过','需关注'].map(f=><button key={f} className={filter===f?'selected':''} onClick={()=>setFilter(f)}>{f}</button>)}</div>
        <label className="search"><Search size={16}/><input aria-label="搜索 PR" placeholder="搜索仓库、PR 或标题" value={query} onChange={e=>setQuery(e.target.value)}/></label></div>
      <div className="event-list" data-testid="event-list">{recent.slice(0,limit).map(row)}{!recent.length&&<p className="empty">最近 24 小时暂无匹配的 PR 动态</p>}
        <button className="history-toggle" aria-expanded={history} onClick={()=>setHistory(!history)}><ChevronRight size={16} style={{transform:history?'rotate(90deg)':undefined}}/>24 小时以前 · {old.length} 条</button>
        {history&&old.slice(0,Math.max(0,limit-recent.length)).map(row)}
        {limit<displayed.length&&<div ref={sentinel} className="load-more"><button className="text-button" onClick={()=>setLimit(n=>n+30)}>继续加载</button></div>}
      </div>
    </section>
    {preview&&<aside className="run-preview" aria-label="执行详情预览"><div className="section-head"><h2>执行详情</h2><button className="icon" title="关闭预览" onClick={()=>setPreview(undefined)}><X size={18}/></button></div>
      <h3>#{preview.pr_number} {preview.title}</h3><p className="muted">{preview.repo}</p><code>head {preview.head_sha?.slice(0,8)||'待解析'}</code>
      {previewError&&<p className="error">{previewError}</p>}
      <div className="preview-stages">{preview.stages?.map(s=><button key={s.id} className={stage===s.id?'selected':''} onClick={()=>setStage(s.id)}><span>{s.name}</span><span className={`badge ${s.status==='running'?'active':s.conclusion==='success'?'pass':s.conclusion==='failure'?'fail':'wait'}`}>{s.status==='running'?'执行中':s.conclusion==='success'?'通过':s.conclusion==='failure'?'失败':'未执行'}</span></button>)}</div>
      <h3>实时日志</h3><pre className="preview-log">{logs}</pre>
      <p className="muted">已归档用例证据 {preview.evidence_cases?.length||0} 条</p>
      <button className="text-button" onClick={()=>open(preview)}>打开完整检视详情 →</button>
    </aside>}
  </div>;
}
