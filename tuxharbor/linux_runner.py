"""Linux-side execution & verification engine for TuxHarbor migration plans."""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from tuxharbor.models import (
    is_safe_flatpak_id,
    is_safe_https_url,
    is_safe_npm_package,
    is_safe_package_name,
    is_safe_vscode_extension,
)


def detect_linux_environment() -> dict[str, Any]:
    """Detect Linux distro, package manager, Flatpak availability, and desktop environment."""
    is_linux = platform.system() == "Linux"
    distro_name = platform.platform()
    distro_id = ""

    os_release = Path("/etc/os-release")
    if is_linux and os_release.is_file():
        try:
            for line in os_release.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("PRETTY_NAME="):
                    distro_name = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("ID="):
                    distro_id = line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass

    pm = ""
    if is_linux:
        for candidate, binary in [
            ("apt", "apt-get"),
            ("dnf", "dnf"),
            ("pacman", "pacman"),
            ("zypper", "zypper"),
        ]:
            if shutil.which(binary):
                pm = candidate
                break

    return {
        "is_linux": is_linux,
        "distro_name": distro_name,
        "distro_id": distro_id,
        "package_manager": pm,
        "has_flatpak": bool(shutil.which("flatpak")),
        "has_sudo": bool(shutil.which("sudo")),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
    }


