"""Upgraded local console (8081 by default; see core.companion_config for how the port is chosen). Frozen 8080 is deliberately untouched."""
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import dashboard_server as d

ROOT = Path(__file__).resolve().parent            # the code: console pages, helper scripts
from core.paths import home as tribunal_home, data_dir   # noqa: E402 - this machine's runtime files and records
# The console is a fixed allowlist of local files: nothing outside console/ is ever served.
STATIC_FILES = {'/': 'index.html', '/console.js': 'console.js', '/console.css': 'console.css',
                '/stage.css': 'stage.css', '/trinity.js': 'trinity.js', '/stage.js': 'stage.js', '/i18n.js': 'i18n.js', '/i18n_classic.js': 'i18n_classic.js'}


_PICK_LOCK = threading.Lock()


def pick_folder(initial: str = "", timeout: int = 300) -> dict:
    """Open the native folder dialog on this PC's desktop and return {'path': str} ('' when cancelled). One at a time."""
    if not _PICK_LOCK.acquire(blocking=False):
        return {"error": "폴더 선택 창이 이미 열려 있습니다."}
    try:
        from core.pythons import tribunal_python
        out = subprocess.run([tribunal_python(), str(ROOT / "scripts" / "pick_folder.py"), initial or ""],
                             capture_output=True, timeout=timeout)
        if out.returncode == 3:
            return {"error": "macOS가 System Events 제어를 막았습니다. 시스템 설정 → 개인정보 보호 및 보안 → 자동화에서 허용해 주세요."}
        if out.returncode != 0:
            return {"error": "폴더 선택 창을 열지 못했습니다."}
        return {"path": str(json.loads(out.stdout.decode("ascii") or "{}").get("path", ""))}
    except subprocess.TimeoutExpired:
        return {"error": "폴더 선택 시간이 초과됐습니다."}
    except (OSError, ValueError):
        return {"error": "폴더 선택 창을 열지 못했습니다."}
    finally:
        _PICK_LOCK.release()


def open_current_project():
    """(body, status) for /ops/open-project: the console's project folder in the file manager."""
    try:
        current = (d.cached_status_payload() or {}).get('project_path') or ''
    except Exception:
        current = ''
    # fixed sentences: the page shows them through its dictionary (console/i18n.js)
    if not current:
        return {"error": "선택된 프로젝트가 없습니다."}, 409
    ok, info = d.validate_project_path(current)
    if not ok:
        return {"error": "프로젝트 폴더가 없거나 프로젝트로 쓸 수 없습니다."}, 409
    from core.result_manager import ResultManager
    out = ResultManager._open(info)
    return (out, 200) if out.get("status") == "ok" else ({"error": "파일 관리자를 열지 못했습니다."}, 409)


def bridge_config(config=None) -> dict:
    """config.yaml `bridge:`."""
    config = config if config is not None else d.load_config()
    return (config.get('bridge') or {})


def bridge_target_ok(path: str) -> tuple:
    """A request through the bridge (`director do`, another local program) may commission work on any git project
    under config bridge.allowed_roots, except the denied ones (this program itself). Returns (ok, resolved_or_reason)."""
    cfg = bridge_config()
    try:
        target = Path(path).resolve()
    except (OSError, ValueError):
        return False, '경로를 해석할 수 없습니다'
    roots = [Path(r).expanduser().resolve() for r in (cfg.get('allowed_roots') or [])]
    denied = [Path(x).expanduser().resolve() for x in (cfg.get('denied') or [])] + [ROOT.resolve()]
    if not any(target == r or r in target.parents for r in roots):
        return False, '허용된 폴더 밖입니다 (config.yaml bridge.allowed_roots)'
    # Denied folders are matched without regard to case too: on a case-insensitive disk (macOS, Windows) another
    # spelling is the same folder. (Only for refusing: allowing more by case would be wrong on Linux.)
    def fold(x):
        return str(x).casefold()
    if any(target == x or x in target.parents or fold(target) == fold(x) or fold(target).startswith(fold(x) + os.sep.casefold())
           for x in denied):
        return False, '이 폴더에는 지시할 수 없습니다'
    if any(target == r for r in roots):
        return False, '허용 폴더 자체가 아니라 그 안의 프로젝트 폴더를 지정하세요'
    return True, str(target)


