"""Safe, human-readable, distro-agnostic Linux installer script & portable plan generator."""

from __future__ import annotations

import datetime as dt
import re
import shlex
from typing import Any

from tuxharbor import LEGAL_NOTICE_LINES, __version__
from tuxharbor.models import (
    contains_control_or_crlf,
    is_safe_email,
    is_safe_flatpak_id,
    is_safe_https_url,
    is_safe_npm_package,
    is_safe_package_name,
    is_safe_vscode_extension,
)


ALLOWED_DISTROS = {"auto", "apt", "dnf", "pacman", "zypper"}
SAFE_TIMESTAMP_RE = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2})?(?:Z|[+-][0-9]{2}:[0-9]{2})?)?\Z")


def _clean_single_line(text: Any, max_len: int = 160) -> str:
    """Strip CR/LF and ASCII control characters from header/display strings."""
    raw = str(text or "")
    cleaned = "".join(ch if (32 <= ord(ch) < 127) else " " for ch in raw)
    return " ".join(cleaned.split())[:max_len]


def _pick_packages_for_item(item: dict[str, Any]) -> tuple[str, dict[str, str], str]:
    """Return (target_display_name, packages_dict, target_type) for a selected report item."""
    status = item.get("status", "")
    alternatives = item.get("alternatives") or []
    sel_alt_id = item.get("selected_alternative_id")

    if status == "native" and item.get("linux_packages"):
        return _clean_single_line(item.get("name", ""), 120), dict(item.get("linux_packages", {})), "app"

    if alternatives:
        chosen = next((a for a in alternatives if a.get("id") == sel_alt_id), None)
        if not chosen:
            chosen = next((a for a in alternatives if a.get("recommended")), alternatives[0])
        return (
            _clean_single_line(chosen.get("name", item.get("name", "")), 120),
            dict(chosen.get("packages", {})),
            str(chosen.get("type", "app")),
        )

    return _clean_single_line(item.get("name", ""), 120), dict(item.get("linux_packages", {})), "app"


def _sanitize_pkg_tokens(raw_value: Any) -> list[str]:
    """Accept a string or list of distro packages and keep only strictly validated tokens."""
    if isinstance(raw_value, list):
        candidates = [str(x) for x in raw_value]
    else:
        candidates = str(raw_value or "").split()
    tokens: list[str] = []
    for tok in candidates:
        tok = tok.strip()
        if is_safe_package_name(tok):
            tokens.append(tok)
    return tokens


