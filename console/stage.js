'use strict';
/* TRINITY stage HUD. Reads the same read-only endpoints as the workshop (/ops/activity, /status, /chat/messages,
   /ops/replay) and turns them into one model that both the DOM panels and the WebGL scene are painted from.
   Live and replay build the same model, so a replay shows exactly what the live view would have shown. */
(function(){
const T=(window.I18N&&window.I18N.t)||((s,...a)=>s.replace(/\{(\d+)\}/g,(m,i)=>i<a.length?String(a[i]):m)),LANG=window.I18N?window.I18N.lang:'ko';
const $=id=>document.getElementById(id);
const AI={ANTHROPIC:{name:'Claude',rgb:[1,.54,.36],css:'#ff8a5c'},OPENAI:{name:'Codex',rgb:[.24,.95,.75],css:'#3df2c0'},GOOGLE:{name:'Antigravity',rgb:[.42,.65,1],css:'#6aa5ff'}};
const ROLES=['HEAD','BUILDER','REVIEWER'];
const ROLE_KO={HEAD:T('HEAD · 지휘'),BUILDER:T('BUILDER · 구현'),REVIEWER:T('REVIEWER · 검수')};
const DEFAULT_ASSIGN={HEAD:'ANTHROPIC',BUILDER:'GOOGLE',REVIEWER:'OPENAI'};
const PIPE=['PLANNING','BUILDING','VERIFYING','REVIEWING','DECIDING'];
const PHASE={
  IDLE:{word:T('대기'),sub:T('세 AI가 지시를 기다립니다'),core:.18},
  BETWEEN:{word:T('준비'),sub:T('다음 AI 호출을 준비합니다'),core:.42},
  PLANNING:{word:T('계획'),sub:T('HEAD가 할 일을 정합니다'),core:.56},
  BUILDING:{word:T('구현'),sub:T('BUILDER가 코드를 씁니다'),core:.72},
  VERIFYING:{word:T('테스트'),sub:T('Director가 직접 실행해 확인합니다'),core:1},
  REVIEWING:{word:T('검수'),sub:T('REVIEWER가 독립적으로 살핍니다'),core:.72},
  DECIDING:{word:T('판단'),sub:T('HEAD가 통과 여부를 결정합니다'),core:.86}};
const STAGE_TEXT={CHAT:T('요청을 읽고 있습니다'),MISSION_PLANNING:T('다음 단계를 계획하고 있습니다'),PLANNING:T('작업 지시서를 쓰고 있습니다'),ORDER_READY:T('작업 지시서를 쓰고 있습니다'),
  BUILDING:T('코드를 작성하고 있습니다'),REVIEWING:T('결과물을 검수하고 있습니다'),DECIDING:T('통과 여부를 판단하고 있습니다')};
const SHORT={CHAT:T('요청 확인 중'),MISSION_PLANNING:T('다음 단계 계획 중'),PLANNING:T('지시서 작성 중'),ORDER_READY:T('지시서 작성 중'),BUILDING:T('코드 작성 중'),REVIEWING:T('검수 중'),DECIDING:T('판단 중')};
const STAGE_LABEL={PLANNING:T('계획'),ORDER_READY:T('구현 준비'),BUILDING:T('코드 작성'),VERIFYING:T('테스트'),REVIEWING:T('독립 검토'),DECIDING:T('HEAD 판단'),PASS:T('통과'),FAIL:T('실패'),
  HUMAN_REQUIRED:T('사용자 확인'),TIMEOUT:T('시간 초과'),IDLE:T('대기'),MISSION_PLANNING:T('다음 단계 계획'),ENTRY_REVIEW:T('오더 검토'),CHAT:T('대화')};
const STATE_KO={PASS:T('통과'),FAIL:T('실패'),TIMEOUT:T('시간 초과'),HUMAN_REQUIRED:T('확인 필요'),RECOVERED:T('복구 완료')};
const STEP_CLASS={PASS:'ok',RECOVERED:'ok',FAIL:'bad',TIMEOUT:'bad',HUMAN_REQUIRED:'warn'},STEP_MARK={ok:'✓',bad:'✗',warn:'!',run:'▶',todo:''};
const MISSION_BADGE={DONE:[T('완료'),'ok'],INCOMPLETE:[T('예산 소진'),'warn'],BLOCKED:[T('확인 필요'),'warn'],FAILED:[T('실패'),'bad']};
const PULSE={ok:[.35,1,.7],bad:[1,.32,.4],warn:[1,.78,.4],done:[1,.93,.75]};

let activity=null,status=null,win=null,winAuto=true,replay=null,lastModel=null,center=null,timerBase=null;
const seenSteps=new Map(),seenFeed={event:new Set(),call:new Set()};let firstPaint=true;

function el(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function utc(iso){return iso?new Date(iso+(/Z|[+]\d\d:\d\d$/.test(iso)?'':'Z')).getTime():0;}
function ago(ms){const s=Math.max(0,Math.floor((Date.now()-ms)/1000));return s<60?s+T('초 전'):s<3600?Math.floor(s/60)+T('분 전'):s<86400?Math.floor(s/3600)+T('시간 전'):Math.floor(s/86400)+T('일 전');}
function clock(sec){sec=Math.max(0,Math.floor(sec));const m=Math.floor(sec/60),s=sec%60;return (m>=60?Math.floor(m/60)+':'+String(m%60).padStart(2,'0'):String(m).padStart(2,'0'))+':'+String(s).padStart(2,'0');}
function span(sec){sec=Math.round(sec||0);if(sec<60)return sec+T('초');const m=Math.floor(sec/60);return m<60?m+T('분'):Math.floor(m/60)+T('시간 ')+(m%60)+T('분');}
function hms(ms){const d=new Date(ms);return [d.getHours(),d.getMinutes(),d.getSeconds()].map(n=>String(n).padStart(2,'0')).join(':');}
function tok(n){n=Math.round(n||0);if(LANG!=='ko')return n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e4?(n/1e3).toFixed(1)+'K':n.toLocaleString('en-US');
  return n>=1e8?(n/1e8).toFixed(2)+'억':n>=1e4?(n/1e4).toFixed(1)+'만':n.toLocaleString('ko-KR');}
function countTo(node,value,fmt){
  const from=node._v||0;node._v=value;if(node._raf)cancelAnimationFrame(node._raf);
  if(from===value||Math.abs(value-from)<1){node.textContent=fmt(value);return;}
  const t0=performance.now(),step=now=>{const k=Math.min(1,(now-t0)/900),e=1-Math.pow(1-k,3);node.textContent=fmt(from+(value-from)*e);if(k<1)node._raf=requestAnimationFrame(step);};
  node._raf=requestAnimationFrame(step);
}
function guarded(fn){let p=null,again=false;const run=()=>{if(p){again=true;return p;}
  p=(async()=>{try{await fn();}finally{p=null;}if(again){again=false;await run();}})();return p;};return run;}
async function getJSON(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw Error(url+' '+r.status);return r.json();}

// ------------------------------------------------------------------ model
const CLI={claude:'ANTHROPIC',antigravity:'GOOGLE',openai:'OPENAI'},CLI_OF={ANTHROPIC:'claude',GOOGLE:'antigravity',OPENAI:'openai'};
let roleSettings=null,roleToken=null;                 // what the NEXT task will use (data/role_settings.json via /ops/roles)
const pollRoles=guarded(async()=>{try{const r=await getJSON('/ops/roles');roleSettings=r.roles;roleToken=r.csrf;repaint();}catch(e){/* keep the last known roles */}});
function assignment(){
  if(roleSettings&&!isLiveNow())return {HEAD:CLI[roleSettings.head],BUILDER:CLI[roleSettings.builder],REVIEWER:CLI[roleSettings.reviewer]};
  const a={...DEFAULT_ASSIGN},prov=(status&&status.providers)||{};
  for(const [p,info] of Object.entries(prov))if(info&&AI[p])for(const r of String(info.role||'').split(/,\s*/))if(ROLES.includes(r))a[r]=p;   // one AI may hold several roles
  return a;
}
function isLiveNow(){const a=activity||{};return (a.working_now||[]).length>0||(a.missions||[]).some(m=>m.live);}
let roleOpener=null;
function closeRoleMenu(refocus){const menu=$('role-menu'),was=!menu.hidden;menu.hidden=true;
  for(const l of document.querySelectorAll('.slot-label'))l.setAttribute('aria-expanded','false');
  if(was&&refocus&&roleOpener&&roleOpener.isConnected)roleOpener.focus();roleOpener=null;}
function openRoleMenu(label){
  const menu=$('role-menu'),slot=Number(label.dataset.slot),role=ROLES[slot];
  if(replay)return;
  if(!roleSettings){notice(T('역할 정보를 아직 불러오지 못했습니다. 잠시 뒤 다시 눌러 주세요.'));return;}
  if(!menu.hidden&&menu.dataset.slot===String(slot)){closeRoleMenu(true);return;}
  closeRoleMenu();roleOpener=label;label.setAttribute('aria-expanded','true');
  menu.dataset.slot=String(slot);menu.replaceChildren(el('p',T('{0} 를 맡을 AI',ROLE_KO[role])+(isLiveNow()?T(' · 진행 중인 작업은 그대로, 다음 작업부터 적용'):'')));
  const key=role.toLowerCase();
  for(const p of ['ANTHROPIC','GOOGLE','OPENAI']){
    const b=el('button',AI[p].name),cur=roleSettings[key]===CLI_OF[p],also=ROLES.filter(r=>r!==role&&roleSettings[r.toLowerCase()]===CLI_OF[p]);
    b.type='button';b.setAttribute('role','menuitem');b.style.setProperty('--c',AI[p].css);b.classList.toggle('on',cur);
    b.append(el('small',cur?T('현재'):also.length?T('{0}도 담당',also.join(', ')):''));
    b.onclick=async()=>{if(cur){closeRoleMenu(true);return;}
      const next={...roleSettings};next[key]=CLI_OF[p];
      for(const x of menu.querySelectorAll('button'))x.disabled=true;
      try{const res=await fetch('/ops/roles',{method:'POST',headers:{'Content-Type':'application/json','X-Tribunal-Token':roleToken},body:JSON.stringify(next)}),out=await res.json();
        if(!res.ok)throw Error(out.error||T('저장 실패'));roleSettings=out.roles;notice(T('역할을 바꿨습니다 · ')+ROLE_KO[role]+' = '+AI[p].name+T(' (다음 작업부터 적용)'));}
      catch(e){notice(T('역할 변경 실패 · ')+e.message);}
      closeRoleMenu(true);repaint();};
    menu.append(b);}
  const r=label.getBoundingClientRect(),c=$('stage-center').getBoundingClientRect();
  menu.hidden=false;
  menu.onkeydown=e=>{const items=[...menu.querySelectorAll('button')],i=items.indexOf(document.activeElement);
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();items[(i+(e.key==='ArrowDown'?1:items.length-1))%items.length].focus();}
    else if(e.key==='Tab'){e.preventDefault();closeRoleMenu(true);}};
  (menu.querySelector('button.on')||menu.querySelector('button')).focus();
  menu.style.transform='translate('+Math.max(4,Math.min(r.left-c.left,c.width-menu.offsetWidth-4)).toFixed(0)+'px,'+(r.bottom-c.top+6+menu.offsetHeight>c.height?Math.max(4,r.top-c.top-menu.offsetHeight-6):r.bottom-c.top+6).toFixed(0)+'px)';   // no room below: open above the label
}
function phaseOf(working,verifying,live){
  const w=working.find(x=>x.role==='BUILDER')||working.find(x=>x.role==='REVIEWER')||working[0];
  if(w){
    if(w.role==='BUILDER')return {phase:'BUILDING',w};
    if(w.role==='REVIEWER')return {phase:'REVIEWING',w};
    return {phase:w.stage==='DECIDING'?'DECIDING':'PLANNING',w};
  }
  return {phase:verifying?'VERIFYING':live?'BETWEEN':'IDLE',w:null};
}
function liveModel(){
  const a=activity||{missions:[],working_now:[],usage:{},recent_calls:[],events:[]};
  const focus=(a.missions||[]).find(m=>m.mission_id===a.focus_mission_id)||null;
  const working=(a.working_now||[]).map(w=>({id:w.id,estimate:w.estimate||null,provider:w.provider,role:w.role,stage:w.stage,elapsed:w.elapsed_sec,at:Date.now()-w.elapsed_sec*1000}));
  const step=focus&&focus.steps.length?focus.steps[focus.steps.length-1]:null,ev=(a.events||[])[0];
  const verifying=!!(focus&&focus.live&&step&&ev&&ev.run_id===step.run_id&&ev.to_state==='VERIFYING'&&Date.now()-utc(ev.at)<30*60e3);
  const usage=a.usage||{};
  if(winAuto)win=usage.mission&&focus&&(focus.live||!(usage.today&&usage.today.total.calls))?'mission':(usage.today&&usage.today.total.calls?'today':(usage.mission?'mission':'all'));
  if(!usage[win])win=usage.today?'today':'all';
  const today=(usage.today&&usage.today.by_provider)||{},stats={};
  for(const p of Object.keys(AI))stats[p]=today[p]?T('오늘 {0}회 · {1} 토큰',today[p].calls,(today[p].exact_tokens<today[p].tokens?'~':'')+tok(today[p].tokens)):T('오늘 호출 없음');
  return {mode:'live',working,assign:assignment(),...phaseOf(working,verifying,!!(focus&&focus.live)),
    mission:focus&&{goal:focus.goal,project:focus.project,status:focus.status,live:focus.live,max:Math.max(focus.max_steps||0,focus.steps.length),
      steps:focus.steps.map(s=>({index:s.index,state:s.state,tests:s.tests})),passed:focus.passed_steps,updated:utc(focus.updated_at),id:focus.mission_id,
      deliverable:focus.deliverable,applied:focus.applied,applyState:focus.apply_state,source:focus.source,profile:focus.profile},
    usage:usage[win]||{by_role:{},by_provider:{},total:{calls:0,seconds:0,tokens:0,exact_tokens:0}},windows:{mission:!!usage.mission,today:!!usage.today,all:!!usage.all},
    calls:(a.recent_calls||[]).slice(0,6).map(c=>({id:c.id,key:c.at+c.role+c.provider,role:c.role,provider:c.provider,seconds:c.seconds,tokens:c.tokens,exact:c.exact,status:c.status,at:utc(c.at)})),
    events:(a.events||[]).slice(0,7).map(e=>({key:e.at+e.run_id+e.to_state,state:e.to_state,label:STAGE_LABEL[e.to_state]||e.state_ko||e.to_state,sub:e.project,at:utc(e.at)})),
    stats,project:(status&&status.project_name)||(focus&&focus.project)||'—'};
}

// ------------------------------------------------------------------ painting
function actorColor(m){return m.w?AI[m.w.provider]?.css||'#fff':m.phase==='VERIFYING'?'#b9ffe2':'#9fb4d8';}
function sentence(m){
  if(m.w){const name=(AI[m.w.provider]||{name:m.w.provider}).name;return [name,T('가 ')+(STAGE_TEXT[m.w.stage]||(m.w.role==='BUILDER'?STAGE_TEXT.BUILDING:m.w.role==='REVIEWER'?STAGE_TEXT.REVIEWING:T('생각하고 있습니다')))];}
  if(m.phase==='VERIFYING')return ['Director',T('가 테스트를 실행하고 있습니다')];
  if(m.phase==='BETWEEN')return ['',T('다음 AI 호출을 준비하고 있습니다')];
  return ['',T('세 AI가 지시를 기다리고 있습니다')];
}
function setSentence(node,m){const [who,rest]=sentence(m);if(node.textContent===who+rest)return;node.replaceChildren();if(who)node.append(el('em',who));node.append(rest);}
function paintNow(m){
  document.body.dataset.phase=m.phase;
  document.documentElement.style.setProperty('--actor',actorColor(m));
  setSentence($('now-headline'),m);setSentence($('caption'),m);
  const ms=m.mission,step=ms&&ms.steps.length?ms.steps[ms.steps.length-1].index:0;
  $('now-sub').textContent=m.phase==='IDLE'?(ms?(m.mode==='replay'?T('다시보기 끝 · ')+(MISSION_BADGE[ms.status]||[ms.status])[0]:T('마지막 미션 ')+(MISSION_BADGE[ms.status]||[ms.status])[0]+' · '+ago(ms.updated)):T('아래 입력창에 지시하면 세 AI가 일을 시작합니다.'))
    :(ms&&(ms.live||m.mode==='replay')?T('미션 {0}/{1}단계 · {2}',step,ms.max,ms.project):PHASE[m.phase].sub);
  $('now-stage').textContent=m.w?ROLE_KO[m.w.role]||m.w.role:PHASE[m.phase].word;
  timerBase=m.w?{at:m.w.at,fixed:m.mode==='replay'?m.w.elapsed:null,estimate:m.mode==='live'?m.w.estimate:null}:null;tickTimer();
  $('phase-word').textContent=PHASE[m.phase].word;$('phase-sub').textContent=PHASE[m.phase].sub;
  const at=PIPE.indexOf(m.phase);
  for(const li of $('pipeline').children){const i=PIPE.indexOf(li.dataset.stage);li.classList.toggle('on',i===at);li.classList.toggle('done',at>i&&at>=0);
    const role=li.dataset.stage==='BUILDING'?'BUILDER':li.dataset.stage==='REVIEWING'?'REVIEWER':li.dataset.stage==='VERIFYING'?null:'HEAD';
    li.style.setProperty('--c',i===at?actorColor(m):role?AI[m.assign[role]].css:'#b9ffe2');}
  const chip=$('top-live');chip.dataset.mode=m.mode==='replay'?'replay':(m.working.length||(ms&&ms.live))?'live':'idle';
  chip.lastElementChild.textContent=m.mode==='replay'?'REPLAY':chip.dataset.mode==='live'?'LIVE':'STANDBY';
  $('top-project').textContent=T('프로젝트 · ')+((ms&&(ms.live||m.mode==='replay')&&ms.project)||m.project);
}
function tickTimer(){
  for(const label of document.querySelectorAll('.slot-label'))if(label._work&&label._work.fixed==null)label.querySelector('.slot-status').textContent=label._work.text+' · '+clock((Date.now()-label._work.at)/1000);
  const node=$('now-elapsed');
  const eta=$('now-eta'),est=timerBase&&timerBase.estimate;eta.hidden=!est;
  if(!timerBase){node.textContent='--:--';return;}
  const sec=timerBase.fixed!=null?timerBase.fixed:(Date.now()-timerBase.at)/1000;
  node.textContent=clock(sec);
  if(est){   // an estimate from past calls of the same kind, never a promise: the bar stops short of full and says so when overdue
    const late=sec>Math.max(est.seconds*2,est.seconds+30),left=Math.round(est.seconds-sec);
    eta.classList.toggle('late',late);eta.firstElementChild.firstElementChild.style.width=Math.min(95,Math.max(3,sec/est.seconds*100))+'%';
    eta.lastElementChild.textContent=(late?T('평소보다 오래 걸리는 중 · 보통 {0}',span(est.seconds)):left>0?T('약 {0} 남음 (추정)',span(left)):T('곧 끝날 시간 (추정)'))+T(' · 최근 {0}회 중앙값',est.samples)+(est.basis==='any_ai'?T(', 다른 AI 포함'):'');
  }
}
function paintMission(m){
  const ms=m.mission,badge=$('mission-badge'),steps=$('mission-steps');
  if(!ms){badge.textContent='—';badge.className='badge';$('mission-goal').textContent=T('아직 미션 기록이 없습니다. 지시를 보내면 여기에 단계별 진행이 표시됩니다.');steps.replaceChildren();$('mission-meta').textContent='';return;}
  const running=ms.status==='RUNNING',b=running?(ms.live?[T('진행 중'),'run']:[T('중단됨 · 재개 대기'),'warn']):(MISSION_BADGE[ms.status]||[ms.status,'']);
  badge.textContent=b[0];badge.className='badge '+b[1];$('mission-goal').textContent=ms.goal;$('mission-goal').title=ms.goal;
  while(steps.children.length>ms.max)steps.lastChild.remove();
  while(steps.children.length<ms.max)steps.append(el('span',String(steps.children.length+1)));
  for(let i=0;i<ms.max;i++){const s=ms.steps.find(x=>x.index===i+1),chip=steps.children[i];
    chip.className=s?(STEP_CLASS[s.state]||'run'):'todo';chip.title=s?T('{0}단계 · {1}',i+1,STATE_KO[s.state]||T('진행 중')):T('남은 단계 예산');
    const mark=STEP_MARK[chip.className]+(i+1);if(chip.textContent!==mark)chip.textContent=mark;chip.setAttribute('role','img');chip.setAttribute('aria-label',chip.title);}
  const last=[...ms.steps].reverse().find(s=>s.tests);
  $('mission-meta').textContent=T('{0}개 단계 통과 · {1}/{2}단계 사용',ms.passed,ms.steps.length,ms.max)+(last?T(' · 테스트 {0}/{1}',last.tests.passed,last.tests.total):'');
  paintDelivery(m);
  if(m.mode!=='live')return;
  for(const s of ms.steps){const key=ms.id+':'+s.index,prev=seenSteps.get(key);seenSteps.set(key,s.state);
    if(!firstPaint&&prev!==s.state&&STEP_CLASS[s.state])Trinity.pulse(PULSE[STEP_CLASS[s.state]]);}
  const mk=ms.id+':status',prev=seenSteps.get(mk);seenSteps.set(mk,ms.status);
  if(!firstPaint&&prev&&prev!==ms.status&&ms.status==='DONE')Trinity.pulse(PULSE.done);
}
const APPLY_KO={applied:[T('원본에 적용됨'),'ok'],blocked:[T('적용 보류 · 충돌/조건'),'warn'],pending:[T('적용 대기'),'warn'],discarded:[T('폐기됨'),''],rolled_back:[T('적용 실패 · 복구됨'),'bad'],busy:[T('적용 진행 중'),'run'],error:[T('적용 오류'),'bad']};
let deliveryBusy=false;
async function decideMission(id,action,extra){
  if(deliveryBusy)return;deliveryBusy=true;if(lastModel)paintDelivery(lastModel);
  try{const body=new URLSearchParams({mission_id:id,action,...(extra||{})});
    const res=await fetch('/ops/mission/decide',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body});
    const out=await res.json().catch(()=>({}));
    if(!res.ok||!out.status)throw Error(out.error||out.reason||(T('서버 응답 ')+res.status));
    const msg={applied:T('원본에 적용했습니다 · {0}개 파일',(out.files||[]).length),blocked:T('적용할 수 없습니다 · ')+((out.blocks||[]).join('; ')||'').slice(0,160),discarded:T('결과물을 폐기했습니다'),resumed:T('미션을 이어서 진행합니다 (단계 예산 {0})',out.max_steps),busy:T('다른 작업이 진행 중입니다')}[out.status]||(out.status+' '+(out.error||out.reason||''));
    notice(msg);Trinity.pulse(out.status==='applied'?PULSE.done:out.status==='blocked'?PULSE.warn:PULSE.ok);}
  catch(e){notice(T('요청 실패 · ')+e.message);}
  finally{deliveryBusy=false;if(lastModel)paintDelivery(lastModel);pollActivity();}
}
function paintDelivery(m){
  let box=$('mission-delivery');
  if(!box){box=el('div','','delivery');box.id='mission-delivery';$('mission-card').append(box);}
  const ms=m.mission,shown=!!(ms&&m.mode==='live'&&ms.deliverable&&ms.status!=='RUNNING');
  const state=shown?((ms.applied&&ms.applied.status)||ms.applyState||'pending'):'',[label,cls]=APPLY_KO[state]||[state,''];
  const sig=JSON.stringify(shown?[ms.id,state,ms.applied&&ms.applied.files,ms.applied&&ms.applied.blocks,ms.source,deliveryBusy]:[]);
  if(box.dataset.sig===sig)return;box.dataset.sig=sig;      // rebuilt only when something changed: a click or the focus is never lost to a poll
  const held=box.contains(document.activeElement)?document.activeElement.dataset.act:null;
  box.replaceChildren();if(!shown)return;
  const head=el('div','','delivery-head');head.append(el('span',(ms.source==='bridge'||ms.source==='solomon'?T('외부 지시 · '):ms.source==='cli'?T('CLI 지시 · '):'')+T('결과물'),'kicker'),el('span',label,'badge '+cls));box.append(head);
  if(ms.applied&&ms.applied.files)box.append(el('small',ms.applied.files.slice(0,6).join(', ')+(ms.applied.files.length>6?T(' 외 {0}개',ms.applied.files.length-6):''),'ai-sub'));
  if(state==='blocked'&&ms.applied&&ms.applied.blocks)box.append(el('small',ms.applied.blocks.join('; ').slice(0,220),'ai-sub'));
  if(state!=='applied'&&state!=='discarded'){
    const row=el('div','','delivery-actions');
    const apply=el('button',deliveryBusy?T('처리 중…'):T('원본에 적용'));apply.type='button';apply.dataset.act='apply';
    apply.onclick=()=>{if(confirm(state==='blocked'?T('충돌한 파일은 건너뛰고 나머지 변경만 원본 프로젝트({0})에 적용할까요?',ms.project||'—'):T('이 미션의 결과물을 원본 프로젝트({0})에 적용할까요? 프로젝트의 파일이 바뀝니다.',ms.project||'—')))decideMission(ms.id,'apply',{on_conflict:state==='blocked'?'skip':'block'});};
    const more=el('button',T('이어서 진행'));more.type='button';more.dataset.act='extend';more.onclick=()=>decideMission(ms.id,'extend');
    const drop=el('button',T('폐기'));drop.type='button';drop.className='ghost';drop.dataset.act='discard';drop.onclick=()=>{if(confirm(T('이 미션의 작업본을 폐기할까요? 기록은 남습니다.')))decideMission(ms.id,'discard');};
    for(const b of [apply,more,drop])b.disabled=deliveryBusy;
    row.append(apply,more,drop);box.append(row);
    if(held){const again=row.querySelector('[data-act="'+held+'"]');if(again&&!again.disabled)again.focus();}
    if(state==='blocked')box.append(el('small',T('"원본에 적용"을 다시 누르면 충돌 파일만 건너뛰고 나머지를 적용합니다.'),'ai-sub'));
  }
}
function paintWork(m){
  for(const b of $('win-tabs').children){b.classList.toggle('on',b.dataset.win===win&&m.mode==='live');b.setAttribute('aria-pressed',String(b.dataset.win===win&&m.mode==='live'));b.disabled=m.mode!=='live'||!m.windows[b.dataset.win];}
  const u=m.usage,total=u.total||{},approx=(total.exact_tokens||0)<(total.tokens||0);
  countTo($('total-tokens'),total.tokens||0,v=>(approx?'~':'')+tok(v));
  $('total-sub').textContent=T('호출 {0}회 · CLI {1}',total.calls||0,span(total.seconds))+(total.failed?T(' · 실패 {0}',total.failed):'');
  const sum=Object.keys(AI).reduce((a,p)=>a+((u.by_provider[p]||{}).tokens||0),0)||1;
  for(const bar of $('share-bar').children)bar.style.width=(((u.by_provider[bar.dataset.p]||{}).tokens||0)/sum*100)+'%';
  const rows=$('role-rows');
  if(!rows.children.length)for(const role of ROLES){const row=el('div','','role-row');row.dataset.role=role;
    const top=el('div','','role-top');top.append(el('b',ROLE_KO[role]),el('strong','—'));
    const nums=el('div','','role-nums');for(const k of [T('호출'),T('CLI 시간'),T('토큰')]){const d=el('div');d.append(el('b','0'),el('span',k));nums.append(d);}
    const bar=el('div','','role-bar');bar.append(el('i'));row.append(top,nums,bar);rows.append(row);}
  for(const row of rows.children){const role=row.dataset.role,b=u.by_role[role],busy=m.working.find(w=>w.role===role);
    const provs=b?Object.entries(b.providers||{}).sort((x,y)=>y[1]-x[1]):[],main=busy?busy.provider:provs.length?provs[0][0]:m.assign[role];
    row.style.setProperty('--c',(AI[main]||{}).css||'#8fa0bd');row.classList.toggle('busy',!!busy);
    row.querySelector('strong').textContent=provs.length?provs.map(([p,n])=>((AI[p]||{name:p}).name)+(provs.length>1?' '+n:'')).join(' · '):(AI[m.assign[role]]||{}).name;
    const n=row.querySelectorAll('.role-nums b');
    countTo(n[0],b?b.calls:0,v=>String(Math.round(v)));n[1].textContent=b?span(b.seconds):T('0초');
    countTo(n[2],b?b.tokens:0,v=>(b&&b.exact_tokens<b.tokens?'~':'')+tok(v));
    row.querySelector('.role-bar i').style.width=((b?b.tokens:0)/(total.tokens||1)*100)+'%';}
}
function paintFeed(list,items,seen,render){
  const frag=[];
  for(const it of items){const li=el('li');render(li,it);if(!seen.has(it.key)){seen.add(it.key);if(!firstPaint)li.classList.add('new');}frag.push(li);}
  const held=list.contains(document.activeElement)?document.activeElement.dataset.key:null;   // the list is rebuilt every poll
  list.replaceChildren(...frag);
  if(held)for(const li of frag)if(li.dataset.key===held){li.focus();break;}
  if(!items.length)list.append(el('li',T('아직 기록이 없습니다.')));
}
function stateColor(m,state){
  if(STEP_CLASS[state])return {ok:'#5ef2b0',bad:'#ff6b7a',warn:'#ffc46b'}[STEP_CLASS[state]];
  if(state==='BUILDING')return AI[m.assign.BUILDER].css;if(state==='REVIEWING')return AI[m.assign.REVIEWER].css;
  if(state==='VERIFYING')return '#b9ffe2';return AI[m.assign.HEAD].css;
}
function paintFeeds(m){
  paintFeed($('event-feed'),m.events,seenFeed.event,(li,e)=>{li.style.setProperty('--dot',e.color||stateColor(m,e.state));li.append(el('b',e.label),el('span',e.sub||''),el('time',e.when||ago(e.at)));});
  paintFeed($('call-feed'),m.calls,seenFeed.call,(li,c)=>{li.style.setProperty('--dot',c.status&&c.status!=='OK'?'#ff6b7a':(AI[c.provider]||{}).css||'#8fa0bd');
    li.append(el('b',(AI[c.provider]||{name:c.provider}).name),el('span',(c.role||'?')+' · '+span(c.seconds)+(c.tokens?' · '+(c.exact?'':'~')+tok(c.tokens)+T(' 토큰'):'')+(c.status&&c.status!=='OK'?' · '+c.status:'')),el('time',c.when||ago(c.at)));
    if(c.id&&m.mode==='live'){li.classList.add('openable');li.dataset.key='call-'+c.id;li.tabIndex=0;li.setAttribute('role','button');li.title=T('이 호출 안에서 한 일 보기');
      li.onclick=()=>openCall(c.id);li.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openCall(c.id);}};}});
}

