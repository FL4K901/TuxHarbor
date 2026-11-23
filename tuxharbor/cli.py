"""Unified CLI & Native Desktop GUI entry point for TuxHarbor (Windows .exe & Linux binary)."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import sys
from pathlib import Path

from tuxharbor import __app_name__, __version__
from tuxharbor.catalog import CatalogEngine
from tuxharbor.delivery import save_migration_bundle
from tuxharbor.generators.html_report import generate_html_report
from tuxharbor.generators.linux_script import build_migration_plan, generate_linux_script
from tuxharbor.linux_runner import apply_plan_on_linux
from tuxharbor.models import sanitize_filename_prefix
from tuxharbor.scanners.dev_tools import scan_dev_environment
from tuxharbor.scanners.projects import scan_projects_folders
from tuxharbor.scanners.windows_apps import detect_system_hardware, scan_installed_apps


def _ensure_safe_stdio(cli_requested: bool) -> None:
    """Guard against sys.stdout/stderr being None in PyInstaller --windowed builds on Windows."""
    if sys.stdout is not None and sys.stderr is not None:
        return

    attached = False
    if cli_requested and platform.system() == "Windows":
        try:
            # Attach to existing parent terminal (PowerShell/cmd) without creating a new console window
            if ctypes.windll.kernel32.AttachConsole(-1):
                attached = True
        except Exception:
            attached = False

    if attached:
        try:
            if sys.stdout is None:
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            if sys.stderr is None:
                sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            return
        except OSError:
            pass

    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _run_cli_scan(args: argparse.Namespace) -> int:
    print(f"[{__app_name__} v{__version__}] Scanning system...")
    apps = scan_installed_apps(include_winget=not args.no_winget, demo_mode=args.demo)
    dev_env = scan_dev_environment(demo_mode=args.demo)
    projects = scan_projects_folders(args.projects or [], demo_mode=args.demo) if (args.projects or args.demo) else []

    runtime_ids = [r["catalog_id"] for r in dev_env.runtimes if r.get("catalog_id")]
    if dev_env.vscode_installed:
        runtime_ids.append("vscode")
    for p in projects:
        runtime_ids.extend(p.get("recommended_runtimes", []))

    catalog = CatalogEngine()
    hw_profile = detect_system_hardware(demo_mode=args.demo)
    analysis = catalog.analyze_apps(apps, detected_runtime_ids=runtime_ids, hardware_profile=hw_profile)
    analysis["dev_env"] = dev_env.to_dict()
    analysis["projects"] = projects
    analysis["target_distro"] = args.distro
    analysis["prefer_flatpak"] = not args.no_flatpak

    safe_prefix = sanitize_filename_prefix(args.name, default="tuxharbor-migration")
    plan = build_migration_plan(analysis)
    script = generate_linux_script(plan)
    report_html = generate_html_report(
        payload=analysis,
        plan=plan,
        script_filename=f"{safe_prefix}-install.sh",
    )
    saved = save_migration_bundle(
        destination_dir=args.out,
        filename_prefix=safe_prefix,
        report_html=report_html,
        linux_script=script,
        plan=plan,
        create_zip=not args.no_zip,
    )

    c = analysis["counts"]
    print(f"Linux Readiness Score: {analysis['readiness_score']}%")
    print(
        f"Matched Apps: {c['total_matched']} (Native: {c['native']}, Alternatives: {c['alternative']}, "
        f"Compat: {c['compat']}, Attention: {c['attention']})"
    )
    print(
        f"Hardware & Drivers: {c.get('hardware_drivers', 0)} | PC Games: {c.get('games', 0)} | "
        f"OS Built-ins excluded: {c.get('os_builtins', 0)} | Other / Niche: {c.get('unmatched', 0)}"
    )
    print("\nSaved files:")
    for f in saved["files"]:
        print(f"  - {f}")
    print("\nREMINDER: Back up your projects and personal files to an external drive or cloud storage before switching!")
    return 0


def _run_linux_apply(args: argparse.Namespace) -> int:
    plan_file = Path(args.linux_apply).expanduser().resolve()
    if not plan_file.is_file():
        print(f"Error: Plan file not found: {plan_file}", file=sys.stderr)
        return 1
    if plan_file.stat().st_size > 5 * 1024 * 1024:
        print("Error: Plan file exceeds the 5 MB safety limit.", file=sys.stderr)
        return 1
    try:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Error: Could not read or parse plan JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(plan, dict) or not isinstance(plan.get("apps", []), list):
        print("Error: Invalid TuxHarbor plan JSON structure.", file=sys.stderr)
        return 1
    res = apply_plan_on_linux(plan, dry_run=args.dry_run)
    for line in res["logs"]:
        print(line)
    print(f"\nDone! Succeeded: {len(res['succeeded'])}, Failed: {len(res['failed'])}")
    if res["manual"]:
        print("\nWeb apps / Official downloads:")
        for m in res["manual"]:
            print(f"  - [{m['kind']}] {m['name']}: {m['url']}")
    return 0 if not res["failed"] else 2


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    cli_flags = {"--cli-scan", "--linux-apply", "--version", "-h", "--help"}
    _ensure_safe_stdio(cli_requested=any(tok in cli_flags for tok in raw_argv))

    parser = argparse.ArgumentParser(
        prog="tuxharbor",
        description="TuxHarbor — Open-source Windows-to-Linux migration analyzer, alternative finder & auto-installer.",
    )
    parser.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run with realistic demo Windows PC data (great for previewing on any OS).",
    )

    # Headless CLI scan mode
    parser.add_argument("--cli-scan", action="store_true", help="Run headless scan and export bundle without opening the GUI.")
    parser.add_argument("--out", default="./tuxharbor-export", help="Output directory for --cli-scan.")
    parser.add_argument("--name", default="tuxharbor-migration", help="Custom filename prefix for exported files.")
    parser.add_argument("--projects", nargs="*", help="Project directories to scan for Linux compatibility & Git backup risks.")
    parser.add_argument(
        "--distro",
        default="auto",
        choices=["auto", "apt", "dnf", "pacman", "zypper"],
        help="Target Linux package manager.",
    )
    parser.add_argument("--no-winget", action="store_true", help="Skip winget query during Windows scan.")
    parser.add_argument("--no-flatpak", action="store_true", help="Prefer native distro packages over Flatpak.")
    parser.add_argument("--no-zip", action="store_true", help="Skip creating bundle .zip archive.")

    # Headless Linux apply mode
    parser.add_argument("--linux-apply", metavar="PLAN_JSON", help="Apply a TuxHarbor *-plan.json directly on Linux.")
    parser.add_argument("--dry-run", action="store_true", help="Preview commands without installing (for --linux-apply).")

    args = parser.parse_args(raw_argv)

    if args.linux_apply:
        return _run_linux_apply(args)
    if args.cli_scan:
        return _run_cli_scan(args)

    # Launch native desktop GUI (lazy import keeps --cli-scan / --linux-apply fast on headless Linux!)
    from tuxharbor.gui import launch_gui

    return launch_gui(demo_mode=args.demo)


if __name__ == "__main__":
    raise SystemExit(main())
