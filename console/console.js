'use strict';
const T=(window.I18N&&window.I18N.t)||((s,...a)=>s.replace(/\{(\d+)\}/g,(m,i)=>i<a.length?String(a[i]):m));   // i18n.js missing: Korean, and the stop buttons still work
const frame=document.getElementById('workspace');
const labels={PARKED:T('정지한 작업'),NONE:T('작업 대기'),IDLE:T('작업 대기'),PLANNING:T('설계 중'),ORDER_READY:T('제작 준비'),BUILDING:T('제작 중'),VERIFYING:T('테스트 실행 중'),REVIEWING:T('감리 중'),DECIDING:T('결과 판단 중'),PASS:T('검증 통과'),RECOVERED:T('복구 완료 · 검증 통과'),FAIL:T('검증 실패'),HUMAN_REQUIRED:T('확인 · 수정 필요'),REJECTED:T('거절한 작업'),TIMEOUT:T('실행 시간 초과')};
let busy=false,doc;
function el(tag,text,cls){const n=doc.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;}
// The Details tab in English. The page is rendered in Korean and its own script keeps rewriting it, so its text is
// translated where it stands (i18n_classic.js) and again whenever it changes. What people and the AIs wrote - chat
// messages, file contents, the draft in the input box - is left alone; a text without an entry stays Korean.
function english(d){
 const C=window.I18N_CLASSIC;if(!C||!(window.I18N&&window.I18N.lang==='en')||d.__english)return;d.__english=true;
 const ATTRS=['title','placeholder','aria-label'],KEEP_PRE=new Set(['mission-details','confirm-body']);
 // Names and words that are somebody's own: a project folder, the goal in a result's header, a system line's original.
 const THEIRS='#project-name,#project-label,.pname,#rd-head,.evraw';
 const theirs=node=>{for(let e=node.nodeType===1?node:node.parentElement;e;e=e.parentElement){const t=e.tagName;
   if(t==='SCRIPT'||t==='STYLE'||t==='TEXTAREA'||t==='CODE'||(t==='PRE'&&!KEEP_PRE.has(e.id))||e.matches(THEIRS))return true;}return false;};
 const text=node=>{if(theirs(node))return;const was=node.nodeValue,now=C.tr(was);if(now!==was)node.nodeValue=now;};
 const attrs=e=>{if(theirs(e))return;for(const a of ATTRS){if(a==='title'&&e.matches('.evt'))continue;   // that tooltip is the original line
   const was=e.getAttribute(a);if(was){const now=C.tr(was);if(now!==was)e.setAttribute(a,now);}}
   if(e.tagName==='INPUT'&&/^(button|submit)$/.test(e.type)){const now=C.tr(e.value);if(now!==e.value)e.value=now;}};
 const all=root=>{if(root.nodeType===3){text(root);return;}if(root.nodeType!==1)return;
   const walk=d.createTreeWalker(root,NodeFilter.SHOW_TEXT);for(let n=walk.nextNode();n;n=walk.nextNode())text(n);
   attrs(root);for(const e of root.querySelectorAll('[title],[placeholder],[aria-label],input'))attrs(e);};
 // A live region is announced whenever its text is written. The page's script writes only when the text differs
 // from what it reads back, so these keep answering with the Korean they were given: nothing is written, and read
 // out, again and again for a text that did not change.
 const write=Object.getOwnPropertyDescriptor(d.defaultView.Node.prototype,'textContent').set;
 for(const region of d.querySelectorAll('[role=status],[role=alert],[aria-live]')){let given=region.textContent;
   Object.defineProperty(region,'textContent',{configurable:true,get:()=>given,set(v){v=String(v);if(v===given)return;given=v;write.call(region,C.tr(v));}});}
 all(d.body);d.documentElement.lang='en';
 // A write that is already English changes nothing here, so the observer settles after one pass.
 new (d.defaultView.MutationObserver)(records=>{for(const r of records){
   if(r.type==='characterData')text(r.target);else if(r.type==='attributes')attrs(r.target);else for(const n of r.addedNodes)all(n);}})
   .observe(d.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:ATTRS});
 const w=d.defaultView;for(const name of ['confirm','alert']){const ask=w[name].bind(w);w[name]=message=>ask(C.tr(String(message)));}
}
function setup(){
 doc=frame.contentDocument;if(!doc?.getElementById('main'))return;
 english(doc);
 if(doc.getElementById('mission-control'))return;
 doc.body.classList.add('director-v2');
 const css=doc.createElement('link');css.rel='stylesheet';css.href='/console.css';doc.head.append(css);
 const panel=el('section','','mission-control');panel.id='mission-control';panel.setAttribute('aria-label',T('현재 작업 요약'));
 const summary=el('div','','mission-summary'),state=el('div','','mission-state');state.append(el('span',T('현재 작업'),'mission-kicker'),el('strong',T('연결 중')));state.lastChild.id='mission-state';
 const next=el('div','','mission-next');next.append(el('span',T('다음 행동'),'mission-kicker'),el('p',T('실행 기록을 읽고 있습니다.')));next.lastChild.id='mission-next';next.lastChild.setAttribute('aria-live','polite');summary.append(state,next);
 const meta=el('div','','mission-meta');for(const id of ['mission-project','mission-updated','mission-tests']){const n=el('span','—');n.id=id;meta.append(n);}
 const evidence=el('details','','mission-evidence');evidence.append(el('summary',T('현재 실행의 상세 원인과 ID')));const body=el('pre');body.id='mission-details';evidence.append(body);
 panel.append(summary,meta,evidence);doc.getElementById('corestrip').before(panel);
 const tools=el('div','','conversation-tools');
 const noise=el('button',T('시스템 알림 숨기기'));noise.type='button';noise.setAttribute('aria-pressed','false');noise.onclick=()=>{const hidden=doc.body.classList.toggle('hide-system');noise.textContent=hidden?T('시스템 알림 보기'):T('시스템 알림 숨기기');noise.setAttribute('aria-pressed',String(hidden));};
 const latest=el('button',T('최신 대화 ↓'));latest.type='button';latest.onclick=()=>{const box=doc.getElementById('chat-box');box.scrollTop=box.scrollHeight;};
 tools.append(noise,latest);doc.getElementById('chat-head').after(tools);
 setupRoles();
 setupFolderPicker();
 // reading and tab order = what is seen: summary, alerts, working area, AI cards, role note
 {const main=doc.getElementById('main'),alertBar=doc.getElementById('alert-bar');if(alertBar)main.before(alertBar);main.after(doc.getElementById('corestrip'),doc.getElementById('role-notice'));}
 doc.getElementById('chat-box').setAttribute('aria-label',T('ARCHITECT 대화 기록'));refresh();
}
async function refresh(){if(busy||!doc||!doc.getElementById('mission-control'))return;busy=true;try{
 const response=await fetch('/status',{cache:'no-store'});if(!response.ok)throw Error(T('상태 조회 실패'));const s=await response.json(),run=s.run||{},state=run.state||'NONE';
 doc.getElementById('mission-state').textContent=labels[state]||state;
 doc.getElementById('mission-control').dataset.state=state;
 let next=s.next_step||s.stage_sentence||T('새 작업을 입력해 주세요.');
 if(!s.next_step&&(s.pending_result_count||0)>0&&state!=='HUMAN_REQUIRED')next=T('결과물 {0}건이 적용을 기다립니다. 확인하고 적용할지 결정하세요.',s.pending_result_count);
 if(state==='HUMAN_REQUIRED'&&run.details){next=run.details.includes('PERMISSION_SETUP_FAILED')?T('실행 준비 오류로 중단됐습니다. 작업 경로와 권한 규칙을 수정한 뒤 다시 검증해야 합니다.'):run.details.includes('BASELINE_FAILED')?T('구현 전 검사에서 중단됐습니다. 상세 원인에서 실패한 테스트와 환경을 확인하세요.'):run.details.includes('P1')?T('감리에서 수정할 결함이 발견됐습니다. 수정 후 테스트와 감리를 다시 진행해야 합니다.'):next;}
 const nextText=next,nextEl=doc.getElementById('mission-next');
 if(nextEl.dataset.said!==nextText){nextEl.dataset.said=nextText;nextEl.textContent=nextText;}   // announced (aria-live) only when it really changes - compared with what was asked for, not with what the English screen shows
 doc.getElementById('mission-project').textContent=T('프로젝트 · ')+(s.project_name||T('미선택'));
 const timestamp=run.updated_at?new Date(run.updated_at+(/Z|[+]\d\d:\d\d$/.test(run.updated_at)?'':'Z')):null;
 const elapsed=timestamp?Math.max(0,Math.floor((Date.now()-timestamp.getTime())/1000)):null;
 doc.getElementById('mission-updated').textContent=elapsed===null?T('아직 실행 기록이 없습니다.'):T('최근 단계 기록 · ')+ago(run.updated_at);
 doc.getElementById('mission-tests').textContent=T('적용 대기 ')+(s.pending_result_count||0)+T('건 · 승인 대기 ')+(s.human_required_count||0)+T('건');
 doc.getElementById('mission-details').textContent=(run.run_id||T('작업 없음'))+'\n'+(run.details||s.stage_sentence||'')+T('\n최근 실행 기록: ')+(run.updated_at||T('없음'));
 document.getElementById('shell-error').hidden=true;offlineVeil(0);
 }catch(e){const error=document.getElementById('shell-error');error.hidden=false;error.textContent=T('상태 연결을 확인하고 있습니다 · ')+e.message;offlineVeil((window.__pollMisses||0)+1);}finally{busy=false;}}
