from pathlib import Path
import pytest
from core.bootstrap import prepare_project, snapshot, git, bootstrap_tests, configure_runtime
from core.git_manager import GitManager

def test_new_directory_git_without_user_index_changes(tmp_path):
    p = Path(prepare_project(tmp_path / 'new'))
    assert git(p, 'rev-parse', 'HEAD')
    assert git(p, 'ls-files') == ''

def test_snapshot_carries_untracked_tests_preserves_index_and_head(tmp_path):
    p = Path(prepare_project(tmp_path / 'new'))
    (p / 'tests').mkdir(); (p / 'tests/test_real.py').write_text('def test_real(): assert True\n')
    (p / '.env').write_text('PRIVATE=do-not-copy')
    before = git(p, 'status', '--porcelain'); head = git(p, 'rev-parse', 'HEAD')
    sha = snapshot(p)
    assert 'tests/test_real.py' in git(p, 'ls-tree', '-r', '--name-only', sha)
    assert '.env' not in git(p, 'ls-tree', '-r', '--name-only', sha)
    assert git(p, 'rev-parse', 'HEAD') == head
    assert git(p, 'status', '--porcelain') == before

def test_bootstrap_initial_test_and_existing_test_never_replaced(tmp_path):
    p = Path(prepare_project(tmp_path / 'new'))
    rel = bootstrap_tests(p)
    assert rel == 'tests/test_director_bootstrap.py'
    assert not git(p, 'status', '--porcelain')
    before = (p / rel).read_bytes()
    assert bootstrap_tests(p) is None
    assert (p / rel).read_bytes() == before

def test_existing_failed_test_not_bootstrapped(tmp_path):
    p = Path(prepare_project(tmp_path / 'new')); (p / 'tests').mkdir()
    (p / 'tests/test_failure.py').write_text('def test_failure(): assert False\n')
    assert bootstrap_tests(p) is None

def test_snapshot_preserves_staged_and_unstaged_versions(tmp_path):
    p = Path(prepare_project(tmp_path / 'new'))
    source = p / 'feature.py'
    source.write_text('value = 1\n')
    git(p, 'add', 'feature.py')
    source.write_text('value = 2\n')
    before = git(p, 'status', '--porcelain')
    sha = snapshot(p)
    assert git(p, 'show', ':feature.py') == 'value = 1'
    assert source.read_text() == 'value = 2\n'
    assert git(p, 'show', sha + ':feature.py') == 'value = 2'
    assert git(p, 'status', '--porcelain') == before

def test_snapshot_excludes_untracked_sensitive_directories(tmp_path):
    """Paths that look like secrets never enter the snapshot. A plain data file does: it used to be left out too, and
    then a step's new 'data/*.json' fixtures were missing for the next step (see SUFFIXES in core/bootstrap.py). The
    test kept expecting the old rule until 2026-11-22."""
    p = Path(prepare_project(tmp_path / 'new'))
    for rel in ['secrets/settings.json', 'credentials/config.json', 'config/api_token.json', '.env.local', 'keys/private_key.json',
                'data/fixture.json', '.venv/lib/site.py', 'node_modules/x/index.js']:
        target = p / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{}')
    sha = snapshot(p)
    assert git(p, 'ls-tree', '-r', '--name-only', sha) == 'data/fixture.json'

def test_the_snapshot_says_which_untracked_files_went_in_and_which_stayed_out(tmp_path):
    from core.bootstrap import snapshot_excludes
    p = Path(prepare_project(tmp_path / 'proj'))
    for rel in ['src/app.py', 'data/fixture.json', 'data/private/customers.csv', 'exports/report.csv', 'notes.txt',
                'secrets/key.json', 'node_modules/x/index.js', 'photo.raw']:
        target = p / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('x')
    (p / 'big.json').write_text('x' * 2_000_001)
    config = {'bootstrap': {'snapshot_exclude': ['*.csv']}, 'projects': {str(p): {'snapshot_exclude': ['data/private/**', 'notes.txt']},
                                                                        str(tmp_path / 'other'): {'snapshot_exclude': ['src/**']}}}
    patterns = snapshot_excludes(config, p)
    assert patterns == ['*.csv', 'data/private/**', 'notes.txt']           # another project's patterns do not apply here
    seen = {}
    sha = snapshot(p, exclude=patterns, report=seen)
    assert git(p, 'ls-tree', '-r', '--name-only', sha).split() == ['data/fixture.json', 'src/app.py']
    assert seen['untracked_included'] == ['data/fixture.json', 'src/app.py'] and seen['untracked_included_count'] == 2
    assert seen['untracked_skipped'] == {'excluded_by_config': ['data/private/customers.csv', 'exports/report.csv', 'notes.txt'],
                                         'secret_name': ['secrets/key.json'], 'tool_folder': ['node_modules/x/index.js'],
                                         'not_a_source_type': ['photo.raw'], 'too_large': ['big.json']}
    assert seen['untracked_skipped_count']['excluded_by_config'] == 3 and seen['exclude_patterns'] == patterns
    assert git(p, 'status', '--porcelain') != ''                           # the real index and working copy are untouched
    assert snapshot(p) and snapshot_excludes({}, p) == []                  # no patterns, no report: as before


