const $ = id => document.getElementById(id);
const publicFeed = document.documentElement.dataset.snapshotUrl;
const localUpdates = !publicFeed && ['127.0.0.1', 'localhost'].includes(location.hostname);
let data, selected, loading = false;
const fmt = (v, digits=0) => v == null ? '—' : Number(v).toLocaleString('en-US',{maximumFractionDigits:digits});
const when = (value, compact=false) => new Intl.DateTimeFormat('en-US',{timeZone:$('zone').value,month:'short',day:'numeric',hour:'2-digit',minute:compact?undefined:'2-digit',hour12:false}).format(new Date(value));
function text(id,value){$(id).textContent=value;}
function node(tag,content,cls){const n=document.createElement(tag);if(content!=null)n.textContent=content;if(cls)n.className=cls;return n;}
function render(){
  selected=data.runs.find(r=>r.id===$('issue').value);
  if(!selected)return;
  const r=selected, peak=r.rows.reduce((a,b)=>b.forecast_mw>a.forecast_mw?b:a);
  text('peak',fmt(peak.forecast_mw)+' MW');text('peakTime',when(peak.timestamp_utc)+' · '+$('zone').value);
  text('wape',r.metrics.wape_percent==null?'—':fmt(r.metrics.wape_percent,2)+'%');
  text('mae',fmt(r.metrics.mae_mw,1));text('coverage',r.scored_hours+' / '+r.rows.length);
  text('scoreStatus',r.status==='complete'?'All actuals available':r.pending_hours+' '+(r.pending_hours===1?'hour':'hours')+' awaiting actuals');
  text('issueMeta','Issued '+when(r.issue_time_utc)+' · '+$('zone').value+' · '+r.status+' scoring');
  $('hours').replaceChildren(...r.rows.map(row=>{
    const tr=node('tr');[when(row.timestamp_utc),fmt(row.forecast_mw,1),row.actual_mw==null?'Pending':fmt(row.actual_mw,1),row.actual_mw==null?'—':fmt(row.forecast_mw-row.actual_mw,1)].forEach((v,i)=>tr.append(node('td',v,row.actual_mw==null&&i>1?'pending':'')));return tr;
  }));
  $('provenance').replaceChildren();
  for(const [label,value] of [['Issue ID',r.id],['Model SHA-256',r.model_sha256],['Image',r.image_uri||'Not recorded'],['Scored at',r.scored_at_utc?when(r.scored_at_utc):'Awaiting actuals']]){
    const p=node('p');p.append(node('strong',label+': '),document.createTextNode(value));$('provenance').append(p);
  }
  chart(r.rows);
}
function chart(rows){
  const width=Math.max(540,$('chart').clientWidth), right=width-25;
  const ns='http://www.w3.org/2000/svg', svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${width} 290`);svg.style.minWidth='540px';svg.setAttribute('role','img');
  const title=document.createElementNS(ns,'title');title.textContent='Hourly forecast and available actual demand. Exact values appear in the table below.';svg.append(title);
  const values=rows.flatMap(r=>[r.forecast_mw,r.actual_mw]).filter(v=>v!=null), lo=Math.floor(Math.min(...values)*.9/100)*100, hi=Math.ceil(Math.max(...values)*1.06/100)*100;
  const x=i=>65+i*(right-65)/Math.max(1,rows.length-1), y=v=>235-(v-lo)/(hi-lo||1)*210;
  function el(tag,attrs,content){const n=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(content!=null)n.textContent=content;svg.append(n);return n;}
  for(let i=0;i<5;i++){const value=lo+(hi-lo)*i/4;el('line',{x1:65,x2:right,y1:y(value),y2:y(value),stroke:'#2a3d57','stroke-dasharray':'3 5'});el('text',{x:52,y:y(value)+4,'text-anchor':'end'},fmt(value));}
  rows.forEach((r,i)=>{if(i%4===0||i===rows.length-1)el('text',{x:x(i),y:265,'text-anchor':'middle'},when(r.timestamp_utc,true));});
  for(const [key,color] of [['forecast_mw','#ffce32'],['actual_mw','#61b9ff']]){
    let path='',gap=true;rows.forEach((r,i)=>{if(r[key]==null){gap=true;return;}path+=(gap?'M':'L')+x(i)+','+y(r[key])+' ';gap=false;});
    el('path',{d:path,fill:'none',stroke:color,'stroke-width':key==='forecast_mw'?3:2.5,'stroke-linejoin':'round'});
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
    const option = node('option', when(run.issue_time_utc) + ' · ' + run.status);
    option.value = run.id;
    return option;
  }));
  if (data.runs.some(run => run.id === previousId)) $('issue').value = previousId;
  const age = (Date.now() - Date.parse(data.generated_at_utc)) / 3600000;
  const expired = Date.parse(data.runs[0].origin_utc) + data.runs[0].rows.length * 3600000 < Date.now();
  text('notice', data.demo
    ? 'DEMO DATA · Illustrative values only. This is not GridCast production performance.'
    : `${publicFeed ? 'AWS data · Updated twice daily. ' : 'Stored AWS snapshot · '}${age > 24 ? 'Snapshot is more than 24 hours old. ' : ''}${expired ? 'The latest available forecast horizon has ended. ' : ''}Accuracy includes observed hours only; missing actuals stay pending.`);
  text('updated', 'Snapshot: ' + when(data.generated_at_utc) + ' ' + $('zone').value);
  $('pipelines').replaceChildren(...data.pipelines.map(pipeline => {
    const item = node('div', null, 'pipeline');
    const latest = pipeline.executions[0];
    item.append(node('strong', pipeline.name.endsWith('ingestion') ? 'Demand & weather imports' : 'Daily forecast'));
    item.append(node('span', latest?.status || 'UNKNOWN', 'badge' + (latest?.status === 'SUCCEEDED' ? '' : ' bad')));
    item.append(node('small', latest ? when(latest.started_at_utc) + ' ' + $('zone').value : 'No executions recorded'));
    item.append(node('small', pipeline.executions.map(e => e.status === 'SUCCEEDED' ? '✓' : e.status === 'FAILED' ? '×' : '·').join('  ') + '  Recent executions, newest first'));
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
      text('notice', 'Snapshot refresh failed. Showing the last loaded snapshot; data may be out of date.');
    } else {
      text('notice', publicFeed ? 'Forecast data is temporarily unavailable. Try Refresh data again shortly, or explore the clearly labeled demo.' : 'No valid forecast snapshot available. Export a snapshot to view real results, or open the clearly labeled demo.');
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
  text('notice', 'Updating from AWS… This can take up to two minutes.');
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
    text('notice', (error.name === 'TimeoutError' ? 'AWS update timed out.' : error.message) + ' Showing the saved snapshot.');
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