def project_registry() -> list:
    """Projects a bridge request can target: config `projects:` entries, every project a mission ever ran on, and git folders
    one level under the allowed roots. Each entry carries the latest mission and whether a deliverable awaits."""
    from core.mission import MissionStore
    cfg = d.load_config()
    seen = {}

    def add(path, origin):
        ok, resolved = bridge_target_ok(path)
        if not ok or not Path(resolved).is_dir():
            return
        key = resolved.casefold()
        entry = seen.setdefault(key, {'path': resolved, 'name': Path(resolved).name, 'origins': [], 'git': (Path(resolved) / '.git').exists(),
                                      'missions': 0, 'last_mission': None})
        if origin not in entry['origins']:
            entry['origins'].append(origin)
    for key in (cfg.get('projects') or {}):
        add(key, 'config')
    for root in bridge_config(cfg).get('allowed_roots') or []:
        try:
            for child in sorted(Path(root).expanduser().iterdir()):
                if child.is_dir() and (child / '.git').exists():
                    add(child, 'root')
        except OSError:
            pass
    missions = sorted(MissionStore().all(), key=lambda m: m.get('updated_at', ''))
    for m in missions:
        add(m.get('project_path', ''), 'mission')
        ok, resolved = bridge_target_ok(m.get('project_path', ''))
        if ok and resolved.casefold() in seen:
            e = seen[resolved.casefold()]
            e['missions'] += 1
            e['last_mission'] = {'mission_id': m['mission_id'], 'status': m.get('status'), 'goal': (m.get('goal') or '')[:160],
                                 'updated_at': m.get('updated_at'), 'applied': (m.get('applied') or {}).get('status')}
    return sorted(seen.values(), key=lambda e: (e['last_mission'] is None, -(e['missions']), e['name']))