@pytest.mark.parametrize("rel,pattern,excluded", [
    ("x/priv/y.json", "**/priv/**", True), ("priv/u.csv", "**/priv/**", True),       # a leading ** once matched nothing at all
    ("priv/sub/deep.csv", "priv/*", True), ("priv/sub/deep.csv", "priv/*.csv", False), ("priv/a.csv", "priv/*.csv", True),
    ("top.csv", "**/*.csv", True), ("a/b/top.csv", "**/*.csv", True),
    ("x/priv/a.py", "priv", True), ("private/a.py", "priv", False),                  # a bare name: any folder or file of that name
    ("data/private/c.csv", "data/private/**", True), ("data/privatex/c.csv", "data/private/**", False),
    ("data/private/c.csv", "data/private/", True), ("data/public/c.csv", "data/private", False),
    ("src/app.py", "*.csv", False), ("a/B.CSV", "*.csv", True), ("docs/notes.txt", "notes.txt", True),
    ("a/b/c.py", "a/**/c.py", True), ("a/c.py", "a/**/c.py", True), ("a/bc.py", "a/**/c.py", False),
    ("data/x1.json", "data/x[0-9].json", True), ("data/x1.json", "data/x[!0-9].json", False),
    ("Data/Private/C.csv", "data\\private\\**", True),
])
def test_exclude_patterns_mean_what_gitignore_means(rel, pattern, excluded):
    from core.bootstrap import excluded_by
    assert excluded_by(rel, [pattern]) is excluded


def test_an_exclude_setting_that_cannot_be_read_stops_instead_of_excluding_nothing(tmp_path):
    from core.bootstrap import excluded_by, snapshot_excludes
    for unreadable in ("", "**", "/", "   "):
        with pytest.raises(ValueError):
            excluded_by("a.py", [unreadable])
    assert snapshot_excludes({"bootstrap": {"snapshot_exclude": "*.csv"}}, tmp_path) == ["*.csv"]     # one pattern, not five letters
    for wrong in (5, {"a": 1}, ["ok", 3], [""], ["**"]):
        with pytest.raises(ValueError):
            snapshot_excludes({"bootstrap": {"snapshot_exclude": wrong}}, tmp_path)
    with pytest.raises(ValueError):
        snapshot_excludes({"projects": {str(tmp_path): {"snapshot_exclude": 7}}}, tmp_path)


def test_a_later_step_keeps_the_previous_steps_new_files_whatever_their_names():
    """The exclude list is for the operator's own untracked files; a step's deliverable must reach the next step."""
    import core.orchestrator as o
    src = Path(o.__file__).read_text(encoding="utf-8")
    assert "exclude=None if base_worktree else snapshot_excludes(self.config, proj_path)" in src
    assert "exclude=None if mission_base else snapshot_excludes(self.config, project_path)" in src


def test_control_root_rejected():
    from core.bootstrap import SOURCE_ROOT
    with pytest.raises(ValueError): prepare_project(SOURCE_ROOT)
    with pytest.raises(ValueError): prepare_project('')

def test_project_runtime_selected_without_global_config_mutation(tmp_path):
    exe = tmp_path / '.venv/Scripts/python.exe'; exe.parent.mkdir(parents=True); exe.touch()
    cfg = {'verification': {'test_command': 'python -m pytest tests/'}}
    assert configure_runtime(cfg, tmp_path)['verification']['test_command'][0] == str(exe.resolve())
    assert cfg['verification']['test_command'] == 'python -m pytest tests/'

def test_protected_glob_outside_grants_keeps_default_deny(tmp_path):
    from agents.antigravity_maker import AntigravityMaker
    from schemas.order import OrderSchema
    maker = AntigravityMaker()
    maker._setup_scoped_permissions(tmp_path, OrderSchema(goal='test', allowed_paths=['src/**'], protected_paths=['.env.*']))
    assert maker._native_protected_permission_paths == []
    assert not (tmp_path / '.env.local').exists()

def test_protected_glob_overlap_still_fails_closed(tmp_path):
    from agents.antigravity_maker import AntigravityMaker
    from schemas.order import OrderSchema
    with pytest.raises(ValueError):
        AntigravityMaker()._setup_scoped_permissions(tmp_path, OrderSchema(goal='test', allowed_paths=['src/**'], protected_paths=['src/secret*']))

@pytest.mark.parametrize('with_product_test', [True, False])
def test_empty_project_prepares_and_requires_real_tests(tmp_path, with_product_test):
    from tests.test_v0234_resume_parity import _mock_orch
    from schemas.order import OrderSchema
    orch = _mock_orch(bootstrap={'enabled': True}, verification={'test_command': 'python -m pytest tests/'})
    def build(b, order, wt):
        p = Path(wt)
        (p / 'feature.py').write_text('def double(x):\n    return x * 2\n')
        if with_product_test:
            (p / 'tests/test_feature.py').write_text('from feature import double\ndef test_double():\n    assert double(4) == 8\n')
        return ['feature.py'] + (['tests/test_feature.py'] if with_product_test else [])
    order = OrderSchema(goal='Create double helper and tests', allowed_paths=['feature.py', 'tests/**'], acceptance_criteria=['double(4) == 8'])
    result = orch.run(str(tmp_path / 'fresh'), order.goal, order=order, maker_fn=build)
    assert result['baseline_verification']['passed'] is True
    assert result['baseline_verification']['test_counts']['passed'] == 1
    assert result['final_state'] == ('PASS' if with_product_test else 'FAIL')