def build_migration_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize user selections from the GUI/CLI into a portable migration-plan.json object."""
    target_distro = str(payload.get("target_distro", "auto")).lower()
    if target_distro not in ALLOWED_DISTROS:
        target_distro = "auto"

    prefer_flatpak = bool(payload.get("prefer_flatpak", True))
    include_vscode_exts = bool(payload.get("include_vscode_extensions", True))
    include_git_config = bool(payload.get("include_git_config", False))
    include_npm_globals = bool(payload.get("include_npm_globals", False))

    matched_items: list[dict[str, Any]] = payload.get("matched", [])
    planned_apps: list[dict[str, Any]] = []
    seen_targets: set[str] = set()

    for item in matched_items:
        if not item.get("selected") or item.get("no_install_needed"):
            continue
        target_name, pkgs, target_type = _pick_packages_for_item(item)
        if target_type not in ("app", "cli", "web"):
            target_type = "app"
        dedup_key = target_name.lower().strip()
        if not target_name or dedup_key in seen_targets:
            continue
        seen_targets.add(dedup_key)

        clean_pkgs: dict[str, Any] = {}
        for pm in ("apt", "dnf", "pacman", "zypper"):
            if pm in pkgs:
                toks = _sanitize_pkg_tokens(pkgs[pm])
                if toks:
                    clean_pkgs[pm] = toks
        fp_raw = str(pkgs.get("flatpak", "")).strip()
        if fp_raw and is_safe_flatpak_id(fp_raw):
            clean_pkgs["flatpak"] = fp_raw
        url = str(pkgs.get("official_url", "")).strip()
        if is_safe_https_url(url):
            clean_pkgs["official_url"] = url

        planned_apps.append(
            {
                "source_windows_app": _clean_single_line(item.get("name", ""), 120),
                "target_linux_app": target_name,
                "category": _clean_single_line(item.get("category", "utilities"), 40),
                "status": _clean_single_line(item.get("status", "native"), 30),
                "type": target_type,
                "packages": clean_pkgs,
            }
        )

    dev_env = payload.get("dev_env", {}) or {}
    vscode_exts: list[str] = []
    if include_vscode_exts:
        for ext in payload.get("selected_vscode_extensions", dev_env.get("vscode_extensions", [])):
            ext_s = str(ext).strip()
            if is_safe_vscode_extension(ext_s):
                vscode_exts.append(ext_s)

    npm_globals: list[str] = []
    if include_npm_globals:
        for pkg in payload.get("selected_npm_globals", dev_env.get("npm_globals", [])):
            pkg_s = str(pkg).strip()
            if is_safe_npm_package(pkg_s):
                npm_globals.append(pkg_s)

    git_config: dict[str, str] = {}
    if include_git_config:
        gname = str(dev_env.get("git_user_name", "")).strip()
        gemail = str(dev_env.get("git_user_email", "")).strip()
        if gname and not contains_control_or_crlf(gname) and not gname.startswith("-"):
            git_config["user_name"] = gname[:120]
        if gemail and is_safe_email(gemail) and not gemail.startswith("-"):
            git_config["user_email"] = gemail[:160]

    return {
        "schema": "tuxharbor-plan/v1",
        "generator": f"TuxHarbor {__version__}",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "target_distro": target_distro,
        "prefer_flatpak": prefer_flatpak,
        "backup_reminder": (
            "IMPORTANT: TuxHarbor migrates tools and alternatives ONLY — NOT your personal files or project "
            "source code. Back up your projects, .env files, SSH keys, and personal documents to an external "
            "drive or cloud storage before switching operating systems."
        ),
        "apps": planned_apps,
        "vscode_extensions": sorted(set(vscode_exts), key=str.lower),
        "npm_globals": sorted(set(npm_globals), key=str.lower),
        "git_config": git_config,
        "projects_summary": payload.get("projects", []),
        "readiness_score": int(payload.get("readiness_score", 100)),
    }


def generate_linux_script(plan: dict[str, Any]) -> str:
    """Generate a strictly quoted, distro-auto-detecting Bash installer script (Unix LF)."""
    if not isinstance(plan, dict):
        raise ValueError("Migration plan must be a JSON object.")
    prefer_flatpak = bool(plan.get("prefer_flatpak", True))
    target_distro = str(plan.get("target_distro", "auto")).lower()
    if target_distro not in ALLOWED_DISTROS:
        target_distro = "auto"
    raw_ts = str(plan.get("generated_at", "") or "").strip()
    generated_at = raw_ts if SAFE_TIMESTAMP_RE.match(raw_ts) else "unknown"

    raw_apps = plan.get("apps", [])
    apps: list[dict[str, Any]] = [a for a in raw_apps if isinstance(a, dict)] if isinstance(raw_apps, list) else []
    raw_exts = plan.get("vscode_extensions", [])
    vscode_exts: list[str] = (
        [str(e).strip() for e in raw_exts if isinstance(e, str) and is_safe_vscode_extension(e.strip())]
        if isinstance(raw_exts, list)
        else []
    )
    raw_npm = plan.get("npm_globals", [])
    npm_globals: list[str] = (
        [str(p).strip() for p in raw_npm if isinstance(p, str) and is_safe_npm_package(p.strip())]
        if isinstance(raw_npm, list)
        else []
    )
    raw_git = plan.get("git_config", {}) or {}
    git_config: dict[str, str] = {}
    if isinstance(raw_git, dict):
        gname = str(raw_git.get("user_name", "")).strip()
        if gname and not contains_control_or_crlf(gname) and not gname.startswith("-"):
            git_config["user_name"] = gname[:120]
        gemail = str(raw_git.get("user_email", "")).strip()
        if gemail and is_safe_email(gemail) and not gemail.startswith("-"):
            git_config["user_email"] = gemail[:160]

    flatpak_apps: list[tuple[str, str]] = []
    native_per_pm: dict[str, list[tuple[str, list[str]]]] = {
        "apt": [],
        "dnf": [],
        "pacman": [],
        "zypper": [],
    }
    manual_or_web: list[tuple[str, str, str]] = []  # (name, type, url)
    pm_fallback_urls: list[tuple[str, list[str], str]] = []  # (name, covered_pms, url)

    for app in apps:
        name = _clean_single_line(app.get("target_linux_app", "App"), 120) or "App"
        app_type = str(app.get("type", "app"))
        raw_pkgs = app.get("packages", {})
        pkgs = raw_pkgs if isinstance(raw_pkgs, dict) else {}

        # Defense-in-depth re-validation on every token from plan.json
        fp_raw = str(pkgs.get("flatpak", "")).strip()
        flatpak_id = fp_raw if is_safe_flatpak_id(fp_raw) else ""
        url_raw = str(pkgs.get("official_url", "")).strip()
        official_url = url_raw if is_safe_https_url(url_raw) else ""

        validated_pm: dict[str, list[str]] = {}
        for pm in ("apt", "dnf", "pacman", "zypper"):
            toks = _sanitize_pkg_tokens(pkgs.get(pm, []))
            if toks:
                validated_pm[pm] = toks
        has_pm = bool(validated_pm)

        if app_type == "web":
            if official_url:
                manual_or_web.append((name, "web", official_url))
            continue

        # CLI tools prefer native distro package managers over Flatpak
        if app_type == "cli" and has_pm:
            for pm, toks in validated_pm.items():
                native_per_pm[pm].append((name, toks))
            if official_url and len(validated_pm) < 4:
                pm_fallback_urls.append((name, sorted(validated_pm.keys()), official_url))
            continue

        if prefer_flatpak and flatpak_id:
            flatpak_apps.append((name, flatpak_id))
        elif has_pm:
            for pm, toks in validated_pm.items():
                native_per_pm[pm].append((name, toks))
            if official_url and len(validated_pm) < 4:
                pm_fallback_urls.append((name, sorted(validated_pm.keys()), official_url))
        elif flatpak_id:
            flatpak_apps.append((name, flatpak_id))
        elif official_url:
            manual_or_web.append((name, "manual", official_url))

    lines: list[str] = [
        "#!/usr/bin/env bash",
        "# =============================================================================",
        f"# TuxHarbor Linux Setup Script (v{__version__})",
        f"# Generated: {generated_at}",
        f"# Target Distro: {target_distro} | Prefer Flatpak: {str(prefer_flatpak).lower()}",
        "#",
        "# REMINDER: This script installs tools and alternatives ONLY.",
        "# Make sure your personal files and projects are safely backed up to an",
        "# external drive, Git remote, or cloud storage before switching.",
        "#",
        *[f"# {ln}" for ln in LEGAL_NOTICE_LINES],
        "#",
        "# Usage:",
        "#   chmod +x tuxharbor-migration-install.sh",
        "#   ./tuxharbor-migration-install.sh              # Interactive install",
        "#   ./tuxharbor-migration-install.sh --dry-run    # Preview commands without installing",
        "#   ./tuxharbor-migration-install.sh --yes        # Auto-confirm without prompts",
        "# =============================================================================",
        "",
        "set -uo pipefail",
        "",
        "DRY_RUN=0",
        "AUTO_YES=0",
        'for arg in "$@"; do',
        '  case "$arg" in',
        "    --dry-run) DRY_RUN=1 ;;",
        "    -y|--yes) AUTO_YES=1 ;;",
        "    -h|--help)",
        '      echo "Usage: $0 [--dry-run] [--yes]"',
        "      exit 0",
        "      ;;",
        "  esac",
        "done",
        "",
        'GREEN="\\033[1;32m"',
        'CYAN="\\033[1;36m"',
        'YELLOW="\\033[1;33m"',
        'RED="\\033[1;31m"',
        'BOLD="\\033[1m"',
        'RESET="\\033[0m"',
        "",
        "SUCCEEDED=()",
        "FAILED=()",
        "",
        'info()  { printf "${CYAN}[INFO]${RESET} %s\\n" "$*"; }',
        'ok()    { printf "${GREEN}[ OK ]${RESET} %s\\n" "$*"; }',
        'warn()  { printf "${YELLOW}[WARN]${RESET} %s\\n" "$*"; }',
        'err()   { printf "${RED}[FAIL]${RESET} %s\\n" "$*"; }',
        "",
        "run_cmd() {",
        '  if [[ "$DRY_RUN" -eq 1 ]]; then',
        '    printf "  ${YELLOW}[dry-run]${RESET} %s\\n" "$*"',
        "    return 0",
        "  fi",
        '  "$@"',
        "}",
        "",
        'printf "${BOLD}${CYAN}\\n======================================================\\n"',
        'printf "   Welcome to TuxHarbor — Linux Auto-Setup\\n"',
        'printf "======================================================${RESET}\\n\\n"',
        'if [[ "$DRY_RUN" -eq 1 ]]; then',
        '  warn "DRY-RUN mode enabled — no changes will be made to your system."',
        "fi",
        "",
        "# Detect package manager",
        'PM=""',
        'if command -v apt-get >/dev/null 2>&1; then PM="apt"',
        'elif command -v dnf >/dev/null 2>&1; then PM="dnf"',
        'elif command -v pacman >/dev/null 2>&1; then PM="pacman"',
        'elif command -v zypper >/dev/null 2>&1; then PM="zypper"',
        "fi",
        "",
        'DISTRO_NAME="Linux"',
        'if [[ -f /etc/os-release ]]; then',
        '  DISTRO_NAME=$(grep -E "^PRETTY_NAME=" /etc/os-release | cut -d= -f2- | tr -d \'"\')',
        "fi",
        'info "Detected system: ${DISTRO_NAME} (package manager: ${PM:-none})"',
        "",
        'if [[ "$AUTO_YES" -eq 0 && "$DRY_RUN" -eq 0 ]]; then',
        '  printf "\\nProceed with installing your selected Linux tools & alternatives? [Y/n] "',
        '  read -r REPLY || REPLY="y"',
        '  if [[ -n "$REPLY" && ! "$REPLY" =~ ^[Yy]$ ]]; then',
        '    info "Cancelled by user."',
        "    exit 0",
        "  fi",
        "fi",
        "",
        "install_sys_pkg() {",
        '  local label="$1"; shift',
        '  info "Installing ${label} ($*)..."',
        '  case "$PM" in',
        '    apt)    if run_cmd sudo apt-get install -y -- "$@"; then ok "$label"; SUCCEEDED+=("$label"); else err "$label"; FAILED+=("$label"); fi ;;',
        '    dnf)    if run_cmd sudo dnf install -y -- "$@"; then ok "$label"; SUCCEEDED+=("$label"); else err "$label"; FAILED+=("$label"); fi ;;',
        '    pacman) if run_cmd sudo pacman -S --needed --noconfirm -- "$@"; then ok "$label"; SUCCEEDED+=("$label"); else err "$label"; FAILED+=("$label"); fi ;;',
        '    zypper) if run_cmd sudo zypper --non-interactive install -- "$@"; then ok "$label"; SUCCEEDED+=("$label"); else err "$label"; FAILED+=("$label"); fi ;;',
        '    *)      warn "No supported system package manager detected for ${label}"; FAILED+=("$label") ;;',
        "  esac",
        "}",
        "",
        "# Update package index once",
        'case "$PM" in',
        '  apt)    info "Updating apt package index..."; run_cmd sudo apt-get update ;;',
        '  pacman) info "Refreshing pacman databases..."; run_cmd sudo pacman -Sy --noconfirm ;;',
        "esac",
        "",
    ]

    # System package installations by detected PM
    has_any_native = any(native_per_pm[pm] for pm in native_per_pm)
    if has_any_native:
        lines.append("# --- Native Distro Packages ---")
        lines.append('case "$PM" in')
        for pm in ("apt", "dnf", "pacman", "zypper"):
            if not native_per_pm[pm]:
                continue
            lines.append(f"  {pm})")
            for label, pkg_list in native_per_pm[pm]:
                q_label = shlex.quote(label)
                q_pkgs = " ".join(shlex.quote(p) for p in pkg_list)
                lines.append(f"    install_sys_pkg {q_label} {q_pkgs}")
            lines.append("    ;;")
        lines.append("esac")
        lines.append("")

    # Flatpak setup & installations
    if flatpak_apps:
        lines.extend(
            [
                "# --- Flatpak Applications (Universal across distros) ---",
                "if ! command -v flatpak >/dev/null 2>&1; then",
                '  info "Flatpak not found — installing Flatpak..."',
                '  install_sys_pkg "Flatpak" flatpak',
                "fi",
                "",
                'if command -v flatpak >/dev/null 2>&1 || [[ "$DRY_RUN" -eq 1 ]]; then',
                '  info "Ensuring Flathub repository is enabled..."',
                "  run_cmd flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo",
                "",
                "  install_flatpak() {",
                '    local label="$1"; local app_id="$2"',
                '    info "Installing ${label} via Flatpak (${app_id})..."',
                '    if run_cmd flatpak install -y flathub "$app_id"; then',
                '      ok "$label"',
                '      SUCCEEDED+=("$label")',
                "    else",
                '      err "$label (${app_id})"',
                '      FAILED+=("$label")',
                "    fi",
                "  }",
                "",
            ]
        )
        for label, fid in flatpak_apps:
            lines.append(f"  install_flatpak {shlex.quote(label)} {shlex.quote(fid)}")
        lines.append("fi")
        lines.append("")

    # VS Code Extensions (strictly array-invoked, zero unquoted word splitting)
    if vscode_exts:
        lines.extend(
            [
                "# --- VS Code Extensions ---",
                "CODE_CMD=()",
                "if command -v code >/dev/null 2>&1; then",
                '  CODE_CMD=(code)',
                "elif command -v flatpak >/dev/null 2>&1 && flatpak info com.visualstudio.code >/dev/null 2>&1; then",
                '  CODE_CMD=(flatpak run com.visualstudio.code)',
                "fi",
                "",
                'if [[ "${#CODE_CMD[@]}" -gt 0 || "$DRY_RUN" -eq 1 ]]; then',
                '  info "Installing VS Code extensions..."',
                "  install_vscode_ext() {",
                '    local ext_id="$1"',
                '    if [[ "$DRY_RUN" -eq 1 ]]; then',
                '      printf "  ${YELLOW}[dry-run]${RESET} code --install-extension %s\\n" "$ext_id"',
                "      return 0",
                "    fi",
                '    if "${CODE_CMD[@]}" --install-extension "$ext_id" --force >/dev/null 2>&1; then',
                '      ok "VS Code ext: ${ext_id}"',
                "    else",
                '      warn "Could not install VS Code ext: ${ext_id}"',
                "    fi",
                "  }",
                "",
            ]
        )
        for ext in vscode_exts:
            lines.append(f"  install_vscode_ext {shlex.quote(ext)}")
        lines.extend(
            [
                "else",
                '  warn "VS Code CLI not found yet — re-run extension installs once VS Code is installed."',
                "fi",
                "",
            ]
        )

    # npm global packages
    if npm_globals:
        lines.extend(
            [
                "# --- Global npm CLI Tools ---",
                'if command -v npm >/dev/null 2>&1 || [[ "$DRY_RUN" -eq 1 ]]; then',
                '  info "Installing global npm packages..."',
            ]
        )
        for pkg in npm_globals:
            q_pkg = shlex.quote(pkg)
            lines.append(
                f"  if run_cmd npm install -g -- {q_pkg}; then ok {shlex.quote('npm: ' + pkg)}; else warn {shlex.quote('npm failed: ' + pkg)}; fi"
            )
        lines.append("fi")
        lines.append("")

    # Optional Git Identity
    if git_config:
        lines.append("# --- Git Global Identity ---")
        lines.append('if command -v git >/dev/null 2>&1 || [[ "$DRY_RUN" -eq 1 ]]; then')
        if git_config.get("user_name"):
            lines.append(f"  run_cmd git config --global -- user.name {shlex.quote(git_config['user_name'])}")
        if git_config.get("user_email"):
            lines.append(f"  run_cmd git config --global -- user.email {shlex.quote(git_config['user_email'])}")
        lines.append('  ok "Configured Git global identity"')
        lines.append("fi")
        lines.append("")

    # Manual / Web Apps & Distro-Fallback Official Downloads summary
    if manual_or_web or pm_fallback_urls:
        lines.append("# --- Web Apps & Official Direct Downloads ---")
        lines.append('printf "\\n${BOLD}${CYAN}Web Apps & Official Downloads to open in your browser:${RESET}\\n"')
        for name, kind, url in manual_or_web:
            tag = "Web App" if kind == "web" else "Official Linux Download"
            lines.append(f"printf '  - [%s] %s -> %s\\n' {shlex.quote(tag)} {shlex.quote(name)} {shlex.quote(url)}")
        for name, covered_pms, url in pm_fallback_urls:
            covered_pat = "|".join(covered_pms)
            lines.append('case "$PM" in')
            lines.append(f"  {covered_pat}) ;;")
            lines.append(
                f"  *) printf '  - [Official Linux Download] %s -> %s\\n' {shlex.quote(name)} {shlex.quote(url)} ;;"
            )
            lines.append("esac")
        lines.append("")

    # Final Summary
    lines.extend(
        [
            'printf "\\n${BOLD}${GREEN}======================================================\\n"',
            'printf "   TuxHarbor Setup Complete!\\n"',
            'printf "======================================================${RESET}\\n"',
            'printf "  Installed successfully: %d\\n" "${#SUCCEEDED[@]}"',
            'printf "  Failed / skipped:       %d\\n" "${#FAILED[@]}"',
            'if [[ "${#FAILED[@]}" -gt 0 ]]; then',
            '  printf "${YELLOW}  Items to review:${RESET}\\n"',
            '  for item in "${FAILED[@]}"; do printf "    - %s\\n" "$item"; done',
            "fi",
            'printf "\\nTip: Log out and back in if you installed Flatpak apps or Docker for the first time.\\n\\n"',
            "",
            "# =============================================================================",
            *[f"# {ln}" for ln in LEGAL_NOTICE_LINES],
            "# =============================================================================",
        ]
    )

    return "\n".join(lines) + "\n"