def _installed_flatpaks() -> set[str]:
    flatpak_bin = shutil.which("flatpak")
    if not flatpak_bin:
        return set()
    try:
        res = subprocess.run(
            [flatpak_bin, "list", "--app", "--columns=application"],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        if res.returncode == 0:
            return {ln.strip() for ln in res.stdout.splitlines() if ln.strip()}
    except (OSError, subprocess.TimeoutExpired):
        pass
    return set()


def _safe_pm_list(raw_pkgs: Any) -> list[str]:
    if not isinstance(raw_pkgs, list):
        return []
    return [p.strip() for p in raw_pkgs if isinstance(p, str) and is_safe_package_name(p.strip())]


def _pm_install_cmd(pm: str, pkgs: list[str]) -> list[str]:
    safe = _safe_pm_list(pkgs)
    if not safe:
        return []
    if pm == "apt":
        return ["sudo", "apt-get", "install", "-y", "--", *safe]
    if pm == "dnf":
        return ["sudo", "dnf", "install", "-y", "--", *safe]
    if pm == "pacman":
        return ["sudo", "pacman", "-S", "--needed", "--noconfirm", "--", *safe]
    if pm == "zypper":
        return ["sudo", "zypper", "--non-interactive", "install", "--", *safe]
    return []


def _pm_install_cmd_str(pm: str, pkgs: list[str]) -> str:
    return " ".join(_pm_install_cmd(pm, pkgs))


def inspect_plan_on_linux(plan: dict[str, Any]) -> dict[str, Any]:
    """Inspect a migration-plan.json against the current system and preview safe actions."""
    if not isinstance(plan, dict):
        raise ValueError("Invalid migration plan format (expected JSON object).")
    env = detect_linux_environment()
    pm = env["package_manager"]
    prefer_flatpak = bool(plan.get("prefer_flatpak", True))
    installed_fp = _installed_flatpaks() if env["is_linux"] else set()

    raw_apps = plan.get("apps", [])
    apps_list = [a for a in raw_apps if isinstance(a, dict)] if isinstance(raw_apps, list) else []

    items_status: list[dict[str, Any]] = []
    for app in apps_list:
        name = str(app.get("target_linux_app", "App"))
        raw_pkgs = app.get("packages", {})
        pkgs = raw_pkgs if isinstance(raw_pkgs, dict) else {}
        app_type = str(app.get("type", "app"))

        fp_raw = str(pkgs.get("flatpak", "")).strip()
        fp_id = fp_raw if is_safe_flatpak_id(fp_raw) else ""
        pm_pkgs = _safe_pm_list(pkgs.get(pm, [])) if pm else []
        url_raw = str(pkgs.get("official_url", "")).strip()
        official_url = url_raw if is_safe_https_url(url_raw) else ""

        installed = False
        action = "manual"
        command_preview = ""

        if app_type == "web":
            action = "web"
            command_preview = official_url
        elif app_type == "cli" and pm and pm_pkgs:
            action = pm
            command_preview = _pm_install_cmd_str(pm, pm_pkgs)
            installed = bool(shutil.which(pm_pkgs[0]))
        elif prefer_flatpak and fp_id:
            action = "flatpak"
            command_preview = f"flatpak install -y flathub {fp_id}"
            installed = fp_id in installed_fp
        elif pm and pm_pkgs:
            action = pm
            command_preview = _pm_install_cmd_str(pm, pm_pkgs)
            installed = bool(shutil.which(pm_pkgs[0]))
        elif fp_id:
            action = "flatpak"
            command_preview = f"flatpak install -y flathub {fp_id}"
            installed = fp_id in installed_fp
        elif official_url:
            action = "manual"
            command_preview = official_url

        items_status.append(
            {
                "source_windows_app": str(app.get("source_windows_app", "")),
                "target_linux_app": name,
                "action": action,
                "command_preview": command_preview,
                "installed": installed,
            }
        )

    valid_exts = [e for e in (plan.get("vscode_extensions", []) or []) if isinstance(e, str) and is_safe_vscode_extension(e.strip())]
    valid_npm = [p for p in (plan.get("npm_globals", []) or []) if isinstance(p, str) and is_safe_npm_package(p.strip())]

    return {
        "environment": env,
        "items": items_status,
        "vscode_extensions_count": len(valid_exts),
        "npm_globals_count": len(valid_npm),
    }


def apply_plan_on_linux(
    plan: dict[str, Any],
    dry_run: bool = True,
    log_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Apply or dry-run a TuxHarbor migration plan natively on Linux (strictly shell=False)."""
    if not isinstance(plan, dict):
        raise ValueError("Invalid migration plan format (expected JSON object).")
    env = detect_linux_environment()
    if not env["is_linux"] and not dry_run:
        raise RuntimeError("Live installation can only run on Linux. Use Dry Run to preview on Windows/macOS.")

    pm = env["package_manager"] or "apt"
    prefer_flatpak = bool(plan.get("prefer_flatpak", True))
    logs: list[str] = []
    succeeded: list[str] = []
    failed: list[str] = []
    manual: list[dict[str, str]] = []

    def emit(line: str) -> None:
        logs.append(line)
        if log_callback:
            try:
                log_callback(line)
            except Exception:
                pass

    def exec_step(label: str, cmd: list[str]) -> None:
        if not cmd:
            return
        cmd_str = shlex.join(cmd)
        if dry_run:
            emit(f"[dry-run] {label}: {cmd_str}")
            succeeded.append(label)
            return
        emit(f"[run] {label}: {cmd_str}")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300, shell=False)
            if res.returncode == 0:
                emit(f"[ok] {label}")
                succeeded.append(label)
            else:
                err_tail = (res.stderr or res.stdout or "").strip().splitlines()[-1:]
                emit(f"[fail] {label}: {' '.join(err_tail)}")
                failed.append(label)
        except (OSError, subprocess.TimeoutExpired) as exc:
            emit(f"[fail] {label}: {exc}")
            failed.append(label)

    raw_apps = plan.get("apps", [])
    apps_list = [a for a in raw_apps if isinstance(a, dict)] if isinstance(raw_apps, list) else []

    # Ensure Flathub if any valid Flatpak app is present
    needs_flatpak = any(
        isinstance(a.get("packages"), dict)
        and is_safe_flatpak_id(str(a["packages"].get("flatpak", "")).strip())
        for a in apps_list
        if a.get("type") != "web"
    )
    if needs_flatpak:
        if not env["has_flatpak"]:
            exec_step("Flatpak", _pm_install_cmd(pm, ["flatpak"]))
        exec_step(
            "Flathub Remote",
            [
                "flatpak",
                "remote-add",
                "--if-not-exists",
                "flathub",
                "https://dl.flathub.org/repo/flathub.flatpakrepo",
            ],
        )

    for app in apps_list:
        name = str(app.get("target_linux_app", "App"))
        raw_pkgs = app.get("packages", {})
        pkgs = raw_pkgs if isinstance(raw_pkgs, dict) else {}
        app_type = str(app.get("type", "app"))

        fp_raw = str(pkgs.get("flatpak", "")).strip()
        if fp_raw and not is_safe_flatpak_id(fp_raw):
            emit(f"[skip] Rejected unsafe Flatpak ID for {name}")
            fp_id = ""
        else:
            fp_id = fp_raw

        raw_pm_pkgs = pkgs.get(pm, [])
        pm_pkgs = _safe_pm_list(raw_pm_pkgs)
        if isinstance(raw_pm_pkgs, list) and len(pm_pkgs) < len(raw_pm_pkgs):
            emit(f"[skip] Rejected unsafe package token(s) for {name}")

        url_raw = str(pkgs.get("official_url", "")).strip()
        url = url_raw if is_safe_https_url(url_raw) else ""

        if app_type == "web":
            if url:
                manual.append({"name": name, "kind": "web", "url": url})
            continue

        if app_type == "cli" and pm_pkgs:
            exec_step(name, _pm_install_cmd(pm, pm_pkgs))
        elif prefer_flatpak and fp_id:
            exec_step(name, ["flatpak", "install", "-y", "flathub", fp_id])
        elif pm_pkgs:
            exec_step(name, _pm_install_cmd(pm, pm_pkgs))
        elif fp_id:
            exec_step(name, ["flatpak", "install", "-y", "flathub", fp_id])
        elif url:
            manual.append({"name": name, "kind": "manual", "url": url})

    # VS Code extensions
    code_bin = shutil.which("code")
    raw_exts = plan.get("vscode_extensions", [])
    for raw_ext in (raw_exts if isinstance(raw_exts, list) else []):
        if not isinstance(raw_ext, str):
            continue
        ext = raw_ext.strip()
        if not is_safe_vscode_extension(ext):
            emit("[skip] Rejected unsafe VS Code extension ID")
            continue
        if code_bin or dry_run:
            exec_step(f"VS Code ext: {ext}", [code_bin or "code", "--install-extension", ext, "--force"])

    # Global npm packages (strictly validated)
    npm_bin = shutil.which("npm")
    raw_npms = plan.get("npm_globals", [])
    for raw_pkg in (raw_npms if isinstance(raw_npms, list) else []):
        if not isinstance(raw_pkg, str):
            continue
        pkg = raw_pkg.strip()
        if not is_safe_npm_package(pkg):
            emit("[skip] Rejected unsafe npm package name")
            continue
        if npm_bin or dry_run:
            exec_step(f"npm global: {pkg}", [npm_bin or "npm", "install", "-g", "--", pkg])

    return {
        "dry_run": dry_run,
        "environment": env,
        "succeeded": succeeded,
        "failed": failed,
        "manual": manual,
        "logs": logs,
    }