// ------------------------------------------------------------------ inside one call (/ops/call)
// The CLIs' own records say which tools ran and what was said; nothing here is estimated. When a record is
// missing the panel says so instead of showing an empty success.
const SOURCE_KO={transcript:T('Claude 세션 기록'),rollout:T('Codex 세션 기록'),stream:T('Antigravity 실시간 출력')};
const CALL_STATUS={RUNNING:T('진행 중'),OK:T('완료'),ERROR:T('실패'),FAILED:T('실패'),TIMEOUT:T('시간 초과'),INTERRUPTED:T('중단됨')};
const QUIET_SHOW=60,QUIET_WARN=120;   // seconds without a new event before it is mentioned / highlighted (the runner stops a silent CLI on its own)
let liveCall=null,openId=null,openData=null,callFilter='all',callBusy=false,callOpener=null,callRetry=0;
function eventText(e){return e.kind==='tool'?[e.name,e.detail]:e.kind==='say'?[T('말'),e.detail]:e.kind==='think'?[T('생각'),'']:[T('응답 끝'),e.detail];}
function paintDoing(){
  const b=$('now-doing'),d=liveCall,ev=d&&d.found?d.events.filter(e=>e.kind!=='done'):[];
  if(!d||replay){b.hidden=true;return;}
  b.hidden=false;const last=ev[ev.length-1],[name,detail]=last?eventText(last):['',''];
  b.children[1].textContent=last?name+(detail?' · '+detail:''):(d.found?T('아직 도구를 쓰지 않았습니다'):T('활동 기록을 기다리는 중'));
  const quiet=d.quiet_sec||0;
  b.children[2].textContent=[d.found?T('도구 {0}회',d.tools)+(d.errors?T(' · 오류 {0}건',d.errors):''):'',quiet>=QUIET_SHOW?T('{0}째 새 활동 없음',span(quiet)):''].filter(Boolean).join(' · ');
  b.classList.toggle('bad',!!(last&&last.error));b.classList.toggle('quiet',quiet>=QUIET_WARN);
}
function paintCall(){
  const d=openData,list=$('cp-events');
  if(!d){$('cp-title').textContent=T('불러오는 중…');$('cp-meta').textContent='';$('cp-note').textContent='';list.replaceChildren();return;}
  $('cp-title').textContent=d.known?(d.provider_name||d.provider)+' · '+(ROLE_KO[d.role]||d.role||T('역할 없음')):T('기록에 없는 호출');
  $('cp-meta').textContent=d.known?[CALL_STATUS[d.status]||d.status,d.seconds!=null?span(d.seconds):'',d.found?T('도구 {0}회',d.tools):'',d.found&&d.errors?T('오류 {0}건',d.errors):'',SOURCE_KO[d.source]||''].filter(Boolean).join(' · '):'';
  const stick=list.scrollHeight-list.scrollTop-list.clientHeight<40;
  const shown=(d.events||[]).filter(e=>callFilter==='all'||(callFilter==='tool'?e.kind==='tool':e.error));
  list.replaceChildren(...shown.map(e=>{const li=el('li','',e.kind+(e.error?' bad':'')),[name,detail]=eventText(e);
    li.append(el('time',e.at?hms(utc(e.at)):''),el('b',name),el('span',detail||''));
    if(e.error)li.append(el('em',T('오류')));return li;}));
  if(stick)list.scrollTop=list.scrollHeight;
  $('cp-note').textContent=!d.known?T('이 번호의 호출 기록이 없습니다.')
    :!d.found?(d.status==='RUNNING'?T('CLI가 아직 기록을 남기지 않았습니다. 곧 다시 확인합니다.'):T('이 호출의 내부 기록을 찾지 못했습니다. 이 기능이 생기기 전의 호출이거나, CLI가 기록을 남기지 않았거나, 기록 형식이 바뀐 경우입니다.'))
    :!shown.length?(callFilter==='error'?T('오류가 난 도구 호출이 없습니다.'):callFilter==='tool'?T('도구를 쓰지 않은 호출입니다.'):T('기록된 활동이 없습니다.'))
    :d.total>d.events.length?T('최근 {0}건만 표시합니다 (전체 {1}건).',d.events.length,d.total):'';
}
function openCall(id){if(!$('ai-panel').hidden)setAIPanel(false,true);callOpener=document.activeElement;openId=id;callRetry=5;openData=liveCall&&liveCall.id===id?liveCall:null;$('call-panel').hidden=false;paintCall();pollCall();$('cp-close').focus();}
function closeCall(){openId=null;openData=null;$('call-panel').hidden=true;
  const back=callOpener&&callOpener.dataset.key?document.querySelector('[data-key="'+callOpener.dataset.key+'"]'):callOpener;callOpener=null;if(back&&back.isConnected)back.focus();}