class CompanionHandler(d.DashboardHandler):
    def do_GET(self):
        if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0]:
            return self._send_json({'error': 'local requests only'}, 403)
        path = urlsplit(self.path).path
        try:                                    # a GET that carries a body: read it, or closing the socket with unread
            unread = int(self.headers.get('Content-Length') or 0)       # data resets the connection mid-response
        except ValueError:
            unread = 0
        if 0 < unread <= 65536:
            self.rfile.read(unread)
        if path == '/ops/hello':                # "is this the Tribunal AI console of this folder?" (core.companion_config)
            from core.companion_config import hello_payload
            nonce = parse_qs(urlsplit(self.path).query).get('nonce', [''])[0]
            # install_root: the demo console (scripts/demo_console.py) must not pass for this folder's real console
            return self._send_json(hello_payload(getattr(self.server, 'install_root', tribunal_home()), self.server.bridge_token, nonce))
        if path == '/ops/roles':
            from core.role_settings import current, independence
            roles = current(d.load_config())
            return self._send_json({'roles': roles, 'independence': independence(roles), 'csrf': self.server.bridge_token})
        if path == '/ops/ai':                   # AI settings panel: chosen model/effort, what can be chosen, plan and limits
            from core import cli_limits, cli_settings
            settings = cli_settings.load()
            limits = cli_limits.snapshot(settings['antigravity']['model'], settings['usage_poll_minutes'] * 60)
            from core import cli_accounts
            return self._send_json({'settings': settings, 'options': cli_settings.options(), 'limits': limits,
                                    'accounts': cli_accounts.snapshot(limits),
                                    'alerts': cli_limits.alerts(limits, {c: settings[c]['warn_percent'] for c in cli_settings.CLIS})})
        if path == '/favicon.ico':                    # browsers ask for it on their own; there is none: say so without an error
            self.send_response(204); self.send_header('Cache-Control', 'max-age=86400'); self.end_headers(); return
        if path in STATIC_FILES:
            name = STATIC_FILES[path]
            body = (ROOT / 'console' / name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', {'html': 'text/html', 'js': 'text/javascript', 'css': 'text/css'}[name.rsplit('.', 1)[1]] + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers(); self.wfile.write(body); return
        if path == '/classic':
            self.path = '/'
        elif path == '/ops/state':
            report = data_dir() / 'cli_diagnostics.json'
            return self._send_json({'csrf': self.server.bridge_token,
                'diagnostics': json.loads(report.read_text(encoding='utf-8')) if report.exists() else None,
                'status': d.cached_status_payload()})
        elif path.startswith('/bridge/'):
            if not self.authorized():
                return self._send_json({'error': 'bridge authentication required'}, 403)
            try:
                if path == '/bridge/status':
                    return self._send_json({'ok': True, 'version': '1.0'})
                if path == '/bridge/projects':
                    return self._send_json({'projects': project_registry()})
                if path == '/bridge/digest':
                    return self._send_json(d.build_digest_payload())
                if path == '/bridge/missions':
                    from core.mission import MissionStore
                    rows = sorted(MissionStore().all(), key=lambda m: m.get('updated_at', ''), reverse=True)[:30]
                    return self._send_json({'missions': [d.mission_view(m) for m in rows]})
                if path.startswith('/bridge/missions/'):
                    from core.mission import MissionStore
                    ident = path.split('/')[3][:80]
                    m = MissionStore().load(ident)
                    if not m:
                        return self._send_json({'error': '알 수 없는 작업입니다'}, 404)
                    return self._send_json(d.mission_view(m))
            except ValueError as exc:
                return self._send_json({'error': str(exc)}, 400)
        return super().do_GET()

    def authorized(self):
        return secrets.compare_digest(self.headers.get('X-Tribunal-Token', ''), self.server.bridge_token)

    def do_POST(self):
        if self.path == '/ops/ai/refresh':          # "check now": ask the three CLIs again on the next read
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            try:
                self.rfile.read(min(int(self.headers.get('Content-Length') or 0), 4096))
            except (ValueError, OSError):
                pass
            from core import cli_limits
            return self._send_json({'refreshing': cli_limits.refresh_now()})
        if self.path in ('/ops/ai/account', '/ops/ai/account/reveal'):   # sign in / switch / sign out through the CLI itself
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            try:
                from core import cli_accounts
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Invalid account request')
                body = json.loads(self.rfile.read(size))
                cli, action = str(body.get('cli') or ''), str(body.get('action') or '')
                if cli not in cli_accounts.CLIS:
                    raise ValueError('Unknown AI')
                if self.path.endswith('/reveal'):           # the full address, only on request and never stored by us
                    return self._send_json({'email': cli_accounts.reveal(cli)})
                return self._send_json(cli_accounts.start(cli, action))
            except (ValueError, TypeError) as exc:
                return self._send_json({'error': str(exc)[:300]}, 400)
            except Exception as exc:
                return self._send_json({'error': type(exc).__name__ + ': ' + str(exc)[:200]}, 500)
        if self.path == '/ops/ai':
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            try:
                from core import cli_settings
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4096 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Invalid settings request')
                settings = cli_settings.save(json.loads(self.rfile.read(size)))
                return self._send_json({'settings': settings})
            except (ValueError, TypeError) as exc:
                return self._send_json({'error': str(exc)[:300]}, 400)
            except Exception as exc:
                return self._send_json({'error': str(exc)[:300]}, 500)
        if self.path == '/ops/roles':
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            try:
                from core.role_settings import save
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Invalid role request')
                roles = save(json.loads(self.rfile.read(size)))
                try:
                    # Make the provider cards show the new ARCHITECT/MAKER/INSPECTOR labels right away instead of
                    # after the next run (resolve_roles rewrites provider_health.current_role; can_proceed is ignored here).
                    from core.provider_manager import ProviderManager
                    ProviderManager().resolve_roles(roles['architect'], roles['maker'], roles['inspector'], strict=True)
                    d.invalidate_status_cache()
                except Exception as exc:  # bookkeeping only; the saved file is already the source of truth
                    logging.getLogger('director.companion').warning('role bookkeeping refresh failed: %s', exc)
                return self._send_json({'roles': roles, 'message': '저장됨 · 다음 대화/작업부터 적용됩니다. 진행 중인 실행은 유지됩니다.'})
            except (ValueError, TypeError, KeyError) as exc:
                return self._send_json({'error': str(exc)}, 400)
            except OSError:
                return self._send_json({'error': '역할 설정을 저장하지 못했습니다.'}, 500)
        if self.path == '/ops/missions/stop':
            # 작업 정지 (2026-11-03): stop running missions + kill their CLI processes; the dashboard stays up.
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            try:
                size = int(self.headers.get('Content-Length') or 0)
                payload = json.loads(self.rfile.read(size)) if 0 < size <= 4096 else {}
                if not isinstance(payload, dict):
                    payload = {}
                return self._send_json(d.stop_missions(str(payload.get('reason', ''))[:300], payload.get('mission_id') or None, by=str(payload.get('by') or '사용자')[:40]))
            except (ValueError, TypeError) as exc:
                return self._send_json({'error': str(exc)}, 400)
        if self.path == '/ops/shutdown':
            # "시스템 중지" (2026-11-02): stop the companion from the console or through the bridge. Records, worktrees and
            # mission state stay on disk; resume_on_start picks interrupted missions up again when it is restarted.
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            try:
                unread = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                unread = 0
            if 0 < unread <= 65536:
                self.rfile.read(unread)
            self.server.stopping = True
            logging.getLogger('director.companion').warning('shutdown requested from %s', self.headers.get('Referer') or 'local client')
            import threading
            threading.Thread(target=self.server.shutdown, name='director-shutdown', daemon=True).start()
            return self._send_json({'stopping': True, 'message': 'Tribunal AI를 멈춥니다. 기록과 작업본은 남고, 다시 켜면 중단된 작업을 이어갑니다.'})
        if self.path == '/ops/pick-folder':
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            try:
                current = (d.cached_status_payload() or {}).get('project_path') or ''
            except Exception:
                current = ''
            result = pick_folder(current)
            return self._send_json(result, 409 if 'error' in result else 200)
        if self.path in ('/ops/run-plan', '/ops/run-result'):
            # "실행해 보기": the plan (what would run, where) and starting exactly that plan. Nothing starts without the
            # local token and the command the page showed; the server builds the plan again from its own records.
            try:
                size = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(size).decode('utf-8') or '{}') if 0 < size <= 4096 else {}
            except (ValueError, OSError, UnicodeDecodeError):
                body = {}
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            run_id = str(body.get('run_id') or '') if isinstance(body, dict) else ''
            if not re.fullmatch(r'RUN-[A-Za-z0-9-]{1,80}', run_id):
                return self._send_json({'error': 'run_id required'}, 400)
            from core import run_preview
            if self.path == '/ops/run-plan':
                return self._send_json(run_preview.plan(run_id))
            out = run_preview.start(run_id, str(body.get('command') or ''), expected_folder=str(body.get('place') or ''))   # what and where, as shown
            if out.get('status') == 'started':
                try:
                    d.ChatManager().add_message(d.active_session_id(), "SYSTEM", f"[HUMAN] 결과 실행해 보기: {run_id} · {out.get('command', '')[:200]}", run_id=run_id)
                except Exception:
                    pass
            return self._send_json(out, 200 if out.get('status') in ('started', 'manual') else 409)
        if self.path == '/ops/open-project':
            # Opens the project the console works on in Finder / Explorer. The page sends no path: only the folder the
            # server already has as the project, and only while it is still a valid project, is ever opened.
            try:                                     # nothing in a body is used; read it so the reply is not cut off
                self.rfile.read(min(int(self.headers.get('Content-Length') or 0), 4096))
            except (ValueError, OSError):
                pass
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            return self._send_json(*open_current_project())
        if self.path == '/bridge/missions' or (self.path.startswith('/bridge/missions/') and self.path.endswith('/decide')):
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'bridge authentication required'}, 403)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 32000 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('JSON request required')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError('object required')
                if self.path == '/bridge/missions':
                    ident = str(payload.get('request_id', ''))
                    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', ident):
                        raise ValueError('안정적인 request_id가 필요합니다')
                    from core.mission import MissionStore
                    known = [m for m in MissionStore().all() if m.get('request_id') == ident]
                    if known:                                  # retries never start a second mission
                        return self._send_json({'status': 'duplicate', 'mission_id': known[0]['mission_id'], 'mission': d.mission_view(known[0])})
                    ok, target = bridge_target_ok(str(payload.get('project_path', '')))
                    if not ok:
                        raise ValueError(target)
                    goal = str(payload.get('goal', '')).strip()
                    if not 5 <= len(goal) <= 6000:
                        raise ValueError('작업 목표는 5~6000자여야 합니다')
                    result = d.start_goal_mission(target, goal, profile=payload.get('profile'), source='cli' if ident.startswith('cli-') else 'bridge', request_id=ident,
                                                  create_project=bool(payload.get('create_project')), auto_apply=payload.get('auto_apply'))
                    code = {'started': 202, 'busy': 409, 'question': 200, 'escalated': 200}.get(result.get('status'), 400)
                    return self._send_json(result, code)
                ident = self.path.split('/')[3][:80]
                result = d.decide_mission(ident, str(payload.get('action', '')), reason=str(payload.get('reason', ''))[:500],
                                          max_steps=payload.get('max_steps'), on_conflict=str(payload.get('on_conflict', 'block')), by='BRIDGE')
                return self._send_json(result, 200 if result.get('status') != 'error' else 400)
            except (ValueError, TypeError, KeyError) as exc:
                return self._send_json({'error': str(exc)}, 400)
            except Exception as exc:
                return self._send_json({'error': str(exc)[:500]}, 500)
        return super().do_POST()


