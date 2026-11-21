'use strict';
/* TRINITY stage HUD. Reads the same read-only endpoints as the workshop (/ops/activity, /status, /chat/messages,
   /ops/replay) and turns them into one model that both the DOM panels and the WebGL scene are painted from.
   Live and replay build the same model, so a replay shows exactly what the live view would have shown. */
(function(){
const T=(window.I18N&&window.I18N.t)||((s,...a)=>s.replace(/\{(\d+)\}/g,(m,i)=>i<a.length?String(a[i]):m)),LANG=window.I18N?window.I18N.lang:'ko';
const $=id=>document.getElementById(id);
const AI={ANTHROPIC:{name:'Claude',rgb:[1,.54,.36],css:'#ff8a5c'},OPENAI:{name:'Codex',rgb:[.24,.95,.75],css:'#3df2c0'},GOOGLE:{name:'Antigravity',rgb:[.42,.65,1],css:'#6aa5ff'}};
const ROLES=['ARCHITECT','MAKER','INSPECTOR'];
const ROLE_KO={ARCHITECT:T('ARCHITECT · 설계'),MAKER:T('MAKER · 제작'),INSPECTOR:T('INSPECTOR · 감리')};
const DEFAULT_ASSIGN={ARCHITECT:'ANTHROPIC',MAKER:'GOOGLE',INSPECTOR:'OPENAI'};
const PIPE=['PLANNING','BUILDING','VERIFYING','REVIEWING','DECIDING'];
const PHASE={
  IDLE:{word:T('대기'),sub:T('세 AI가 지시를 기다립니다'),core:.18},
  BETWEEN:{word:T('준비'),sub:T('다음 AI 호출을 준비합니다'),core:.42},
  PLANNING:{word:T('설계'),sub:T('ARCHITECT가 할 일을 정합니다'),core:.56},
  BUILDING:{word:T('제작'),sub:T('MAKER가 코드를 씁니다'),core:.72},
  VERIFYING:{word:T('테스트'),sub:T('TRIBUNAL이 직접 실행해 확인합니다'),core:1},
  REVIEWING:{word:T('감리'),sub:T('INSPECTOR가 독립적으로 살핍니다'),core:.72},
  DECIDING:{word:T('판단'),sub:T('ARCHITECT가 통과 여부를 결정합니다'),core:.86}};
const STAGE_TEXT={CHAT:T('요청을 읽고 있습니다'),MISSION_PLANNING:T('다음 단계를 계획하고 있습니다'),PLANNING:T('작업 지시서를 쓰고 있습니다'),ORDER_READY:T('작업 지시서를 쓰고 있습니다'),
  BUILDING:T('코드를 작성하고 있습니다'),REVIEWING:T('결과물을 감리하고 있습니다'),DECIDING:T('통과 여부를 판단하고 있습니다')};
const SHORT={CHAT:T('요청 확인 중'),MISSION_PLANNING:T('다음 단계 계획 중'),PLANNING:T('지시서 작성 중'),ORDER_READY:T('지시서 작성 중'),BUILDING:T('코드 작성 중'),REVIEWING:T('감리 중'),DECIDING:T('판단 중')};
const STAGE_LABEL={PLANNING:T('설계'),ORDER_READY:T('제작 준비'),BUILDING:T('제작'),VERIFYING:T('테스트'),REVIEWING:T('감리'),DECIDING:T('판단'),PASS:T('통과'),FAIL:T('실패'),
  HUMAN_REQUIRED:T('사용자 확인'),TIMEOUT:T('시간 초과'),IDLE:T('대기'),MISSION_PLANNING:T('다음 단계 계획'),ENTRY_REVIEW:T('오더 검토'),CHAT:T('대화')};
const STATE_KO={PASS:T('통과'),FAIL:T('실패'),TIMEOUT:T('시간 초과'),HUMAN_REQUIRED:T('확인 필요'),RECOVERED:T('복구 완료')};
const STEP_CLASS={PASS:'ok',RECOVERED:'ok',FAIL:'bad',TIMEOUT:'bad',HUMAN_REQUIRED:'warn'},STEP_MARK={ok:'✓',bad:'✗',warn:'!',run:'▶',todo:''};
const MISSION_BADGE={DONE:[T('완료'),'ok'],INCOMPLETE:[T('단계 한도 도달'),'warn'],BLOCKED:[T('확인 필요'),'warn'],FAILED:[T('실패'),'bad']};
// The inspector's own tests in one step (server: inspector_tests.summary) → what to show, or null when there is no record.
const ITEST_REASON={'no acceptable test file':T('받아들일 수 있는 테스트 파일이 없습니다'),'no test command is configured':T('테스트 명령이 설정되어 있지 않습니다'),"the project's own tests do not pass yet":T('프로젝트 자체 테스트가 아직 통과하지 못했습니다'),'the worktree is too large to copy':T('작업 폴더가 너무 커서 복사하지 않았습니다'),'the run record is inside the worktree':T('실행 기록이 작업 폴더 안에 있습니다'),'the work folder is missing':T('작업 폴더를 찾지 못했습니다'),'could not be run':T('실행하는 중에 오류가 났습니다'),
  'path and content must be text':T('경로와 내용이 글자가 아닙니다'),'must be a repo-relative path with forward slashes':T('프로젝트 기준 상대 경로가 아닙니다'),'must be a plain relative path inside a test directory':T('테스트 폴더 안의 단순한 상대 경로가 아닙니다'),'file name must mark it as an inspector test (e.g. test_inspector_<topic>.py)':T('파일 이름이 감리 테스트 형식이 아닙니다'),'must be inside a test directory (tests/, test/, __tests__/, spec/)':T('테스트 폴더 안이 아닙니다'),'protected path':T('보호된 경로입니다'),'its directory does not exist in the project':T('프로젝트에 없는 폴더입니다'),'a file with this name already exists':T('같은 이름의 파일이 이미 있습니다'),'outside the worktree':T('작업 폴더 밖입니다'),'listed twice':T('두 번 적혀 있습니다'),'contains code that could move real money':T('실제 돈을 움직일 수 있는 코드가 들어 있습니다')};
function itestReason(r){return ITEST_REASON[r]||(/^larger than /.test(r)?T('파일이 너무 큽니다'):/^more than /.test(r)?T('파일 수가 한도를 넘었습니다'):r);}
// "1단계 만에 완료 · 최대 6단계": how far the mission got, in words (steps used / passed / the limit).
function stepLine(used,passed,max,status,live){
  if(!used)return T('아직 시작한 단계가 없습니다 · 최대 {0}단계',max);
  if(status==='RUNNING')return live===false?T('{0}단계에서 멈춤 · 최대 {1}단계',used,max):T('{0}단계 진행 중 · 최대 {1}단계',used,max);
  if(status==='DONE'&&passed===used)return T('{0}단계 만에 완료 · 최대 {1}단계',used,max);
  if(status==='INCOMPLETE'&&used>=max)return T('{0}단계를 모두 썼지만 끝내지 못함',max);
  return T('{0}단계 중 {1}단계 통과 · 최대 {2}단계',used,passed,max);
}
function testLine(t){const total=t.total||0,bad=Math.max(t.failed||0,total-(t.passed||0));return !total?T('테스트 결과 없음'):bad>0?T('테스트 {0}개 중 {1}개 실패',total,bad):T('테스트 {0}개 모두 통과',total);}
function inspectorTests(t){
  if(!t||!t.status)return null;
  const files=t.files||[],n=files.length,tip=[];
  const label=t.status==='passed'?T('감리 테스트 통과 · 파일 {0}개',n):t.status==='failed'?T('감리 테스트 실패 · 파일 {0}개',n):t.status==='skipped'?T('감리 테스트 건너뜀'):T('감리 테스트 제안 없음');
  if(t.status==='none')tip.push(T('INSPECTOR가 추가 테스트를 제안하지 않았습니다. 기존 테스트가 기준을 충분히 확인한다고 본 경우입니다.'));
  if(n)tip.push(T('INSPECTOR가 쓴 테스트를 TRIBUNAL이 버리는 복사본에서 실행했습니다: {0}',files.join(', ')));
  if(n&&t.counts&&t.counts.total!=null)tip.push(T('함께 실행한 전체 테스트 {0}/{1} 통과',t.counts.passed,t.counts.total));
  if(t.status==='failed')tip.push(T('실패는 수정 요청으로 처리됩니다.'));
  if(t.reason)tip.push(T('건너뛴 이유: {0}',itestReason(t.reason)));
  for(const r of t.rejected||[])tip.push(T('받지 않은 파일: {0} ({1})',r.path,itestReason(r.reason)));
  return {label,cls:t.status==='passed'?'ok':t.status==='failed'?'bad':t.status==='skipped'?'warn':'none',tip};
}
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
  if(roleSettings&&!isLiveNow())return {ARCHITECT:CLI[roleSettings.architect],MAKER:CLI[roleSettings.maker],INSPECTOR:CLI[roleSettings.inspector]};
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
  menu.dataset.slot=String(slot);menu.replaceChildren(el('p',T('{0} 담당 AI',ROLE_KO[role])+(isLiveNow()?T(' · 진행 중인 작업은 그대로, 다음 작업부터 적용'):'')));
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
  const w=working.find(x=>x.role==='MAKER')||working.find(x=>x.role==='INSPECTOR')||working[0];
  if(w){
    if(w.role==='MAKER')return {phase:'BUILDING',w};
    if(w.role==='INSPECTOR')return {phase:'REVIEWING',w};
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
      steps:focus.steps.map(s=>({index:s.index,state:s.state,tests:s.tests,itests:s.inspector_tests,run:s.run_id,note:s.note,review:s.review,repairs:s.repairs})),passed:focus.passed_steps,blocked:focus.blocked_reason,summary:focus.summary,deliverableRun:focus.deliverable_run_id,updated:utc(focus.updated_at),id:focus.mission_id,
      deliverable:focus.deliverable,applied:focus.applied,applyState:focus.apply_state,source:focus.source,profile:focus.profile},
    usage:usage[win]||{by_role:{},by_provider:{},total:{calls:0,seconds:0,tokens:0,exact_tokens:0}},windows:{mission:!!usage.mission,today:!!usage.today,all:!!usage.all},
    calls:(a.recent_calls||[]).slice(0,6).map(c=>({id:c.id,key:c.at+c.role+c.provider,role:c.role,provider:c.provider,seconds:c.seconds,tokens:c.tokens,exact:c.exact,status:c.status,at:utc(c.at)})),
    events:(a.events||[]).slice(0,7).map(e=>({key:e.at+e.run_id+e.to_state,state:e.to_state,label:STAGE_LABEL[e.to_state]||e.state_ko||e.to_state,sub:e.project,at:utc(e.at)})),
    stats,project:(status&&status.project_name)||(focus&&focus.project)||'—'};
}