async function pollCall(){
  if(callBusy)return;callBusy=true;                      // one round at a time: a slow answer never overwrites a newer one
  try{
    const w=!replay&&activity&&(activity.working_now||[])[0];
    if(w&&w.id){try{const d=await getJSON('/ops/call?id='+w.id);liveCall=d;}catch(e){/* keep the last one */}}else liveCall=null;
    paintDoing();
    // A finished call is read once more while its record is still missing: the CLI may flush it a moment late.
    const again=openData&&(openData.status==='RUNNING'||(!openData.found&&callRetry>0));
    if(openId!=null&&(!openData||again)){const id=openId;if(openData&&openData.status!=='RUNNING')callRetry--;
      try{const d=liveCall&&liveCall.id===id?liveCall:await getJSON('/ops/call?id='+id);if(openId===id){openData=d;paintCall();}}catch(e){/* next tick */}}
  }finally{callBusy=false;}
}
function paintScene(m){
  const act=[.1,.1,.1],edge=[0,0,0],colors=[];
  ROLES.forEach((role,i)=>{const w=m.working.find(x=>x.role===role),p=w?w.provider:m.assign[role];if(w)act[i]=1;colors.push((AI[p]||AI[m.assign[role]]).rgb);
    const label=document.querySelector('.slot-label[data-slot="'+i+'"]'),acting=w&&w.provider!==m.assign[role];
    label.style.setProperty('--c',(AI[p]||{}).css||'#fff');label.classList.toggle('busy',!!w);
    label.querySelector('.slot-name').textContent=((AI[p]||{name:p}).name)+(acting?T(' (대행)'):'');
    label._work=w?{text:SHORT[w.stage]||(role==='BUILDER'?SHORT.BUILDING:role==='REVIEWER'?SHORT.REVIEWING:T('작업 중')),at:w.at,fixed:m.mode==='replay'?w.elapsed:null}:null;
    label.querySelector('.slot-status').textContent=label._work?label._work.text+' · '+clock(label._work.fixed!=null?label._work.fixed:(Date.now()-label._work.at)/1000):T('대기');
    label.querySelector('.slot-stat').textContent=m.stats[p]||'';
    const cfg=label.querySelector('.slot-cfg'),hot=m.mode==='live'&&!!alertOf(CLI_OF[p]);cfg.textContent=m.mode==='live'?cfgLine(p)+(hot?' · '+T('한도 임박'):''):'';cfg.classList.toggle('alert',hot);});
  $('independence').hidden=!(m.mode==='live'&&roleSettings&&(roleSettings.reviewer===roleSettings.head||roleSettings.reviewer===roleSettings.builder));
  if(m.phase==='BUILDING')edge[0]=1;if(m.phase==='REVIEWING')edge[1]=1;if(m.phase==='DECIDING')edge[2]=1;
  if(m.phase==='VERIFYING')act[1]=.5;
  Trinity.set({act,edge,colors,core:PHASE[m.phase].core,verify:m.phase==='VERIFYING'?1:0});
}
let lastPhase=null;
function stinger(m){
  const key=m.phase+(m.w?m.w.provider:'');
  if(key===lastPhase)return;const first=lastPhase===null;lastPhase=key;
  if(first||m.phase==='IDLE'||m.phase==='BETWEEN')return;
  const s=$('stinger');s.replaceChildren(el('small',m.w?(AI[m.w.provider]||{name:''}).name+' · '+(m.w.role||''):'DIRECTOR'),el('strong',PHASE[m.phase].word));
  s.style.setProperty('--c',actorColor(m));s.classList.remove('show');void s.offsetWidth;s.classList.add('show');
}
function paint(m){lastModel=m;stinger(m);paintNow(m);paintMission(m);paintWork(m);paintFeeds(m);paintScene(m);firstPaint=false;document.body.classList.add('ready');}
const params=new URLSearchParams(location.search),attract=params.get('attract')==='1';let idleSince=null;
function isLive(){const a=activity||{};return (a.working_now||[]).length>0||(a.missions||[]).some(m=>m.live);}
function repaint(){
  if(attract&&activity){
    if(replay&&isLive())stopReplay();
    else if(!replay&&!isLive()){idleSince=idleSince||Date.now();if(Date.now()-idleSince>12000){idleSince=null;startReplay();}}
    else if(isLive())idleSince=null;
  }
  if(!replay)paint(liveModel());
}

