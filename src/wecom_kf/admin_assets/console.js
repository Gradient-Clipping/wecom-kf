// Pure view model: no inferred success, synthetic percent, or HTML from the API.
function jobProgressModel(job = {}) {
  const p = job.progress || {}, solve = job.kind === 'solve';
  const count = v => typeof v === 'number' && Number.isFinite(v) && v >= 0 && Number.isInteger(v);
  const pairs = [['关卡', p.passed_challenges, p.total_challenges], ['作业', p.passed_homeworks, p.total_homeworks], ['单元', p.passed_units, p.total_units]];
  const pair = p.unknown === true ? null : pairs.find(([, done, total]) => count(done) && count(total) && total > 0 && done <= total);
  const failures = Array.isArray(p.failures) ? p.failures.filter(v => typeof v === 'string' && v.trim()) : null;
  const reportedUnknown = p.unknown === true || p.unknown === false ? p.unknown : (pair ? false : null);
  const failed = job.status === 'failed' || p.has_error === true || !!failures?.length;
  return {
    solve, known: solve && !!pair, done: pair?.[1], total: pair?.[2],
    percent: pair ? Math.floor(pair[1] / pair[2] * 100) : null,
    summary: !solve ? '账号验证 · 无做题进度' : pair ? `${pair[0]}已通过 ${pair[1]} / ${pair[2]}` : '进度未知 · 等待上报',
    current: typeof p.current === 'string' && p.current.trim() ? p.current : (job.status === 'queued' ? '排队等待执行' : '当前步骤未上报'),
    unknown: reportedUnknown, failed, error: job.status === 'failed' ? '任务出错' : p.has_error === true ? '执行出错' : failures?.length ? `存在 ${failures.length} 条失败记录` : p.has_error === false ? '暂无错误记录' : '错误状态未上报',
    failures: failures || []
  };
}
if (typeof module !== 'undefined' && module.exports) module.exports = { jobProgressModel };
(() => {
  if (typeof document === 'undefined') return;
  const $ = (s) => document.querySelector(s), esc = (v) => { const d = document.createElement('div'); d.textContent = v == null ? '' : String(v); return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;'); };
  const pages = new Set(['overview','jobs','bindings','settings']);
  const state = { page: 1, pageSize: 20, activePage: 'overview', timer: null, syncing: false, syncQueued: false, posting: false, jobsSeq: 0, bindingsSeq: 0, detailSeq: 0, filters: new URLSearchParams(), metadata: null, bindingQuery: null, detailId: null };
  // Adapted from SecMind's ControlStarfield: a dependency-free canvas layer
  // keeps the admin shell lightweight while preserving its nebula/constellation
  // feel. It is decorative only and never intercepts pointer events.
  function initNebula(){
    const canvas=$('#nebula-canvas');
    if(!canvas||!canvas.getContext)return;
    const context=canvas.getContext('2d');
    if(!context)return;
    const reduceMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
    const palette={white:'62, 104, 140',cyan:'22, 133, 178'}, lerp=(a,b,t)=>a+(b-a)*t;
    const seeded=(seed)=>{let s=seed>>>0;return()=>{s+=0x6d2b79f5;let v=s;v=Math.imul(v^(v>>>15),v|1);v^=v+Math.imul(v^(v>>>7),v|61);return((v^(v>>>14))>>>0)/4294967296;}};
    const sprite=(rgb)=>{const c=document.createElement('canvas'),size=64,r=size/2;c.width=size;c.height=size;const x=c.getContext('2d'),g=x.createRadialGradient(r,r,0,r,r,r);g.addColorStop(0,`rgba(${rgb},1)`);g.addColorStop(.18,`rgba(${rgb},.94)`);g.addColorStop(.42,`rgba(${rgb},.48)`);g.addColorStop(.72,`rgba(${rgb},.12)`);g.addColorStop(1,`rgba(${rgb},0)`);x.fillStyle=g;x.fillRect(0,0,size,size);return c;};
    const sprites={white:sprite(palette.white),cyan:sprite(palette.cyan)};
    const pointer={active:false,targetX:0,targetY:0,x:0,y:0};let width=0,height=0,stars=[],animationId=0,lastTime=0,isVisible=!document.hidden;
    const countFor=(w)=>w<=430?74:w<=744?108:w<=1180?146:184;
    const build=()=>{const random=seeded((width*73856093)^(height*19349663));stars=Array.from({length:countFor(width)},()=>{const depth=random(),orbit=lerp(.08,.58,Math.pow(random(),.7));return{angle:random()*Math.PI*2,color:random()<.24?'cyan':'white',depth,orbitRadiusX:width*orbit,orbitRadiusY:height*orbit*lerp(.76,1.08,random()),orbitSpeed:lerp(.08,.24,random()),pulsePhase:random()*Math.PI*2,pulseSpeed:lerp(1.8,5.2,random()),size:lerp(.82,1.5,random())*lerp(.78,1.2,depth),sparkle:random()>.94};});};
    const resize=()=>{width=canvas.clientWidth;height=canvas.clientHeight;const ratio=Math.min(window.devicePixelRatio||1,2);canvas.width=Math.max(1,Math.floor(width*ratio));canvas.height=Math.max(1,Math.floor(height*ratio));context.setTransform(ratio,0,0,ratio,0,0);build();};
    const draw=(time,staticFrame=false)=>{const elapsed=staticFrame?0:time*.001,cx=width*.56,cy=height*.5;context.clearRect(0,0,width,height);context.save();context.globalCompositeOperation='screen';const cloud=context.createRadialGradient(width*.74,height*.19,0,width*.74,height*.19,Math.max(width,height)*.58);cloud.addColorStop(0,'rgba(83,201,235,.20)');cloud.addColorStop(.32,'rgba(52,164,211,.10)');cloud.addColorStop(1,'rgba(52,164,211,0)');context.fillStyle=cloud;context.fillRect(0,0,width,height);const cloud2=context.createRadialGradient(width*.22,height*.76,0,width*.22,height*.76,Math.max(width,height)*.48);cloud2.addColorStop(0,'rgba(112,180,238,.12)');cloud2.addColorStop(.36,'rgba(69,142,204,.06)');cloud2.addColorStop(1,'rgba(69,142,204,0)');context.fillStyle=cloud2;context.fillRect(0,0,width,height);context.globalCompositeOperation='lighter';pointer.x=lerp(pointer.x,pointer.active?pointer.targetX:0,.035);pointer.y=lerp(pointer.y,pointer.active?pointer.targetY:0,.035);stars.forEach(star=>{const angle=star.angle-elapsed*star.orbitSpeed,parallax=lerp(3,16,star.depth),x=cx+Math.cos(angle)*star.orbitRadiusX+pointer.x*parallax,y=cy+Math.sin(angle)*star.orbitRadiusY+pointer.y*parallax;if(x<-30||x>width+30||y<-30||y>height+30)return;const pulse=staticFrame?.62:.5+.5*Math.sin(elapsed*star.pulseSpeed+star.pulsePhase),brightness=lerp(.32,1,pulse),core=star.size*lerp(.86,1.3,brightness),halo=core*lerp(7.5,11,star.depth),rgb=palette[star.color];context.globalAlpha=brightness*lerp(.48,.78,star.depth);context.drawImage(sprites[star.color],x-halo/2,y-halo/2,halo,halo);context.globalAlpha=brightness*lerp(.72,1,star.depth);context.fillStyle=`rgb(${rgb})`;context.beginPath();context.arc(x,y,core,0,Math.PI*2);context.fill();if(star.sparkle&&brightness>.7){const ray=core*4.5;context.globalAlpha=(brightness-.7)*.72;context.strokeStyle=`rgb(${rgb})`;context.lineWidth=.55;context.beginPath();context.moveTo(x-ray,y);context.lineTo(x+ray,y);context.moveTo(x,y-ray);context.lineTo(x,y+ray);context.stroke();}});context.restore();};
    const animate=(time)=>{if(!isVisible||reduceMotion.matches)return;if(!lastTime||time-lastTime>=(width<=744?32:16)){draw(time);lastTime=time;}animationId=requestAnimationFrame(animate);};
    const restart=()=>{cancelAnimationFrame(animationId);lastTime=0;resize();draw(0,true);if(isVisible&&!reduceMotion.matches)animationId=requestAnimationFrame(animate);};
    const handlePointerMove=(event)=>{pointer.targetX=event.clientX/Math.max(width,1)-.5;pointer.targetY=event.clientY/Math.max(height,1)-.5;pointer.active=true;};
    const handlePointerOut=(event)=>{if(!event.relatedTarget)pointer.active=false;};
    const handleVisibility=()=>{isVisible=!document.hidden;restart();};
    const observer=new ResizeObserver(restart);observer.observe(canvas);reduceMotion.addEventListener('change',restart);document.addEventListener('visibilitychange',handleVisibility);window.addEventListener('pointermove',handlePointerMove,{passive:true});window.addEventListener('pointerout',handlePointerOut);restart();
  }
  const entry = (group, code) => (state.metadata?.[group] || []).find(item => item.code === code);
  const label = (group, code, fallback='未知') => esc(entry(group, code)?.label || code || fallback);
  const serviceName = (code) => esc(entry('services', code)?.name || code || '未记录');
  const statusTone = (code) => { const tone=entry('job_statuses', code)?.tone; return ['good','warn','bad'].includes(tone)?tone:''; };
  async function loadMetadata(){
    if(state.metadata)return;
    const data=await api('/admin/api/metadata');
    state.metadata=data;
    for(const [name,group,title] of [['status','job_statuses','全部状态'],['kind','job_kinds','全部类型']]){
      const select=$(`#job-filters select[name="${name}"]`), value=select.value;
      select.innerHTML=`<option value="">${title}</option>`+(data[group]||[]).filter(item=>item.filterable!==false).map(item=>`<option value="${esc(item.code)}">${esc(item.label||item.code)}</option>`).join('');
      select.value=value;select.disabled=false;
    }
  }
  const fmtTime = (v) => v ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'medium',timeStyle:'short'}).format(new Date(Number(v)*1000)) : '—';
  const showAlert = (msg, bad=true) => { const el=$('#alert'); el.textContent=msg; el.hidden=!msg; el.className='alert '+(bad?'':'ok'); };
  const api = async (url) => { const r=await fetch(url,{credentials:'same-origin',headers:{Accept:'application/json'}}); if(r.status===401){ location.href='/admin'; throw new Error('session_expired'); } if(!r.ok) throw new Error('data_unavailable'); return r.json(); };
  function progress(job){
    const p=jobProgressModel(job), name=job.account||job.customer_id||'任务';
    const bar=p.solve?`<progress class="job-progress-bar ${p.failed?'has-error':''}" max="${p.known?p.total:100}" ${p.known?`value="${p.done}"`:''} aria-label="${esc(name)}：${esc(p.summary)}" aria-valuetext="${esc(p.summary)}"></progress>`:'';
    const failure = p.failures.length ? `<div class="progress-error"><strong>失败原因：</strong>${esc(p.failures[0])}</div>` : '';
    return `<div class="job-progress"><div class="progress-user">${esc(name)}</div><div class="progress-caption"><span>${esc(p.summary)}</span>${p.known?`<strong>${p.percent}%</strong>`:''}</div>${bar}<div class="progress-current">${esc(p.current)}</div><span class="badge ${p.failed?'bad':p.error==='错误状态未上报'||p.unknown===true?'warn':'good'}">${esc(p.error)}</span>${failure}</div>`;
  }
  function renderOverview(d){
    const counts=d.counts||[], total=counts.reduce((a,x)=>a+Number(x.count||0),0), active=counts.filter(x=>entry('job_statuses',x.status)?.group==='active').reduce((a,x)=>a+Number(x.count||0),0), ended=counts.filter(x=>entry('job_statuses',x.status)?.group==='ended').reduce((a,x)=>a+Number(x.count||0),0);
    $('#metric-grid').innerHTML=[['全部任务',total,'全库统计'],['进行中',active,'排队 + 运行中'],['已结束',ended,'完成状态，不代表业务成功'],['已绑定账号',Number(d.bindings||0),'全库绑定数量']].map(x=>`<div class="metric-card"><div class="metric-label">${x[0]}</div><div class="metric-value">${x[1]}</div><div class="metric-note">${x[2]}</div></div>`).join('');
    $('#status-summary').innerHTML=counts.length?counts.map(x=>`<div class="status-line"><span>${label('job_kinds',x.kind,'任务')} · ${label('job_statuses',x.status)}</span><strong>${Number(x.count||0)}</strong></div>`).join(''):'<div class="empty">暂无任务状态</div>';
    $('#workers').innerHTML=(d.workers||[]).length?(d.workers||[]).map(w=>{const known=w.heartbeat!=null, healthy=known&&w.healthy!==false&&(Date.now()/1000-Number(w.heartbeat)<300);return `<div class="worker-line"><span>${esc(w.role||'未命名')}</span><span class="badge ${!known?'warn':healthy?'good':'bad'}">${!known?'未知/未上报':healthy?'正常':'心跳延迟'}</span></div>`}).join(''):'<div class="empty">暂无心跳上报</div>';
    $('#system-health').textContent=!(d.workers||[]).length?'暂无进程心跳':d.workers.some(w=>w.heartbeat==null)?'存在未上报进程':d.workers.some(w=>w.healthy===false||Date.now()/1000-Number(w.heartbeat)>=300)?'存在心跳延迟':'已上报进程心跳正常';
    $('#replies').innerHTML=(d.replies||[]).length?(d.replies||[]).map(x=>`<div class="reply-line"><span>${label('reply_statuses',x.status)}</span><strong>${Number(x.count||0)}</strong></div>`).join(''):'<div class="empty">暂无消息记录</div>';
    renderSettings(d);
  }
  function renderSettings(d){if(state.posting || $('#services').contains(document.activeElement))return;const rows=[...(state.metadata?.services||[]).map(s=>{const current=(d.services||[]).find(item=>item.code===s.code);return {...s,enabled:current?!!current.enabled:null};}),{code:'human-support',name:'人工客服',enabled:typeof d.human_support_enabled==='boolean'?d.human_support_enabled:null}];$('#services').innerHTML=rows.length?rows.map(s=>`<div class="setting-card"><div><strong>${esc(s.name)}</strong><div class="muted">${s.enabled===null?'状态未上报':s.enabled?'已开启':'已关闭'}</div></div><label class="switch"><input type="checkbox" aria-label="${esc(s.name)}开关" data-service="${esc(s.code)}" ${s.enabled?'checked':''} ${s.enabled===null?'disabled':''}><span class="slider"></span></label></div>`).join(''):'<div class="empty">暂无可配置服务</div>';}
  async function loadOverview(){await loadMetadata();const d=await api('/admin/api/overview');renderOverview(d);return d;}
  async function loadJobs(){const seq=++state.jobsSeq, f=state.filters, p=new URLSearchParams({page:String(state.page),page_size:String(state.pageSize)});for(const [k,v] of f){if(!v)continue;if(k==='from'){p.set(k,String(Math.floor(new Date(v+'T00:00:00+08:00').getTime()/1000)));}else if(k==='to'){p.set(k,String(Math.floor(new Date(v+'T23:59:59+08:00').getTime()/1000)));}else p.set(k,v);}const d=await api('/admin/api/jobs?'+p);if(seq!==state.jobsSeq)return;state.page=Number(d.page||1);$('#jobs-body').innerHTML=(d.items||[]).length?d.items.map(j=>`<tr><td><strong>${esc(j.id)}</strong></td><td>${esc(j.customer_id||'—')}</td><td>${label('job_kinds',j.kind)}</td><td><span class="badge ${statusTone(j.status)}">${label('job_statuses',j.status)}</span></td><td>${progress(j)}</td><td>${fmtTime(j.updated_at)}</td><td><button class="btn btn-ghost detail-btn" aria-label="查看任务 ${esc(j.id)}" data-id="${esc(j.id)}">查看</button></td></tr>`).join(''):'<tr><td colspan="7" class="empty">没有匹配任务</td></tr>';const pages=Number(d.pages||1);$('#pager').innerHTML=`<button data-page="${Math.max(1,state.page-1)}" ${state.page<=1?'disabled':''}>上一页</button><span class="muted">第 ${state.page} / ${pages} 页 · 筛选结果 ${d.total||0} 条</span><button data-page="${Math.min(pages,state.page+1)}" ${state.page>=pages?'disabled':''}>下一页</button>`;}
  async function loadBindings(q){const seq=++state.bindingsSeq;const d=await api('/admin/api/bindings?q='+encodeURIComponent(q||''));if(seq!==state.bindingsSeq)return;$('#bindings-body').innerHTML=(d.items||[]).length?d.items.map(b=>`<tr><td>${esc(b.customer_id)}</td><td>${esc(b.account||'—')}</td><td>${esc(b.login_no||'—')}</td><td>${esc(b.external_userid||'—')}</td><td>${fmtTime(b.created_at)}</td><td><form class="unbind-form" data-customer="${esc(b.customer_id)}"><input name="login_no" maxlength="128" placeholder="输入登录号确认" required><button class="btn btn-ghost" type="submit">解绑</button></form></td></tr>`).join(''):'<tr><td colspan="6" class="empty">暂无匹配绑定</td></tr>';}
  async function detail(id){const seq=++state.detailSeq;const d=await api('/admin/api/jobs/'+encodeURIComponent(id)),j=d.job||{};if(seq!==state.detailSeq)return;state.detailId=id;const model=jobProgressModel(j), failures=Array.isArray(j.progress?.failures)?j.progress.failures.filter(x=>typeof x==='string'&&x.trim()):[];const failureHtml=failures.length?failures.map((x,i)=>`<p class="failure-detail"><strong>失败 ${i+1}</strong><span>${esc(x)}</span></p>`).join(''):'<p class="failure-empty">当前任务没有失败记录</p>';$('#drawer-body').innerHTML=`<div class="detail-row"><span>任务 ID</span><strong>${esc(j.id)}</strong></div><div class="detail-row"><span>状态</span><strong>${label('job_statuses',j.status)}</strong></div><div class="detail-row"><span>任务类型</span><strong>${label('job_kinds',j.kind)}</strong></div><div class="detail-row"><span>服务</span><strong>${serviceName(j.service)}</strong></div><div class="detail-row"><span>账号</span><strong>${esc(j.account||'未记录')}</strong></div><div class="detail-row"><span>客户</span><strong>${esc(j.customer_id||'—')}</strong></div><div class="detail-row"><span>进度</span>${progress(j)}</div><div class="detail-row"><span>当前步骤</span><span>${esc(model.current)}</span></div><div class="detail-row"><span>通过关卡</span><span>${esc(j.progress?.passed_challenges??"未知")} / ${esc(j.progress?.total_challenges??"总数未知")}</span></div><div class="detail-row failure-row"><span>失败原因</span><div class="failure-details">${failureHtml}</div></div><p class="muted">任务已结束不代表业务成功，请结合持久化进度与失败原因判断。</p><div class="detail-row"><span>创建时间</span><span>${fmtTime(j.created_at)}</span></div><div class="detail-row"><span>更新时间</span><span>${fmtTime(j.updated_at)}</span></div>`;$('#job-drawer').classList.add('open');$('#drawer-backdrop').classList.add('open');$('#job-drawer').setAttribute('aria-hidden','false');}
  async function loadActivePage(page=state.activePage){
    await loadMetadata();
    if(page==='overview'||page==='settings')return loadOverview();
    if(page==='jobs')return loadJobs();
    if(page==='bindings'&&state.bindingQuery!==null)return loadBindings(state.bindingQuery);
  }
  async function sync(){
    if(state.posting)return;
    if(state.syncing){state.syncQueued=true;return;}
    state.syncing=true;state.syncQueued=false;
    const page=state.activePage;
    $('#sync-status').textContent='同步中…';
    try{await loadActivePage(page);if(page==='overview')$('#last-success').textContent='最近成功：'+fmtTime(Date.now()/1000);$('#sync-status').textContent='已同步';}
    catch(e){$('#sync-status').textContent='同步失败 · 显示上次数据';showAlert(e.message==='session_expired'?'会话已过期，正在跳转登录':'数据暂不可用，请稍后重试');}
    finally{state.syncing=false;if(state.syncQueued||page!==state.activePage){state.syncQueued=false;queueMicrotask(sync);}}
  }

  // Keep submitted queries separate from editable form values.
  const run = async (button, action, message) => {
    if(button)button.disabled=true;
    showAlert('');
    try { await action(); } catch(e) { showAlert(message+'；请重试。'); }
    finally { if(button)button.disabled=false; }
  };
  async function post(url, body) {
    body.set('csrf',$('meta[name="csrf-token"]').content);
    const r=await fetch(url,{method:'POST',body,credentials:'same-origin'});
    if(!r.ok)throw new Error('operation_failed');
    // A successful 303 follows to the authenticated shell; fetch never navigates this page.
    if(r.redirected && !['/','/admin','/admin/'].includes(new URL(r.url).pathname))throw new Error('session_expired');
  }
  $('#refresh-btn').addEventListener('click',e=>run(e.target,sync,'刷新失败'));
  function submitJobs(button) {
    state.page=1;state.filters=new URLSearchParams(new FormData($('#job-filters')));
    return run(button,loadJobs,'任务查询失败，仍显示上次结果');
  }
  $('#job-filters').addEventListener('submit',e=>{e.preventDefault();submitJobs(e.submitter);});
  $('#clear-filters').addEventListener('click',e=>{$('#job-filters').reset();submitJobs(e.target);});
  $('#pager').addEventListener('click',e=>{
    if(!e.target.dataset.page)return;
    const previous=state.page;state.page=Number(e.target.dataset.page);
    run(e.target,async()=>{try{await loadJobs();}catch(error){state.page=previous;throw error;}},'分页失败');
  });
  $('#jobs-body').addEventListener('click',e=>{if(e.target.dataset.id)run(e.target,()=>detail(e.target.dataset.id),'任务详情不可用');});
  $('#binding-form').addEventListener('submit',e=>{e.preventDefault();state.bindingQuery=String(new FormData(e.target).get('q')||'');run(e.submitter,()=>loadBindings(state.bindingQuery),'绑定查询失败');});
  $('#bindings-body').addEventListener('submit',e=>{
    if(!e.target.classList.contains('unbind-form'))return;
    e.preventDefault();
    if(state.posting||!confirm('解绑将移除当前客户关联，是否继续？'))return;
    const form=e.target, body=new URLSearchParams(new FormData(form));
    state.posting=true;
    run(e.submitter,async()=>{
      try {await post('/admin/bindings/'+encodeURIComponent(form.dataset.customer)+'/delete',body);showAlert('解绑成功',false);await loadBindings(state.bindingQuery||'');}
      finally {state.posting=false;}
    },'解绑失败，请检查登录号、会话或任务状态');
  });
  $('#services').addEventListener('change',e=>{
    const input=e.target;if(!input.dataset.service)return;
    if(state.posting){input.checked=!input.checked;return;}
    const intended=input.checked;
    state.posting=true;
    const body=new URLSearchParams({enabled:intended?'1':'0'});
    const url=input.dataset.service==='human-support'?'/admin/human-support':'/admin/services/'+encodeURIComponent(input.dataset.service);
    run(input,async()=>{
      try {await post(url,body);input.closest('.setting-card').querySelector('.muted').textContent=intended?'已开启':'已关闭';showAlert('设置已保存',false);}
      catch(error){input.checked=!intended;throw error;}
      finally {state.posting=false;}
    },'设置保存失败，已恢复原状态');
  });
  function closeDrawer(){++state.detailSeq;$('#job-drawer').classList.remove('open');$('#drawer-backdrop').classList.remove('open');$('#job-drawer').setAttribute('aria-hidden','true');}
  $('#drawer-close').addEventListener('click',closeDrawer);
  $('#drawer-backdrop').addEventListener('click',closeDrawer);
  function closeMenu(){ $('.sidebar').classList.remove('open'); $('.menu-toggle').setAttribute('aria-expanded','false'); }
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeDrawer();closeMenu();}});
  $('.menu-toggle').setAttribute('aria-expanded','false');
  $('.menu-toggle').addEventListener('click',()=>{
    const open=$('.sidebar').classList.toggle('open');
    $('.menu-toggle').setAttribute('aria-expanded',String(open));
  });
  function routePage(){
    const requested=location.hash.slice(1), page=pages.has(requested)?requested:'overview';
    if(!pages.has(requested))history.replaceState(null,'','#'+page);
    state.activePage=page;
    document.querySelectorAll('.app-page').forEach(section=>{section.hidden=section.dataset.page!==page;});
    document.querySelectorAll('.nav-item').forEach(item=>{
      const active=item.dataset.page===page;
      item.classList.toggle('active',active);
      if(active)item.setAttribute('aria-current','page');else item.removeAttribute('aria-current');
    });
    if(page!=='jobs')closeDrawer();
    closeMenu();
    $('#main-content').focus({preventScroll:true});
  }
  $('.sidebar nav').addEventListener('click',e=>{if(e.target.closest('a'))closeMenu();});
  window.addEventListener('hashchange',()=>{routePage();sync();});
  function autoSync(){
    const paused=document.visibilityState!=='visible'||$('#job-drawer').classList.contains('open')||state.posting||document.activeElement?.matches('input,select');
    $('#sync-note').textContent=paused?'· 操作期间暂停':'';
    if(!paused)sync();
  }
  initNebula();routePage();sync();state.timer=setInterval(autoSync,15000);
  document.addEventListener('visibilitychange',autoSync);
})();
