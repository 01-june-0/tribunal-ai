"""Prepare local projects without staging or committing the user's working copy."""
import os
import subprocess
import tempfile
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
# What a milestone hands to the next one. A missing extension is not harmless: a web game's '.cjs' tests and new
# 'data/*.json' files were dropped between milestones and every following step failed on "the tests disappeared".
SUFFIXES = {'.py', '.pyi', '.md', '.txt', '.toml', '.yaml', '.yml', '.json', '.js', '.cjs', '.mjs', '.ts', '.tsx', '.jsx', '.vue',
            '.html', '.css', '.scss', '.sql', '.rs', '.go', '.java', '.kt', '.swift', '.c', '.h', '.cpp', '.cs', '.gradle', '.xml',
            '.ini', '.cfg', '.csv', '.bat', '.cmd', '.sh', '.ps1', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.ico',
            '.mq5', '.mqh', '.mq4', '.set'}

def git(root, *args, env=None):
    p = subprocess.run(['git', *args], cwd=str(root), env=env, input='', capture_output=True,
                       text=True, encoding='utf-8', errors='replace', timeout=30)
    if p.returncode: raise ValueError(p.stderr.strip())
    return p.stdout.strip()

def identity():
    env = os.environ.copy()
    env.update(GIT_AUTHOR_NAME='AI DEV Bootstrap', GIT_AUTHOR_EMAIL='bootstrap@localhost',
               GIT_COMMITTER_NAME='AI DEV Bootstrap', GIT_COMMITTER_EMAIL='bootstrap@localhost')
    return env

def prepare_project(path):
    if not str(path).strip(): raise ValueError('프로젝트 경로가 필요합니다')
    root = Path(path).resolve()
    if root == Path(root.anchor) or root == Path.home() or root == SOURCE_ROOT or SOURCE_ROOT in root.parents or root in SOURCE_ROOT.parents:
        raise ValueError('프로젝트 루트로 사용할 수 없는 광범위/제어 경로입니다')
    root.mkdir(parents=True, exist_ok=True)
    if not (root / '.git').exists(): git(root, 'init')
    try: git(root, 'rev-parse', '--verify', 'HEAD')
    except ValueError:
        tree = git(root, 'mktree')
        commit = git(root, 'commit-tree', tree, '-m', 'AI DEV empty starting point', env=identity())
        git(root, 'update-ref', 'HEAD', commit)
    return str(root)

TOOL_FOLDERS = {'.director_worktrees', '.venv', 'venv', 'node_modules', '__pycache__', '.claude', '.agents', '.git'}
SECRET_WORDS = ('secret', 'credential', 'token', '.env', 'private_key')
REPORT_MAX = 200                                    # paths kept per list in a snapshot report


def _exclude_rule(pattern: str):
    """One `snapshot_exclude` pattern as a test on a repo-relative path, with the meaning .gitignore gives it:
    - no slash ("*.csv", "private"): matches that name at any depth - a file, or a folder and everything in it;
    - with a slash ("data/private/**", "exports/*.csv", "**/tmp/**"): matched from the project root, `*` stays
      inside one path segment, `**` spans any number of them;
    - a match on a folder covers everything below it.
    Case is ignored (more is excluded on a case-sensitive disk, never less). A pattern that cannot be read raises:
    silently excluding nothing would be the dangerous way to be wrong."""
    import fnmatch
    import re
    text = str(pattern).strip().replace('\\', '/').lower()
    while text.startswith('./'):
        text = text[2:]
    text = text.strip('/')
    if not text or text in ('**', '.'):
        raise ValueError(f'snapshot_exclude pattern {pattern!r} is empty or would match nothing in particular')
    parts = text.split('/')
    if len(parts) == 1:
        name = re.compile(fnmatch.translate(parts[0]))
        return lambda rel: any(name.match(segment) for segment in rel.lower().split('/'))
    regex = '^'
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == '**':
            regex += '.*' if last else '(?:[^/]+/)*'
            continue
        piece = ''
        k = 0
        while k < len(part):
            ch = part[k]
            if ch == '*':
                piece += '[^/]*'
            elif ch == '?':
                piece += '[^/]'
            elif ch == '[':
                end = part.find(']', k + 2)
                if end < 0:
                    piece += re.escape(ch)
                else:
                    body = part[k + 1:end]
                    piece += '[' + ('^' + body[1:] if body.startswith('!') else body).replace('\\', '\\\\') + ']'
                    k = end
            else:
                piece += re.escape(ch)
            k += 1
        regex += piece + ('' if last else '/')
    try:
        whole = re.compile(regex + '$')
    except re.error as exc:
        raise ValueError(f'snapshot_exclude pattern {pattern!r} cannot be read: {exc}')

    def test(rel: str) -> bool:
        segments = rel.lower().split('/')
        return any(whole.match('/'.join(segments[:n])) for n in range(1, len(segments) + 1))    # the file, or a folder above it
    return test