// ------------------------------------------------------------------ scene-pinned labels
function onFrame(f){
  center=$('stage-center').getBoundingClientRect();
  const W=window.innerWidth,H=window.innerHeight,foot=$('stage-foot').offsetHeight+10;
  Trinity.focus({x:center.left/W,y:center.top/H,w:center.width/W,h:Math.max(.2,(center.height-foot)/H)});
  const u=f.unit,labels=document.querySelectorAll('.slot-label');
  $('stage-center').classList.toggle('compact',u<185);              // small scene: labels drop their stat line
  labels.forEach((n,i)=>{const [x,y]=f.slots[i],w=n.offsetWidth,h=n.offsetHeight;
    let lx=i===0?x+u*.27:x-w/2,ly=i===0?y-h+4:y+u*.27;                 // HEAD: above-right; BUILDER/REVIEWER: centred below
    lx=Math.min(Math.max(lx-center.left,2),center.width-w-2);ly=Math.max(ly-center.top,2);
    n.style.transform='translate('+lx.toFixed(1)+'px,'+ly.toFixed(1)+'px)';});
}

// ------------------------------------------------------------------ AI settings (/ops/ai): model, effort, plan, limits
// Limits are shown only where the CLI (or, for Claude, the usage lookup the operator allowed) reports them; a
// missing value says why instead of showing a number.
const AI_ORDER=['ANTHROPIC','GOOGLE','OPENAI'];
// Whether the CLI can be used at all (the server's health record), next to how much of its limits is left.
const HEALTH={HEALTHY:[T('정상'),'ok'],RECOVERING:[T('복구 중'),'warn'],DEGRADED:[T('불안정'),'warn'],QUOTA_LOW:[T('한도 낮음'),'warn'],QUOTA_EXHAUSTED:[T('한도 소진'),'bad'],
  AUTH_FAILED:[T('로그인 필요'),'bad'],TIMEOUT:[T('응답 없음'),'bad'],UNAVAILABLE:[T('사용 불가'),'bad'],CONFIG_ERROR:[T('설정 오류'),'bad'],UNKNOWN:[T('확인 전'),'']};