// The workshop is only kept fresh while it is the view in front and the window is visible.
const workshopSeen=()=>!document.hidden&&document.body.dataset.view==='workshop';
const onWorkshopSeen=fn=>{new MutationObserver(()=>{if(workshopSeen())fn();}).observe(document.body,{attributes:true,attributeFilter:['data-view']});document.addEventListener('visibilitychange',()=>{if(workshopSeen())fn();});};
setInterval(()=>{if(workshopSeen())refresh();},5000);onWorkshopSeen(refresh);
frame.addEventListener('load',setup);if(frame.contentDocument?.readyState==='complete')setup();


function setupRoles(){
 // Roles are chosen on the stage (role menu), where one AI may hold several. The workshop only says so: its old
 // cycle buttons worked from a copy of the roles read once and could overwrite what was set there.
 const notice=el('p',T('역할은 한눈에 탭의 역할 메뉴에서 지정합니다. 변경은 다음 대화/작업부터 적용되고, 진행 중인 실행은 그대로 유지됩니다.'),'role-notice');
 notice.id='role-notice';doc.getElementById('corestrip').after(notice);
}

// The mission, workload, call and event lists live on the stage only; the workshop keeps the time helper.
function ago(iso){if(!iso)return '';const t=new Date(iso+(/Z|[+]\d\d:\d\d$/.test(iso)?'':'Z')),s=Math.max(0,Math.floor((Date.now()-t)/1000));return s<60?s+T('초 전'):s<3600?Math.floor(s/60)+T('분 전'):s<86400?Math.floor(s/3600)+T('시간 전'):Math.floor(s/86400)+T('일 전');}

