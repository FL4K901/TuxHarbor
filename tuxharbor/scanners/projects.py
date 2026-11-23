"""Read-only project compatibility & Git backup safety scanner.

Never copies, uploads, or reads secret values (such as .env contents).
Only inspects project manifests, build files, and git status to help users:
1. Identify which Linux runtimes their projects require.
2. Catch Windows-specific dependencies (WPF, WinForms, .bat/.ps1 scripts, C:\\ paths) early.
3. Spot uncommitted/unpushed Git work or local-only repos before switching OS.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tuxharbor.models import ProjectFinding


SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    ".nuxt",
    "dist",
    "build",
    "out",
    "target",
    "bin",
    "obj",
    ".idea",
    ".vscode",
    "vendor",
    "coverage",
    ".cache",
}

PROJECT_MARKERS = {
    "package.json": ("Node.js / JavaScript", "nodejs"),
    "tsconfig.json": ("TypeScript", "nodejs"),
    "pyproject.toml": ("Python", "python"),
    "requirements.txt": ("Python", "python"),
    "Cargo.toml": ("Rust", "rust"),
    "go.mod": ("Go", "golang"),
    "pom.xml": ("Java (Maven)", "java-jdk"),
    "build.gradle": ("Java / Gradle", "java-jdk"),
    "build.gradle.kts": ("Kotlin / Gradle", "java-jdk"),
    "Dockerfile": ("Docker", "docker-desktop"),
    "docker-compose.yml": ("Docker Compose", "docker-desktop"),
    "docker-compose.yaml": ("Docker Compose", "docker-desktop"),
    "pubspec.yaml": ("Flutter / Dart", None),
    "composer.json": ("PHP", None),
    "Gemfile": ("Ruby", None),
}

WIN_PATH_RE = re.compile(r"[A-Za-z]:\\\\[^\s\"']+")


def detect_suggested_project_dirs() -> list[str]:
    """Return existing common developer project directories on this computer."""
    home = Path.home()
    candidates = [
        home / "Projects",
        home / "projects",
        home / "Dev",
        home / "dev",
        home / "Code",
        home / "code",
        home / "workspace",
        home / "source" / "repos",
        home / "Documents" / "GitHub",
        home / "Documents" / "Projects",
        home / "Desktop",
    ]
    found: list[str] = []
    seen: set[str] = set()
    for p in candidates:
        try:
            if p.is_dir():
                resolved = str(p.resolve())
                if resolved.lower() not in seen:
                    seen.add(resolved.lower())
                    found.append(resolved)
        except OSError:
            continue
    return found


def _run_git(project_dir: Path, args: list[str]) -> tuple[int, str]:
    git_bin = shutil.which("git")
    if not git_bin:
        return 1, ""
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        res = subprocess.run(
            [git_bin, "-c", "core.fsmonitor=false", "--no-optional-locks", *args],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
            shell=False,
            creationflags=creationflags,
        )
        return res.returncode, (res.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def _is_project_root(folder: Path) -> bool:
    try:
        entries = {p.name for p in folder.iterdir()}
    except OSError:
        return False

    if ".git" in entries:
        return True
    if any(m in entries for m in PROJECT_MARKERS):
        return True
    if any(name.endswith((".csproj", ".sln", ".vbproj")) for name in entries):
        return True
    return False


def _analyze_single_project(folder: Path) -> ProjectFinding:
    finding = ProjectFinding(name=folder.name, path=str(folder))
    stacks: set[str] = set()
    runtimes: set[str] = set()

    try:
        top_entries = list(folder.iterdir())
    except OSError:
        return finding

    entry_names = {p.name for p in top_entries}

    for marker, (stack_name, runtime_id) in PROJECT_MARKERS.items():
        if marker in entry_names:
            stacks.add(stack_name)
            if runtime_id:
                runtimes.add(runtime_id)

    # Check .NET projects (.csproj / .sln) for WPF / WinForms / Windows-only targets
    csproj_files = [
        p for p in top_entries
        if p.is_file() and not p.is_symlink() and p.suffix.lower() in (".csproj", ".vbproj")
    ]
    if csproj_files or any(p.suffix.lower() == ".sln" for p in top_entries if p.is_file()):
        stacks.add(".NET / C#")
        runtimes.add("dotnet-sdk")
        for proj_file in csproj_files[:5]:
            try:
                txt = proj_file.read_text(encoding="utf-8", errors="ignore")[:50000]
                if "<UseWPF>true</UseWPF>" in txt or "<UseWindowsForms>true</UseWindowsForms>" in txt or "-windows" in txt.lower():
                    finding.compatibility = "blocker"
                    finding.linux_warnings.append(
                        {
                            "severity": "blocker",
                            "message": f"{proj_file.name} targets Windows desktop UI (WPF/WinForms), which does not run natively on Linux.",
                        }
                    )
            except OSError:
                pass

    # Check Windows-specific scripts (.bat / .cmd / .ps1)
    win_scripts = [p.name for p in top_entries if p.is_file() and p.suffix.lower() in (".bat", ".cmd", ".ps1")]
    if win_scripts:
        if finding.compatibility == "ready":
            finding.compatibility = "warning"
        sample = ", ".join(win_scripts[:3])
        finding.linux_warnings.append(
            {
                "severity": "warning",
                "message": f"Contains Windows scripts ({sample}) — consider Bash (.sh) equivalents for Linux.",
            }
        )

    # Check package.json scripts for hardcoded Windows drive paths
    pkg_json = folder / "package.json"
    if pkg_json.is_file() and not pkg_json.is_symlink():
        try:
            pkg_txt = pkg_json.read_text(encoding="utf-8", errors="ignore")[:40000]
            if WIN_PATH_RE.search(pkg_txt):
                if finding.compatibility == "ready":
                    finding.compatibility = "warning"
                finding.linux_warnings.append(
                    {
                        "severity": "warning",
                        "message": "package.json contains hardcoded Windows drive paths (e.g. C:\\\\...).",
                    }
                )
        except OSError:
            pass

    # Check .env files presence ONLY (NEVER open or read .env contents!)
    env_files = [
        p.name
        for p in top_entries
        if p.is_file() and (p.name == ".env" or p.name.startswith(".env.")) and not p.name.endswith(".example")
    ]
    if env_files:
        finding.has_env_files = True
        finding.backup_warnings.append(
            {
                "severity": "warning",
                "message": f"Contains local config ({', '.join(env_files[:3])}) — typically ignored by Git; back it up securely.",
            }
        )

    # Git backup safety checks
    if (folder / ".git").exists():
        finding.is_git_repo = True
        rc_rem, rem_out = _run_git(folder, ["remote"])
        finding.has_remote = rc_rem == 0 and bool(rem_out.strip())
        if not finding.has_remote:
            finding.backup_warnings.append(
                {
                    "severity": "high",
                    "message": "Git repository has no remote configured — source code exists only on this PC.",
                }
            )

        rc_st, st_out = _run_git(folder, ["status", "--porcelain"])
        if rc_st == 0 and st_out:
            uncommitted = len([ln for ln in st_out.splitlines() if ln.strip()])
            finding.uncommitted_count = uncommitted
            finding.backup_warnings.append(
                {
                    "severity": "high",
                    "message": f"{uncommitted} uncommitted file(s) — commit and push, or copy to an external backup.",
                }
            )

        rc_up, up_out = _run_git(folder, ["rev-list", "--count", "@{u}..HEAD"])
        if rc_up == 0 and up_out.isdigit() and int(up_out) > 0:
            unpushed = int(up_out)
            finding.unpushed_count = unpushed
            finding.backup_warnings.append(
                {
                    "severity": "high",
                    "message": f"{unpushed} local commit(s) not pushed to remote yet.",
                }
            )
    else:
        finding.backup_warnings.append(
            {
                "severity": "high",
                "message": "Not a Git repository — back up this folder to an external drive or cloud storage.",
            }
        )

    finding.stacks = sorted(stacks)
    finding.recommended_runtimes = sorted(runtimes)
    return finding


def scan_projects_folders(
    root_dirs: list[str],
    max_depth: int = 3,
    max_projects: int = 60,
    demo_mode: bool = False,
) -> list[dict[str, Any]]:
    """Scan user-selected project directories (read-only) for stack, Linux readiness, and backup risks."""
    if demo_mode:
        return [
            ProjectFinding(
                name="my-saas-webapp",
                path=r"C:\Users\Demo\Projects\my-saas-webapp",
                stacks=["Node.js / JavaScript", "TypeScript", "Docker"],
                recommended_runtimes=["nodejs", "docker-desktop"],
                backup_warnings=[
                    {
                        "severity": "warning",
                        "message": "Contains local config (.env.local) — typically ignored by Git; back it up securely.",
                    }
                ],
                is_git_repo=True,
                has_remote=True,
                has_env_files=True,
                compatibility="ready",
            ).to_dict(),
            ProjectFinding(
                name="python-ai-scripts",
                path=r"C:\Users\Demo\Projects\python-ai-scripts",
                stacks=["Python"],
                recommended_runtimes=["python"],
                backup_warnings=[
                    {
                        "severity": "high",
                        "message": "4 uncommitted file(s) — commit and push, or copy to an external backup.",
                    }
                ],
                is_git_repo=True,
                has_remote=True,
                uncommitted_count=4,
                compatibility="ready",
            ).to_dict(),
            ProjectFinding(
                name="legacy-wpf-tool",
                path=r"C:\Users\Demo\Projects\legacy-wpf-tool",
                stacks=[".NET / C#"],
                recommended_runtimes=["dotnet-sdk"],
                linux_warnings=[
                    {
                        "severity": "blocker",
                        "message": "LegacyApp.csproj targets Windows desktop UI (WPF/WinForms), which does not run natively on Linux.",
                    }
                ],
                backup_warnings=[
                    {
                        "severity": "high",
                        "message": "Not a Git repository — back up this folder to an external drive or cloud storage.",
                    }
                ],
                is_git_repo=False,
                compatibility="blocker",
            ).to_dict(),
        ]

    findings: list[ProjectFinding] = []
    visited: set[str] = set()

    def walk(current: Path, depth: int) -> None:
        if len(findings) >= max_projects or depth > max_depth:
            return
        try:
            key = str(current.resolve()).lower()
        except OSError:
            return
        if key in visited:
            return
        visited.add(key)

        if _is_project_root(current):
            findings.append(_analyze_single_project(current))
            return  # Don't recurse inside a detected project root

        if depth == max_depth:
            return

        try:
            children = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return

        for child in children:
            if child.is_symlink() or not child.is_dir():
                continue
            if child.name in SKIP_DIRS or child.name.startswith("."):
                continue
            walk(child, depth + 1)

    for raw_dir in root_dirs:
        if not raw_dir:
            continue
        p = Path(raw_dir).expanduser()
        if p.is_dir() and not p.is_symlink():
            walk(p, 0)

    return [f.to_dict() for f in findings]