// ------------------------------------------------------------------ painting
function actorColor(m){return m.w?AI[m.w.provider]?.css||'#fff':m.phase==='VERIFYING'?'#b9ffe2':'#9fb4d8';}
function sentence(m){
  if(m.w){const name=(AI[m.w.provider]||{name:m.w.provider}).name;return [name,T('가 ')+(STAGE_TEXT[m.w.stage]||(m.w.role==='MAKER'?STAGE_TEXT.BUILDING:m.w.role==='INSPECTOR'?STAGE_TEXT.REVIEWING:T('생각하고 있습니다')))];}
  if(m.phase==='VERIFYING')return ['TRIBUNAL',T('이 테스트를 실행하고 있습니다')];
  if(m.phase==='BETWEEN')return ['',T('다음 AI 호출을 준비하고 있습니다')];
  return ['',T('세 AI가 지시를 기다리고 있습니다')];
}
function setSentence(node,m){const [who,rest]=sentence(m);if(node.textContent===who+rest)return;node.replaceChildren();if(who)node.append(el('em',who));node.append(rest);}
function paintNow(m){
  document.body.dataset.phase=m.phase;
  document.documentElement.style.setProperty('--actor',actorColor(m));
  setSentence($('now-headline'),m);setSentence($('caption'),m);
  const ms=m.mission,step=ms&&ms.steps.length?ms.steps[ms.steps.length-1].index:0;
  $('now-sub').textContent=m.phase==='IDLE'?(ms?(m.mode==='replay'?T('다시보기 끝 · ')+(MISSION_BADGE[ms.status]||[ms.status])[0]:T('마지막 작업 ')+(MISSION_BADGE[ms.status]||[ms.status])[0]+' · '+ago(ms.updated)):T('아래 입력창에 지시하면 세 AI가 일을 시작합니다.'))
    :(ms&&(ms.live||m.mode==='replay')?T('{0}단계 진행 중 · 최대 {1}단계',step,ms.max)+' · '+ms.project:PHASE[m.phase].sub);
  $('now-stage').textContent=m.w?ROLE_KO[m.w.role]||m.w.role:PHASE[m.phase].word;
  timerBase=m.w?{at:m.w.at,fixed:m.mode==='replay'?m.w.elapsed:null,estimate:m.mode==='live'?m.w.estimate:null}:null;tickTimer();
  $('phase-word').textContent=PHASE[m.phase].word;$('phase-sub').textContent=PHASE[m.phase].sub;
  const at=PIPE.indexOf(m.phase);
  for(const li of $('pipeline').children){const i=PIPE.indexOf(li.dataset.stage);li.classList.toggle('on',i===at);li.classList.toggle('done',at>i&&at>=0);
    const role=li.dataset.stage==='BUILDING'?'MAKER':li.dataset.stage==='REVIEWING'?'INSPECTOR':li.dataset.stage==='VERIFYING'?null:'ARCHITECT';
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
  if(!ms){badge.textContent='—';badge.className='badge';$('mission-goal').textContent=T('아직 작업 기록이 없습니다. 지시를 보내면 여기에 단계별 진행이 표시됩니다.');steps.replaceChildren();$('mission-meta').textContent='';delete $('mission-meta').dataset.sig;paintAttention(m);paintDelivery(m);paintLoose(m);return;}
  const running=ms.status==='RUNNING',b=running?(ms.live?[T('진행 중'),'run']:[T('중단됨 · 재개 대기'),'warn']):(MISSION_BADGE[ms.status]||[ms.status,'']);
  badge.textContent=b[0];badge.className='badge '+b[1];$('mission-goal').textContent=ms.goal;$('mission-goal').title=ms.goal;
  while(steps.children.length>ms.max)steps.lastChild.remove();
  while(steps.children.length<ms.max)steps.append(el('span',String(steps.children.length+1)));
  for(let i=0;i<ms.max;i++){const s=ms.steps.find(x=>x.index===i+1),chip=steps.children[i];
    chip.className=s?(STEP_CLASS[s.state]||'run'):'todo';chip.title=s?T('{0}단계 · {1}',i+1,STATE_KO[s.state]||T('진행 중')):T('아직 쓰지 않은 단계');
    const mark=STEP_MARK[chip.className]+(i+1);if(chip.textContent!==mark)chip.textContent=mark;chip.setAttribute('role','img');chip.setAttribute('aria-label',chip.title);}
  const last=[...ms.steps].reverse().find(s=>s.tests);
  const meta=$('mission-meta'),text=stepLine(ms.steps.length,ms.passed,ms.max,ms.status,m.mode==='replay'||ms.live)+(last?' · '+testLine(last.tests):'');
  const it=inspectorTests((ms.steps[ms.steps.length-1]||{}).itests),sig=text+'|'+(it?it.cls+it.label+it.tip.join('|'):'');      // the newest step only: an older step's outcome would read as the current one
  if(meta.dataset.sig!==sig){meta.dataset.sig=sig;const open=!!meta.querySelector('details[open]');meta.replaceChildren(text);
    if(it){const box=el('details','','itest '+it.cls);box.open=open&&it.tip.length>0;box.append(el('summary',it.label));for(const line of it.tip)box.append(el('p',line));meta.append(box);}}
  paintAttention(m);paintDelivery(m);paintLoose(m);
  if(m.mode!=='live')return;
  for(const s of ms.steps){const key=ms.id+':'+s.index,prev=seenSteps.get(key);seenSteps.set(key,s.state);
    if(!firstPaint&&prev!==s.state&&STEP_CLASS[s.state])Trinity.pulse(PULSE[STEP_CLASS[s.state]]);}
  const mk=ms.id+':status',prev=seenSteps.get(mk);seenSteps.set(mk,ms.status);
  if(!firstPaint&&prev&&prev!==ms.status&&ms.status==='DONE')Trinity.pulse(PULSE.done);
}
const APPLY_KO={applied:[T('원본에 적용됨'),'ok'],blocked:[T('적용 보류 · 충돌/조건'),'warn'],pending:[T('적용 대기'),'warn'],discarded:[T('폐기됨'),''],rolled_back:[T('적용 실패 · 복구됨'),'bad'],busy:[T('적용 진행 중'),'run'],error:[T('적용 오류'),'bad']};
let deliveryBusy=false;
async function decideMission(id,action,extra){
  if(deliveryBusy)return null;deliveryBusy=true;let answer=null;if(lastModel){paintAttention(lastModel);paintDelivery(lastModel);}if(result)paintResult();
  try{const body=new URLSearchParams({mission_id:id,action,...(extra||{})});
    const res=await fetch('/ops/mission/decide',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body});
    const out=await res.json().catch(()=>({}));
    if(!res.ok||!out.status)throw Error(out.error||out.reason||(T('서버 응답 ')+res.status));
    const msg={applied:T('원본에 적용했습니다 · {0}개 파일',(out.files||[]).length),blocked:T('적용할 수 없습니다 · ')+blockText(out.blocks).slice(0,160),discarded:T('결과물을 폐기했습니다'),resumed:T('작업을 이어서 진행합니다 (최대 {0}단계)',out.max_steps),busy:T('다른 작업이 진행 중입니다'),stale:T('결과물이 바뀌었습니다. 변경 내용을 다시 열어 확인해 주세요.')}[out.status]||(out.status+' '+(out.error||out.reason||''));
    notice(msg);Trinity.pulse(out.status==='applied'?PULSE.done:out.status==='blocked'?PULSE.warn:PULSE.ok);answer=out;}
  catch(e){notice(T('요청 실패 · ')+e.message);}
  finally{deliveryBusy=false;if(lastModel){paintAttention(lastModel);paintDelivery(lastModel);}await pollActivity();if(result)paintResult();}
  return answer;
}
// The engine names conflicting files in English ("Conflicts: a.py, b.py"); the rest of a refusal is shown as it is.
function blockText(blocks){return (blocks||[]).map(b=>String(b).replace(/^Conflicts: /,T('충돌한 파일: '))).join('; ');}
function applyMission(ms,state){
  if(confirm(state==='blocked'?T('충돌한 파일은 건너뛰고 나머지 변경만 원본 프로젝트({0})에 적용할까요?',ms.project||'—'):T('이 작업의 결과물을 원본 프로젝트({0})에 적용할까요? 프로젝트의 파일이 바뀝니다.',ms.project||'—')))
    return decideMission(ms.id,'apply',{on_conflict:state==='blocked'?'skip':'block',...(ms.deliverableRun?{run_id:ms.deliverableRun}:{})});
  return null;
}