// ---------------------------------------------------------------- project folder: native Windows dialog instead of typing a path
async function chooseProjectFolder(){
 const roles=await fetch('/ops/roles',{cache:'no-store'}).then(r=>r.json());
 const picked=await fetch('/ops/pick-folder',{method:'POST',headers:{'X-Tribunal-Token':roles.csrf}}).then(r=>r.json());
 if(picked.error)throw Error(picked.error);
 if(!picked.path)return null;
 const res=await fetch('/project',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','Accept':'application/json'},body:new URLSearchParams({path:picked.path}).toString()}).then(r=>r.json());
 return {path:picked.path,ok:res.status==='ok',message:res.message||''};
}
function setupFolderPicker(){
 const old=doc.getElementById('project-change'),form=doc.getElementById('project-form');if(!old||!form)return;
 const button=old.cloneNode(true);old.replaceWith(button);button.textContent=T('폴더 선택…');
 const manual=el('button',T('경로 직접 입력'),'ghost');manual.type='button';manual.onclick=()=>{form.style.display=form.style.display==='none'?'':'none';if(form.style.display!=='none')doc.getElementById('project-input').focus();};
 button.after(' ',manual);
 const note=doc.getElementById('project-result');
 button.onclick=async()=>{if(button.disabled)return;button.disabled=true;const label=button.textContent;button.textContent=T('폴더 선택 창 열림…');
  try{const r=await chooseProjectFolder();if(r){form.style.display='';if(note)note.textContent=r.ok?T('선택됨 · ')+r.path:r.message;if(r.ok){form.style.display='none';doc.getElementById('project-name').textContent=r.path.split(/[\/]/).filter(Boolean).pop();doc.getElementById('project-path').textContent=r.path;}}}
  catch(e){form.style.display='';if(note)note.textContent=T('폴더 선택 창을 열지 못했습니다. 경로를 직접 입력해 주세요. (')+e.message+')';}
  finally{button.disabled=false;button.textContent=label;refresh();}};
}

// ---------------------------------------------------------------- 시스템 중지 (2026-11-02): stop the companion from the console
function showVeil(title,detail){
 let veil=document.getElementById('shutdown-veil');
 if(!veil){veil=document.createElement('div');veil.id='shutdown-veil';document.body.append(veil);}
 veil.innerHTML=T('<div><strong></strong><p class="veil-detail"></p><p>다시 켜려면 <code>start-companion.sh</code>(맥·리눅스) 또는 <code>start-companion.ps1</code>(윈도우)을 실행하세요.</p></div>');
 veil.querySelector('strong').textContent=title;veil.querySelector('.veil-detail').textContent=detail||'';
 document.body.classList.add('offline');
}
function offlineVeil(misses){
 window.__pollMisses=misses;
 if(misses===0){if(!window.__stoppedByButton){document.getElementById('shutdown-veil')?.remove();document.body.classList.remove('offline');}return;}
 if(misses>=3&&!document.getElementById('shutdown-veil'))showVeil(T('Tribunal AI가 꺼져 있습니다'),T('서버(')+(location.port||'8081')+T(')가 응답하지 않습니다. 화면의 움직임은 브라우저 안의 연출일 뿐, 실행 중인 작업은 없습니다.'));
}
// heartbeat: the stage view does not run the workshop status poll, so check the server itself every 5 s
setInterval(async()=>{if(document.hidden||(workshopSeen()&&doc?.getElementById('mission-control')))return;try{   // a workshop that never loaded cannot notice a dead server itself
const r=await fetch('/ops/roles',{cache:'no-store'});if(!r.ok)throw Error(r.status);offlineVeil(0);}catch(e){offlineVeil((window.__pollMisses||0)+1);}},5000);
(()=>{
 const b=document.getElementById('btn-shutdown');if(!b)return;
 b.onclick=async()=>{
  if(!confirm(T('Tribunal AI를 멈출까요?\n진행 중인 실행이 있으면 중단됩니다. 기록과 작업본은 남고, 다시 켜면 중단된 작업을 이어갑니다.')))return;
  b.disabled=true;b.textContent=T('멈추는 중…');
  try{
   const roles=await fetch('/ops/roles',{cache:'no-store'}).then(r=>r.json());
   const r=await fetch('/ops/shutdown',{method:'POST',headers:{'X-Tribunal-Token':roles.csrf}});const j=await r.json();
   if(!r.ok)throw Error(j.error||T('중지 실패'));
   window.__stoppedByButton=true;showVeil(T('Tribunal AI가 멈췄습니다'),j.message);
  }catch(e){alert(T('중지 실패 · ')+e.message);b.disabled=false;b.textContent=T('시스템 중지');}
 };
})();

// ---------------------------------------------------------------- 작업 정지 (2026-11-03): stop running missions, keep the dashboard
(()=>{
 const b=document.getElementById('btn-halt');if(!b)return;
 b.onclick=async()=>{
  if(!confirm(T('실행 중인 작업을 멈출까요?\n지금 돌고 있는 AI 프로세스를 끊고 작업을 정지 상태로 둡니다. 기록과 작업본은 남고, 나중에 재개할 수 있습니다.')))return;
  b.disabled=true;const was=b.textContent;b.textContent=T('정지 중…');
  try{
   const roles=await fetch('/ops/roles',{cache:'no-store'}).then(r=>r.json());
   const r=await fetch('/ops/missions/stop',{method:'POST',headers:{'Content-Type':'application/json','X-Tribunal-Token':roles.csrf},body:JSON.stringify({reason:'console 작업 정지 버튼'})});
   const j=await r.json();if(!r.ok)throw Error(j.error||T('정지 실패'));
   alert(j.status==='stopped'?(T('작업 ')+j.missions.join(', ')+T(' 정지 · AI 프로세스 ')+j.killed.length+T('개 종료')):T('실행 중인 작업이 없습니다.'));
  }catch(e){alert(T('정지 실패 · ')+e.message);}finally{b.disabled=false;b.textContent=was;}
 };
})();