def run():
    from core.companion_config import load_companion_config, choose_port, write_runtime, clear_runtime
    config = load_companion_config(tribunal_home())
    if os.environ.get('TRIBUNAL_DB_PATH'):
        print('Tribunal AI: TRIBUNAL_DB_PATH is set — records are read from and written to ' + os.environ['TRIBUNAL_DB_PATH'], flush=True)
    action, port, note = choose_port(tribunal_home())
    if action == 'running':                     # a second start is not an error: say where the console is
        print('Tribunal AI already running http://127.0.0.1:' + str(port), flush=True)
        return
    if action == 'blocked':
        raise SystemExit('Tribunal AI cannot start: ' + note)
    if note:
        print('Tribunal AI: ' + note, flush=True)
    d._ensure_schema()
    try:
        server = d.DashboardServer(('127.0.0.1', port), CompanionHandler)
    except OSError as exc:                      # lost a race for the port after the check above
        again = choose_port(tribunal_home())
        if again[0] == 'running':
            print('Tribunal AI already running http://127.0.0.1:' + str(again[1]), flush=True)
            return
        raise SystemExit(f'Tribunal AI cannot start: port {port} was taken while starting ({exc}). Start again.')
    from core.companion_config import bridge_token_path
    token_path = bridge_token_path(tribunal_home())
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(48), encoding='utf-8')
    server.bridge_token = token_path.read_text(encoding='utf-8').strip()
    if (d.load_config().get('autonomy') or {}).get('resume_on_start'):
        import threading
        threading.Thread(target=d.resume_interrupted_missions, name='director-mission-resume', daemon=True).start()
    server.stopping = False
    write_runtime(tribunal_home(), server.server_address[1])
    print('Tribunal AI console http://127.0.0.1:' + str(server.server_address[1]), flush=True)
    try:
        server.serve_forever()
    finally:
        clear_runtime(tribunal_home())
        server.server_close()
        print('Tribunal AI companion stopped (system stop)', flush=True)


if __name__ == '__main__':
    run()