def excluded_by(rel: str, patterns) -> bool:
    """A repo-relative path against the operator's exclude patterns (`snapshot_exclude` in config.yaml)."""
    rel = str(rel).replace('\\', '/').lstrip('./') if str(rel).startswith('./') else str(rel).replace('\\', '/')
    return any(_exclude_rule(pattern)(rel) for pattern in patterns or [])


def snapshot_excludes(config, project) -> list:
    """Patterns for this project: `bootstrap.snapshot_exclude` plus `projects.<path>.snapshot_exclude`. They live in
    the Director's config, never in the project, so a Maker cannot remove them. A value that is not a list of text
    patterns stops the run instead of being guessed at."""
    def listed(value, where):
        if value in (None, ''):
            return []
        if isinstance(value, str):
            value = [value]                          # `snapshot_exclude: "*.csv"` means that one pattern
        if not isinstance(value, (list, tuple)) or not all(isinstance(x, str) and x.strip() for x in value):
            raise ValueError(f'{where}.snapshot_exclude must be a list of patterns')
        for pattern in value:
            _exclude_rule(pattern)                   # unreadable patterns are found here, before anything is copied
        return [x.strip() for x in value]
    patterns = listed(((config or {}).get('bootstrap') or {}).get('snapshot_exclude'), 'bootstrap')
    for key, override in ((config or {}).get('projects') or {}).items():
        try:
            same = Path(key).expanduser().resolve() == Path(project).resolve()
        except (OSError, ValueError):
            same = False
        if same and isinstance(override, dict):
            patterns += listed(override.get('snapshot_exclude'), f'projects.{key}')
    return patterns


