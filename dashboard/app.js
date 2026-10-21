const $ = id => document.getElementById(id);
let data, selected;
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
  text('scoreStatus',r.status==='complete'?'All actuals available':r.pending_hours+' hours awaiting actuals');
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
  const ns='http://www.w3.org/2000/svg', svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 1000 290');svg.setAttribute('role','img');
  const title=document.createElementNS(ns,'title');title.textContent='Hourly forecast and available actual demand. Exact values appear in the table below.';svg.append(title);
  const values=rows.flatMap(r=>[r.forecast_mw,r.actual_mw]).filter(v=>v!=null), lo=Math.floor(Math.min(...values)*.9/100)*100, hi=Math.ceil(Math.max(...values)*1.06/100)*100;
  const x=i=>65+i*910/Math.max(1,rows.length-1), y=v=>235-(v-lo)/(hi-lo||1)*210;
  function el(tag,attrs,content){const n=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(content!=null)n.textContent=content;svg.append(n);return n;}
  for(let i=0;i<5;i++){const value=lo+(hi-lo)*i/4;el('line',{x1:65,x2:975,y1:y(value),y2:y(value),stroke:'#e7ece3','stroke-dasharray':'3 5'});el('text',{x:52,y:y(value)+4,'text-anchor':'end'},fmt(value));}
  rows.forEach((r,i)=>{if(i%4===0||i===rows.length-1)el('text',{x:x(i),y:265,'text-anchor':'middle'},when(r.timestamp_utc,true));});
  for(const [key,color] of [['forecast_mw','#167d68'],['actual_mw','#ce8350']]){
    let path='',gap=true;rows.forEach((r,i)=>{if(r[key]==null){gap=true;return;}path+=(gap?'M':'L')+x(i)+','+y(r[key])+' ';gap=false;});
    el('path',{d:path,fill:'none',stroke:color,'stroke-width':key==='forecast_mw'?3:2.5,'stroke-linejoin':'round'});
    rows.forEach((r,i)=>{if(r[key]!=null){const p=el('circle',{cx:x(i),cy:y(r[key]),r:3,fill:color});const t=document.createElementNS(ns,'title');t.textContent=when(r.timestamp_utc)+' · '+(key==='forecast_mw'?'Forecast':'Actual')+' '+fmt(r[key],1)+' MW';p.append(t);}});
  }
  $('chart').replaceChildren(svg);
}
async function load(){
  try{
    const demo=new URLSearchParams(location.search).get('demo')==='1';
    const response=await fetch(demo?'demo.json':'snapshot.json',{cache:'no-store'});
    if(!response.ok)throw new Error('No snapshot');
    data=await response.json();
    if(!data.runs?.length)throw new Error('No forecast issues available');
    data.runs.sort((a,b)=>Date.parse(b.issue_time_utc)-Date.parse(a.issue_time_utc));
    $('issue').replaceChildren(...data.runs.map(r=>{const o=node('option',when(r.issue_time_utc)+' · '+r.status);o.value=r.id;return o;}));
    const age=(Date.now()-Date.parse(data.generated_at_utc))/3600000;
    text('notice',data.demo?'DEMO DATA · Illustrative values only. This is not GridCast production performance.':`Stored AWS snapshot · ${age>24?'More than 24 hours old. ':''}Accuracy includes observed hours only; missing actuals stay pending.`);
    text('updated','Snapshot: '+when(data.generated_at_utc)+' '+$('zone').value);
    $('pipelines').replaceChildren(...data.pipelines.map(p=>{
      const item=node('div',null,'pipeline'), latest=p.executions[0];item.append(node('strong',p.name.replace('gridcast-','')==='ingestion'?'Demand & weather imports':'Daily forecast'));
      item.append(node('span',latest?.status||'UNKNOWN','badge'+(latest?.status==='SUCCEEDED'?'':' bad')));
      item.append(node('small',latest?when(latest.started_at_utc)+' '+$('zone').value:'No executions recorded'));
      item.append(node('small',p.executions.map(e=>e.status==='SUCCEEDED'?'✓':e.status==='FAILED'?'×':'·').join('  ')+'  Recent executions, newest first'));return item;
    }));render();
  }catch(error){text('notice','No forecast snapshot available. Export a snapshot to view real results, or open the clearly labeled demo.');const a=node('a','View demo');a.href='?demo=1';$('notice').append(document.createTextNode(' '),a);}
}
$('issue').addEventListener('change',render);$('zone').addEventListener('change',()=>{const id=selected?.id;load().then(()=>{if(id){$('issue').value=id;render();}});});$('reload').addEventListener('click',load);
$('download').addEventListener('click',()=>{
  if(!selected)return;
  const fields=['timestamp_utc','horizon_hours','forecast_mw','actual_mw'];
  const csv=[fields.join(','),...selected.rows.map(r=>fields.map(f=>r[f]??'').join(','))].join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));const a=node('a');a.href=url;a.download='gridcast-'+selected.id+'.csv';a.click();URL.revokeObjectURL(url);
});load();