// ------------------------------------------------------------------ approval and "why it stopped", on the mission card
const KO=!window.I18N||window.I18N.lang!=='en';
let approvalBusy=false,approvalSaid='';
const orders=new Map();                                    // run id -> ORDER, fetched once when its details are opened
async function decideRun(runId,kind){
  if(approvalBusy)return;approvalBusy=true;if(lastModel)paintAttention(lastModel);
  try{const rid=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():String(Date.now())+'-'+Math.random().toString(16).slice(2);
    const res=await fetch(kind==='approve'?'/run/approve':'/run/reject',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json','X-Requested-With':'fetch'},body:new URLSearchParams({run_id:runId,request_id:rid})});
    const out=await res.json().catch(()=>({}));
    if(!res.ok&&!out.status)throw Error(T('서버 응답 ')+res.status);
    const good=out.status==='accepted'||out.status==='ok';
    approvalSaid=good?(kind==='approve'?T('승인했습니다 · 안전 검사를 거쳐 작업을 계속합니다'):T('거절했습니다 · 이 단계는 실행되지 않습니다')):T('처리하지 못했습니다 · ')+(out.message||out.error||out.status||'');
    notice(approvalSaid);if(good)Trinity.pulse(kind==='approve'?PULSE.ok:PULSE.warn);}
  catch(e){notice(T('요청 실패 · ')+e.message);}
  finally{approvalBusy=false;await pollStatus();pollActivity();}
}
function stopReason(text){
  const s=String(text||'');let m;
  if((m=s.match(/^(\d+) consecutive milestones failed/)))return T('{0}단계 연속으로 통과하지 못해 멈췄습니다.',m[1]);
  if((m=s.match(/^step budget \((\d+)\) used; next step was: (.*)$/s)))return T('최대 {0}단계를 모두 썼습니다. 다음에 하려던 일: {1}',m[1],m[2]);
  if((m=s.match(/^ARCHITECT could not plan the next step: (.*)$/s)))return T('ARCHITECT가 다음 단계를 계획하지 못했습니다: {0}',m[1]);
  return s;
}
function stepNote(s){
  const bits=[T('{0}단계 · {1}',s.index,STATE_KO[s.state]||s.state||T('진행 중'))];
  if(s.tests)bits.push(testLine(s.tests));
  if(s.review)bits.push(s.review==='pass'?T('감리 통과'):T('감리 수정 요청'));
  if(s.repairs)bits.push(T('자동 수정 {0}회',s.repairs));
  return bits.join(' · ');
}
function orderDetails(runId){
  const box=el('details','','more');box.append(el('summary',T('ARCHITECT가 세운 이 단계의 지시서')));const body=el('div');box.append(body);
  const fill=o=>{body.replaceChildren();
    if(!o){body.append(el('p',T('지시서를 불러오지 못했습니다.')));return;}
    const list=el('ol');
    const row=(label,value)=>{const text=Array.isArray(value)?value.join(', '):value;if(text){const li=el('li');li.append(el('b',label+' '),el('span',String(text).slice(0,600)));list.append(li);}};
    row(T('목표:'),o.goal);row(T('바꿀 수 있는 파일:'),o.allowed_paths);row(T('건드리면 안 되는 파일:'),o.protected_paths);row(T('지울 수 있는 것:'),o.allowed_deletions);row(T('완료 기준:'),o.acceptance_criteria);
    body.append(list);};
  box.addEventListener('toggle',async()=>{if(!box.open||box.dataset.loaded)return;box.dataset.loaded='1';
    if(orders.has(runId))return fill(orders.get(runId));
    body.replaceChildren(el('p',T('지시서를 불러오는 중…')));
    try{const r=await getJSON('/run/inspect?run_id='+encodeURIComponent(runId));if(r.error)throw Error(r.error);if(r.order)orders.set(runId,r.order);fill(r.order||null);if(!r.order)delete box.dataset.loaded;}catch(e){fill(null);delete box.dataset.loaded;}});
  return box;
}
// Which block the card shows: 'approve' (a decision is asked of the user), 'wait' (approved, restarting), 'stuck'
// (stopped by a gate no approval can open) or 'stopped' (the mission ended without finishing). null: nothing to say.
const AT_WORK=new Set(['PLANNING','ORDER_READY','BUILDING','VERIFYING','REVIEWING','DECIDING']);
function attentionKind(m){
  const ms=m.mission,ap=status&&status.approval;
  if(m.mode!=='live')return null;
  // The waiting run is this card's business when it is a step of the mission shown, or when it belongs to no mission
  // at all: a task stopped at its very start has no mission yet, and no other card would ever ask about it.
  const inCard=!!(ap&&ms&&ms.steps.some(s=>s.run===ap.run_id));
  const orphan=!!(ap&&!inCard&&ap.in_mission===false);          // the server's word: this page sees only the newest few missions
  const mine=ap&&ap.state==='HUMAN_REQUIRED'&&(inCard||orphan);
  if(mine&&ap.required)return 'approve';
  if(mine&&(ap.inflight||ap.approved)&&!ap.rejected)return 'wait';
  if(mine&&!ap.rejected&&(ap.blocking||[]).length)return 'stuck';
  if(ms&&!ms.live&&['BLOCKED','INCOMPLETE','FAILED'].includes(ms.status)){
    // An approved run is picked up again before the mission record says so: its last step is at work, nothing is stopped.
    const last=ms.steps[ms.steps.length-1];
    return last&&AT_WORK.has(last.state)?'wait':'stopped';}
  return null;
}
function paintAttention(m){
  let box=$('mission-attention');
  if(!box){box=el('div','','delivery attention-box');box.id='mission-attention';$('mission-card').append(box);}
  const ms=m.mission,ap=(status&&status.approval)||{},kind=attentionKind(m);
  $('mission-card').classList.toggle('attn',kind==='approve');$('mission-card').classList.toggle('stopped',kind==='stuck'||kind==='stopped');
  const dstate=ms?((ms.applied&&ms.applied.status)||ms.applyState||'pending'):'',offered=!!(ms&&ms.deliverable&&dstate!=='applied'&&dstate!=='discarded');   // the delivery box below offers "이어서 진행"
  const own=!!(ms&&ms.steps.some(s=>s.run===ap.run_id));                // false: a new task that has no card yet
  const sig=JSON.stringify(!kind?[]:[kind,own,ap.goal,ms&&ms.id,ms&&ms.status,ms&&ms.blocked,ms&&ms.summary,ms&&ms.steps,ap.run_id,ap.stage,ap.items,ap.blocking,approvalBusy,deliveryBusy,offered]);
  if(box.dataset.sig===sig)return;box.dataset.sig=sig;        // rebuilt only on a real change: an open list or the focus survives every poll
  const held=box.contains(document.activeElement)?document.activeElement.dataset.act:null,opened=[...box.querySelectorAll('details[open]')].map(d=>d.dataset.k);
  box.replaceChildren();box.hidden=!kind;if(!kind){delete box.dataset.kind;return;}
  const word=it=>(KO&&it.title_ko)||it.title||it.code||'',why=it=>(KO&&it.why_ko)||it.why||'';
  // `file` is a path for most gates and a sentence for a decision the ARCHITECT handed back to the user
  const list=items=>{const ul=el('ul','','why');for(const it of items){const li=el('li',word(it));if(it.file){if(/\s/.test(it.file)&&it.file.length>40)li.append(el('p',it.file));else li.append(' · ',el('code',it.file));}ul.append(li);}return ul;};
  if(kind==='approve'){
    const items=ap.items||[];
    box.append(el('strong',ap.stage==='POST_BUILD'?T('제작 결과에 확인이 필요합니다'):own?T('시작 전에 확인이 필요합니다'):T('새 작업이 승인을 기다립니다')));
    if(!own&&ap.goal)box.append(el('p',ap.goal,'new-goal'));
    if(items[0]&&why(items[0]))box.append(el('p',why(items[0])));
    if(items.length)box.append(list(items));
    const row=el('div','','delivery-actions');
    const yes=el('button',approvalBusy?T('처리 중…'):T('승인하고 계속'));yes.type='button';yes.className='warn';yes.dataset.act='approve';yes.onclick=()=>decideRun(ap.run_id,'approve');
    const no=el('button',T('거절'));no.type='button';no.dataset.act='reject';no.onclick=()=>{if(confirm(T('이 단계를 거절할까요? 거절하면 이 단계는 실행되지 않습니다.')))decideRun(ap.run_id,'reject');};
    for(const b of [yes,no])b.disabled=approvalBusy;
    row.append(yes,no);box.append(row);const d=orderDetails(ap.run_id);d.dataset.k='order';box.append(d);
  }else if(kind==='wait'){
    box.append(el('strong',T('작업을 다시 시작하는 중')),el('p',T('안전 검사를 거친 뒤 이어서 진행합니다.')));
  }else{
    box.append(el('strong',T('멈춘 이유')));
    if(kind==='stuck'){box.append(el('p',T('승인으로 풀 수 없는 문제로 멈췄습니다. ARCHITECT에게 다시 지시해 주세요.')));if(!own&&ap.goal)box.append(el('p',ap.goal,'new-goal'));box.append(list(ap.blocking));
      const first=ap.blocking[0];if(why(first))box.append(el('small',why(first),'ai-sub'));}
    else box.append(el('p',stopReason(ms.blocked)||T('끝내지 못하고 멈췄습니다.')));
    if(ms&&ms.steps.length&&(own||kind==='stopped')){const d=el('details','','more');d.dataset.k='steps';d.append(el('summary',T('단계별 결과')));const ol=el('ol');
      for(const s of ms.steps){const li=el('li');li.append(el('b',stepNote(s)));if(s.note)li.append(el('span',' — '+s.note));ol.append(li);}
      d.append(ol);box.append(d);}
    if(ms&&ms.summary&&(own||kind==='stopped')){const d=el('details','','more');d.dataset.k='summary';d.append(el('summary',T('ARCHITECT 요약')),el('p',ms.summary));box.append(d);}
    if(kind==='stopped'&&(!offered||ms.status==='BLOCKED')){      // BLOCKED: more steps would stop at the same gate, so the ARCHITECT plans again
      const act=ms.status==='BLOCKED'?'replan':'extend',row=el('div','','delivery-actions'),again=el('button',deliveryBusy?T('처리 중…'):act==='replan'?T('다시 계획해서 시도'):T('이어서 시도'));
      again.type='button';again.dataset.act=act;again.disabled=deliveryBusy;again.onclick=()=>decideMission(ms.id,act);row.append(again);box.append(row);}
  }
  for(const d of box.querySelectorAll('details'))if(opened.includes(d.dataset.k)||(d.dataset.k==='steps'&&box.dataset.kind!==kind))d.open=true;   // the step list starts open
  box.dataset.kind=kind;
  if(held){const again=box.querySelector('[data-act="'+held+'"]');if(again&&!again.disabled)again.focus();}
}

// ------------------------------------------------------------------ what changed (the deliverable), then apply
let result=null,resultOpener=null;                         // {ms, data, file, done}: the result exactly as it was opened
function diffBody(text){                                   // the file header (up to the first @@) is not content; later "--- x" lines are
  const lines=String(text||'').split('\n'),at=lines.findIndex(l=>l.startsWith('@@'));
  return at<0?lines.filter(l=>!/^(diff --git|index |--- |\+\+\+ |new file mode|deleted file mode|similarity index|rename (from|to) )/.test(l)):lines.slice(at);
}
function diffLines(text){let a=0,d=0;for(const l of diffBody(text)){if(l[0]==='+')a++;else if(l[0]==='-')d++;}return [a,d];}
async function openResult(ms){
  if(!$('ai-panel').hidden)setAIPanel(false,true);if(openId!=null)closeCall();
  resultOpener=document.activeElement;const mine=result={ms,data:null,file:null,done:null};
  for(const id of ['rp-sum','rp-files','rp-diff','rp-actions'])delete $(id).dataset.sig;
  $('result-panel').hidden=false;paintResult();$('rp-close').focus();
  try{mine.data=await getJSON('/result?run_id='+encodeURIComponent(ms.deliverableRun));}catch(e){mine.data={error:e.message};}
  if(result===mine){const files=(mine.data.changed_files||[]);mine.file=files.length?files[0].path:null;paintResult();}
}
function closeResult(){if(!result)return;result=null;$('result-panel').hidden=true;
  const back=resultOpener&&document.contains(resultOpener)?resultOpener:document.querySelector('#mission-delivery [data-act="apply"]')||$('tab-stage');   // the opener may have been redrawn meanwhile
  resultOpener=null;if(back)back.focus();}
// Each part is rebuilt only when what it shows changed, so a poll never moves the diff being read or drops the focus.
function paintResult(){
  if(!result)return;
  const loose=!!result.ms.loose,d=result.data;
  const now=loose?result.ms:lastModel&&lastModel.mode==='live'&&lastModel.mission&&lastModel.mission.id===result.ms.id?lastModel.mission:null,live=now||result.ms;
  if(loose&&d&&d.goal)live.goal=d.goal;
  const recorded={READY:'pending',APPLIED:'applied',DISCARDED:'discarded',APPLY_BLOCKED:'blocked'}[((d&&d.result)||{}).state]||'pending';
  const state=result.done||(loose?recorded:(live.applied&&live.applied.status)||live.applyState||'pending');
  // Deciding is offered only for what is on screen: not while the task runs again, and not once its result is another run.
  const moved=loose?'':!now?T('이 작업은 지금 화면의 작업이 아닙니다. 작업 카드에서 다시 열어 주세요.'):now.status==='RUNNING'?T('작업이 다시 진행 중입니다. 끝난 뒤 변경 내용을 다시 열어 주세요.'):now.deliverableRun!==result.ms.deliverableRun?T('결과물이 바뀌었습니다. 변경 내용을 다시 열어 확인해 주세요.'):'';
  $('rp-title').textContent=live.goal||'—';$('rp-title').title=live.goal||'';
  let meta=T('프로젝트 · ')+(live.project||'—')+' · '+((APPLY_KO[state]||[state])[0]),where='';
  if(d&&d.worktree_path){const full=String(d.worktree_path),base=String(d.project_path||''),inside=base&&full.startsWith(base);
    meta+=' · '+T('결과물 위치: ')+(inside?(live.project||'')+full.slice(base.length):full.split(/[\\/]/).slice(-2).join('/'));where=full;}
  if($('rp-meta').textContent!==meta)$('rp-meta').textContent=meta;$('rp-meta').title=where;
  const sum=$('rp-sum'),files=$('rp-files'),diff=$('rp-diff'),note=$('rp-note'),acts=$('rp-actions');
  const once=(node,sig,build)=>{if(node.dataset.sig===sig)return;node.dataset.sig=sig;node.replaceChildren();build();};
  let said='';
  if(!d||d.error){for(const n of [sum,files,diff,acts]){n.replaceChildren();delete n.dataset.sig;}diff.hidden=true;
    note.textContent=!d?T('변경 내용을 불러오는 중…'):T('변경 내용을 불러오지 못했습니다 · ')+d.error;return;}
  const list=d.changed_files||[],diffs=d.file_diffs||{};let add=0,del=0;const per={};
  for(const f of list){per[f.path]=diffLines(diffs[f.path]);add+=per[f.path][0];del+=per[f.path][1];}
  once(sum,'s'+result.ms.deliverableRun,()=>{
    const tile=(big,small,cls)=>{const t=el('div','','rp-tile'+(cls?' '+cls:''));t.append(el('b',big),el('span',small));sum.append(t);};
    tile(T('파일 {0}개',list.length),T('+{0}줄 · −{1}줄',add,del));
    const post=(d.tests||{}).post;
    if(post&&post.total){const bad=Math.max(post.failed||0,post.total-(post.passed||0));tile(bad?T('{0}개 실패',bad):T('{0}개 통과',post.passed||0),bad?T('테스트 {0}개 중',post.total):T('테스트 · 실패 없음'),bad?'bad':'ok');}
    else tile(T('테스트 결과 없음'),T('테스트'),'');
    const verdict=(d.tests||{}).inspector||(d.inspector||{}).verdict,found=((d.inspector||{}).p0||[]).length+((d.inspector||{}).p1||[]).length;
    if(verdict)tile(verdict==='pass'?T('감리 통과'):T('감리 수정 요청'),found?T('지적 {0}건',found):T('지적 없음'),verdict==='pass'?'ok':'bad');});
  once(files,'f'+result.ms.deliverableRun+'|'+result.file,()=>{
    for(const f of list){const b=el('button',f.path+' ');b.type='button';b.dataset.path=f.path;b.setAttribute('aria-pressed',String(f.path===result.file));
      if(per[f.path][0])b.append(el('em','+'+per[f.path][0]));if(per[f.path][1])b.append(' ',el('s','−'+per[f.path][1]));
      if(f.type==='D')b.append(' ',el('s',T('삭제')));else if(f.type==='A')b.append(' ',el('em',T('새 파일')));
      b.onclick=()=>{result.file=f.path;paintResult();[...files.children].find(x=>x.dataset.path===f.path)?.focus();};files.append(b);}});
  if(!list.length)said=d.worktree_exists===false?T('작업 사본이 더 이상 없어 변경 내용을 보여 줄 수 없습니다.'):T('바뀐 파일이 없습니다.');
  const lines=result.file?diffBody(diffs[result.file]).filter((l,i,all)=>i<all.length-1||l!==''):[],MAX=1500;
  diff.hidden=!result.file;
  once(diff,'d'+result.ms.deliverableRun+'|'+result.file,()=>{
    diff.setAttribute('aria-label',T('{0} 변경 내용',result.file||''));diff.scrollTop=0;
    for(const l of lines.slice(0,MAX))diff.append(el('div',l||' ',l.startsWith('@@')?'h':l[0]==='+'?'a':l[0]==='-'?'d':''));
    if(result.file&&!lines.length)diff.append(el('div',T('이 파일은 변경 내용을 글자로 보여 줄 수 없습니다.')));});
  if(lines.length>MAX)said=T('변경 내용이 길어 앞의 {0}줄만 보여 줍니다.',MAX);
  const open=state!=='applied'&&state!=='discarded';
  if(open&&moved)said=moved;
  else if(state==='blocked'){const why=result.blocks||(live.applied&&live.applied.blocks)||[];said=T('적용 보류: ')+(blockText(why).slice(0,300)||T('"원본에 적용"을 다시 누르면 충돌 파일만 건너뛰고 나머지를 적용합니다.'));}
  // (the server's own pre-check is not repeated here: it is decided, and explained, when "원본에 적용" is pressed)
  if(note.textContent!==said)note.textContent=said;
  once(acts,JSON.stringify([state,deliveryBusy,!!moved,open]),()=>{
    if(!open||moved)return;
    const apply=el('button',deliveryBusy?T('처리 중…'):T('원본에 적용'));apply.type='button';apply.dataset.act='apply';
    apply.onclick=async()=>{const mine=result;let out=null;
      if(!loose)out=await applyMission(mine.ms,state);
      else if(confirm(state==='blocked'?T('충돌한 파일은 건너뛰고 나머지 변경만 원본 프로젝트({0})에 적용할까요?',mine.ms.project||'—'):T('이 작업의 결과물을 원본 프로젝트({0})에 적용할까요? 프로젝트의 파일이 바뀝니다.',mine.ms.project||'—')))out=await decideResult(mine.ms.id,'apply',state==='blocked'?{on_conflict:'skip'}:{});
      if(out&&result===mine){if(out.status==='applied')mine.done='applied';else if(out.status==='blocked'){mine.done='blocked';mine.blocks=out.blocks||[];}}
      paintResult();if(result===mine&&mine.done==='applied')$('rp-close').focus();};
    const more=el('button',T('이어서 진행'));more.type='button';more.dataset.act='extend';more.onclick=async()=>{await decideMission(result.ms.id,'extend');closeResult();};
    const drop=el('button',T('폐기'));drop.type='button';drop.className='ghost';drop.dataset.act='discard';
    drop.onclick=async()=>{if(confirm(T('이 작업의 결과물을 폐기할까요? 기록은 남습니다.'))){if(loose)await decideResult(result.ms.id,'discard');else await decideMission(result.ms.id,'discard',{run_id:result.ms.deliverableRun});closeResult();}};
    for(const b of [apply,more,drop])b.disabled=deliveryBusy;acts.append(...(loose?[apply,drop]:[apply,more,drop]));});
}

// A run that passed outside any mission (a task approved at its very start runs on its own) has no card: its result is
// listed under the card so it can be read, applied or discarded here too.
function looseResults(){
  // The server says which results belong to no mission: this page only ever sees the newest few missions.
  const s=status||{};return [...(s.results||[]),...(s.blocked_results||[])].filter(r=>r.run_id&&r.in_mission===false);
}
async function decideResult(runId,kind,extra){
  if(deliveryBusy)return null;deliveryBusy=true;let answer=null;if(lastModel)paintLoose(lastModel);if(result)paintResult();
  try{const rid=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():String(Date.now())+'-'+Math.random().toString(16).slice(2);
    const res=await fetch(kind==='apply'?'/result/apply':'/result/discard',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json','X-Requested-With':'fetch'},body:new URLSearchParams({run_id:runId,request_id:rid,...(extra||{})})});
    const out=await res.json().catch(()=>({}));
    if(!out.status)throw Error(out.error||(T('서버 응답 ')+res.status));
    const msg={applied:T('원본에 적용했습니다 · {0}개 파일',(out.files||[]).length),blocked:T('적용할 수 없습니다 · ')+blockText(out.blocks).slice(0,160),discarded:T('결과물을 폐기했습니다')}[out.status]||(out.status+' '+(out.error||out.reason||(out.blocks||[]).join('; ')||''));
    notice(msg);Trinity.pulse(out.status==='applied'?PULSE.done:out.status==='discarded'?PULSE.ok:PULSE.warn);answer=out;}
  catch(e){notice(T('요청 실패 · ')+e.message);}
  finally{deliveryBusy=false;await pollStatus();if(result)paintResult();}
  return answer;
}
function paintLoose(m){
  let box=$('loose-results');
  if(!box){box=el('div','','delivery');box.id='loose-results';$('mission-card').append(box);}
  const list=m.mode==='live'?looseResults():[],sig=JSON.stringify([list.map(r=>[r.run_id,r.changed_count,r.project_name,r.result_state]),deliveryBusy]);
  if(box.dataset.sig===sig)return;box.dataset.sig=sig;
  const held=box.contains(document.activeElement)?document.activeElement.dataset.run:null;
  box.replaceChildren();box.hidden=!list.length;if(!list.length)return;
  const head=el('div','','delivery-head');head.append(el('span',T('작업 기록 없이 끝난 결과물'),'kicker'),el('span',T('적용 대기 {0}건',list.length),'badge warn'));box.append(head);
  for(const r of list.slice(0,4)){const row=el('div','','delivery-actions'),b=el('button',T('변경 내용 보기'));b.type='button';b.dataset.run=r.run_id;b.disabled=deliveryBusy;
    b.onclick=()=>openResult({loose:true,id:r.run_id,deliverableRun:r.run_id,goal:'',project:r.project_name});
    row.append(b,el('small',(r.project_name||'—')+' · '+T('파일 {0}개',r.changed_count||0)+(r.result_state==='APPLY_BLOCKED'?' · '+APPLY_KO.blocked[0]:''),'ai-sub'));box.append(row);
    if(held===r.run_id)b.focus();}
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
  if(state==='blocked'&&ms.applied&&ms.applied.blocks)box.append(el('small',blockText(ms.applied.blocks).slice(0,220),'ai-sub'));
  if(state!=='applied'&&state!=='discarded'){
    const row=el('div','','delivery-actions');
    // The first button shows what changed; "원본에 적용" lives in that panel, after the changes have been seen.
    const apply=el('button',deliveryBusy?T('처리 중…'):ms.deliverableRun?T('변경 내용 보기'):T('원본에 적용'));apply.type='button';apply.dataset.act='apply';
    apply.onclick=()=>{if(ms.deliverableRun)openResult(ms);else applyMission(ms,state);};
    const more=el('button',T('이어서 진행'));more.type='button';more.dataset.act='extend';more.onclick=()=>decideMission(ms.id,'extend');
    const drop=el('button',T('폐기'));drop.type='button';drop.className='ghost';drop.dataset.act='discard';drop.onclick=()=>{if(confirm(T('이 작업의 결과물을 폐기할까요? 기록은 남습니다.')))decideMission(ms.id,'discard',ms.deliverableRun?{run_id:ms.deliverableRun}:{});};
    for(const b of [apply,more,drop])b.disabled=deliveryBusy;
    row.append(apply,more,drop);box.append(row);
    if(held){const again=row.querySelector('[data-act="'+held+'"]');if(again&&!again.disabled)again.focus();}
    if(state==='blocked')box.append(el('small',ms.deliverableRun?T('"변경 내용 보기"에서 "원본에 적용"을 다시 누르면 충돌 파일만 건너뛰고 나머지를 적용합니다.'):T('"원본에 적용"을 다시 누르면 충돌 파일만 건너뛰고 나머지를 적용합니다.'),'ai-sub'));
    else if(ms.status==='DONE'&&ms.deliverableRun)box.append(el('small',T('원본 프로젝트는 아직 그대로입니다. 변경 내용을 보고 정하세요.'),'ai-sub'));
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
  if(state==='BUILDING')return AI[m.assign.MAKER].css;if(state==='REVIEWING')return AI[m.assign.INSPECTOR].css;
  if(state==='VERIFYING')return '#b9ffe2';return AI[m.assign.ARCHITECT].css;
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
function openCall(id){if(!$('ai-panel').hidden)setAIPanel(false,true);if(result)closeResult();callOpener=document.activeElement;openId=id;callRetry=5;openData=liveCall&&liveCall.id===id?liveCall:null;$('call-panel').hidden=false;paintCall();pollCall();$('cp-close').focus();}
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
    label._work=w?{text:SHORT[w.stage]||(role==='MAKER'?SHORT.BUILDING:role==='INSPECTOR'?SHORT.REVIEWING:T('작업 중')),at:w.at,fixed:m.mode==='replay'?w.elapsed:null}:null;
    label.querySelector('.slot-status').textContent=label._work?label._work.text+' · '+clock(label._work.fixed!=null?label._work.fixed:(Date.now()-label._work.at)/1000):T('대기');
    label.querySelector('.slot-stat').textContent=m.stats[p]||'';
    const cfg=label.querySelector('.slot-cfg'),hot=m.mode==='live'&&!!alertOf(CLI_OF[p]);cfg.textContent=m.mode==='live'?cfgLine(p)+(hot?' · '+T('한도 임박'):''):'';cfg.classList.toggle('alert',hot);});
  $('independence').hidden=!(m.mode==='live'&&roleSettings&&(roleSettings.inspector===roleSettings.architect||roleSettings.inspector===roleSettings.maker));
  if(m.phase==='BUILDING')edge[0]=1;if(m.phase==='REVIEWING')edge[1]=1;if(m.phase==='DECIDING')edge[2]=1;
  if(m.phase==='VERIFYING')act[1]=.5;
  Trinity.set({act,edge,colors,core:PHASE[m.phase].core,verify:m.phase==='VERIFYING'?1:0});
}
let lastPhase=null;
function stinger(m){
  const key=m.phase+(m.w?m.w.provider:'');
  if(key===lastPhase)return;const first=lastPhase===null;lastPhase=key;
  if(first||m.phase==='IDLE'||m.phase==='BETWEEN')return;
  const s=$('stinger');s.replaceChildren(el('small',m.w?(AI[m.w.provider]||{name:''}).name+' · '+(m.w.role||''):'TRIBUNAL'),el('strong',PHASE[m.phase].word));
  s.style.setProperty('--c',actorColor(m));s.classList.remove('show');void s.offsetWidth;s.classList.add('show');
}
function paint(m){lastModel=m;stinger(m);paintNow(m);paintMission(m);paintWork(m);paintFeeds(m);paintScene(m);firstPaint=false;document.body.classList.add('ready');if(result)paintResult();}
const params=new URLSearchParams(location.search),attract=params.get('attract')==='1';let idleSince=null;
function repaint(){
  if(attract&&activity){
    if(replay&&isLiveNow())stopReplay();
    else if(!replay&&!isLiveNow()){idleSince=idleSince||Date.now();if(Date.now()-idleSince>12000){idleSince=null;startReplay();}}
    else if(isLiveNow())idleSince=null;
  }
  if(!replay)paint(liveModel());
}

// ------------------------------------------------------------------ scene-pinned labels
// ---- intro: the roll call sits on the scene's own three points and its lights fly to the scene's own core
let introOn=!window.matchMedia||!window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function placeIntro(f){
  const box=$('intro');if(!introOn||!box)return;
  box.style.setProperty('--cx',f.core[0].toFixed(1)+'px');box.style.setProperty('--cy',f.core[1].toFixed(1)+'px');
  const roles=assignment();
  box.querySelectorAll('.intro-call').forEach((n,i)=>{const [x,y]=f.slots[i],p=roles[ROLES[i]];
    n.style.transform='translate('+x.toFixed(1)+'px,'+y.toFixed(1)+'px)';
    n.style.setProperty('--dx',(f.core[0]-x).toFixed(1)+'px');n.style.setProperty('--dy',(f.core[1]-y).toFixed(1)+'px');
    n.style.setProperty('--c',(AI[p]||{}).css||'#fff');
    const name=(AI[p]||{name:''}).name;if(n.children[2].textContent!==name){n.children[1].textContent=ROLE_KO[ROLES[i]];n.children[2].textContent=name;}});
}
function endIntro(){introOn=false;document.body.classList.remove('intro');const box=$('intro');if(box)box.remove();}
function onFrame(f){
  center=$('stage-center').getBoundingClientRect();
  const W=window.innerWidth,H=window.innerHeight,foot=$('stage-foot').offsetHeight+10;
  Trinity.focus({x:center.left/W,y:center.top/H,w:center.width/W,h:Math.max(.2,(center.height-foot)/H)});
  const u=f.unit,labels=document.querySelectorAll('.slot-label');
  $('stage-center').classList.toggle('compact',u<185);              // small scene: labels drop their stat line
  placeIntro(f);
  labels.forEach((n,i)=>{const [x,y]=f.slots[i],w=n.offsetWidth,h=n.offsetHeight;
    let lx=i===0?x+u*.31:x-w/2,ly=i===0?y-h/2:y+u*.31;                 // ARCHITECT: above-right; MAKER/INSPECTOR: centred below
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
const revealed={},accountOpen={};let accountBusy=false;
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
  // folded away until asked for: one quiet button per card. It opens by itself only while a sign-in is under way.
  const open=!!accountOpen[key]||!!a.pending,wrap=el('div','','ai-account'+(open?' open':'')),box=el('div','','ai-account-body'),line=el('div','','ai-account-line');
  const need=a.installed!==false&&a.signed_in===false,tog=el('button','','ai-account-toggle'+(need?' need':''));tog.type='button';tog.dataset.k=key+':acct';tog.setAttribute('aria-expanded',String(open));
  tog.append(el('span',T('계정')+(a.pending?T(' · 로그인 진행 중'):need?T(' · 로그인 필요'):'')),el('i',open?'▴':'▾'));
  tog.onclick=()=>{accountOpen[key]=!open;if(open&&revealed[key]){clearTimeout(revealed[key].timer);delete revealed[key];}paintAI(true);};
  wrap.append(tog);if(!open)return wrap;
  wrap.append(box);box.append(line);
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
  return wrap;
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
  repaint();          // the card first: the pill points at it when the card itself asks for the decision
  const here=lastModel&&attentionKind(lastModel)==='approve';
  $('attention').hidden=!need||document.body.dataset.view==='workshop';$('attention-text').textContent=T('확인이 필요한 작업이 {0}건 있습니다.',need);
  $('attention-go').textContent=here?T('확인하기'):T('작업실에서 확인');$('attention-go').dataset.here=here?'1':'';
  if(result)paintResult();}catch(e){/* the activity poll reports connection trouble */}});

// ------------------------------------------------------------------ replay (real ledger of a finished mission)
let replayLoading=false;
async function startReplay(){
  if(replay){if(attract)return;return stopReplay();}
  if(replayLoading)return;replayLoading=true;
  let data,failed=false;try{data=await getJSON('/ops/replay');}catch(e){data={calls:[]};failed=true;}finally{replayLoading=false;}
  if(replay)return;
  const calls=(data.calls||[]).filter(c=>ROLES.includes(c.role)&&AI[c.provider]).map(c=>({...c,t0:utc(c.started_at)/1000,dur:Math.max(1,c.seconds||1)}));
  if(!calls.length){notice(failed?T('다시보기 기록을 불러오지 못했습니다. 잠시 뒤 다시 시도해 주세요.'):T('다시 볼 작업 기록이 아직 없습니다.'));return;}
  let v=0,prevEnd=calls[0].t0,real=0;const gaps=[];
  calls.forEach((c,i)=>{const gap=Math.max(0,c.t0-prevEnd),vg=Math.min(gap,40);
    if(vg>6&&i&&calls[i-1].role==='MAKER')gaps.push([v,v+vg]);                       // Tribunal itself ran the tests between build and review
    v+=vg;c.v0=v;c.v1=v+c.dur;v=c.v1;real+=gap+c.dur;prevEnd=Math.max(prevEnd,c.t0+c.dur);});
  const stepOf=new Map((data.steps||[]).map(s=>[s.run_id,s])),lastCall=new Map();
  calls.forEach(c=>{if(stepOf.has(c.run_id))lastCall.set(c.run_id,c);});
  replay={data,calls,gaps,total:v,real,speed:v/72,started:performance.now(),stepOf,lastCall,done:new Set(),events:[],finished:false};
  $('replay-bar').hidden=false;document.body.classList.add('replaying');
  $('replay-text').textContent=T('{0} 작업 · 실제 기록 {1} → {2}배속',data.project,span(real),Math.round(replay.speed));
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
      if(s&&r.lastCall.get(c.run_id)===c){r.events.unshift({key:'step'+s.index,state:s.state,label:T('{0}단계 {1}',s.index,STATE_KO[s.state]||s.state||T('종료')),sub:s.tests?testLine(s.tests):'',when:T('기록')});
        if(STEP_CLASS[s.state])Trinity.pulse(PULSE[STEP_CLASS[s.state]]);}}
  }
  for(const c of r.calls)if(c.v0<=vt&&!c.announced){c.announced=true;r.events.unshift({key:'c'+c.v0,color:AI[c.provider].css,label:T('{0} 시작',(ROLE_KO[c.role]||c.role).split(' · ')[1]),sub:AI[c.provider].name,when:T('기록')});}
  const steps=(r.data.steps||[]).filter(s=>{const first=r.calls.find(c=>c.run_id===s.run_id);return first&&first.v0<=vt;})
    .map(s=>{const last=r.lastCall.get(s.run_id);return {index:s.index,state:last&&last.v1<=vt?s.state:null,tests:last&&last.v1<=vt?s.tests:null,itests:last&&last.v1<=vt?s.inspector_tests:null};});
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