def snapshot(root, exclude=None, report=None):
    """A private commit of the working copy as it is now. `exclude`: the operator's patterns for files that are not
    tracked yet and must stay out. `report` (a dict) is filled with what happened to every such file, so the run
    record can say exactly which untracked files reached the worktree - and therefore the AIs."""
    root = Path(prepare_project(root)); head = git(root, 'rev-parse', 'HEAD')
    others = git(root, '-c', 'core.quotepath=false', 'ls-files', '--others', '--exclude-standard', '-z').split('\0')
    # Newly staged files are not HEAD-tracked and are omitted by ls-files --others.
    # Include their working-copy version in the private index without changing the real index.
    others += git(root, '-c', 'core.quotepath=false', 'diff', '--cached', '--name-only', '--diff-filter=A', '-z').split('\0')
    # Intent-to-add entries (git add -N, which the Director uses so run diffs show new files) are neither untracked
    # nor cached-added; without this a milestone's new files would be lost when the next milestone builds on it.
    others += git(root, '-c', 'core.quotepath=false', 'diff', 'HEAD', '--name-only', '--diff-filter=A', '-z').split('\0')
    safe, skipped = [], {}
    rules = [_exclude_rule(x) for x in exclude or []]
    def skip(why, rel): skipped.setdefault(why, []).append(rel)
    for rel in dict.fromkeys(filter(None, others)):
        p = Path(rel)
        if any(x.lower() in TOOL_FOLDERS for x in p.parts): skip('tool_folder', rel); continue
        if any(any(x in part.lower() for x in SECRET_WORDS) for part in p.parts): skip('secret_name', rel); continue
        if any(rule(p.as_posix()) for rule in rules): skip('excluded_by_config', rel); continue
        target = root / p
        if not target.exists(): continue
        if target.is_symlink() or root not in target.resolve().parents: raise ValueError('Snapshot escapes project: ' + rel)
        if p.suffix.lower() not in SUFFIXES: skip('not_a_source_type', rel); continue
        if target.stat().st_size > 2_000_000: skip('too_large', rel); continue
        safe.append(rel)
    if isinstance(report, dict):
        report['untracked_included'] = sorted(safe)[:REPORT_MAX]
        report['untracked_included_count'] = len(safe)
        report['untracked_skipped'] = {why: sorted(paths)[:REPORT_MAX] for why, paths in skipped.items()}
        report['untracked_skipped_count'] = {why: len(paths) for why, paths in skipped.items()}
        report['exclude_patterns'] = [str(x) for x in (exclude or [])][:50]
    with tempfile.TemporaryDirectory(prefix='director-index-') as tmp:
        env = identity(); env['GIT_INDEX_FILE'] = str(Path(tmp) / 'index')
        git(root, 'read-tree', head, env=env)
        git(root, 'add', '-u', env=env)
        for rel in safe: git(root, 'add', '--', rel, env=env)
        tree = git(root, 'write-tree', env=env)
        commit = git(root, 'commit-tree', tree, '-p', head, '-m', 'AI DEV private working-copy snapshot', env=env)
    return commit

def bootstrap_tests(worktree):
    from core.project_inventory import _inventory
    root = Path(worktree).resolve(); inventory = _inventory(root)
    if inventory['test_files'] or inventory['unsafe_entries']: return None
    if any(Path(p).suffix.lower() not in {'.py', '.pyi'} and Path(p).name != 'requirements.txt'
           for p in inventory['meaningful_source_files']): return None
    rel = 'tests/test_director_bootstrap.py'; target = root / rel
    target.parent.mkdir(exist_ok=True)
    target.write_text('''"""Initial syntax smoke test; NOT product behavior acceptance."""
import ast
from pathlib import Path

def test_existing_python_source_parses():
    root = Path(__file__).resolve().parents[1]
    for path in root.rglob('*.py'):
        if any(part in {'.git', '.agents', '.venv', 'venv', '.director_worktrees', '__pycache__'} for part in path.relative_to(root).parts):
            continue
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
''', encoding='utf-8')
    git(root, 'add', '--', rel)
    git(root, '-c', 'user.name=AI DEV Bootstrap', '-c', 'user.email=bootstrap@localhost',
        'commit', '-m', 'Initial syntax test, product tests still required')
    return rel

def configure_runtime(config, project):
    import copy
    updated = copy.deepcopy(config)
    # Per-project verification lives in the Director's own config (never in the project, where a Maker could
    # weaken it), keyed by the project path.
    for key, override in (updated.get('projects') or {}).items():
        try:
            same = Path(key).resolve() == Path(project).resolve()
        except (OSError, ValueError):
            same = False
        if same and isinstance(override, dict):
            updated.setdefault('verification', {}).update(override.get('verification') or {})
    command = updated.get('verification', {}).get('test_command')
    if command == 'python -m pytest tests/':
        for rel in ('.venv/Scripts/python.exe', '.venv/bin/python'):
            exe = Path(project) / rel
            if exe.is_file():
                updated['verification']['test_command'] = [str(exe.resolve()), '-m', 'pytest', 'tests/']
                break
    return updated