const LIMIT_WHY={loading:T('불러오는 중…'),unavailable:T('CLI가 알려 주지 않음'),lookup_failed:T('조회 실패'),no_record:T('기록 없음'),ok:T('이 요금제 기록에 없음')};
let ai=null,aiAt=0,aiBusy=false,aiEpoch=0,aiSaves=Promise.resolve();
function cfgLine(p){
  if(!ai)return '';const key=CLI_OF[p],s=ai.settings[key]||{},l=ai.limits[key]||{};
  return [s.model,s.effort,l.five_hour?T('5시간 {0}%',Math.round(l.five_hour.used_percent)):null,l.weekly?T('주간 {0}%',Math.round(l.weekly.used_percent)):null].filter(Boolean).join(' · ');
}
function alertOf(key,win,group){return ((ai&&ai.alerts)||[]).find(a=>a.cli===key&&(!win||(a.window===win&&(a.group||null)===(group||null))));}
function limitRow(label,w,state,over){
  const box=el('div','','ai-limit'),top=el('div','','ai-limit-top'),bar=el('div','','ai-bar'),fill=el('i');
  let text=LIMIT_WHY[state]||LIMIT_WHY.unavailable;
  if(w){const pct=Math.round(w.used_percent),left=w.resets_at?(utc(w.resets_at)-Date.now())/1000:null;
    const until=left>=86400?T('{0}일 {1}시간',Math.floor(left/86400),Math.floor(left%86400/3600)):span(left);
    text=left!=null&&left>0?T('{0}% 사용 · {1} 뒤 초기화',pct,until):T('{0}% 사용',pct);
    fill.style.width=Math.min(100,Math.max(0,pct))+'%';box.classList.toggle('bad',!!over);}
  top.append(el('span',label),el('span',text));bar.append(fill);box.append(top,bar);return box;
}
function choiceRow(label,key,field,items,fixed){
  const wrap=el('label','','ai-choice'),sel=document.createElement('select'),cur=(ai.settings[key]||{})[field]||'';
  if(fixed){sel.disabled=true;sel.title=T('이 모델은 추론 강도를 고를 수 없습니다.');}
  sel.append(new Option(T('CLI 기본값'),''));
  for(const it of items)sel.append(new Option(it.name||it.id,it.id));
  if(cur&&!items.some(it=>it.id===cur))sel.append(new Option(cur,cur));      // a value saved earlier that the list no longer offers
  sel.value=fixed?'':cur;sel.onchange=()=>saveAI(s=>{s[key]={...s[key],[field]:sel.value||null};
    if(field==='model'){const m=((ai.options[key]||{}).models||[]).find(x=>x.id===sel.value);if(m&&m.efforts&&!m.efforts.includes(s[key].effort))s[key].effort=null;}});   // a level the new model does not have is cleared
  wrap.append(el('span',label),sel);return wrap;
}
// ---- accounts: who each CLI is signed in as, and its own sign-in / switch / sign-out (core/cli_accounts.py)
const ACC_METHOD={subscription:T('구독 로그인'),api_console:T('API 과금 로그인'),api_key:T('API 키 로그인'),other:T('로그인됨')};
const ACC_ACTION={login:T('로그인'),switch:T('계정 변경'),logout:T('로그아웃'),open:T('터미널에서 열기')};
const revealed={};let accountBusy=false;
async function accountPost(path,body){
  const res=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Tribunal-Token':roleToken},body:JSON.stringify(body)}),out=await res.json().catch(()=>({}));
  if(!res.ok)throw Error(out.error||out.message||(T('서버 응답 ')+res.status));return out;}
