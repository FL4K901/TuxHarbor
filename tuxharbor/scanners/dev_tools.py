"""Developer environment scanner: runtimes, CLIs, VS Code extensions, npm globals, Git config."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tuxharbor.models import DevEnvironment, is_safe_npm_package, is_safe_vscode_extension


RUNTIME_PROBES: list[tuple[str, str, list[str], str]] = [
    # (catalog_id, display_name, command, version_flag)
    ("git", "Git", ["git", "--version"], "git"),
    ("github-cli", "GitHub CLI (gh)", ["gh", "--version"], "gh"),
    ("nodejs", "Node.js", ["node", "--version"], "node"),
    ("python", "Python 3", ["python", "--version"], "python"),
    ("docker-desktop", "Docker", ["docker", "--version"], "docker"),
    ("golang", "Go", ["go", "version"], "go"),
    ("rust", "Rust (rustc)", ["rustc", "--version"], "rustc"),
    ("dotnet-sdk", ".NET SDK", ["dotnet", "--version"], "dotnet"),
    ("java-jdk", "Java (JDK)", ["java", "-version"], "java"),
    ("deno", "Deno", ["deno", "--version"], "deno"),
    ("ollama", "Ollama", ["ollama", "--version"], "ollama"),
    ("ffmpeg", "FFmpeg", ["ffmpeg", "-version"], "ffmpeg"),
    ("vscode", "VS Code CLI", ["code", "--version"], "code"),
]


def _run_quick(cmd: list[str], timeout: int = 5) -> str:
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
            shell=False,
            creationflags=creationflags,
        )
        out = (res.stdout or res.stderr or "").strip()
        if res.returncode != 0 and not out:
            return ""
        return out.splitlines()[0].strip() if out else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _scan_vscode_extensions() -> tuple[bool, list[str]]:
    extensions: set[str] = set()
    vscode_found = False

    # Fast local JSON read first (zero process overhead!)
    ext_json = Path.home() / ".vscode" / "extensions" / "extensions.json"
    if ext_json.is_file() and not ext_json.is_symlink():
        vscode_found = True
        try:
            if ext_json.stat().st_size <= 10 * 1024 * 1024:
                data = json.loads(ext_json.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(data, list):
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        ident_obj = item.get("identifier")
                        ident = ident_obj.get("id", "") if isinstance(ident_obj, dict) else ""
                        if is_safe_vscode_extension(ident):
                            extensions.add(ident)
        except (OSError, ValueError):
            pass

    # Fallback / supplement via CLI if available
    code_bin = shutil.which("code") or shutil.which("code.cmd")
    if code_bin:
        vscode_found = True
        if not extensions:
            try:
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                res = subprocess.run(
                    [code_bin, "--list-extensions"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=10,
                    shell=False,
                    creationflags=creationflags,
                )
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        ext = line.strip()
                        if is_safe_vscode_extension(ext):
                            extensions.add(ext)
            except (OSError, subprocess.TimeoutExpired):
                pass

    return vscode_found, sorted(extensions, key=str.lower)


def _scan_npm_globals() -> list[str]:
    """Read global npm packages quickly from global node_modules without spawning slow npm ls."""
    candidates: list[Path] = []
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "npm" / "node_modules")
    else:
        candidates.append(Path("/usr/local/lib/node_modules"))
        candidates.append(Path.home() / ".npm-global" / "lib" / "node_modules")

    pkgs: set[str] = set()
    for base in candidates:
        if not base.is_dir():
            continue
        try:
            for item in base.iterdir():
                if item.name.startswith("."):
                    continue
                if item.name.startswith("@") and item.is_dir():
                    for sub in item.iterdir():
                        if sub.is_dir():
                            cand = f"{item.name}/{sub.name}"
                            if is_safe_npm_package(cand):
                                pkgs.add(cand)
                elif item.is_dir() and item.name not in ("npm", "corepack"):
                    if is_safe_npm_package(item.name):
                        pkgs.add(item.name)
        except OSError:
            continue
    return sorted(pkgs)


def _scan_git_identity() -> tuple[str, str]:
    git_bin = shutil.which("git")
    if not git_bin:
        return "", ""
    name = _run_quick([git_bin, "config", "--global", "user.name"])
    email = _run_quick([git_bin, "config", "--global", "user.email"])
    return name, email


def scan_dev_environment(demo_mode: bool = False) -> DevEnvironment:
    """Detect developer runtimes, CLIs, VS Code extensions, npm globals, and Git identity."""
    if demo_mode:
        return DevEnvironment(
            runtimes=[
                {"catalog_id": "git", "name": "Git", "version": "git version 2.47.1"},
                {"catalog_id": "nodejs", "name": "Node.js", "version": "v22.11.0"},
                {"catalog_id": "python", "name": "Python 3", "version": "Python 3.13.1"},
                {"catalog_id": "github-cli", "name": "GitHub CLI (gh)", "version": "gh version 2.62.0"},
                {"catalog_id": "docker-desktop", "name": "Docker", "version": "Docker version 27.3.1"},
            ],
            vscode_installed=True,
            vscode_extensions=[
                "ms-python.python",
                "dbaeumer.vscode-eslint",
                "esbenp.prettier-vscode",
                "eamodio.gitlens",
                "ms-azuretools.vscode-docker",
                "bradlc.vscode-tailwindcss",
            ],
            npm_globals=["typescript", "pnpm", "vercel"],
            git_user_name="Alex Developer",
            git_user_email="alex@example.com",
            wsl_installed=True,
        )

    runtimes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for catalog_id, name, cmd, binary in RUNTIME_PROBES:
        resolved = shutil.which(binary)
        if not resolved and binary == "python" and platform.system() == "Windows":
            resolved = shutil.which("py")
            if resolved:
                cmd = ["py", "--version"]
        if not resolved:
            continue
        ver = _run_quick([resolved, *cmd[1:]])
        # Windows Microsoft Store python stub returns empty/error
        if not ver or "Microsoft Store" in ver or "not found" in ver.lower():
            continue
        if catalog_id not in seen_ids:
            seen_ids.add(catalog_id)
            runtimes.append(
                {
                    "catalog_id": catalog_id,
                    "name": name,
                    "version": ver[:120],
                    "path": resolved,
                }
            )

    vscode_installed, vscode_extensions = _scan_vscode_extensions()
    npm_globals = _scan_npm_globals()
    git_name, git_email = _scan_git_identity()
    wsl_installed = bool(shutil.which("wsl")) if platform.system() == "Windows" else False

    return DevEnvironment(
        runtimes=runtimes,
        vscode_installed=vscode_installed,
        vscode_extensions=vscode_extensions,
        npm_globals=npm_globals,
        git_user_name=git_name,
        git_user_email=git_email,
        wsl_installed=wsl_installed,
    )