// ------------------------------------------------------------------ chat with ARCHITECT
let lastMsg=0,sending=false,chatFails=0;
const pollChat=guarded(async()=>{
  try{const data=await getJSON('/chat/messages?after_id='+lastMsg),log=$('chat-log'),stick=log.scrollTop+log.clientHeight>=log.scrollHeight-40;
    chatFails=0;
    for(const msg of data.messages||[]){if(msg.id<=lastMsg)continue;lastMsg=msg.id;const role=['USER','ARCHITECT','SYSTEM'].includes(msg.role)?msg.role:'SYSTEM';
      const node=el('div','','chat-msg '+role);if(role!=='SYSTEM')node.append(el('small',role==='USER'?T('나'):'ARCHITECT'));const body=String(msg.content||'');node.append(role==='SYSTEM'&&body.length>260?body.slice(0,260)+'…':body);log.append(node);
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
    if(out.status==='busy'){restore(text);notice(T('ARCHITECT가 이전 요청을 처리하고 있습니다. 잠시 뒤 다시 보내 주세요.'));}
    else if(out.status==='error'||!res.ok)notice(T('ARCHITECT가 응답하지 못했습니다 · ')+(out.error||res.status)+T(' · 보낸 내용은 대화 기록에 남아 있습니다'));
  }catch(e){restore(text);notice(T('전송 실패 · ')+e.message+T(' · 대화 기록에 이미 들어갔는지 확인한 뒤 다시 보내 주세요'));}
  finally{sending=false;btn.disabled=false;btn.textContent=T('보내기');pollChat();pollActivity();}
}
let noticeTimer=0;
function notice(text){const s=$('toast');s.hidden=false;s.textContent=text;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>{s.hidden=true;},6000);}
function restore(text){const t=$('chat-text');if(!t.value){t.value=text;grow();}}   // a message that was not accepted goes back into the box
function grow(){const t=$('chat-text');t.style.height='48px';const h=t.scrollHeight+2;t.style.height=Math.min(160,Math.max(48,h))+'px';t.style.overflowY=h>160?'auto':'hidden';}

// ------------------------------------------------------------------ views
function setAIPanel(open,quiet){const p=$('ai-panel');p.hidden=!open;$('btn-ai').setAttribute('aria-expanded',String(open));
  if(open){if(openId!=null)closeCall();if(result)closeResult();paintAI(true);pollAI();$('ai-close').focus();}else if(!quiet)$('btn-ai').focus();
  paintLimitAlert();}
function setChatLog(open){const log=$('chat-log');log.hidden=!open;$('chat-peek').setAttribute('aria-expanded',String(open));if(open)log.scrollTop=log.scrollHeight;}
function setView(view){
  document.body.dataset.view=view;const work=view==='workshop',frame=$('workspace');
  $('workshop').hidden=!work;$('tab-stage').classList.toggle('on',!work);$('tab-workshop').classList.toggle('on',work);
  $('tab-stage').setAttribute('aria-pressed',String(!work));$('tab-workshop').setAttribute('aria-pressed',String(work));
  if(work&&!frame.getAttribute('src'))frame.src='/classic';
  if(work)Trinity.pause();else Trinity.resume();   // the workshop covers the whole scene
  if(work){$('attention').hidden=true;setBroadcast(false);closeRoleMenu();setChatLog(false);if(openId!=null)closeCall();if(result)closeResult();if(!$('ai-panel').hidden)setAIPanel(false,true);}
}
function setBroadcast(on){
  document.body.classList.toggle('broadcast',on);$('btn-broadcast').textContent=on?T('방송 모드 끝내기'):T('방송 모드');$('btn-broadcast').setAttribute('aria-pressed',String(on));if(on)closeRoleMenu();
  try{if(on&&!document.fullscreenElement)document.documentElement.requestFullscreen().catch(()=>{});else if(!on&&document.fullscreenElement)document.exitFullscreen().catch(()=>{});}catch(e){/* fullscreen is optional */}
}
function start(){
  if(introOn){document.body.classList.add('intro');setTimeout(()=>document.body.classList.remove('intro'),4300);setTimeout(endIntro,6400);}else endIntro();
  Trinity.init($('trinity-canvas'),introOn?{onFrame,bootDelay:2.1,bootTime:1.7}:{onFrame});
  if(params.get('broadcast')==='1'||attract){document.body.classList.add('broadcast');$('btn-broadcast').textContent=T('방송 모드 끝내기');$('btn-broadcast').setAttribute('aria-pressed','true');}   // e.g. an OBS browser source: /?attract=1
  $('tab-stage').onclick=()=>setView('stage');$('tab-workshop').onclick=()=>setView('workshop');$('attention-go').onclick=()=>{const b=$('attention-go').dataset.here&&document.querySelector('#mission-attention [data-act="approve"]');if(b){b.scrollIntoView({block:'center'});b.focus();}else setView('workshop');};$('rp-close').onclick=closeResult;
  $('top-project').onclick=async()=>{const b=$('top-project');if(b.disabled||replay)return;b.disabled=true;b.textContent=T('폴더 선택 창이 열려 있습니다…');
    try{const r=await chooseProjectFolder();if(r)notice(r.ok?T('작업 폴더를 바꿨습니다 · ')+r.path:T('선택할 수 없는 폴더입니다 · ')+r.message);}
    catch(e){notice(T('폴더 선택 창을 열지 못했습니다 · ')+e.message+T(' (작업실 탭에서 경로를 직접 입력할 수 있습니다)'));}
    finally{b.disabled=false;if(lastModel)paintNow(lastModel);pollStatus();pollChat();}};
  for(const label of document.querySelectorAll('.slot-label')){label.title=T('이 역할의 담당 AI 바꾸기');label.tabIndex=0;label.setAttribute('role','button');label.setAttribute('aria-haspopup','menu');label.setAttribute('aria-expanded','false');
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
      else if(!$('ai-panel').hidden)setAIPanel(false);else if(result)closeResult();else if(openId!=null)closeCall();else if(replay)stopReplay();return;}
    if(e.target.closest('textarea,input,select,[contenteditable]')||e.ctrlKey||e.metaKey||e.altKey||e.isComposing||e.repeat||document.body.dataset.view!=='stage')return;
    if(e.key==='b'||e.key==='B'||e.key==='ㅠ')setBroadcast(!document.body.classList.contains('broadcast'));
    if(e.key==='r'||e.key==='R'||e.key==='ㄱ')startReplay();});
  setInterval(()=>{const d=new Date();$('top-clock').textContent=[d.getHours(),d.getMinutes(),d.getSeconds()].map(n=>String(n).padStart(2,'0')).join(':');if(!replay)tickTimer();},1000);
  // Nothing is asked of the server while the window is out of sight; everything is asked again the moment it is back.
  const every=(fn,ms)=>setInterval(()=>{if(!document.hidden)fn();},ms);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){pollActivity();pollStatus();pollChat();pollRoles();pollCall();pollAI();}});
  pollActivity();pollStatus();pollChat();pollRoles();every(pollRoles,8000);
  every(pollActivity,3000);every(pollStatus,6000);every(pollChat,3000);every(pollCall,2000);pollAI();every(pollAI,20000);every(()=>{if(ai&&Object.values(ai.accounts||{}).some(a=>a.pending||a.loading))pollAI();},5000);   // a sign-in under way is watched more closely
     // cheap: the server answers from memory and asks the CLIs itself, at the interval chosen in the panel
}
window.TrinityStage={model:()=>lastModel,replaying:()=>!!replay};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