async function toggleReveal(key){
  if(revealed[key]){clearTimeout(revealed[key].timer);delete revealed[key];paintAI(true);return;}
  try{const out=await accountPost('/ops/ai/account/reveal',{cli:key});if(!out.email){notice(T('계정 주소를 받지 못했습니다.'));return;}
    revealed[key]={email:out.email,masked:((ai.accounts||{})[key]||{}).email_masked,timer:setTimeout(()=>{delete revealed[key];paintAI(true);},20000)};paintAI(true);}   // shown for 20 seconds, then masked again
  catch(e){notice(T('계정 주소 확인 실패 · ')+e.message);}
}
async function accountAction(p,key,act){
  const name=AI[p].name;
  if(accountBusy)return;
  if(act==='logout'&&!confirm(T('{0}에서 로그아웃할까요? 다시 로그인하기 전까지 이 AI는 일할 수 없습니다.',name)))return;
  if(act==='switch'&&!confirm(T('{0} 계정을 바꿀까요? 지금 계정에서 로그아웃한 뒤, 터미널 창에서 새 계정으로 로그인합니다.',name)))return;
  accountBusy=true;paintAI(true);
  try{const out=await accountPost('/ops/ai/account',{cli:key,action:act});
    if(revealed[key]){clearTimeout(revealed[key].timer);delete revealed[key];}
    if(out.status==='started')notice(act==='open'?T('터미널 창에 {0}를 열었습니다.',name):T('터미널 창을 열었습니다. 거기서 {0} 로그인을 마쳐 주세요.',name));
    else if(out.status==='manual')prompt(T('이 환경에서는 터미널 창을 열 수 없습니다. 아래 명령을 터미널에서 직접 실행해 주세요.'),out.command);
    else if(out.status==='busy')notice(T('AI가 일하는 중이라 지금은 할 수 없습니다. 작업이 끝난 뒤 다시 시도해 주세요.'));
    else if(out.status==='done')notice(T('{0}에서 로그아웃했습니다.',name));
    else if(out.status==='checked')notice(T('{0} 계정 상태를 다시 확인합니다.',name));
    else if(out.status==='failed')notice(T('{0} 로그아웃 명령이 실패했습니다. 터미널에서 직접 확인해 주세요.',name));
    else if(out.status==='unavailable')notice(T('{0} CLI가 설치되어 있지 않습니다.',name));
    else notice(T('요청을 끝내지 못했습니다 · ')+(out.message||out.status||''));}
  catch(e){notice(T('요청 실패 · ')+e.message);}
  finally{accountBusy=false;await pollAI(true);}
}
function accountBox(p,key){
  const a=(ai.accounts||{})[key];if(!a)return null;
  const box=el('div','','ai-account'),line=el('div','','ai-account-line');box.append(el('span',T('계정'),'ai-account-k'),line);
  if(a.loading)line.append(el('span',T('계정을 확인하는 중…')));
  else if(a.installed===false)line.append(el('span',T('CLI가 설치되어 있지 않습니다.')));
  else if(a.signed_in===false)line.append(el('span',T('로그인되어 있지 않습니다.')));
  else if(a.email_masked){if(revealed[key]&&revealed[key].masked!==a.email_masked){clearTimeout(revealed[key].timer);delete revealed[key];}   // another account now
    const open=revealed[key];line.append(el('span',open?open.email:a.email_masked,'ai-account-who'));
    const eye=el('button',open?T('가리기'):T('보기'));eye.type='button';eye.className='ai-eye';eye.dataset.k=key+':eye';eye.setAttribute('aria-pressed',String(!!open));
    eye.title=T('계정 주소 전체를 20초 동안 보여 줍니다. 저장하지 않습니다.');eye.onclick=()=>toggleReveal(key);line.append(eye);}
  else line.append(el('span',!a.identity_known?(a.signed_in?T('로그인됨 · 계정 이름은 CLI가 알려 주지 않습니다.'):T('계정 이름과 로그인 여부를 CLI가 알려 주지 않습니다.')):a.signed_in?T('로그인됨'):T('로그인 상태를 확인하지 못했습니다.')));
  const sub=[a.method&&ACC_METHOD[a.method],a.org].filter(Boolean).join(' · ');if(sub)box.append(el('small',sub,'ai-note'));
  if(a.pending)box.append(el('small',T('로그인 진행 중 · 터미널과 브라우저에서 마치면 여기가 바뀝니다.'),'ai-note pend'));
  const row=el('div','','ai-account-actions');
  for(const act of (a.actions||[]).concat(a.pending||!a.identity_known||a.signed_in==null?['check']:[])){
    const b=el('button',act==='check'?T('다시 확인'):ACC_ACTION[act]||act);b.type='button';b.dataset.k=key+':acc:'+act;if(accountBusy)b.setAttribute('aria-busy','true');   // not disabled: the focus stays on it
    if(act==='logout')b.className='danger';if(act==='login')b.className='primary';
    b.onclick=()=>accountAction(p,key,act);row.append(b);}
  if(row.children.length)box.append(row);
  return box;
}
function paintAI(force){
  const box=$('ai-cards');if($('ai-panel').hidden)return;
  if(!ai){box.replaceChildren(el('p',T('불러오는 중…'),'ai-note'));return;}
  paintAITools();
  if(!force&&box.contains(document.activeElement)&&/^(SELECT|INPUT)$/.test(document.activeElement.tagName))return;   // do not rebuild under an open list or while typing
  const held=box.contains(document.activeElement)?document.activeElement.dataset.k:null;   // a forced rebuild (after a save) keeps the field you are in
  box.replaceChildren(...AI_ORDER.map(p=>{const key=CLI_OF[p],l=ai.limits[key]||{},o=ai.options[key]||{models:[],efforts:[]},card=el('div','','ai-card');
    card.style.setProperty('--c',AI[p].css);card.classList.toggle('alert',!!alertOf(key));
    const head=el('div','','ai-card-head');head.append(el('strong',AI[p].name));if(alertOf(key))head.append(el('em',T('한도 임박'),'ai-alert-badge'));
    const hp=(status&&status.providers&&status.providers[p])||null,hs=hp&&(HEALTH[hp.status]||[hp.status,'']);
    if(hs){const tag=el('span',hs[0],'ai-health '+hs[1]);tag.title=[hp.version,hp.error&&hp.error!=='NONE'?hp.error:''].filter(Boolean).join(' · ');head.append(tag);}
    if(l.plan)head.append(el('span',T('요금제 {0}',l.plan),'badge'));
    else{const sel=document.createElement('select'),cur=(ai.settings[key]||{}).plan||'';sel.className='ai-plan';sel.setAttribute('aria-label',T('구독 중인 요금제'));
      sel.title=T('CLI가 요금제를 알려 주지 않습니다. 구독 중인 요금제를 직접 고르세요.');
      sel.append(new Option(T('요금제 선택'),''));for(const it of (o.plans||[]))sel.append(new Option(it.id==='other'?T('기타'):it.name,it.id));
      sel.value=cur;sel.onchange=()=>saveAI(s=>{s[key]={...s[key],plan:sel.value||null};});head.append(sel);}
    const acct=accountBox(p,key);card.append(head);if(acct)card.append(acct);
    card.append(limitRow(T('5시간 한도'),l.five_hour,l.state,alertOf(key,'five_hour')),limitRow(T('주간 한도'),l.weekly,l.state,alertOf(key,'weekly')));
    if(key==='openai'&&l.as_of&&l.source!=='live')card.append(el('small',T('마지막 Codex 호출 기준 · {0}',ago(utc(l.as_of))),'ai-note'));
    const main=key==='antigravity'&&(l.groups||[]).length?(l.headline||l.groups[0].name):null;
    if(main)card.insertBefore(el('small',T('{0} 기준',main),'ai-note'),card.children[1]);
    for(const g of (l.groups||[]).filter(x=>x.name!==main)){   // Antigravity's other model families, Claude's per-model weekly limits
      if(key==='claude'&&g.weekly){card.append(limitRow(T('{0} 주간 한도',g.name),g.weekly,'ok',alertOf(key,'weekly',g.name)));continue;}
      const hot=alertOf(key,'five_hour',g.name)||alertOf(key,'weekly',g.name);
      card.append(el('small',g.name+' · '+[g.five_hour?T('5시간 {0}%',Math.round(g.five_hour.used_percent)):null,g.weekly?T('주간 {0}%',Math.round(g.weekly.used_percent)):null].filter(Boolean).join(' · '),'ai-note'+(hot?' bad':'')));}
    const picked=o.models.find(x=>x.id===(ai.settings[key]||{}).model),efforts=(picked&&picked.efforts)||o.efforts;   // only the levels the chosen model comes in
    card.append(choiceRow(T('모델'),key,'model',o.models),choiceRow(T('추론 강도'),key,'effort',efforts.map(e=>({id:e,name:e})),!!(picked&&picked.efforts&&!picked.efforts.length)||(key==='antigravity'&&!!(ai.settings[key]||{}).model&&!o.models.length)));   // no levels, or the list is not here yet
    if(key==='antigravity'&&!o.models.length)card.append(el('small',T('모델 목록을 불러오는 중'),'ai-note'));
    const warn=el('label','','ai-warn'),num=document.createElement('input');num.type='number';num.min='1';num.max='100';num.step='1';
    num.dataset.k=key+':warn';num.value=String((ai.settings[key]||{}).warn_percent||80);num.setAttribute('aria-label',T('{0} 경고 임계치 (%)',AI[p].name));
    num.onchange=()=>{const v=Number(num.value);
      if(!Number.isInteger(v)||v<1||v>100){notice(T('경고 임계치는 1에서 100 사이의 정수로 입력하세요.'));num.value=String((ai.settings[key]||{}).warn_percent||80);return;}
      saveAI(s=>{s[key]={...s[key],warn_percent:v};});};
    warn.append(el('span',T('경고 임계치')),num,el('span','%'));card.append(warn);
    return card;}));
  if(held){const again=box.querySelector('[data-k="'+held+'"]');if(again)again.focus();}
}
function paintAITools(){
  const sel=$('ai-interval'),mins=(ai.options.poll_minutes||[1,5,10,30]);
  if(document.activeElement!==sel){sel.replaceChildren(...mins.map(m=>new Option(T('{0}분',m),String(m))));sel.value=String(ai.settings.usage_poll_minutes||5);}
  const times=Object.values(ai.limits||{}).map(l=>l&&l.as_of?utc(l.as_of):0).filter(Boolean);
  $('ai-checked').textContent=times.length?T('마지막 조회 {0}',ago(Math.max(...times))):'';
}
function paintLimitAlert(){
  const box=$('limit-alert'),list=(ai&&ai.alerts)||[];
  box.hidden=!list.length||!!replay||!$('ai-panel').hidden;if(box.hidden)return;   // the open panel shows the same warning on its cards
  box.textContent=T('한도 경고 · ')+list.map(a=>{const p=CLI[a.cli],left=a.resets_at?(utc(a.resets_at)-Date.now())/1000:null;
    return T('{0} {1} {2}% (임계치 {3}%)',(AI[p]||{name:a.cli}).name+(a.group?' '+a.group:''),a.window==='weekly'?T('주간'):T('5시간'),Math.round(a.used_percent),a.threshold)
      +(left>0?' · '+T('{0} 뒤 초기화',left>=86400?T('{0}일 {1}시간',Math.floor(left/86400),Math.floor(left%86400/3600)):span(left)):'');}).join('  /  ');
}
let aiFails=0;
async function pollAI(force){
  if(aiBusy&&!force)return;aiBusy=true;const epoch=aiEpoch;
  try{const d=await getJSON('/ops/ai');
    if(d&&d.settings&&epoch===aiEpoch){aiFails=0;ai=d;aiAt=Date.now();paintAI(force);paintLimitAlert();if(lastModel)paintScene(lastModel);}}   // an answer from before a save is dropped
  catch(e){if(++aiFails===3)notice(T('AI 설정·한도 정보를 새로 받지 못하고 있습니다. 보이는 값은 마지막으로 받은 값입니다.'));}
  finally{aiBusy=false;}
}
function saveAI(change){          // one save at a time, each built on the result of the one before
  aiSaves=aiSaves.then(async()=>{
    if(!ai)return;const next=JSON.parse(JSON.stringify(ai.settings));change(next);
    try{const res=await fetch('/ops/ai',{method:'POST',headers:{'Content-Type':'application/json','X-Tribunal-Token':roleToken},body:JSON.stringify(next)}),out=await res.json();
      if(!res.ok)throw Error(out.error||T('저장 실패'));aiEpoch++;ai.settings=out.settings;notice(T('저장했습니다 · 다음 호출부터 적용'));}
    catch(e){notice(T('설정 저장 실패 · ')+e.message);}
    await pollAI(true);
  });
  return aiSaves;
}

