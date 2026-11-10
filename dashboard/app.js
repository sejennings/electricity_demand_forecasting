const $ = id => document.getElementById(id);
const publicFeed = document.documentElement.dataset.snapshotUrl;
const localUpdates = !publicFeed && ['127.0.0.1', 'localhost'].includes(location.hostname);
let data, selected, loading = false;
const fmt = (v, digits=0) => v == null ? '—' : Number(v).toLocaleString('en-US',{maximumFractionDigits:digits});
const when = (value, compact=false) => new Intl.DateTimeFormat('en-US',{
  timeZone:$('zone').value, month:compact?undefined:'short', day:compact?undefined:'numeric',
  hour:'numeric', minute:compact?undefined:'2-digit', hour12:$('zone').value!=='UTC',
  timeZoneName:compact?undefined:'short'
}).format(new Date(value));
const scoreLabel = status => ({complete:'All hours checked', partial:'Some hours checked', pending:'Waiting for measurements'}[status] || 'Results unavailable');
const jobLabel = status => ({SUCCEEDED:'Completed',FAILED:'Needs attention',TIMED_OUT:'Timed out',RUNNING:'Running',ABORTED:'Stopped',PENDING_REDRIVE:'Awaiting retry'}[status] || 'Unknown');
function text(id,value){$(id).textContent=value;}
function node(tag,content,cls){const n=document.createElement(tag);if(content!=null)n.textContent=content;if(cls)n.className=cls;return n;}
function notice(message, tone='info') { text('notice',message); $('notice').dataset.tone=tone; }
function render(){
  selected=data.runs.find(r=>r.id===$('issue').value);
  if(!selected)return;
  const r=selected, peak=r.rows.reduce((a,b)=>b.forecast_mw>a.forecast_mw?b:a);
  text('peak',fmt(peak.forecast_mw)+' MW');text('peakTime',when(peak.timestamp_utc));
  text('wape',r.metrics.wape_percent==null?'—':fmt(r.metrics.wape_percent,2)+'%');
  text('mae',r.metrics.mae_mw==null?'—':fmt(r.metrics.mae_mw,1)+' MW');text('coverage',r.scored_hours+' of '+r.rows.length);
  text('scoreStatus',r.status==='complete'?'All measurements received':r.pending_hours+' '+(r.pending_hours===1?'hour':'hours')+' still waiting for measurements');
  const ended=Date.parse(r.rows.at(-1).timestamp_utc)+3600000<Date.now();
  text('forecastSummary',`${ended?'This past forecast expected':'This forecast expects'} demand to peak at ${fmt(peak.forecast_mw)} MW. `+
    (r.scored_hours ? `${r.scored_hours} of ${r.rows.length} hours have been checked against measured demand.` : 'Measurements are not available yet, so the error numbers are still blank.'));
  text('issueMeta','Made '+when(r.issue_time_utc)+' · '+scoreLabel(r.status));
  $('hours').replaceChildren(...r.rows.map(row=>{
    const tr=node('tr');[when(row.timestamp_utc),fmt(row.forecast_mw,1),row.actual_mw==null?'Waiting':fmt(row.actual_mw,1),row.actual_mw==null?'—':fmt(row.forecast_mw-row.actual_mw,1)].forEach((v,i)=>tr.append(node('td',v,row.actual_mw==null&&i>1?'pending':'')));return tr;
  }));
  $('provenance').replaceChildren();
  for(const [label,value] of [['Forecast ID',r.id],['Model SHA-256',r.model_sha256],...(publicFeed?[]:[['Image',r.image_uri||'Not recorded']]),['Last checked',r.scored_at_utc?when(r.scored_at_utc):'Waiting for measurements']]){
    const p=node('p');p.append(node('strong',label+': '),document.createTextNode(value));$('provenance').append(p);
  }
  chart(r.rows);
}
function chart(rows){
  const width=Math.max(320,$('chart').clientWidth), right=width-16;
  const ns='http://www.w3.org/2000/svg', svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${width} 290`);svg.style.minWidth='320px';svg.setAttribute('role','img');
  const title=document.createElementNS(ns,'title');title.textContent='Hourly forecast and available actual demand. Exact values appear in the table below.';svg.append(title);
  const values=rows.flatMap(r=>[r.forecast_mw,r.actual_mw]).filter(v=>v!=null), lo=Math.floor(Math.min(...values)*.9/100)*100, hi=Math.ceil(Math.max(...values)*1.06/100)*100;
  const x=i=>65+i*(right-65)/Math.max(1,rows.length-1), y=v=>235-(v-lo)/(hi-lo||1)*210;
  function el(tag,attrs,content){const n=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(content!=null)n.textContent=content;svg.append(n);return n;}
  el('text',{x:65,y:13},'MW');
  for(let i=0;i<5;i++){const value=lo+(hi-lo)*i/4;el('line',{x1:65,x2:right,y1:y(value),y2:y(value),stroke:'#dce4df','stroke-dasharray':'3 5'});el('text',{x:52,y:y(value)+4,'text-anchor':'end'},fmt(value));}
  const step=width<600?6:4;
  rows.forEach((r,i)=>{if(i%step===0)el('text',{x:x(i),y:265,'text-anchor':'middle'},when(r.timestamp_utc,true));});
  for(const [key,color] of [['forecast_mw','#28786d'],['actual_mw','#486fa0']]){
    let path='',gap=true;rows.forEach((r,i)=>{if(r[key]==null){gap=true;return;}path+=(gap?'M':'L')+x(i)+','+y(r[key])+' ';gap=false;});
    el('path',{d:path,fill:'none',stroke:color,'stroke-width':key==='forecast_mw'?3:2.5,'stroke-linejoin':'round','stroke-dasharray':key==='actual_mw'?'7 4':'none'});
    rows.forEach((r,i)=>{if(r[key]!=null){const p=el('circle',{cx:x(i),cy:y(r[key]),r:3,fill:color});const t=document.createElementNS(ns,'title');t.textContent=when(r.timestamp_utc)+' · '+(key==='forecast_mw'?'Forecast':'Actual')+' '+fmt(r[key],1)+' MW';p.append(t);}});
  }
  $('chart').replaceChildren(svg);
}
function validateSnapshot(candidate) {
  if (!candidate || !Number.isFinite(Date.parse(candidate.generated_at_utc)) ||
      !Array.isArray(candidate.runs) || !candidate.runs.length || !Array.isArray(candidate.pipelines)) {
    throw new Error('Invalid snapshot');
  }
  const ids = new Set();
  for (const run of candidate.runs) {
    if (!run.id || ids.has(run.id) || !Number.isFinite(Date.parse(run.issue_time_utc)) ||
        !Number.isFinite(Date.parse(run.origin_utc)) || !run.metrics || !Array.isArray(run.rows) || !run.rows.length ||
        run.scored_hours + run.pending_hours !== run.rows.length) throw new Error('Invalid forecast issue');
    ids.add(run.id);
    for (const row of run.rows) {
      if (!Number.isFinite(Date.parse(row.timestamp_utc)) || !Number.isFinite(row.forecast_mw) || row.forecast_mw <= 0 ||
          (row.actual_mw !== null && (!Number.isFinite(row.actual_mw) || row.actual_mw <= 0))) {
        throw new Error('Invalid hourly demand');
      }
    }
  }
  for (const pipeline of candidate.pipelines) {
    if (typeof pipeline.name !== 'string' || !Array.isArray(pipeline.executions) ||
        pipeline.executions.some(e => !Number.isFinite(Date.parse(e.started_at_utc)))) throw new Error('Invalid pipeline status');
  }
}

function renderOverview() {
  const previousId = selected?.id;
  $('issue').replaceChildren(...data.runs.map(run => {
    const option = node('option', when(run.issue_time_utc) + ' · ' + scoreLabel(run.status));
    option.value = run.id;
    return option;
  }));
  if (data.runs.some(run => run.id === previousId)) $('issue').value = previousId;
  const age = (Date.now() - Date.parse(data.generated_at_utc)) / 3600000;
  const expired = Date.parse(data.runs[0].origin_utc) + data.runs[0].rows.length * 3600000 < Date.now();
  const problems=data.pipelines.some(p=>!p.executions[0] ||
    !['SUCCEEDED','RUNNING'].includes(p.executions[0].status) || Date.now()-Date.parse(p.executions[0].started_at_utc)>36*3600000);
  notice(data.demo
    ? 'Demo · These are made-up examples, not results from the live model.'
    : `${age>24?'The saved data is over a day old. ':''}${expired?'The latest forecast has ended. ':''}${problems?'A daily job needs attention. See the job status below. ':''}${publicFeed?'Data is published twice a day; Refresh data checks for a newer copy.':'This is a saved view. Update from AWS checks for newer results.'}`,
    data.demo?'demo':age>24||expired||problems?'warning':'info');
  text('updated', 'Data updated ' + when(data.generated_at_utc));
  $('pipelines').replaceChildren(...data.pipelines.map(pipeline => {
    const item = node('div', null, 'pipeline');
    const latest = pipeline.executions[0];
    const stale=latest && Date.now()-Date.parse(latest.started_at_utc)>36*3600000;
    item.append(node('strong', pipeline.name.endsWith('ingestion') ? 'Demand & weather updates' : 'Daily forecast'));
    item.append(node('span', stale?'No recent run':jobLabel(latest?.status), 'badge' + (latest?.status === 'SUCCEEDED'&&!stale ? '' : ' bad')));
    item.append(node('small', latest ? 'Last run: '+when(latest.started_at_utc) : 'No runs recorded'));
    const failures=pipeline.executions.filter(e=>['FAILED','TIMED_OUT','ABORTED'].includes(e.status)).length;
    item.append(node('small', failures?`${failures} of the last ${pipeline.executions.length} runs did not complete.`:`No failures in the last ${pipeline.executions.length} recorded runs.`));
    if(latest?.status==='FAILED') item.append(node('small','The job stopped. Previously saved forecasts are still available.'));
    return item;
  }));
  render();
}

async function load() {
  if (loading) return;
  loading = true;
  $('reload').disabled = true;
  $('reload').setAttribute('aria-busy', 'true');
  try {
    const demo = new URLSearchParams(location.search).get('demo') === '1';
    $('sync').hidden = demo || !localUpdates;
    if (publicFeed) $('reload').textContent = 'Refresh data';
    const response = await fetch(demo ? 'demo.json' : (publicFeed || 'snapshot.json'), {cache:'no-store', signal:AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error('No snapshot');
    const candidate = await response.json();
    validateSnapshot(candidate);
    candidate.runs.sort((a,b) => Date.parse(b.issue_time_utc) - Date.parse(a.issue_time_utc));
    data = candidate;
    renderOverview();
  } catch (error) {
    if (selected) {
      notice('We couldn’t refresh the data. The last loaded results are still shown; check their update time.','error');
    } else {
      notice(publicFeed ? 'Forecast data is temporarily unavailable. Try Refresh data again shortly, or take a look at the demo.' : 'No saved forecast is available. Use Update from AWS to load results, or take a look at the demo.','error');
      const link = node('a', 'View demo');
      link.href = '?demo=1';
      $('notice').append(document.createTextNode(' '), link);
    }
  } finally {
    loading = false;
    $('reload').disabled = false;
    $('reload').removeAttribute('aria-busy');
  }
}

async function syncFromAWS() {
  if (loading || $('sync').disabled) return;
  $('sync').disabled = true;
  $('sync').setAttribute('aria-busy', 'true');
  notice('Updating from AWS… This can take up to two minutes.');
  try {
    const response = await fetch('/api/refresh', {
      method:'POST', headers:{'X-GridCast-Refresh':'1'}, signal:AbortSignal.timeout(130000)
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.error || 'AWS updates need the GridCast dashboard launcher.');
    }
    await load();
  } catch (error) {
    notice((error.name === 'TimeoutError' ? 'AWS update timed out.' : error.message) + ' Showing the saved view.','error');
  } finally {
    $('sync').disabled = false;
    $('sync').removeAttribute('aria-busy');
  }
}

$('sync').addEventListener('click', syncFromAWS);
$('issue').addEventListener('change', render);
$('zone').addEventListener('change', () => { if (data) renderOverview(); });
$('reload').addEventListener('click', load);
window.addEventListener('resize', () => { if (selected) chart(selected.rows); });
$('download').addEventListener('click',()=>{
  if(!selected)return;
  const fields=['timestamp_utc','horizon_hours','forecast_mw','actual_mw'];
  const csv=[fields.join(','),...selected.rows.map(r=>fields.map(f=>r[f]??'').join(','))].join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));const a=node('a');a.href=url;a.download='gridcast-'+selected.id+'.csv';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
});load();
