"""What a project folder holds, for the bootstrap: source files, tests, and entries that are not safe to read."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List


_IGNORED_PARTS = {
    ".git", ".director_worktrees", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", ".venv", "venv",
}
_BENIGN_ROOT_FILES = {
    ".gitignore", ".gitattributes", ".editorconfig", "license", "license.md",
    "license.txt", "readme", "readme.md", "readme.txt",
}
_SOURCE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".kts",
    ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".cxx", ".cs", ".fs",
    ".rb", ".php", ".swift", ".scala", ".dart", ".lua", ".r", ".jl",
    ".sql", ".vue", ".svelte", ".html", ".css", ".scss", ".sh", ".ps1",
}
_PRODUCT_MANIFESTS = {
    "package.json", "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "pipfile", "poetry.lock", "cargo.toml", "go.mod", "go.sum", "pom.xml",
    "build.gradle", "build.gradle.kts", "composer.json", "gemfile", "makefile",
    "cmakelists.txt", "dockerfile", "docker-compose.yml", "docker-compose.yaml",
}


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath([str(root), str(candidate)]) == str(root)
    except (OSError, ValueError):
        return False


def _is_test_path(relative: Path) -> bool:
    lowered = [part.lower() for part in relative.parts]
    name = relative.name.lower()
    stem = relative.stem.lower()
    return (
        any(part in {"test", "tests", "spec", "specs", "__tests__"} for part in lowered[:-1])
        or name.startswith("test_")
        or stem.endswith("_test")
        or name.endswith(".spec.js")
        or name.endswith(".spec.ts")
        or name.endswith(".test.js")
        or name.endswith(".test.ts")
    )


def _inventory(project: Path) -> Dict[str, List[str]]:
    meaningful: List[str] = []
    tests: List[str] = []
    unsafe_entries: List[str] = []
    other: List[str] = []

    for path in project.rglob("*"):
        try:
            relative = path.relative_to(project)
        except ValueError:
            unsafe_entries.append(str(path))
            continue
        if any(part in _IGNORED_PARTS for part in relative.parts):
            continue
        rel = relative.as_posix()
        try:
            if path.is_symlink():
                resolved = path.resolve(strict=True)
                if not _is_within(project, resolved):
                    unsafe_entries.append(rel)
                    continue
            if not path.is_file():
                continue
        except (OSError, RuntimeError):
            unsafe_entries.append(rel)
            continue

        lower_name = path.name.lower()
        if _is_test_path(relative):
            tests.append(rel)
        elif path.suffix.lower() in _SOURCE_SUFFIXES or lower_name in _PRODUCT_MANIFESTS:
            meaningful.append(rel)
        elif len(relative.parts) == 1 and lower_name in _BENIGN_ROOT_FILES:
            continue
        else:
            other.append(rel)

    return {
        "meaningful_source_files": sorted(set(meaningful)),
        "test_files": sorted(set(tests)),
        "unsafe_entries": sorted(set(unsafe_entries)),
        "other_files": sorted(set(other)),
    }
