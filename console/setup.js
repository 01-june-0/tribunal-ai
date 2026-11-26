'use strict';
/* First-run helper (docs/PACKAGING.md §5; server side core/setup.py). Five steps: cost notice, git, the AI CLIs,
   sign-in, a first task in a practice folder. It opens by itself only on a fresh copy (no cost notice read, no run on
   record); afterwards from the AI settings panel. Nothing is installed without the exact command shown and the person
   pressing 「실행」; the server runs only the command of its own list that matches what was shown. */
(function(){
const T=(window.I18N&&window.I18N.t)||((s,...a)=>s.replace(/\{(\d+)\}/g,(m,i)=>i<a.length?String(a[i]):m)),LANG=window.I18N?window.I18N.lang:'ko';
const $=id=>document.getElementById(id);
function el(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
const AIS=[
  {key:'claude',name:'Claude Code',who:'Anthropic',plan:T('Claude 구독(Pro · Max)'),color:'var(--claude)',page:T('Claude Code 공식 안내'),login:'claude auth login'},
  {key:'openai',name:'Codex',who:'OpenAI',plan:T('ChatGPT 구독(Plus · Pro)'),color:'var(--codex)',page:T('Codex 공식 안내'),login:'codex login'},
  {key:'antigravity',name:'Antigravity',who:'Google',plan:T('Google 계정 (무료 한도 또는 구독)'),color:'var(--agy)',page:T('Antigravity CLI 공식 안내'),login:'agy'}];
const STEPS=[
  {name:T('비용 안내'),kicker:T('1 / 5 · 시작하기 전에'),title:T('Tribunal AI는 무료, AI는 구독이 필요합니다'),
   lead:T('Tribunal은 세 회사의 코딩 AI를 한 팀처럼 부리는 프로그램입니다. 프로그램 자체는 무료이고, 일하는 AI는 각 회사의 구독으로 돌아갑니다.')},
  {name:'git',kicker:T('2 / 5 · git'),title:T('변경 기록 도구(git)를 확인합니다'),lead:T('Tribunal은 원본을 건드리지 않고 작업 사본에서 일합니다. 이때 git이 필요합니다.')},
  {name:T('AI 설치'),kicker:T('3 / 5 · AI 설치'),title:T('코딩 AI를 설치합니다'),
   lead:T('최소 두 개가 있어야 작업을 시킬 수 있습니다. 만드는 AI와 검토하는 AI가 달라야 하기 때문입니다. 셋이면 하나가 한도에 걸려도 이어 갑니다.')},
  {name:T('로그인'),kicker:T('4 / 5 · 로그인'),title:T('각 AI에 구독 계정으로 로그인합니다'),
   lead:T('로그인은 각 AI의 공식 명령으로, 새 터미널 창과 브라우저에서 직접 합니다. Tribunal은 계정 주소만 가려서 보여 줍니다.')},
  {name:T('첫 작업'),kicker:T('5 / 5 · 첫 작업'),title:T('연습용 폴더에서 첫 작업을 시켜 봅니다'),
   lead:T('원본 프로젝트가 아니라 연습용 폴더에서 시작합니다. 결과는 바로 적용하지 않고, 변경 내용을 본 뒤 적용하거나 버릴 수 있습니다.')}];
const GOALS=[T('계산기 창 앱을 만들어줘'),T('할 일 목록 웹 페이지를 만들어줘'),T('지뢰찾기 게임을 만들어줘'),T('내 소개 웹 페이지를 만들어줘')];
let st=null,token='',step=0,agreed=false,consent=false,checking=false,goal=GOALS[0],npmRoute=false,practice=null,pending=null,timer=0,busy=false,lastInstalled=-1,opener=null;

async function getToken(){if(token)return token;const r=await fetch('/ops/roles',{cache:'no-store'});token=(await r.json()).csrf||'';return token;}
async function post(path,body){
  await getToken();
  const res=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Tribunal-Token':token},body:JSON.stringify(body)}),out=await res.json().catch(()=>({}));
  if(res.status===403)token='';            // the console was restarted: ask for the token again next time
  return [res,out];
}
async function load(fresh){
  let r;
  if(fresh){const [res,out]=await post('/ops/setup/refresh',{});if(!res.ok)throw Error(out.error||(T('서버 응답 ')+res.status));st=out;}   // reading anew needs the token
  else{r=await fetch('/ops/setup',{cache:'no-store'});if(!r.ok)throw Error(T('서버 응답 ')+r.status);st=await r.json();}agreed=agreed||st.acknowledged.cost;consent=consent||!!st.acknowledged.agent;
  const n=installed();
  if(lastInstalled>=0&&n>lastInstalled)fetch('/providers/refresh',{method:'POST',headers:{'Accept':'application/json','X-Requested-With':'fetch'}}).catch(()=>{});   // a new AI: the roles see it at once
  lastInstalled=n;return st;
}
const installed=()=>st?AIS.filter(a=>st.clis[a.key].installed).length:0;
function signedIn(a){const acc=(st.accounts||{})[a.key]||{};return a.key==='antigravity'?acc.signed_in!==false:acc.signed_in===true;}   // Antigravity does not say: installed counts
const ready=()=>st?AIS.filter(a=>st.clis[a.key].installed&&signedIn(a)).length:0;
function stepState(i){
  if(!st)return '';
  if(i===0)return agreed&&consent?'done':'';
  if(i===1)return st.git.installed?'done':'need';
  if(i===2)return installed()>=2?'done':'need';
  if(i===3)return ready()>=2?'done':'need';
  return practice?'done':'';
}
function notice(text){const s=$('toast');if(!s)return;s.hidden=false;s.textContent=text;clearTimeout(notice.t);notice.t=setTimeout(()=>{s.hidden=true;},6000);}

// ---- building blocks
function link(item,label){const a=el('a',label+' ↗');a.href=st.commands[item].link;a.target='_blank';a.rel='noopener noreferrer';return a;}
function cmdBox(item,label,what,page){
  const c=st.commands[item],box=el('div','','su-cmd'),lab=el('div','','su-label');
  lab.append(el('span',label),el('span',c.shell==='cmd'?T('명령 프롬프트'):T('터미널'),'su-pill'));
  if(!c.command){box.append(lab,el('p',T('이 컴퓨터에서 바로 실행할 명령이 없습니다. 공식 안내 페이지에서 설치 파일을 내려받아 설치해 주세요.'),'su-note'));
    const acts=el('div','','su-acts');acts.append(link(item,page));box.append(acts);return box;}
  const acts=el('div','','su-acts');
  if(c.runnable){const run=el('button',T('새 터미널 창에서 실행'),'su-btn small');run.type='button';run.onclick=()=>ask(item,what);acts.append(run);}
  const copy=el('button',T('복사'),'su-btn small ghost');copy.type='button';copy.onclick=()=>copyText(c.command);acts.append(copy,link(item,page));
  box.append(lab,el('code',c.command));
  if(!c.runnable)box.append(el('p',T('이 환경에서는 터미널 창을 열 수 없습니다. 명령을 복사해 터미널에 붙여 넣어 실행해 주세요.'),'su-note'));
  if(c.command.startsWith('sudo apt'))box.append(el('p',T('Debian · Ubuntu 기준입니다. 다른 배포판은 공식 안내를 따라 주세요.'),'su-note'));
  box.append(acts);return box;
}
async function copyText(text){try{await navigator.clipboard.writeText(text);notice(T('명령을 복사했습니다.'));}catch(e){prompt(T('아래 명령을 복사해 주세요.'),text);}}
function row(swatch,title,sub,right){
  const r=el('div','','su-row'),who=el('div','','su-who'),t=el('div');
  if(swatch)who.append(swatch);t.append(el('b',title),el('small',sub));who.append(t);r.append(who,right||el('span'));return r;}
function mark(cls,text){const s=el('span',text,'su-icon '+cls);s.setAttribute('aria-hidden','true');return s;}
function dot(color){const s=el('span','','su-swatch');s.style.background=color;return s;}
function stateText(text,cls){return el('span',text,'su-state '+cls);}
function spinner(){const s=el('span','','su-spin su-state wait');s.setAttribute('aria-label',T('확인하는 중'));return s;}

// ---- the five steps
function paintBody(){
  const b=$('su-body');b.replaceChildren();
  if(!st){b.append(el('p',T('이 컴퓨터를 확인하는 중…'),'su-count'));return;}
  if(step===0){
    const cost=el('div','','su-cost');
    for(const a of AIS){const c=el('div','','su-card'),t=el('b');t.append(dot(a.color),a.name);c.append(t,el('small',a.who+' · '+a.plan));cost.append(c);}
    const facts=el('ul','','su-facts');
    for(const [head,rest] of [[T('Tribunal AI는 무료입니다.'),T(' MIT 라이선스이고, 쓴 만큼 돈이 나가는 API 요금은 쓰지 않습니다.')],
      [T('AI 구독이 최소 두 개 필요합니다.'),T(' 이미 쓰고 있는 구독이 있으면 그대로 씁니다.')],
      [T('작업마다 구독 한도를 씁니다.'),T(' 작업 하나에 AI 호출이 여러 번 들어갑니다. 남은 한도는 AI 설정에서 볼 수 있습니다.')],
      [T('요금과 한도는 각 회사가 정합니다.'),T(' Tribunal에 적힌 금액은 없고, 각 서비스의 이용 약관을 따릅니다.')]]){
      const li=el('li'),t=el('div');t.append(el('b',head),el('span',rest));li.append(t);facts.append(li);}
    const ag=el('label','','su-agree'),cb=el('input');cb.type='checkbox';cb.checked=agreed;
    cb.onchange=async()=>{agreed=cb.checked;paint();if(agreed&&!st.acknowledged.cost){try{const [res]=await post('/ops/setup/ack',{what:'cost'});if(res.ok)st.acknowledged.cost=true;}catch(e){/* asked again next time */}}};
    ag.append(cb,el('span',T('이해했습니다. 필요한 구독은 제가 각 회사에서 준비합니다.')));
    // the agent-mode terms (docs/AGENT_MODE.md): without them the Maker runs nothing (core/setup.agent_consented)
    const terms=el('div','','su-terms');terms.append(el('b',T('AI가 이 컴퓨터에서 직접 작업합니다')));
    const tl=el('ul','','su-facts');
    for(const line of [T('제작 AI는 작업 폴더 안에서 직접 명령을 실행하고, 필요한 라이브러리를 설치하고, 파일을 고칩니다. 그때마다 묻지 않습니다.'),
      T('작업은 프로젝트와 분리된 작업 폴더에서 하고, 적용을 누를 때만 프로젝트에 반영됩니다.'),
      T('시스템 전체 설치, 돈·자격 증명, 되돌릴 수 없는 작업은 먼저 묻습니다. AI 설정의 권한에서 바꿀 수 있습니다.'),
      T('완전히 격리된 환경(컨테이너)은 아닙니다. AI가 실행한 명령은 이 컴퓨터에서 실행됩니다.')]){
      const li=el('li'),t=el('div');t.append(el('span',line));li.append(t);tl.append(li);}
    const ag2=el('label','','su-agree'),cb2=el('input');cb2.type='checkbox';cb2.checked=consent;
    cb2.onchange=async()=>{consent=cb2.checked;paint();if(consent&&!st.acknowledged.agent){try{const [res]=await post('/ops/setup/ack',{what:'agent'});if(res.ok)st.acknowledged.agent=true;}catch(e){/* asked again next time */}}};
    ag2.append(cb2,el('span',T('위 내용을 이해했고, AI가 이 컴퓨터에서 명령을 실행하는 데 동의합니다.')));
    terms.append(tl,ag2);
    b.append(cost,facts,ag,terms);
  }else if(step===1){
    const rows=el('div','','su-rows');
    if(checking)rows.append(row(mark('wait',''),'git',T('확인하는 중…'),spinner()));
    else if(st.git.installed)rows.append(row(mark('ok','✓'),'git '+(st.git.version||''),T('설치되어 있습니다'),stateText(T('준비됨'),'ok')));
    else{rows.append(row(mark('bad','✗'),'git',T('이 컴퓨터에 없습니다'),stateText(st.started.includes('git')?T('설치 중…'):T('설치 필요'),st.started.includes('git')?'wait':'bad')));
      rows.append(cmdBox('git',st.system==='win'?T('Windows 공식 설치 (winget)'):st.system==='mac'?T('macOS 개발 도구 설치'):T('git 설치'),T('git을 설치합니다.'),T('git 공식 안내')));
      if(st.system==='mac')rows.append(el('p',T('Apple의 설치 창이 뜨면 「설치」를 누르세요. 몇 분 걸릴 수 있습니다.'),'su-note'));}
    b.append(rows,again());
  }else if(step===2){
    const rows=el('div','','su-rows');
    for(const a of AIS){
      const c=st.clis[a.key],started=st.started.includes(a.key)||(a.key==='openai'&&st.started.includes('openai-npm'));
      const right=checking?spinner():c.installed?stateText(T('✓ 설치됨'),'ok'):stateText(started?T('설치 중…'):T('설치 필요'),started?'wait':'bad');
      rows.append(row(dot(a.color),a.name,a.who+(c.installed?' · '+(c.version||T('버전 모름')):T(' · 설치되어 있지 않음')),right));
      if(c.installed||checking)continue;
      if(a.key==='openai'&&npmRoute){
        if(!st.npm){rows.append(cmdBox('node',T('먼저 Node.js 설치 (npm이 함께 설치됩니다)'),T('Node.js를 설치합니다. npm이 함께 설치됩니다.'),T('Node.js 공식 안내')));}
        else rows.append(cmdBox('openai-npm',T('Codex 설치 (npm)'),T('npm으로 Codex를 설치합니다.'),a.page));
      }else rows.append(cmdBox(a.key,T('{0} 공식 설치 명령',a.name),T('설치합니다: {0}',a.name),a.page));
      if(a.key==='openai'){const alt=el('button',npmRoute?T('공식 설치기로 돌아가기'):T('다른 방법: npm으로 설치'),'su-link');alt.type='button';
        alt.onclick=()=>{npmRoute=!npmRoute;paint();};rows.append(alt);}
    }
    const n=installed(),count=el('p','','su-count');
    count.append(T('지금 '),el('b',T('{0}개',n)),T(' 설치됨 · 최소 2개 필요')+(n===2?T(' (셋째는 나중에 설치해도 됩니다)'):''));
    b.append(rows,count,again());
  }else if(step===3){
    const rows=el('div','','su-rows');
    for(const a of AIS){
      if(!st.clis[a.key].installed)continue;
      const acc=(st.accounts||{})[a.key]||{};let sub,right;
      if(a.key==='antigravity'){sub=T('계정과 로그인 여부를 CLI가 알려 주지 않습니다. 처음이면 터미널에서 열어 로그인하세요.');
        right=button(T('터미널에서 열기'),()=>ask('login:antigravity',T('Antigravity를 터미널에서 엽니다. 처음이면 거기서 로그인합니다.'),a.login));}
      else if(acc.loading||acc.signed_in==null){sub=T('확인하는 중…');right=spinner();}
      else if(acc.signed_in){sub=T('로그인됨')+(acc.email_masked?' · '+acc.email_masked:'');right=stateText(T('✓ 로그인됨'),'ok');}
      else if(acc.pending){sub=T('터미널 창에서 로그인을 마쳐 주세요.');right=stateText(T('로그인 진행 중…'),'wait');}
      else{sub=T('로그인되어 있지 않습니다');right=button(T('로그인'),()=>ask('login:'+a.key,T('{0}에 로그인합니다. 브라우저가 열리면 구독 계정으로 로그인하세요.',a.name),a.login));}
      rows.append(row(dot(a.color),a.name,sub,right));
    }
    if(!rows.children.length)rows.append(el('p',T('설치된 AI가 아직 없습니다. 이전 단계에서 설치해 주세요.'),'su-count'));
    b.append(rows,again());
  }else{
    const k1=el('p',T('연습용 폴더'),'kicker su-k'),f=el('div','','su-field');
    if(practice){f.append(mark('ok','✓'),el('span',T('만들고 프로젝트로 선택했습니다 · {0}',practice),'su-path'));}
    else{f.append(el('span',(st.practice||{})[LANG==='en'?'en':'ko']||'','su-path'));   // the name the server will use (core/setup.py practice_name)
      const make=button(T('만들기'),makePractice);make.disabled=busy;f.append(make);}
    const k2=el('p',T('첫 작업 예시'),'kicker su-k'),ex=el('div','','su-examples');
    for(const g of GOALS){const c=el('button',g,'su-chip');c.type='button';c.setAttribute('aria-pressed',String(g===goal));c.onclick=()=>{goal=g;paint();};ex.append(c);}
    b.append(k1,f,el('p',T('홈 폴더에 새 폴더를 만들고 작업할 프로젝트로 고릅니다. 다른 프로젝트는 나중에 상단의 「프로젝트」 버튼으로 고를 수 있습니다.'),'su-note'),
      k2,ex,el('p',T('끝나면 결과물 창의 「실행해 보기」로 바로 써 볼 수 있습니다. 작업 한 번에 AI 호출이 대략 5~10번 들어갑니다.'),'su-count'));
  }
}
function button(text,fn){const b=el('button',text,'su-btn small');b.type='button';b.onclick=fn;return b;}
function again(){const b=button(T('다시 확인'),recheck);b.classList.add('su-again');return b;}
async function recheck(){checking=true;paint();try{await load(true);}catch(e){notice(T('확인하지 못했습니다 · ')+e.message);}finally{checking=false;paint();}}

function paintRail(){
  const ol=$('su-steps');ol.replaceChildren();
  STEPS.forEach((s,i)=>{const state=stepState(i),li=el('li','',state);if(i===step)li.setAttribute('aria-current','step');
    li.append(el('span',state==='done'?'✓':state==='need'?'!':String(i+1),'su-dot'),el('span',s.name));ol.append(li);});
}
function paint(){
  if(!$('setup'))return;
  const s=STEPS[step];$('su-kicker').textContent=s.kicker;$('su-title').textContent=s.title;$('su-lead').textContent=s.lead;
  paintRail();paintBody();
  $('su-back').style.visibility=step?'visible':'hidden';
  const next=$('su-next');next.textContent=step===4?T('이 작업 시작하기'):T('다음');
  let ok=!!st,why='';
  if(st&&step===0&&!agreed){ok=false;why=T('비용 안내를 읽고 체크해 주세요.');}
  else if(st&&step===0&&!consent){ok=false;why=T('AI가 직접 작업하는 데 동의해 주세요.');}
  if(st&&step===1&&!st.git.installed){ok=false;why=T('git을 설치한 뒤 「다음」이 열립니다.');}
  if(st&&step===2&&installed()<2){ok=false;why=T('AI가 두 개 이상 있어야 합니다.');}
  if(st&&step===3&&ready()<2){ok=false;why=T('두 개 이상 로그인해야 작업을 시킬 수 있습니다.');}
  if(st&&step===4&&!practice){ok=false;why=T('먼저 연습용 폴더를 만들어 주세요.');}
  next.disabled=!ok||busy;$('su-why').textContent=why;
  $('su-later').hidden=!(step===3&&ready()>=2&&ready()<installed());
}

// ---- doing things
function ask(item,what,shown){
  const login=item.startsWith('login:'),command=shown||(st.commands[item]||{}).command;if(!command)return;
  pending={item,command};$('su-d-what').textContent=what;$('su-d-cmd').textContent=command;
  $('su-d-note').textContent=login?T('로그인은 그 AI의 공식 명령이 새 터미널 창에서 합니다. Tribunal은 비밀번호와 토큰을 읽지 않습니다.')
    :T('터미널 창에서 진행 상황을 볼 수 있고, 비밀번호를 묻는 경우 그 창에 직접 입력합니다. 끝나면 이 화면이 다시 확인합니다.');
  $('su-veil').hidden=false;$('su-d-yes').focus();
}
function closeAsk(){$('su-veil').hidden=true;pending=null;}
async function confirmAsk(){
  const p=pending;closeAsk();if(!p)return;
  try{
    if(p.item.startsWith('login:')){        // the same sign-in the AI settings panel starts (core/cli_accounts.py)
      const cli=p.item.slice(6),[res,out]=await post('/ops/ai/account',{cli,action:cli==='antigravity'?'open':'login'});
      if(!res.ok)throw Error(out.error||res.status);
      if(out.status==='started')notice(T('터미널 창을 열었습니다. 거기서 로그인을 마치면 이 화면이 스스로 확인합니다.'));
      else if(out.status==='manual')prompt(T('이 환경에서는 터미널 창을 열 수 없습니다. 아래 명령을 터미널에서 직접 실행해 주세요.'),out.command);
      else if(out.status==='unavailable')notice(T('이 AI의 CLI를 찾지 못했습니다. 이전 단계에서 설치해 주세요.'));
      else notice(T('요청을 끝내지 못했습니다 · ')+(out.message||out.status||''));
    }else{
      const [res,out]=await post('/ops/setup/run',{item:p.item,command:p.command});
      if(out.status==='started')notice(T('터미널 창을 열었습니다. 설치가 끝나면 이 화면이 스스로 다시 확인합니다.'));
      else if(out.status==='manual')prompt(T('이 환경에서는 터미널 창을 열 수 없습니다. 아래 명령을 터미널에서 직접 실행해 주세요.'),out.command);
      else if(out.status==='stale')notice(T('그사이 이 컴퓨터의 상황이 바뀌었습니다. 다시 확인한 명령을 보고 눌러 주세요.'));
      else if(out.status==='needs'){npmRoute=true;notice(T('npm이 없습니다. Node.js를 먼저 설치해 주세요.'));}
      else if(out.status==='unavailable')notice(T('이 컴퓨터에서 바로 실행할 명령이 없습니다. 공식 안내 페이지를 열어 주세요.'));
      else throw Error(out.error||out.reason||res.status);
    }
  }catch(e){notice(T('실행하지 못했습니다 · ')+e.message);}
  await load().catch(()=>{});paint();schedule();
}
async function makePractice(){
  if(busy)return;busy=true;paint();
  try{const [res,out]=await post('/ops/setup/practice',{lang:LANG});
    if(out.status==='ready'){practice=out.path;notice(T('연습용 폴더를 만들고 프로젝트로 골랐습니다 · {0}',out.path));}
    else if(out.status==='needs')notice(T('git이 있어야 연습용 폴더를 만들 수 있습니다.'));
    else throw Error(out.reason||out.error||res.status);}
  catch(e){notice(T('연습용 폴더를 만들지 못했습니다 · ')+e.message);}
  finally{busy=false;paint();}
}
async function finish(){
  if(busy||!practice)return;busy=true;paint();
  try{await post('/ops/setup/ack',{what:'done'});
    await fetch('/providers/refresh',{method:'POST',headers:{'Accept':'application/json','X-Requested-With':'fetch'}}).catch(()=>{});}
  catch(e){/* the task still starts; the helper may open again later */}
  busy=false;close();
  if(window.TrinityStage&&window.TrinityStage.send)window.TrinityStage.send(goal);
}

// ---- opening and closing
function schedule(){clearTimeout(timer);if(!$('setup'))return;
  const watch=st&&(st.started.length||Object.values(st.accounts||{}).some(a=>a.pending||a.loading));
  timer=setTimeout(async()=>{if(!document.hidden&&!checking){try{await load();paint();}catch(e){/* next round */}}schedule();},watch?2000:5000);}
function firstOpenStep(){if(!agreed||!consent)return 0;for(let i=1;i<4;i++)if(stepState(i)==='need')return i;return 4;}
function build(){
  const root=el('section','','su-root');root.id='setup';root.setAttribute('role','dialog');root.setAttribute('aria-modal','true');root.setAttribute('aria-labelledby','su-title');
  const wiz=el('div','','su-wizard glass'),rail=el('nav','','su-rail'),main=el('div','','su-main');rail.setAttribute('aria-label',T('준비 단계'));
  const brand=el('div','','su-brand'),bm=el('span','','brand-mark'),bt=el('div');bm.setAttribute('aria-hidden','true');bm.append(el('i'),el('i'),el('i'));
  bt.append(el('strong','TRIBUNAL AI'),el('span',T('시작하기')));brand.append(bm,bt);
  const steps=el('ol','','su-steps');steps.id='su-steps';
  rail.append(brand,steps,el('p',T('Tribunal은 확인 없이 프로젝트 밖에 아무것도 설치하지 않습니다. 비밀번호와 로그인 토큰은 묻지도 읽지도 않습니다.'),'su-rail-note'));
  const head=el('div','','su-head'),k=el('span','','kicker'),h=el('h2'),lead=el('p','','su-lead'),x=el('button',T('닫기'),'su-close');
  k.id='su-kicker';h.id='su-title';lead.id='su-lead';x.type='button';x.id='su-x';x.title=T('닫기 · AI 설정에서 다시 열 수 있습니다');
  head.append(x,k,h,lead);
  const body=el('div','','su-body');body.id='su-body';body.setAttribute('aria-live','polite');
  const foot=el('div','','su-foot'),back=el('button',T('이전'),'su-btn ghost'),why=el('span','','su-why'),later=el('button',T('나중에 하기'),'su-btn'),next=el('button',T('다음'),'su-btn primary');
  back.id='su-back';why.id='su-why';later.id='su-later';next.id='su-next';for(const b of [back,later,next])b.type='button';
  foot.append(back,why,later,next);main.append(head,body,foot);wiz.append(rail,main);
  const veil=el('div','','su-veil'),dlg=el('div','','su-dialog glass'),dh=el('h3',T('이 명령을 새 터미널 창에서 실행할까요?')),dw=el('p'),cmd=el('div','','su-cmd'),dc=el('code'),dn=el('p','','su-note'),acts=el('div','','su-acts end');
  veil.id='su-veil';veil.hidden=true;veil.setAttribute('role','alertdialog');veil.setAttribute('aria-labelledby','su-d-title');dh.id='su-d-title';dw.id='su-d-what';dc.id='su-d-cmd';dn.id='su-d-note';
  cmd.append(el('div',T('실행할 명령'),'su-label'),dc);
  const no=el('button',T('취소'),'su-btn ghost'),yes=el('button',T('실행'),'su-btn primary');no.type=yes.type='button';no.id='su-d-no';yes.id='su-d-yes';
  acts.append(no,yes);dlg.append(dh,dw,cmd,dn,acts);veil.append(dlg);
  root.append(wiz,veil);document.body.append(root);
  x.onclick=close;back.onclick=()=>{if(step){step--;paint();}};later.onclick=()=>{step=4;paint();};
  next.onclick=()=>{if(next.disabled)return;if(step<4){step++;if(step>=1&&step<=3)recheck();else paint();}else finish();};
  no.onclick=closeAsk;yes.onclick=confirmAsk;
}
function inertRest(on){for(const n of document.body.children)if(n.id!=='setup'&&n.id!=='toast')n.inert=on;}
async function open(){
  if($('setup'))return;opener=document.activeElement;build();inertRest(true);paint();
  try{await load(true);}catch(e){notice(T('확인하지 못했습니다 · ')+e.message);}
  step=firstOpenStep();paint();schedule();$('su-x').focus();
}
function close(){clearTimeout(timer);const root=$('setup');if(!root)return;inertRest(false);root.remove();pending=null;if(opener&&opener.focus)opener.focus();}
// While open, keys belong to the helper: the stage's own shortcuts (B, Escape layers) wait.
document.addEventListener('keydown',e=>{if(!$('setup'))return;
  if(e.key==='Escape'){e.preventDefault();if(!$('su-veil').hidden)closeAsk();else close();}
  e.stopPropagation();},true);
window.TribunalSetup={open};
async function boot(){
  const b=$('ai-setup');if(b)b.onclick=()=>{const p=$('ai-close');if(p)p.click();open();};
  try{const s=await load();if(s.auto_open)setTimeout(open,document.body.classList.contains('intro')?6600:0);}catch(e){/* the console works without the helper */}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