// ------------------------------------------------------------------ live polling
const pollActivity=guarded(async()=>{
  try{const a=await getJSON('/ops/activity');if(a.error)throw Error(a.error);activity=a;$('shell-error').hidden=true;repaint();}
  catch(e){const s=$('shell-error');s.hidden=false;s.textContent=T('작업 현황 연결을 확인하고 있습니다 · ')+e.message;}});
const pollStatus=guarded(async()=>{try{status=await getJSON('/status');
  const pending=status.pending_result_count||0,need=status.human_required_count||0,badge=$('pending-badge');
  badge.hidden=!pending;badge.textContent=pending>99?'99+':String(pending);
  $('attention').hidden=!need||document.body.dataset.view==='workshop';$('attention-text').textContent=T('확인이 필요한 작업이 {0}건 있습니다.',need);
  repaint();}catch(e){/* the activity poll reports connection trouble */}});

// ------------------------------------------------------------------ replay (real ledger of a finished mission)
let replayLoading=false;
async function startReplay(){
  if(replay){if(attract)return;return stopReplay();}
  if(replayLoading)return;replayLoading=true;
  let data,failed=false;try{data=await getJSON('/ops/replay');}catch(e){data={calls:[]};failed=true;}finally{replayLoading=false;}
  if(replay)return;
  const calls=(data.calls||[]).filter(c=>ROLES.includes(c.role)&&AI[c.provider]).map(c=>({...c,t0:utc(c.started_at)/1000,dur:Math.max(1,c.seconds||1)}));
  if(!calls.length){notice(failed?T('다시보기 기록을 불러오지 못했습니다. 잠시 뒤 다시 시도해 주세요.'):T('다시 볼 미션 기록이 아직 없습니다.'));return;}
  let v=0,prevEnd=calls[0].t0,real=0;const gaps=[];
  calls.forEach((c,i)=>{const gap=Math.max(0,c.t0-prevEnd),vg=Math.min(gap,40);
    if(vg>6&&i&&calls[i-1].role==='BUILDER')gaps.push([v,v+vg]);                       // Director ran the tests between build and review
    v+=vg;c.v0=v;c.v1=v+c.dur;v=c.v1;real+=gap+c.dur;prevEnd=Math.max(prevEnd,c.t0+c.dur);});
  const stepOf=new Map((data.steps||[]).map(s=>[s.run_id,s])),lastCall=new Map();
  calls.forEach(c=>{if(stepOf.has(c.run_id))lastCall.set(c.run_id,c);});
  replay={data,calls,gaps,total:v,real,speed:v/72,started:performance.now(),stepOf,lastCall,done:new Set(),events:[],finished:false};
  $('replay-bar').hidden=false;document.body.classList.add('replaying');
  $('replay-text').textContent=T('{0} 미션 · 실제 기록 {1} → {2}배속',data.project,span(real),Math.round(replay.speed));
  $('btn-replay').classList.add('on');$('btn-replay').setAttribute('aria-pressed','true');closeRoleMenu();seenFeed.event.clear();seenFeed.call.clear();
  replay.timer=setInterval(replayTick,120);replayTick();
}
function stopReplay(){
  if(!replay)return;clearInterval(replay.timer);replay=null;$('replay-bar').hidden=true;document.body.classList.remove('replaying');$('btn-replay').classList.remove('on');$('btn-replay').setAttribute('aria-pressed','false');
  seenFeed.event.clear();seenFeed.call.clear();firstPaint=true;repaint();
}
function replayTick(){
  const r=replay;if(!r)return;
  const vt=Math.min(r.total,(performance.now()-r.started)/1000*r.speed);
  $('replay-fill').style.width=(vt/r.total*100)+'%';
  const working=r.calls.filter(c=>c.v0<=vt&&vt<c.v1).map(c=>({provider:c.provider,role:c.role,stage:c.stage,elapsed:vt-c.v0,at:0}));
  const done=r.calls.filter(c=>c.v1<=vt),usage={by_role:{},by_provider:{},total:{calls:0,seconds:0,tokens:0,exact_tokens:0,failed:0}};
  for(const c of done){
    for(const [group,key] of [[usage.by_role,c.role],[usage.by_provider,c.provider]]){const b=group[key]||(group[key]={calls:0,seconds:0,tokens:0,exact_tokens:0,failed:0,providers:{}});
      b.calls++;b.seconds+=c.dur;b.tokens+=c.tokens||0;b.exact_tokens+=c.exact?(c.tokens||0):0;b.failed+=c.status!=='OK'?1:0;b.providers[c.provider]=(b.providers[c.provider]||0)+1;}
    const t=usage.total;t.calls++;t.seconds+=c.dur;t.tokens+=c.tokens||0;t.exact_tokens+=c.exact?(c.tokens||0):0;t.failed+=c.status!=='OK'?1:0;
    if(!r.done.has(c)){r.done.add(c);
      const s=r.stepOf.get(c.run_id);
      if(s&&r.lastCall.get(c.run_id)===c){r.events.unshift({key:'step'+s.index,state:s.state,label:T('{0}단계 {1}',s.index,STATE_KO[s.state]||s.state||T('종료')),sub:s.tests?T('테스트 {0}/{1}',s.tests.passed,s.tests.total):'',when:T('기록')});
        if(STEP_CLASS[s.state])Trinity.pulse(PULSE[STEP_CLASS[s.state]]);}}
  }
  for(const c of r.calls)if(c.v0<=vt&&!c.announced){c.announced=true;r.events.unshift({key:'c'+c.v0,color:AI[c.provider].css,label:T('{0} 시작',(ROLE_KO[c.role]||c.role).split(' · ')[1]),sub:AI[c.provider].name,when:T('기록')});}
  const steps=(r.data.steps||[]).filter(s=>{const first=r.calls.find(c=>c.run_id===s.run_id);return first&&first.v0<=vt;})
    .map(s=>{const last=r.lastCall.get(s.run_id);return {index:s.index,state:last&&last.v1<=vt?s.state:null,tests:last&&last.v1<=vt?s.tests:null};});
  const verifying=!working.length&&r.gaps.some(g=>g[0]<=vt&&vt<g[1]),stats={};
  for(const p of Object.keys(AI)){const b=usage.by_provider[p];stats[p]=b?T('{0}회 · {1} 토큰',b.calls,tok(b.tokens)):'';}
  const finished=vt>=r.total;
  paint({mode:'replay',working,assign:assignment(),...phaseOf(working,verifying,!finished),
    mission:{goal:r.data.goal,project:r.data.project,status:finished?r.data.status:'RUNNING',live:!finished,max:Math.max(r.data.max_steps||0,(r.data.steps||[]).length),steps,
      passed:steps.filter(s=>s.state==='PASS').length,updated:Date.now(),id:'replay'},
    usage,windows:{},calls:done.slice(-6).reverse().map(c=>({key:'d'+c.v0,role:c.role,provider:c.provider,seconds:c.dur,tokens:c.tokens,exact:c.exact,status:c.status,when:T('기록')})),
    events:r.events.slice(0,7),stats,project:r.data.project});
  if(finished&&!r.finished){r.finished=true;if(r.data.status==='DONE')Trinity.pulse(PULSE.done);clearInterval(r.timer);setTimeout(()=>{if(replay===r)stopReplay();},6000);}
}

// ------------------------------------------------------------------ chat with HEAD
let lastMsg=0,sending=false,chatFails=0;
const pollChat=guarded(async()=>{
  try{const data=await getJSON('/chat/messages?after_id='+lastMsg),log=$('chat-log'),stick=log.scrollTop+log.clientHeight>=log.scrollHeight-40;
    chatFails=0;
    for(const msg of data.messages||[]){if(msg.id<=lastMsg)continue;lastMsg=msg.id;const role=['USER','HEAD','SYSTEM'].includes(msg.role)?msg.role:'SYSTEM';
      const node=el('div','','chat-msg '+role);if(role!=='SYSTEM')node.append(el('small',role==='USER'?T('나'):'HEAD'));const body=String(msg.content||'');node.append(role==='SYSTEM'&&body.length>260?body.slice(0,260)+'…':body);log.append(node);
      $('peek-role').textContent=role==='USER'?T('나'):role;$('peek-role').dataset.role=role;$('peek-text').textContent=String(msg.content||'').replace(/\s+/g,' ').slice(0,200);}
    while(log.children.length>80)log.firstChild.remove();
    if(stick)log.scrollTop=log.scrollHeight;
    if(!lastMsg)$('peek-text').textContent=T('아직 대화가 없습니다. 오른쪽에 지시를 입력해 보세요.');
  }catch(e){if(++chatFails>=2&&!lastMsg)$('peek-text').textContent=T('대화 기록을 불러오지 못했습니다. 다시 시도하는 중입니다.');}
});
async function send(text){
  if(sending||!text.trim())return;sending=true;const btn=$('chat-send');btn.disabled=true;btn.textContent=T('전송 중…');
  try{
    const body=new URLSearchParams({message:text,request_id:'stage-'+Date.now().toString(36)+Math.random().toString(36).slice(2,8)});
    const pending=fetch('/chat',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body});
    $('chat-text').value='';grow();setTimeout(pollChat,600);
    const res=await pending,out=await res.json().catch(()=>({}));
    if(out.status==='busy'){restore(text);notice(T('HEAD가 이전 요청을 처리하고 있습니다. 잠시 뒤 다시 보내 주세요.'));}
    else if(out.status==='error'||!res.ok)notice(T('HEAD가 응답하지 못했습니다 · ')+(out.error||res.status)+T(' · 보낸 내용은 대화 기록에 남아 있습니다'));
  }catch(e){restore(text);notice(T('전송 실패 · ')+e.message+T(' · 대화 기록에 이미 들어갔는지 확인한 뒤 다시 보내 주세요'));}
  finally{sending=false;btn.disabled=false;btn.textContent=T('보내기');pollChat();pollActivity();}
}
let noticeTimer=0;
function notice(text){const s=$('toast');s.hidden=false;s.textContent=text;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>{s.hidden=true;},6000);}
function restore(text){const t=$('chat-text');if(!t.value){t.value=text;grow();}}   // a message that was not accepted goes back into the box
function grow(){const t=$('chat-text');t.style.height='48px';const h=t.scrollHeight+2;t.style.height=Math.min(160,Math.max(48,h))+'px';t.style.overflowY=h>160?'auto':'hidden';}

// ------------------------------------------------------------------ views
function setAIPanel(open,quiet){const p=$('ai-panel');p.hidden=!open;$('btn-ai').setAttribute('aria-expanded',String(open));
  if(open){if(openId!=null)closeCall();paintAI(true);pollAI();$('ai-close').focus();}else if(!quiet)$('btn-ai').focus();
  paintLimitAlert();}
function setChatLog(open){const log=$('chat-log');log.hidden=!open;$('chat-peek').setAttribute('aria-expanded',String(open));if(open)log.scrollTop=log.scrollHeight;}
function setView(view){
  document.body.dataset.view=view;const work=view==='workshop',frame=$('workspace');
  $('workshop').hidden=!work;$('tab-stage').classList.toggle('on',!work);$('tab-workshop').classList.toggle('on',work);
  $('tab-stage').setAttribute('aria-pressed',String(!work));$('tab-workshop').setAttribute('aria-pressed',String(work));
  if(work&&!frame.getAttribute('src'))frame.src='/classic';
  if(work){$('attention').hidden=true;setBroadcast(false);closeRoleMenu();setChatLog(false);if(openId!=null)closeCall();if(!$('ai-panel').hidden)setAIPanel(false,true);}
}
function setBroadcast(on){
  document.body.classList.toggle('broadcast',on);$('btn-broadcast').textContent=on?T('방송 모드 끝내기'):T('방송 모드');$('btn-broadcast').setAttribute('aria-pressed',String(on));if(on)closeRoleMenu();
  try{if(on&&!document.fullscreenElement)document.documentElement.requestFullscreen().catch(()=>{});else if(!on&&document.fullscreenElement)document.exitFullscreen().catch(()=>{});}catch(e){/* fullscreen is optional */}
}
function start(){
  Trinity.init($('trinity-canvas'),{onFrame});
  if(params.get('broadcast')==='1'||attract){document.body.classList.add('broadcast');$('btn-broadcast').textContent=T('방송 모드 끝내기');$('btn-broadcast').setAttribute('aria-pressed','true');}   // e.g. an OBS browser source: /?attract=1
  $('tab-stage').onclick=()=>setView('stage');$('tab-workshop').onclick=()=>setView('workshop');$('attention-go').onclick=()=>setView('workshop');
  $('top-project').onclick=async()=>{const b=$('top-project');if(b.disabled||replay)return;b.disabled=true;b.textContent=T('폴더 선택 창이 열려 있습니다…');
    try{const r=await chooseProjectFolder();if(r)notice(r.ok?T('작업 폴더를 바꿨습니다 · ')+r.path:T('선택할 수 없는 폴더입니다 · ')+r.message);}
    catch(e){notice(T('폴더 선택 창을 열지 못했습니다 · ')+e.message+T(' (작업실 탭에서 경로를 직접 입력할 수 있습니다)'));}
    finally{b.disabled=false;if(lastModel)paintNow(lastModel);pollStatus();pollChat();}};
  for(const label of document.querySelectorAll('.slot-label')){label.title=T('이 역할을 맡을 AI 바꾸기');label.tabIndex=0;label.setAttribute('role','button');label.setAttribute('aria-haspopup','menu');label.setAttribute('aria-expanded','false');
    label.onclick=e=>{e.stopPropagation();openRoleMenu(label);};label.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openRoleMenu(label);}};}
  document.addEventListener('click',e=>{if(!e.target.closest('#role-menu'))closeRoleMenu();});
  $('btn-replay').onclick=startReplay;$('replay-stop').onclick=stopReplay;
  $('btn-broadcast').onclick=()=>setBroadcast(!document.body.classList.contains('broadcast'));
  document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement&&document.body.classList.contains('broadcast'))setBroadcast(false);});
  for(const b of $('win-tabs').children)b.onclick=()=>{win=b.dataset.win;winAuto=false;repaint();};
  $('now-doing').onclick=()=>{if(liveCall)openCall(liveCall.id);};$('cp-close').onclick=closeCall;
  $('btn-ai').onclick=()=>setAIPanel($('ai-panel').hidden);$('ai-close').onclick=()=>setAIPanel(false);
  $('limit-alert').onclick=()=>{if($('ai-panel').hidden)$('btn-ai').click();};
  $('ai-interval').onchange=()=>saveAI(s=>{s.usage_poll_minutes=Number($('ai-interval').value);});
  $('ai-health').onclick=async()=>{const b=$('ai-health');b.disabled=true;
    try{const res=await fetch('/providers/refresh',{method:'POST',headers:{'Accept':'application/json','X-Requested-With':'fetch'}});if(!res.ok)throw Error(String(res.status));
      const out=await res.json();await pollStatus();
      for(const p of AI_ORDER)if(status&&status.providers&&status.providers[p]&&(out.providers||{})[p])status.providers[p].status=out.providers[p];   // the answer just given wins over a cached /status
      paintAI(true);
      notice(T('AI 상태를 다시 확인했습니다 · ')+AI_ORDER.map(p=>AI[p].name+' '+((HEALTH[(out.providers||{})[p]]||[(out.providers||{})[p]||'?'])[0])).join(' · '));}
    catch(e){notice(T('AI 상태 확인 실패 · ')+e.message);}finally{b.disabled=false;}};
  $('ai-refresh').onclick=async()=>{const b=$('ai-refresh');b.disabled=true;
    try{const res=await fetch('/ops/ai/refresh',{method:'POST',headers:{'Content-Type':'application/json','X-Tribunal-Token':roleToken},body:'{}'});if(!res.ok)throw Error(String(res.status));
      await pollAI(true);setTimeout(()=>pollAI(true),6000);notice(T('세 CLI에 다시 묻는 중입니다. 잠시 뒤 값이 바뀝니다.'));}
    catch(e){notice(T('조회 요청 실패 · ')+e.message);}finally{b.disabled=false;}};
  for(const b of $('cp-filters').children)b.onclick=()=>{callFilter=b.dataset.f;for(const o of $('cp-filters').children){o.classList.toggle('on',o===b);o.setAttribute('aria-pressed',String(o===b));}paintCall();};
  $('chat-peek').onclick=()=>setChatLog($('chat-log').hidden);
  $('chat-form').addEventListener('submit',e=>{e.preventDefault();send($('chat-text').value);});
  $('chat-text').addEventListener('input',grow);
  $('chat-text').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.keyCode!==229){e.preventDefault();send($('chat-text').value);}});
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'){   // one layer per press, the topmost first
      if(!$('role-menu').hidden)closeRoleMenu(true);else if(!$('chat-log').hidden){setChatLog(false);if(e.target.id!=='chat-text')$('chat-peek').focus();}
      else if(!$('ai-panel').hidden)setAIPanel(false);else if(openId!=null)closeCall();else if(replay)stopReplay();return;}
    if(e.target.closest('textarea,input,select,[contenteditable]')||e.ctrlKey||e.metaKey||e.altKey||e.isComposing||e.repeat||document.body.dataset.view!=='stage')return;
    if(e.key==='b'||e.key==='B'||e.key==='ㅠ')setBroadcast(!document.body.classList.contains('broadcast'));
    if(e.key==='r'||e.key==='R'||e.key==='ㄱ')startReplay();});
  setInterval(()=>{const d=new Date();$('top-clock').textContent=[d.getHours(),d.getMinutes(),d.getSeconds()].map(n=>String(n).padStart(2,'0')).join(':');if(!replay)tickTimer();},1000);
  pollActivity();pollStatus();pollChat();pollRoles();setInterval(pollRoles,8000);
  setInterval(pollActivity,3000);setInterval(pollStatus,6000);setInterval(pollChat,3000);setInterval(pollCall,2000);pollAI();setInterval(pollAI,20000);setInterval(()=>{if(ai&&Object.values(ai.accounts||{}).some(a=>a.pending||a.loading))pollAI();},5000);   // a sign-in under way is watched more closely
     // cheap: the server answers from memory and asks the CLIs itself, at the interval chosen in the panel
}
window.TrinityStage={model:()=>lastModel,replaying:()=>!!replay};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
