"""Comprehensive unit, security, English-only, architecture, CLI, and GUI tests for TuxHarbor."""

from __future__ import annotations

import ast
import base64
import builtins
import contextlib
import importlib
import io
import json
import re
import shutil
import smtplib
import ssl
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tuxharbor import LEGAL_NOTICE_LINES
from tuxharbor.catalog import CatalogEngine
from tuxharbor.cli import main as cli_main
from tuxharbor.delivery import (
    _sanitize_error_without_secret,
    build_webmail_draft_urls,
    open_saved_path,
    save_migration_bundle,
    send_migration_email_smtp,
)
from tuxharbor.generators.html_report import generate_html_report
from tuxharbor.generators.linux_script import build_migration_plan, generate_linux_script
from tuxharbor.linux_runner import apply_plan_on_linux, inspect_plan_on_linux
from tuxharbor.models import (
    InstalledApp,
    contains_control_or_crlf,
    is_safe_email,
    is_safe_external_link,
    is_safe_flatpak_id,
    is_safe_hostname,
    is_safe_https_url,
    is_safe_https_url_for_hosts,
    is_safe_npm_package,
    is_safe_package_name,
    is_safe_steam_app_id,
    is_safe_vscode_extension,
    sanitize_filename_prefix,
)
from tuxharbor.scanners.projects import scan_projects_folders
from tuxharbor.scanners.windows_apps import (
    MAX_ACF_BYTES,
    MAX_VDF_BYTES,
    _clean_version,
    _is_safe_local_dir,
    _parse_steam_appmanifest_acf,
    _parse_steam_library_folders_vdf,
    _parse_winget_output,
    _read_bounded_text,
    _scan_steam_games,
    get_demo_apps,
    normalize_app_key,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
HEBREW_RE = re.compile(r"[\u0590-\u05FF]")


class TestZeroServerArchitecture(unittest.TestCase):
    """Strict regression tests guaranteeing zero HTTP server, zero web UI, and zero open ports."""

    def test_server_py_and_web_dir_do_not_exist(self) -> None:
        self.assertFalse((REPO_ROOT / "tuxharbor" / "server.py").exists(), "tuxharbor/server.py must not exist")
        self.assertFalse((REPO_ROOT / "tuxharbor" / "web").exists(), "tuxharbor/web/ must not exist")
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("tuxharbor.server")

    def test_no_module_imports_http_server(self) -> None:
        py_files = [REPO_ROOT / "main.py", *(REPO_ROOT / "tuxharbor").rglob("*.py")]
        self.assertGreaterEqual(len(py_files), 10)
        for py_file in py_files:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotEqual(
                            alias.name,
                            "http.server",
                            f"{py_file.relative_to(REPO_ROOT)} must not import http.server",
                        )
                        self.assertFalse(
                            alias.name.startswith("http.server."),
                            f"{py_file.relative_to(REPO_ROOT)} must not import {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    self.assertNotEqual(
                        mod,
                        "http.server",
                        f"{py_file.relative_to(REPO_ROOT)} must not import from http.server",
                    )
                    self.assertFalse(
                        mod.startswith("http.server."),
                        f"{py_file.relative_to(REPO_ROOT)} must not import from {mod}",
                    )
        # Runtime guarantee: importing TuxHarbor modules must not pull in http.server
        self.assertNotIn("http.server", sys.modules)


class TestEnglishOnlyCompliance(unittest.TestCase):
    """Verify 100% international English across all source files, catalog, docs, and generated outputs."""

    def test_zero_hebrew_characters_in_sources_catalog_and_docs(self) -> None:
        targets = [
            REPO_ROOT / "tuxharbor" / "data" / "catalog.json",
            REPO_ROOT / "tuxharbor" / "generators" / "html_report.py",
            REPO_ROOT / "tuxharbor" / "generators" / "linux_script.py",
            REPO_ROOT / "tuxharbor" / "delivery.py",
            REPO_ROOT / "tuxharbor" / "gui.py",
            REPO_ROOT / "tuxharbor" / "catalog.py",
            REPO_ROOT / "tuxharbor" / "cli.py",
            REPO_ROOT / "tuxharbor" / "models.py",
            REPO_ROOT / "tuxharbor" / "linux_runner.py",
            REPO_ROOT / "tuxharbor" / "__init__.py",
            REPO_ROOT / "tuxharbor" / "scanners" / "projects.py",
            REPO_ROOT / "tuxharbor" / "scanners" / "windows_apps.py",
            REPO_ROOT / "tuxharbor" / "scanners" / "dev_tools.py",
            REPO_ROOT / "README.md",
            REPO_ROOT / "CONTRIBUTING.md",
            REPO_ROOT / "SECURITY.md",
            REPO_ROOT / "DISCLAIMER.md",
            REPO_ROOT / "PRIVACY.md",
            REPO_ROOT / "THIRD_PARTY_NOTICES.md",
        ]
        for path in targets:
            self.assertTrue(path.is_file(), f"Required file missing: {path.name}")
            content = path.read_text(encoding="utf-8")
            match = HEBREW_RE.search(content)
            self.assertIsNone(
                match,
                f"Found forbidden Hebrew Unicode character in {path.relative_to(REPO_ROOT)}: {match.group(0)!r}"
                if match
                else "",
            )

    def test_zero_hebrew_in_generated_html_and_bash_outputs(self) -> None:
        catalog = CatalogEngine()
        analysis = catalog.analyze_apps(get_demo_apps(), detected_runtime_ids=["git", "nodejs", "python"])
        analysis["projects"] = scan_projects_folders([], demo_mode=True)
        analysis["dev_env"] = {
            "vscode_extensions": ["ms-python.python", "dbaeumer.vscode-eslint"],
            "npm_globals": ["typescript", "@angular/cli"],
            "git_user_name": "Jane Developer",
            "git_user_email": "jane@example.com",
        }
        analysis["include_vscode_extensions"] = True
        analysis["include_npm_globals"] = True
        analysis["include_git_config"] = True

        plan = build_migration_plan(analysis)
        script = generate_linux_script(plan)
        html_out = generate_html_report(analysis, plan, script_filename="demo-install.sh")

        self.assertIsNone(HEBREW_RE.search(html_out), "Generated HTML report contains Hebrew characters")
        self.assertIsNone(HEBREW_RE.search(script), "Generated Bash script contains Hebrew characters")
        self.assertIsNone(HEBREW_RE.search(json.dumps(plan)), "Generated plan JSON contains Hebrew characters")

        self.assertIn('<html lang="en" dir="ltr">', html_out)
        self.assertNotIn("<script", html_out.lower())
        for line in LEGAL_NOTICE_LINES:
            self.assertIn(f"# {line}", script)
            self.assertIn(line.replace('"', "&quot;"), html_out)


class TestCatalogAndModels(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = CatalogEngine()

    def test_catalog_integrity_english_schema_and_package_safety(self) -> None:
        """Every catalog entry must use English-only keys and pass strict shell/URL validation."""
        self.assertGreaterEqual(len(self.catalog.entries), 100)
        forbidden_keys = {"summary_he", "tagline_he", "label_he", "summary_en", "tagline_en", "label_en", "he"}

        for cat_id, cat_meta in self.catalog.categories.items():
            self.assertTrue(cat_meta.get("label"), f"Missing label for category {cat_id}")
            self.assertTrue(forbidden_keys.isdisjoint(cat_meta.keys()), f"Legacy key in category {cat_id}")

        seen_ids: set[str] = set()
        for entry in self.catalog.entries:
            eid = entry["id"]
            self.assertNotIn(eid, seen_ids, f"Duplicate catalog id: {eid}")
            seen_ids.add(eid)
            self.assertIn(entry["status"], {"native", "alternative", "compat", "attention"})
            self.assertTrue(entry.get("summary"), f"Missing English summary in {eid}")
            self.assertTrue(forbidden_keys.isdisjoint(entry.keys()), f"Legacy key in {eid}")

            for pm, val in (entry.get("linux_packages") or {}).items():
                if pm == "official_url":
                    self.assertTrue(is_safe_https_url(val), f"Unsafe official_url in {eid}: {val}")
                elif pm == "flatpak":
                    self.assertTrue(is_safe_flatpak_id(val), f"Unsafe flatpak ID in {eid}: {val}")
                else:
                    for tok in str(val).split():
                        self.assertTrue(is_safe_package_name(tok), f"Unsafe package token '{tok}' in {eid}")

            for alt in entry.get("alternatives") or []:
                self.assertTrue(alt.get("tagline"), f"Missing tagline in alt {alt.get('id')} of {eid}")
                self.assertTrue(forbidden_keys.isdisjoint(alt.keys()), f"Legacy key in alt {alt.get('id')}")
                for pm, val in (alt.get("packages") or {}).items():
                    if pm == "official_url":
                        self.assertTrue(is_safe_https_url(val), f"Unsafe alt URL in {alt['id']}: {val}")
                    elif pm == "flatpak":
                        self.assertTrue(is_safe_flatpak_id(val), f"Unsafe alt flatpak ID in {alt['id']}: {val}")
                    else:
                        for tok in str(val).split():
                            self.assertTrue(is_safe_package_name(tok), f"Unsafe alt token '{tok}' in {alt['id']}")

        # Validate hardware_drivers rules schema & HTTPS URLs
        self.assertGreaterEqual(len(self.catalog.hardware_driver_rules), 10)
        seen_hw_ids: set[str] = set()
        for hw in self.catalog.hardware_driver_rules:
            hid = hw["id"]
            self.assertNotIn(hid, seen_hw_ids, f"Duplicate hardware rule id: {hid}")
            seen_hw_ids.add(hid)
            self.assertIn(hw["driver_status"], {"official_driver", "kernel_builtin", "oem_utility"})
            self.assertTrue(hw.get("name"), f"Missing name in hardware rule {hid}")
            self.assertTrue(hw.get("summary"), f"Missing summary in hardware rule {hid}")
            if hw.get("official_url"):
                self.assertTrue(is_safe_https_url(hw["official_url"]), f"Unsafe hardware URL in {hid}")

        # Validate known_games rules schema
        self.assertGreaterEqual(len(self.catalog.known_games), 10)
        seen_game_ids: set[str] = set()
        for gm in self.catalog.known_games:
            gid = gm["id"]
            self.assertNotIn(gid, seen_game_ids, f"Duplicate known_game id: {gid}")
            seen_game_ids.add(gid)
            self.assertIn(gm["status"], {"anticheat_blocked", "anticheat_caution", "check_protondb"})
            self.assertTrue(gm.get("match_patterns"), f"Missing match_patterns in known_game {gid}")
            self.assertTrue(gm.get("note"), f"Missing note in known_game {gid}")

        # Zero pipe-to-shell patterns anywhere in catalog.json
        raw_catalog_text = (REPO_ROOT / "tuxharbor" / "data" / "catalog.json").read_text(encoding="utf-8")
        self.assertNotRegex(raw_catalog_text, r"curl\s+.*\|\s*(?:ba)?sh")

    def test_matching_and_exclusions(self) -> None:
        apps = [
            InstalledApp("Google Chrome", "131.0"),
            InstalledApp("Notepad++ (64-bit x64)", "8.7"),
            InstalledApp("Microsoft Edge WebView2 Runtime", "130.0"),  # Must be excluded from Edge!
            InstalledApp("Riot Vanguard", "1.0"),
            InstalledApp("TotallyUnknownAppXYZ", "1.0"),
        ]
        res = self.catalog.analyze_apps(apps)
        matched_ids = {m["id"] for m in res["matched"]}
        self.assertIn("google-chrome", matched_ids)
        self.assertIn("notepad-plus-plus", matched_ids)
        self.assertIn("riot-anticheat", matched_ids)
        self.assertNotIn("microsoft-edge", matched_ids)
        self.assertEqual(len(res["os_builtins"]), 1)
        self.assertEqual(res["os_builtins"][0]["name"], "Microsoft Edge WebView2 Runtime")
        self.assertEqual(len(res["unmatched"]), 1)
        self.assertEqual(res["unmatched"][0]["name"], "TotallyUnknownAppXYZ")

    def test_filename_sanitization_blocks_traversal_and_windows_reserved_names(self) -> None:
        self.assertEqual(sanitize_filename_prefix("../../etc/passwd"), "etcpasswd")
        self.assertEqual(sanitize_filename_prefix("..\\..\\evil"), "evil")
        self.assertEqual(sanitize_filename_prefix("my pc 2026!@#"), "my-pc-2026")
        self.assertEqual(sanitize_filename_prefix("   "), "tuxharbor-migration")
        # Windows reserved device names (exact, lowercase, and dotted stems)
        for reserved in ("CON", "con", "NUL", "nul", "PRN", "AUX", "COM1", "com9", "LPT1", "LPT9", "CON.txt", "NUL.kit"):
            self.assertEqual(
                sanitize_filename_prefix(reserved),
                "tuxharbor-migration",
                f"Windows reserved filename '{reserved}' was not blocked!",
            )

    def test_strict_validators_block_newline_bypass_and_injections(self) -> None:
        # Native package names
        self.assertTrue(is_safe_package_name("python3-pip"))
        self.assertTrue(is_safe_package_name("g++"))
        self.assertFalse(is_safe_package_name("vlc\n"))
        self.assertFalse(is_safe_package_name("vlc\r\n"))
        self.assertFalse(is_safe_package_name("/tmp/evil.deb"))
        self.assertFalse(is_safe_package_name("https://evil.example/pkg.rpm"))
        self.assertFalse(is_safe_package_name("vlc; rm -rf /"))
        self.assertFalse(is_safe_package_name("$(whoami)"))
        self.assertFalse(is_safe_package_name("-rf"))
        self.assertFalse(is_safe_package_name("pkg..evil"))

        # Flatpak reverse-DNS IDs
        self.assertTrue(is_safe_flatpak_id("com.visualstudio.code"))
        self.assertTrue(is_safe_flatpak_id("org.mozilla.firefox"))
        self.assertFalse(is_safe_flatpak_id("org.mozilla.firefox\n"))
        self.assertFalse(is_safe_flatpak_id("org.evil.App; rm -rf /"))
        self.assertFalse(is_safe_flatpak_id("singleword"))
        self.assertFalse(is_safe_flatpak_id("org..evil.App"))

        # npm globals
        self.assertTrue(is_safe_npm_package("typescript"))
        self.assertTrue(is_safe_npm_package("@angular/cli"))
        self.assertFalse(is_safe_npm_package("typescript\n"))
        self.assertFalse(is_safe_npm_package("pkg;whoami"))
        self.assertFalse(is_safe_npm_package("../evil"))
        self.assertFalse(is_safe_npm_package("--global-flag"))

        # VS Code extensions
        self.assertTrue(is_safe_vscode_extension("ms-python.python"))
        self.assertFalse(is_safe_vscode_extension("--evil.ext"))
        self.assertFalse(is_safe_vscode_extension("ms-python.python\n"))
        self.assertFalse(is_safe_vscode_extension("ms-python.python; echo pwn"))

        # Email, hostname, HTTPS/external links, control chars
        self.assertTrue(is_safe_email("user@example.com"))
        self.assertFalse(is_safe_email("user@example.com\r\nBcc:evil@x.com"))
        self.assertFalse(is_safe_email("user@example.com\n"))
        self.assertFalse(is_safe_email("bad..dot@example.com"))
        self.assertTrue(is_safe_hostname("smtp.gmail.com"))
        self.assertTrue(is_safe_hostname("127.0.0.1"))
        self.assertFalse(is_safe_hostname("smtp.gmail.com\r\n"))
        self.assertFalse(is_safe_hostname("-badhost.com"))
        self.assertTrue(is_safe_https_url("https://flathub.org/apps"))
        self.assertFalse(is_safe_https_url("http://flathub.org/apps"))
        self.assertFalse(is_safe_https_url("javascript:alert(1)"))
        self.assertFalse(is_safe_https_url("file:///etc/passwd"))
        self.assertFalse(is_safe_https_url("https://user:pass@example.com/"))
        self.assertTrue(is_safe_external_link("mailto:user@example.com?subject=Test"))
        self.assertFalse(is_safe_external_link("javascript:alert(1)"))
        self.assertTrue(contains_control_or_crlf("abc\r\n"))
        self.assertTrue(contains_control_or_crlf("abc\x00"))
        self.assertFalse(contains_control_or_crlf("clean-value"))

        # Steam AppID & host-pinned HTTPS URLs
        self.assertTrue(is_safe_steam_app_id("1245620"))
        self.assertFalse(is_safe_steam_app_id("1245620\n"))
        self.assertFalse(is_safe_steam_app_id("abc"))
        self.assertFalse(is_safe_steam_app_id("12345678901"))
        self.assertTrue(is_safe_https_url_for_hosts("https://www.protondb.com/app/1245620", ("www.protondb.com", "protondb.com")))
        self.assertFalse(is_safe_https_url_for_hosts("https://evil-protondb.com/app/1245620", ("www.protondb.com", "protondb.com")))
        self.assertFalse(is_safe_https_url_for_hosts("http://www.protondb.com/app/1245620", ("www.protondb.com", "protondb.com")))
        self.assertTrue(is_safe_https_url_for_hosts("https://areweanticheatyet.com/?search=ELDEN+RING", ("areweanticheatyet.com",)))
        self.assertFalse(is_safe_https_url_for_hosts("https://phish.example/?q=areweanticheatyet.com", ("areweanticheatyet.com",)))


class TestSmartClassificationAndScanners(unittest.TestCase):
    """Comprehensive tests for 5-bucket smart classification, winget parser, and Steam scanner."""

    def setUp(self) -> None:
        self.catalog = CatalogEngine()

    def test_language_independent_os_builtin_filtering_hebrew_and_runtimes(self) -> None:
        """Hebrew & multi-locale Windows Store names paired with MSIX/family IDs route to os_builtins, NOT unmatched."""
        apps = [
            # Localized Hebrew Windows Store apps (using ASCII Unicode escapes to keep test source pure ASCII)
            InstalledApp(
                "\u05de\u05d7\u05e9\u05d1\u05d5\u05df Windows",  # Hebrew Calculator
                "11.2405.2.0",
                "Microsoft Corporation",
                "winget",
                package_id="MSIX\\Microsoft.WindowsCalculator_11.2405.2.0_x64__8wekyb3d8bbwe",
            ),
            InstalledApp(
                "\u05e6\u05d9\u05d9\u05e8",  # Hebrew Paint
                "11.2409.30.0",
                "Microsoft Corporation",
                "winget",
                package_id="MSIX\\Microsoft.Paint_11.2409.30.0_x64__8wekyb3d8bbwe",
            ),
            InstalledApp(
                "\u05db\u05dc\u05d9 \u05d4\u05d7\u05d9\u05ea\u05d5\u05da",  # Hebrew Snipping Tool
                "11.2408.15.0",
                "Microsoft Corporation",
                "winget",
                package_id="MSIX\\Microsoft.ScreenSketch_11.2408.15.0_x64__8wekyb3d8bbwe",
            ),
            InstalledApp(
                "\u05d4\u05e8\u05d7\u05d1\u05d5\u05ea \u05d5\u05d9\u05d3\u05d0\u05d5 HEVC",  # Hebrew HEVC codec
                "2.1.1802.0",
                "Microsoft Corporation",
                "winget",
                package_id="MSIX\\Microsoft.HEVCVideoExtension_2.1.1802.0_x64__8wekyb3d8bbwe",
            ),
            InstalledApp(
                "\u05e2\u05e8\u05db\u05ea \u05d7\u05d5\u05d5\u05d9\u05d4 \u05de\u05e7\u05d5\u05de\u05d9\u05ea \u05e2\u05d1\u05e8\u05d9\u05ea",  # Hebrew LXP
                "26100.1.0.0",
                "Microsoft Corporation",
                "winget",
                package_id="MSIX\\Microsoft.LanguageExperiencePackhe-IL_26100.1.0.0_neutral__8wekyb3d8bbwe",
            ),
            # Arbitrary non-English Store app identified only by MicrosoftWindows family suffix
            InstalledApp(
                "Windows-Web-Erlebnispaket",
                "524.20501.0.0",
                "Microsoft Corporation",
                "winget",
                package_id="MSIX\\MicrosoftWindows.Client.WebExperience_524.20501.0.0_x64__cw5n1h2txyewy",
            ),
            # System runtimes & Registry-only OS helpers
            InstalledApp(
                "Microsoft Windows Desktop Runtime - 8.0.14 (x64)",
                "8.0.14",
                "Microsoft Corporation",
                "registry",
                package_id="Microsoft.DotNet.DesktopRuntime.8",
            ),
            InstalledApp(
                "Microsoft.WindowsAppRuntime.1.5",
                "5001.214.1843.0",
                "Microsoft Corporation",
                "winget",
                package_id="MSIX\\Microsoft.WindowsAppRuntime.1.5_5001.214.1843.0_x64__8wekyb3d8bbwe",
            ),
            InstalledApp(
                "Microsoft Filter Pack 2.0",
                "14.0.7015.1000",
                "Microsoft Corporation",
                "registry",
                package_id="{95140000-2000-0409-1000-0000000FF1CE}",
            ),
            InstalledApp(
                "OfficePushNotificationsUtility",
                "16.0.1",
                "Microsoft Corporation",
                "registry",
                package_id="Microsoft.OfficePushNotificationUtility",
            ),
            # Real user apps that must NOT be swallowed by OS built-ins
            InstalledApp(
                "Outlook (localized)",
                "1.2025.1",
                "Microsoft Corporation",
                "winget",
                winget_id="Microsoft.Outlook",
                package_id="Microsoft.Outlook",
            ),
            InstalledApp("OneDrive", "24.221", "Microsoft Corporation", "registry"),
            InstalledApp("\u03bcTorrent", "3.6.0", "BitTorrent Inc.", "registry"),  # Greek lowercase mu
            InstalledApp("Windows Subsystem for Linux", "2.3.26", "Microsoft Corporation", "registry"),
            InstalledApp("GenuineNicheToolXYZ", "1.0", "SmallVendor", "registry"),
        ]

        res = self.catalog.analyze_apps(apps)
        builtin_names = {b["name"] for b in res["os_builtins"]}
        matched_ids = {m["id"]: m for m in res["matched"]}
        unmatched_names = [u["name"] for u in res["unmatched"]]

        # All 10 localized OS built-ins & runtimes must land in os_builtins
        self.assertEqual(len(res["os_builtins"]), 10)
        self.assertIn("\u05de\u05d7\u05e9\u05d1\u05d5\u05df Windows", builtin_names)
        self.assertIn("\u05e6\u05d9\u05d9\u05e8", builtin_names)
        self.assertIn("\u05db\u05dc\u05d9 \u05d4\u05d7\u05d9\u05ea\u05d5\u05da", builtin_names)
        self.assertIn("Microsoft Filter Pack 2.0", builtin_names)

        # Real user apps match cleanly
        self.assertIn("microsoft-outlook", matched_ids)
        self.assertIn("cloud-sync", matched_ids)
        self.assertIn("utorrent", matched_ids)
        self.assertIn("wsl", matched_ids)
        self.assertTrue(matched_ids["wsl"]["no_install_needed"])
        self.assertFalse(matched_ids["wsl"]["selected"])

        # Only GenuineNicheToolXYZ remains unmatched
        self.assertEqual(unmatched_names, ["GenuineNicheToolXYZ"])

        # WSL must NEVER leak into plan.json or install.sh
        plan = build_migration_plan(res)
        planned_sources = {a["source_windows_app"] for a in plan["apps"]}
        self.assertNotIn("Windows Subsystem for Linux (WSL)", planned_sources)
        script = generate_linux_script(plan)
        self.assertNotIn("Windows Subsystem for Linux", script)

    def test_hardware_drivers_nvidia_intel_amd_consolidation_and_no_intellij_collision(self) -> None:
        """NVIDIA folds into ONE official Linux driver card; Intel & AMD -> Built into Linux Kernel; IntelliJ unaffected."""
        apps = [
            # Localized Hebrew NVIDIA Graphics Driver + NVIDIA App + Control Panel + PhysX + HD Audio
            InstalledApp(
                "\u05de\u05e0\u05d4\u05dc \u05d4\u05ea\u05e7\u05df \u05d2\u05e8\u05e4\u05d9 \u05e9\u05dc NVIDIA 566.14",
                "566.14",
                "NVIDIA Corporation",
                "registry",
                package_id="{B2FE1952-0186-46C3-BAEC-A80AA35AC5B8}_Display.Driver",
            ),
            InstalledApp("NVIDIA App", "11.0.1.189", "NVIDIA Corporation", "winget", winget_id="Nvidia.NvidiaApp", package_id="Nvidia.NvidiaApp"),
            InstalledApp("NVIDIA Control Panel", "8.1.966.0", "NVIDIA Corp.", "winget", package_id="MSIX\\NVIDIACorp.NVIDIAControlPanel_8.1.966.0_x64__56jybvy8sckqj"),
            InstalledApp("NVIDIA PhysX System Software 9.23.1019", "9.23.1019", "NVIDIA Corporation", "registry"),
            InstalledApp("NVIDIA HD Audio Driver 1.4.2.6", "1.4.2.6", "NVIDIA Corporation", "registry"),
            # Intel suite
            InstalledApp("Intel Graphics Software", "26.1.0", "Intel Corporation", "registry", package_id="Intel.GraphicsSoftware"),
            InstalledApp("Intel Driver & Support Assistant", "24.5.39.4", "Intel", "registry"),
            InstalledApp("Intel(R) Computing Improvement Program", "2.4.1", "Intel Corporation", "registry"),
            InstalledApp("oneAPI Level Zero", "1.17.44", "Intel Corporation", "registry"),
            # AMD suite
            InstalledApp("AMD Software: Adrenalin Edition", "24.10.1", "Advanced Micro Devices, Inc.", "registry"),
            InstalledApp("AMD Chipset Software", "6.07.22.037", "Advanced Micro Devices, Inc.", "registry"),
            # IntelliJ must NOT collide with Intel driver rule!
            InstalledApp("IntelliJ IDEA Community Edition 2024.3", "2024.3", "JetBrains s.r.o.", "registry"),
            # Generic OEM peripheral driver
            InstalledApp("GK6XPlus USB Keyboard Driver", "6.0.0.50", "Shenzhen Vendor", "registry"),
        ]

        res = self.catalog.analyze_apps(apps)
        hw_by_id = {h["id"]: h for h in res["hardware_drivers"]}
        matched_ids = {m["id"] for m in res["matched"]}

        # NVIDIA folds cleanly into ONE official_driver entry (never alternative or unmatched!)
        self.assertIn("hw-nvidia", hw_by_id)
        nv = hw_by_id["hw-nvidia"]
        self.assertEqual(nv["driver_status"], "official_driver")
        self.assertEqual(nv["driver_status_label"], "Official Linux Driver")
        self.assertEqual(nv["component_count"], 5)
        self.assertTrue(is_safe_https_url(nv["official_url"]))

        # Intel & AMD -> Built into Linux Kernel
        self.assertIn("hw-intel", hw_by_id)
        self.assertEqual(hw_by_id["hw-intel"]["driver_status"], "kernel_builtin")
        self.assertEqual(hw_by_id["hw-intel"]["driver_status_label"], "Built into Linux Kernel")
        self.assertEqual(hw_by_id["hw-intel"]["component_count"], 4)

        self.assertIn("hw-amd", hw_by_id)
        self.assertEqual(hw_by_id["hw-amd"]["driver_status"], "kernel_builtin")
        self.assertEqual(hw_by_id["hw-amd"]["driver_status_label"], "Built into Linux Kernel")
        self.assertEqual(hw_by_id["hw-amd"]["component_count"], 2)

        # Generic OEM keyboard driver caught in hardware_drivers
        self.assertIn("hw-keyboard-oem", hw_by_id)

        # IntelliJ matched as IDE, zero unmatched, and zero NVIDIA/Intel/AMD leakage into install.sh
        self.assertIn("intellij-idea", matched_ids)
        self.assertEqual(res["unmatched"], [])
        self.assertEqual(len(res["matched"]), 1)

        plan = build_migration_plan(res)
        script = generate_linux_script(plan)
        self.assertNotIn("NVIDIA", script)
        self.assertNotIn("Intel Graphics", script)
        self.assertNotIn("AMD Radeon", script)

    def test_game_detection_steam_riot_rockstar_and_launchers_separation(self) -> None:
        """Detected PC games route to games bucket with ProtonDB & AreWeAntiCheatYet links (NOT Flathub)."""
        apps = [
            InstalledApp(
                "ELDEN RING",
                "",
                "FromSoftware",
                "steam",
                package_id="Steam App 1245620",
            ),
            InstalledApp(
                "Teamfight Tactics",
                "Game",
                "Riot Games, Inc",
                "registry",
                package_id="Riot Game teamfighttactics.live",
                uninstall_string='"C:\\Riot Games\\Riot Client\\RiotClientServices.exe" --uninstall-product=teamfighttactics',
            ),
            InstalledApp(
                "Grand Theft Auto V Enhanced",
                "1.0.812.8",
                "Rockstar Games",
                "registry",
                install_location=r"C:\Program Files\Rockstar Games\Grand Theft Auto V Enhanced",
            ),
            InstalledApp(
                "IndieQuest Demo",
                "Game",
                "Indie Studio",
                "registry",
            ),
            # Launchers & anti-cheat stay in matched (category='gaming'), NOT games
            InstalledApp("Steam", "2.10.91", "Valve Corporation", "registry", winget_id="Valve.Steam"),
            InstalledApp("Rockstar Games Launcher", "1.0.95", "Rockstar Games", "registry"),
            InstalledApp("Riot Vanguard", "1.0", "Riot Games", "registry"),
        ]

        res = self.catalog.analyze_apps(apps)
        games_by_name = {g["name"]: g for g in res["games"]}
        matched_ids = {m["id"] for m in res["matched"]}

        self.assertEqual(set(games_by_name.keys()), {"ELDEN RING", "Teamfight Tactics", "Grand Theft Auto V Enhanced", "IndieQuest Demo"})
        self.assertEqual(res["unmatched"], [])

        # ELDEN RING -> direct Steam AppID ProtonDB link + AreWeAntiCheatYet link
        er = games_by_name["ELDEN RING"]
        self.assertEqual(er["platform"], "Steam")
        self.assertEqual(er["steam_app_id"], "1245620")
        self.assertEqual(er["protondb_url"], "https://www.protondb.com/app/1245620")
        self.assertEqual(er["anticheat_url"], "https://areweanticheatyet.com/?search=ELDEN+RING")

        # Teamfight Tactics -> Blocked by Anti-Cheat, 'Game' version stripped
        tft = games_by_name["Teamfight Tactics"]
        self.assertEqual(tft["status"], "anticheat_blocked")
        self.assertEqual(tft["version"], "")
        self.assertTrue(tft["protondb_url"].startswith("https://www.protondb.com/search?q="))
        self.assertTrue(tft["anticheat_url"].startswith("https://areweanticheatyet.com/?search="))

        # GTA V Enhanced -> Online Anti-Cheat Caution
        gta = games_by_name["Grand Theft Auto V Enhanced"]
        self.assertEqual(gta["status"], "anticheat_caution")
        self.assertEqual(gta["platform"], "Rockstar Games")

        # Launchers stay in matched
        self.assertIn("steam", matched_ids)
        self.assertIn("rockstar-launcher", matched_ids)
        self.assertIn("riot-anticheat", matched_ids)

        # Verify InstalledApp.to_dict() NEVER exposes internal uninstall_string
        for app in apps:
            self.assertNotIn("uninstall_string", app.to_dict())

    def test_universal_hardware_snapdragon_arm64_and_oem_vendors(self) -> None:
        """Qualcomm Snapdragon/ARM64, AMD, MediaTek, Broadcom, Lenovo/Dell/HP/Surface, tablets, printers & generic drivers classify cleanly."""
        apps = [
            InstalledApp("Qualcomm Control Panel", "1.0", "Qualcomm Technologies"),
            InstalledApp("MediaTek Wi-Fi 6E MT7922 Driver", "3.3", "MediaTek Inc."),
            InstalledApp("Broadcom 802.11 Network Adapter", "7.35", "Broadcom"),
            InstalledApp("Lenovo Vantage", "10.24", "Lenovo"),
            InstalledApp("Dell SupportAssist", "4.0", "Dell Inc."),
            InstalledApp("HP Smart", "150.1", "HP Inc."),
            InstalledApp("Microsoft Surface App", "61.0", "Microsoft Corporation"),
            InstalledApp("Wacom Tablet", "6.4", "Wacom Technology"),
            InstalledApp("Samsung Magician", "8.1", "Samsung Electronics"),
            InstalledApp("Canon IJ Printer Assistant", "1.0", "Canon Inc."),
            InstalledApp("Acme Corp Fingerprint Driver", "2.0", "Acme Hardware"),
        ]
        arm_profile = {
            "arch": "ARM64",
            "is_arm64": True,
            "cpu": "Snapdragon(R) X Elite - X1E80100",
            "gpus": ["Qualcomm(R) Adreno(TM) X1-85 GPU"],
            "manufacturer": "Lenovo",
            "model": "ThinkPad T14s Gen 6",
        }
        res = self.catalog.analyze_apps(apps, hardware_profile=arm_profile)
        hw_ids = {h["id"] for h in res["hardware_drivers"]}
        for expected in (
            "hw-qualcomm-snapdragon",
            "hw-mediatek-wifi",
            "hw-broadcom",
            "hw-lenovo",
            "hw-dell",
            "hw-hp",
            "hw-surface",
            "hw-tablets",
            "hw-storage-ssd",
            "hw-printers",
            "hw-keyboard-oem",
        ):
            self.assertIn(expected, hw_ids, f"Missing hardware group: {expected}")
        self.assertEqual(res["unmatched"], [])

        # Report renders hardware profile bar + ARM64 advisory
        plan = build_migration_plan(res)
        html_out = generate_html_report(res, plan, script_filename="arm-install.sh")
        self.assertIn("ARM64 / Windows-on-ARM Detected", html_out)
        self.assertIn("Snapdragon(R) X Elite", html_out)
        self.assertIn("Live USB", html_out)
        # Ensure USER_GUIDE.md exists and is 100% English
        guide_text = (Path(__file__).resolve().parent.parent / "USER_GUIDE.md").read_text(encoding="utf-8")
        self.assertNotRegex(guide_text, r"[\u0590-\u05FF]")

    def test_winget_parser_preserves_msix_arp_ids_and_rejects_garbled_versions(self) -> None:
        """Winget table parser handles spaces in ARP/MSIX IDs, >/< prefixes, BiDi, CJK, and spinner lines."""
        sample_stdout = "\n".join(
            [
                "   - \r   \\ \r   | \rName                                    Id                                                                    Version             Available     Source",
                "------------------------------------------------------------------------------------------------------------------------------------------------------------",
                "ELDEN RING                              ARP\\Machine\\X86\\ELDEN RING_is1                                        Unknown",
                "Cheat Engine 7.6                        ARP\\Machine\\X64\\Cheat Engine_is1                                      >                   7.6",
                "Teamfight Tactics                       ARP\\User\\X64\\Riot Game teamfighttactics.live                          Game",
                "Google Chrome                           Google.Chrome                                                         131.0.6778.86       132.0.0.0     winget",
                "Deno                                    DenoLand.Deno                                                         < 2.1.4             2.1.5         winget",
                "\u200f\u05de\u05d7\u05e9\u05d1\u05d5\u05df Windows\u200e                        MSIX\\Microsoft.WindowsCalculator_11.2405.2.0_x64__8wekyb3d8bbwe       11.2405.2.0",
                "Visual Studio Code                      Microsoft.VisualStudioCode                                            > 1.95.3                          winget",
                "2 upgrades available.",
            ]
        )

        parsed = _parse_winget_output(sample_stdout)
        by_key = {normalize_app_key(a.name): a for a in parsed}

        # Trailing summary line must be skipped
        self.assertNotIn("2 upgrades available.", by_key)

        # Bogus versions RING_is1, Engine_is1, >, Unknown must NEVER appear as versions
        er = by_key["elden ring"]
        self.assertEqual(er.package_id, r"ARP\Machine\X86\ELDEN RING_is1")
        self.assertEqual(er.winget_id, "")
        self.assertEqual(er.version, "")

        ce = by_key["cheat engine 7.6"]
        self.assertEqual(ce.package_id, r"ARP\Machine\X64\Cheat Engine_is1")
        self.assertEqual(ce.winget_id, "")
        self.assertEqual(ce.version, "")

        tft = by_key["teamfight tactics"]
        self.assertEqual(tft.package_id, r"ARP\User\X64\Riot Game teamfighttactics.live")
        self.assertEqual(tft.winget_id, "")

        # Real winget IDs populate both winget_id and package_id; < / > prefixes stripped cleanly
        chrome = by_key["google chrome"]
        self.assertEqual(chrome.winget_id, "Google.Chrome")
        self.assertEqual(chrome.package_id, "Google.Chrome")
        self.assertEqual(chrome.version, "131.0.6778.86")

        deno = by_key["deno"]
        self.assertEqual(deno.winget_id, "DenoLand.Deno")
        self.assertEqual(deno.version, "2.1.4")

        vscode = by_key["visual studio code"]
        self.assertEqual(vscode.version, "1.95.3")

        # BiDi-wrapped localized Store app preserves full MSIX package_id
        calc = by_key[normalize_app_key("\u05de\u05d7\u05e9\u05d1\u05d5\u05df Windows")]
        self.assertEqual(calc.package_id, r"MSIX\Microsoft.WindowsCalculator_11.2405.2.0_x64__8wekyb3d8bbwe")
        self.assertEqual(calc.winget_id, "")
        self.assertEqual(calc.version, "11.2405.2.0")

        # Direct _clean_version sanity checks
        for bogus in ("RING_is1", "Engine_is1", ">", "<", "<=", "Unknown", "ARP\\Machine\\X86\\Foo", "MSIX\\Bar"):
            self.assertEqual(_clean_version(bogus), "", f"_clean_version failed to reject {bogus!r}")

    def test_steam_scanner_read_only_vdf_acf_and_owasp_guards(self) -> None:
        """Steam scanner reads valid manifests, filters Steam tools, and blocks UNC/traversal/oversized files."""
        # Reject UNC / SMB / traversal paths before touching network or disk
        self.assertIsNone(_is_safe_local_dir(r"\\attacker.local\share\Steam", require_win_drive=True))
        self.assertIsNone(_is_safe_local_dir("//attacker.local/share/Steam", require_win_drive=False))
        self.assertIsNone(_is_safe_local_dir(r"C:\Games\..\Evil", require_win_drive=True))
        self.assertIsNone(_is_safe_local_dir("relative/path", require_win_drive=True))

        # Pure VDF / ACF parsers
        vdf_sample = '"libraryfolders" { "0" { "path" "C:\\\\Program Files (x86)\\\\Steam" } "1" { "path" "\\\\\\\\evil\\\\share" } }'
        self.assertEqual(
            _parse_steam_library_folders_vdf(vdf_sample),
            [r"C:\Program Files (x86)\Steam", r"\\evil\share"],
        )
        self.assertEqual(
            _parse_steam_appmanifest_acf('"AppState" { "appid" "1245620" "name" "ELDEN RING" }'),
            ("1245620", "ELDEN RING"),
        )
        self.assertIsNone(_parse_steam_appmanifest_acf('"AppState" { "appid" "bad_id" "name" "Hack" }'))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            steamapps = root / "steamapps"
            steamapps.mkdir()

            # Valid game manifest
            (steamapps / "appmanifest_1245620.acf").write_text(
                '"AppState"\n{\n  "appid" "1245620"\n  "name" "ELDEN RING"\n}\n',
                encoding="utf-8",
            )
            # Steam runtime tool (must be ignored)
            (steamapps / "appmanifest_228980.acf").write_text(
                '"AppState"\n{\n  "appid" "228980"\n  "name" "Steamworks Common Redistributables"\n}\n',
                encoding="utf-8",
            )
            # Oversized ACF (> MAX_ACF_BYTES) must be safely skipped
            (steamapps / "appmanifest_999999.acf").write_bytes(
                b'"AppState" { "appid" "999999" "name" "TooBig" } ' + b"A" * (MAX_ACF_BYTES + 64)
            )
            # Oversized VDF (> MAX_VDF_BYTES) must return "" cleanly
            oversized_vdf = steamapps / "libraryfolders.vdf"
            oversized_vdf.write_bytes(b" " * (MAX_VDF_BYTES + 64))
            self.assertEqual(_read_bounded_text(oversized_vdf, MAX_VDF_BYTES), "")

            found = _scan_steam_games(steam_roots=[root])
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].name, "ELDEN RING")
            self.assertEqual(found[0].package_id, "Steam App 1245620")
            self.assertEqual(found[0].source, "steam")


class TestSecurityAndGenerators(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = CatalogEngine()
        self.demo_analysis = self.catalog.analyze_apps(get_demo_apps(), detected_runtime_ids=["git", "nodejs", "python"])
        self.demo_analysis["dev_env"] = {
            "vscode_extensions": ["ms-python.python", "bad;rm -rf /", "--flag.ext"],
            "npm_globals": ["typescript", "@angular/cli", "evil;id"],
            "git_user_name": "Test User",
            "git_user_email": "test@example.com",
        }
        self.demo_analysis["include_vscode_extensions"] = True
        self.demo_analysis["include_npm_globals"] = True
        self.demo_analysis["include_git_config"] = True

    def test_smtp_header_injection_and_validation_blocked(self) -> None:
        plan = build_migration_plan(self.demo_analysis)
        base_cfg = {
            "preset": "gmail",
            "host": "smtp.gmail.com",
            "port": 587,
            "security": "starttls",
            "username": "sender@example.com",
            "recipient": "target@example.com",
            "password": "app-password-1234",
        }

        # Header injection in recipient, username, host, password, filename_prefix
        with self.assertRaises(ValueError):
            send_migration_email_smtp({**base_cfg, "recipient": "ok@x.com\r\nBcc:evil@x.com"}, "kit", "<html/>", "#!/bin/bash\n", plan)
        with self.assertRaises(ValueError):
            send_migration_email_smtp({**base_cfg, "username": "ok@x.com\nBcc:evil@x.com"}, "kit", "<html/>", "#!/bin/bash\n", plan)
        with self.assertRaises(ValueError):
            send_migration_email_smtp({**base_cfg, "host": "smtp.gmail.com\r\n"}, "kit", "<html/>", "#!/bin/bash\n", plan)
        with self.assertRaises(ValueError):
            send_migration_email_smtp({**base_cfg, "password": "secret\r\n"}, "kit", "<html/>", "#!/bin/bash\n", plan)
        with self.assertRaises(ValueError):
            send_migration_email_smtp(base_cfg, "kit\r\nBcc:evil@x.com", "<html/>", "#!/bin/bash\n", plan)

        # Invalid ports & unencrypted mode rejected
        for bad_port in (0, -1, 65536, True, "not-a-port"):
            with self.assertRaises(ValueError):
                send_migration_email_smtp({**base_cfg, "port": bad_port}, "kit", "<html/>", "#!/bin/bash\n", plan)
        with self.assertRaises(ValueError):
            send_migration_email_smtp({**base_cfg, "security": "none"}, "kit", "<html/>", "#!/bin/bash\n", plan)

        # Webmail draft URLs also reject CR/LF injection
        with self.assertRaises(ValueError):
            build_webmail_draft_urls("user@example.com\r\nBcc:evil@x.com", "kit", plan)

        # Secret scrubbing never leaks plain, base64, or AUTH PLAIN password
        secret = "SuperSecretAppPass!99"
        user = "alice@example.com"
        b64_pw = base64.b64encode(secret.encode()).decode("ascii")
        b64_plain = base64.b64encode(f"\x00{user}\x00{secret}".encode()).decode("ascii")
        scrubbed = _sanitize_error_without_secret(
            RuntimeError(f"fail plain={secret} b64={b64_pw} auth={b64_plain}"),
            secret,
            username=user,
        )
        self.assertNotIn(secret, scrubbed)
        self.assertNotIn(b64_pw, scrubbed)
        self.assertNotIn(b64_plain, scrubbed)
        self.assertIn("[REDACTED]", scrubbed)

        auth_msg = _sanitize_error_without_secret(smtplib.SMTPAuthenticationError(535, b"Bad credentials"), secret, user)
        self.assertIn("authentication failed", auth_msg.lower())
        ssl_msg = _sanitize_error_without_secret(ssl.SSLError("cert verify failed"), secret, user)
        self.assertIn("tls certificate", ssl_msg.lower())

    def test_bash_script_blocks_shell_injection_uses_lf_and_passes_bash_n(self) -> None:
        # Build a deliberately tampered plan directly to test defense-in-depth in generate_linux_script
        tampered_plan = build_migration_plan(self.demo_analysis)
        tampered_plan["generated_at"] = "2026-11-23\nrm -rf / # injected"
        tampered_plan["target_distro"] = "apt\nwhoami"
        tampered_plan["apps"].append(
            {
                "source_windows_app": "Evil $(id)",
                "target_linux_app": "EvilApp\necho_breakout",
                "category": "utilities",
                "status": "native",
                "type": "app",
                "packages": {
                    "flatpak": "org.evil.App; rm -rf /",
                    "apt": ["goodpkg", "$(evil)", "`bad`", "/tmp/evil.deb", "--evil-flag"],
                    "official_url": "javascript:alert(1)",
                },
            }
        )
        tampered_plan["vscode_extensions"].extend(["bad;rm -rf /", "--flag.ext", "pub.ext\nwhoami"])
        tampered_plan["npm_globals"].extend(["evil;id", "../traverse", "--option"])
        tampered_plan["git_config"] = {
            "user_name": "--option-injection",
            "user_email": "bad@example.com\nrm -rf /",
        }

        script = generate_linux_script(tampered_plan)

        self.assertNotIn("\r\n", script)
        self.assertIn("# Generated: unknown", script)
        self.assertIn("# Target Distro: auto", script)
        self.assertIn("install_sys_pkg 'EvilApp echo_breakout' goodpkg", script)
        self.assertNotIn("\necho_breakout", script)
        self.assertNotIn("rm -rf /", script)
        self.assertNotIn("$(evil)", script)
        self.assertNotIn("/tmp/evil.deb", script)
        self.assertNotIn("--evil-flag", script)
        self.assertNotIn("--flag.ext", script)
        self.assertNotIn("javascript:alert", script)
        self.assertNotIn("--option-injection", script)
        self.assertIn("CODE_CMD=()", script)
        self.assertIn('"${CODE_CMD[@]}"', script)
        self.assertIn("ms-python.python", script)
        self.assertIn("typescript", script)
        self.assertIn("#!/usr/bin/env bash", script)
        self.assertIn("--dry-run", script)
        self.assertIn("backed up", script.lower())

        # Verify actual Bash syntax validity using Git Bash (on Windows) or system bash (on POSIX)
        if sys.platform.startswith("win"):
            git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
            bash_bin = str(git_bash) if git_bash.is_file() else None
        else:
            bash_bin = shutil.which("bash")
        if bash_bin:
            with tempfile.TemporaryDirectory() as tmp:
                sh_file = Path(tmp) / "tampered-test.sh"
                sh_file.write_bytes(script.encode("utf-8"))
                proc = subprocess.run([bash_bin, "-n", str(sh_file)], capture_output=True, text=True, timeout=15)
                self.assertEqual(proc.returncode, 0, f"bash -n failed: {proc.stderr}")

    def test_linux_runner_blocks_tampered_plan_injections(self) -> None:
        tampered = {
            "prefer_flatpak": False,
            "apps": [
                {
                    "source_windows_app": "Good",
                    "target_linux_app": "VLC",
                    "type": "app",
                    "packages": {
                        "apt": ["vlc", "; rm -rf /", "/tmp/evil.deb", "--evil"],
                        "flatpak": "org.videolan.VLC; whoami",
                        "official_url": "javascript:alert(1)",
                    },
                },
                {
                    "source_windows_app": "BadType",
                    "target_linux_app": "Broken",
                    "type": "app",
                    "packages": {"apt": "not-a-list"},
                },
                "not-a-dict",
            ],
            "vscode_extensions": ["ms-python.python", "--bad.ext", "evil;whoami"],
            "npm_globals": ["typescript", "pkg;rm -rf /", "../evil"],
        }

        inspected = inspect_plan_on_linux(tampered)
        self.assertEqual(len(inspected["items"]), 2)
        self.assertEqual(inspected["vscode_extensions_count"], 1)
        self.assertEqual(inspected["npm_globals_count"], 1)

        applied = apply_plan_on_linux(tampered, dry_run=True)
        joined_logs = "\n".join(applied["logs"])
        self.assertNotIn("rm -rf /", joined_logs)
        self.assertNotIn("whoami", joined_logs)
        self.assertNotIn("/tmp/evil.deb", joined_logs)
        self.assertNotIn("--bad.ext", joined_logs)
        self.assertIn("[skip]", joined_logs)
        self.assertIn("ms-python.python", joined_logs)
        self.assertIn("typescript", joined_logs)
        self.assertEqual(len(applied["failed"]), 0)

        # Live install must refuse to run on non-Linux OS
        if sys.platform.startswith("win"):
            with self.assertRaises(RuntimeError):
                apply_plan_on_linux(tampered, dry_run=False)

    def test_html_report_escapes_xss_and_safely_url_encodes_unmatched(self) -> None:
        self.demo_analysis["matched"][0]["name"] = '<script>alert("xss")</script>'
        self.demo_analysis["matched"][0]["linux_packages"] = {"official_url": "javascript:alert(1)"}
        self.demo_analysis["unmatched"] = [
            {
                "name": 'EvilApp&platform=windows" onmouseover="alert(1)',
                "publisher": "<b>BadPub</b>",
                "version": "1.0",
            }
        ]
        self.demo_analysis["projects"] = [
            {
                "name": "<img src=x onerror=alert(1)>",
                "path": r"C:\Evil\<script>",
                "stacks": ["Python"],
                "compatibility": '<script>evil</script>',
                "linux_warnings": [{"severity": "warning", "message": "<svg onload=alert(1)>"}],
                "backup_warnings": [],
            }
        ]

        plan = build_migration_plan(self.demo_analysis)
        html_out = generate_html_report(self.demo_analysis, plan, script_filename='kit"<script>.sh')

        self.assertNotIn('<script>alert("xss")</script>', html_out)
        self.assertNotIn("<svg onload=alert(1)>", html_out)
        self.assertNotIn("<img src=x onerror=alert(1)>", html_out)
        self.assertNotIn('href="javascript:', html_out)
        self.assertNotIn('onmouseover="alert(1)"', html_out)
        self.assertIn("&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;", html_out)
        # Verify URL query parameter encoding blocked parameter injection
        self.assertIn("EvilApp%26platform%3Dwindows%22+onmouseover%3D%22alert%281%29", html_out)
        # Verify offline CSP, Backup Reminder, and Legal Notice
        self.assertIn('http-equiv="Content-Security-Policy"', html_out)
        self.assertIn("default-src 'none'", html_out)
        self.assertIn("Don't Forget to Back Up Your Projects", html_out)
        self.assertIn("independent open-source software (MIT License)", html_out)

    def test_categorized_html_report_and_host_pinned_game_links_xss_safety(self) -> None:
        """Categorized HTML report renders all 5 buckets cleanly and blocks XSS/phishing URLs in new sections."""
        demo = self.catalog.analyze_apps(
            [
                *get_demo_apps(),
                InstalledApp("Windows Subsystem for Linux", "2.3", "Microsoft Corporation", "registry"),
            ],
            detected_runtime_ids=["git", "nodejs", "python", "deno", "ollama"],
        )
        plan = build_migration_plan(demo)
        html_clean = generate_html_report(demo, plan, script_filename="cat-test-install.sh")

        # Categorized headings + 5-bucket strip + dedicated sections
        self.assertIn("Applications &amp; Developer Tools", html_clean)
        self.assertIn("Web Browsers", html_clean)
        self.assertIn("Development &amp; IDEs", html_clean)
        self.assertIn("Runtimes &amp; CLIs", html_clean)
        self.assertIn("Hardware &amp; Drivers", html_clean)
        self.assertIn("NVIDIA GPU &amp; Drivers", html_clean)
        self.assertIn("Official Linux Driver", html_clean)
        self.assertIn("Intel Graphics, Wireless &amp; Platform", html_clean)
        self.assertIn("Built into Linux Kernel", html_clean)
        self.assertIn("PC Games &amp; Launchers", html_clean)
        self.assertIn("Detected PC Games", html_clean)
        self.assertIn("https://www.protondb.com/app/1245620", html_clean)
        self.assertIn("https://areweanticheatyet.com/?search=ELDEN+RING", html_clean)
        self.assertIn("independent, community-maintained compatibility databases", html_clean)
        self.assertIn('<details class="os-details">', html_clean)
        self.assertIn("Windows built-in apps, codecs &amp; runtimes excluded", html_clean)
        self.assertIn("Other / Niche Applications", html_clean)
        self.assertIn("Handled by Linux", html_clean)
        # Games must NOT appear inside Flathub search links!
        self.assertNotIn("flathub.org/apps/search?q=ELDEN+RING", html_clean)
        self.assertNotIn("flathub.org/apps/search?q=Teamfight+Tactics", html_clean)

        # Adversarial XSS + domain spoofing injection into hardware_drivers, games, and os_builtins
        tampered = dict(demo)
        tampered["hardware_drivers"] = [
            {
                "id": "hw-evil",
                "name": "<script>alert('hw')</script>",
                "driver_status": "official_driver",
                "driver_status_label": "<b>BadLabel</b>",
                "summary": "<img src=x onerror=alert(1)>",
                "official_url": "javascript:alert(1)",
                "detected_components": ["<svg onload=alert(1)>"],
                "component_count": 1,
            }
        ]
        tampered["games"] = [
            {
                "name": 'EvilGame"<script>alert(1)</script>',
                "publisher": "<b>Pub</b>",
                "version": "1.0",
                "platform": "<img src=x>",
                "steam_app_id": "not-numeric",
                "status": "check_protondb",
                "status_label": "Check ProtonDB",
                "note": "<script>evil_note()</script>",
                "protondb_url": "https://evil-phishing.example/protondb",
                "anticheat_url": "https://attacker.example/anticheat",
            }
        ]
        tampered["os_builtins"] = [
            {"name": "<script>builtin()</script>", "version": "1.0", "reason": "<b>Reason</b>"}
        ]
        html_sec = generate_html_report(tampered, plan)
        self.assertNotIn("<script", html_sec.lower())
        self.assertNotIn("javascript:alert", html_sec)
        self.assertNotIn("evil-phishing.example", html_sec)
        self.assertNotIn("attacker.example", html_sec)
        self.assertIn("https://www.protondb.com/search?q=EvilGame", html_sec)
        self.assertIn("https://areweanticheatyet.com/?search=EvilGame", html_sec)
        self.assertIn("&lt;script&gt;alert(&#x27;hw&#x27;)&lt;/script&gt;", html_sec)
        self.assertIn("&lt;script&gt;builtin()&lt;/script&gt;", html_sec)

    def test_cross_distro_pacman_only_fallback_urls_and_zero_curl_pipe_sh(self) -> None:
        """Pacman-only tools like Deno & Ollama emit official URL fallbacks for apt/dnf/zypper with zero curl|sh."""
        apps = [
            InstalledApp("Deno", "2.1.0", "Deno Land Inc.", "winget", winget_id="DenoLand.Deno"),
            InstalledApp("Ollama", "0.5.0", "Ollama", "registry", winget_id="Ollama.Ollama"),
            InstalledApp("NVIDIA App", "11.0.1", "NVIDIA Corporation", "winget", winget_id="Nvidia.NvidiaApp"),
            InstalledApp("Windows Subsystem for Linux", "2.3", "Microsoft Corporation", "registry"),
        ]
        analysis = self.catalog.analyze_apps(apps)
        plan = build_migration_plan(analysis)
        script = generate_linux_script(plan)

        # Arch installs natively via pacman; non-Arch prints official Linux URLs via case "$PM"
        self.assertIn("install_sys_pkg Deno deno", script)
        self.assertIn("install_sys_pkg Ollama ollama", script)
        self.assertIn("pacman) ;;", script)
        self.assertIn("https://docs.deno.com/runtime/getting_started/installation/", script)
        self.assertIn("https://ollama.com/download/linux", script)
        # Zero curl|sh, zero NVIDIA/WSL leakage
        self.assertNotIn("curl ", script)
        self.assertNotIn("NVIDIA", script)
        self.assertNotIn("Windows Subsystem for Linux", script)

        if sys.platform.startswith("win"):
            git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
            bash_bin = str(git_bash) if git_bash.is_file() else None
        else:
            bash_bin = shutil.which("bash")
        if bash_bin:
            with tempfile.TemporaryDirectory() as tmp:
                sh_file = Path(tmp) / "cross-distro.sh"
                sh_file.write_bytes(script.encode("utf-8"))
                proc = subprocess.run([bash_bin, "-n", str(sh_file)], capture_output=True, text=True, timeout=15)
                self.assertEqual(proc.returncode, 0, f"bash -n failed: {proc.stderr}")

    def test_save_bundle_lf_zip_0755_and_open_path_allowlist(self) -> None:
        plan = build_migration_plan(self.demo_analysis)
        script = generate_linux_script(plan)
        report = generate_html_report(self.demo_analysis, plan)

        with tempfile.TemporaryDirectory() as tmp:
            res = save_migration_bundle(tmp, "my-linux-kit", report, script, plan, create_zip=True)
            sh_bytes = Path(res["script_path"]).read_bytes()
            self.assertNotIn(b"\r\n", sh_bytes)
            self.assertTrue(Path(res["report_path"]).is_file())
            self.assertTrue(Path(res["plan_path"]).is_file())
            self.assertTrue(Path(res["zip_path"]).is_file())

            with zipfile.ZipFile(res["zip_path"], "r") as zf:
                names = zf.namelist()
                self.assertIn("my-linux-kit-install.sh", names)
                for name in names:
                    self.assertNotIn("/", name)
                    self.assertNotIn("\\", name)
                    self.assertNotIn("..", name)
                sh_info = zf.getinfo("my-linux-kit-install.sh")
                self.assertEqual((sh_info.external_attr >> 16) & 0o777, 0o755)

            # open_saved_path blocks unauthorized paths and non-HTML files
            self.assertFalse(open_saved_path(r"C:\Windows\System32\calc.exe", allowed_dir=tmp))
            self.assertFalse(open_saved_path(res["script_path"], allowed_dir=tmp))
            self.assertFalse(open_saved_path(res["plan_path"], allowed_dir=tmp))
            self.assertFalse(open_saved_path("bad\x00path", allowed_dir=tmp))

        # Reject empty/control-char destination_dir
        with self.assertRaises(ValueError):
            save_migration_bundle("", "kit", report, script, plan)
        with self.assertRaises(ValueError):
            save_migration_bundle("C:\\bad\npath", "kit", report, script, plan)

    def test_webmail_draft_urls(self) -> None:
        plan = build_migration_plan(self.demo_analysis)
        urls = build_webmail_draft_urls("user@example.com", "kit", plan)
        self.assertTrue(urls["gmail"].startswith("https://mail.google.com/"))
        self.assertTrue(urls["outlook"].startswith("https://outlook.live.com/"))
        self.assertTrue(urls["mailto"].startswith("mailto:user%40example.com"))
        self.assertIsNone(HEBREW_RE.search(json.dumps(urls)))


class TestProjectScannerSecurity(unittest.TestCase):
    def test_env_files_are_never_opened_or_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "my-win-app"
            proj.mkdir()
            (proj / "App.csproj").write_text(
                "<Project><PropertyGroup><UseWPF>true</UseWPF></PropertyGroup></Project>",
                encoding="utf-8",
            )
            env_path = proj / ".env"
            env_local_path = proj / ".env.local"
            env_path.write_text("API_KEY=TOP_SECRET_DO_NOT_READ_12345", encoding="utf-8")
            env_local_path.write_text("DB_PASS=ANOTHER_SECRET_99999", encoding="utf-8")
            (proj / "deploy.bat").write_text("@echo off\necho hi\n", encoding="utf-8")

            real_open = builtins.open
            opened_files: list[str] = []

            def guarded_open(file, *args, **kwargs):
                name = str(file)
                opened_files.append(name)
                if Path(name).name.startswith(".env"):
                    raise AssertionError(f"SECURITY VIOLATION: .env file was opened: {name}")
                return real_open(file, *args, **kwargs)

            with mock.patch("builtins.open", side_effect=guarded_open):
                findings = scan_projects_folders([tmp])

            self.assertEqual(len(findings), 1)
            f = findings[0]
            self.assertEqual(f["compatibility"], "blocker")
            self.assertTrue(f["has_env_files"])
            self.assertFalse(f["is_git_repo"])
            serialized = json.dumps(f)
            self.assertNotIn("TOP_SECRET_DO_NOT_READ_12345", serialized)
            self.assertNotIn("ANOTHER_SECRET_99999", serialized)
            self.assertIsNone(HEBREW_RE.search(serialized))


class TestCLIHeadlessModes(unittest.TestCase):
    def test_cli_scan_demo_and_linux_apply_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli_main(["--cli-scan", "--demo", "--out", tmp, "--name", "cli-test"])
            self.assertEqual(rc, 0)
            self.assertIn("Linux Readiness Score:", buf.getvalue())
            out_dir = Path(tmp)
            report = out_dir / "cli-test-report.html"
            script = out_dir / "cli-test-install.sh"
            plan = out_dir / "cli-test-plan.json"
            bundle = out_dir / "cli-test-bundle.zip"
            for p in (report, script, plan, bundle):
                self.assertTrue(p.is_file(), f"CLI scan did not create {p.name}")

            self.assertIsNone(HEBREW_RE.search(report.read_text(encoding="utf-8")))
            self.assertNotIn(b"\r\n", script.read_bytes())

            buf_apply = io.StringIO()
            with contextlib.redirect_stdout(buf_apply):
                rc_apply = cli_main(["--linux-apply", str(plan), "--dry-run"])
            self.assertEqual(rc_apply, 0)
            self.assertIn("[dry-run]", buf_apply.getvalue())


class TestNativeDesktopGUISmoke(unittest.TestCase):
    """Non-blocking GUI smoke test exercising all 4 Planner steps, modals, and Linux Mode."""

    def test_gui_full_wizard_and_linux_mode_smoke(self) -> None:
        from tuxharbor.gui import TuxHarborApp

        app = TuxHarborApp(demo_mode=True)
        try:
            app.withdraw()
            app.update()

            # Load realistic demo scan synchronously (showcases all 5 buckets)
            analysis = app.load_demo_scan_sync()
            self.assertGreater(len(analysis["matched"]), 10)
            self.assertGreaterEqual(len(analysis["hardware_drivers"]), 2)
            self.assertGreaterEqual(len(analysis["games"]), 2)
            self.assertGreaterEqual(len(analysis["os_builtins"]), 2)
            self.assertGreaterEqual(len(analysis["unmatched"]), 1)
            self.assertGreater(analysis["readiness_score"], 50)

            # Inject a no_install_needed item (WSL) to verify bulk-select never selects it
            wsl_entry = app.catalog.by_id["wsl"]
            analysis["matched"].append(
                app.catalog._build_matched_item(
                    wsl_entry,
                    [InstalledApp("Windows Subsystem for Linux", "2.3", "Microsoft Corporation", "registry")],
                )
            )

            # Step 1 -> Step 2 (Categorized Report, Hardware & Drivers, PC Games, OS Built-ins)
            app.go_to_step(1)
            app.update()
            app.go_to_step(2)
            app.update()

            # Verify 5-bucket summary bar and dedicated Step 2 panels are populated
            summary_txt = app.bucket_summary_label.cget("text")
            self.assertIn("Hardware & Drivers:", summary_txt)
            self.assertIn("PC Games:", summary_txt)
            self.assertIn("Windows OS Built-ins Excluded:", summary_txt)
            self.assertGreater(len(app.hardware_panel.winfo_children()), 0)
            self.assertGreater(len(app.games_panel.winfo_children()), 0)
            self.assertGreater(len(app.os_builtins_panel.winfo_children()), 0)
            self.assertGreater(len(app.unmatched_panel.winfo_children()), 0)

            # Exercise category dropdown filter
            cat_vals = list(app.category_menu.cget("values"))
            self.assertIn("All Categories", cat_vals)
            self.assertGreater(len(cat_vals), 3)
            for cat_label in cat_vals[:4]:
                app.var_category_filter.set(cat_label)
                app._render_apps_list()
                app.update()
            app.var_category_filter.set("All Categories")
            app._render_apps_list()

            # Exercise status filters, search, bulk select (respecting no_install_needed), and toggles
            for flt in ("Native", "Alternative", "Compat", "Attention", "All"):
                app.var_status_filter.set(flt)
                app._render_apps_list()
                app.update()

            app.var_search.set("Chrome")
            app._render_apps_list()
            app.var_search.set("")
            app._render_apps_list()
            app._bulk_select_apps(False)
            app._bulk_select_apps(True)
            wsl_item = next(m for m in analysis["matched"] if m["id"] == "wsl")
            self.assertFalse(wsl_item["selected"], "Bulk Select All must never select no_install_needed items (WSL)")
            app._toggle_os_builtins()
            self.assertTrue(app.os_builtins_expanded)
            app._toggle_os_builtins()
            self.assertFalse(app.os_builtins_expanded)
            app._toggle_unmatched()
            app._toggle_unmatched()
            app.update()

            # Step 3 (Mandatory Backup Reminder & 4-item checklist)
            app.go_to_step(3)
            app.update()
            for var in (app.var_chk_external, app.var_chk_gitpush, app.var_chk_secrets, app.var_chk_media):
                var.set(True)
            app._update_backup_counter()
            self.assertIn("4 / 4", app.chk_counter_label.cget("text"))
            app.update()

            # Step 4 (Delivery mode switching, Save As preview, password mask/clear, modals)
            app.go_to_step(4)
            app.update()
            for mode in ("Save Locally (PC / USB / Cloud)", "Send Securely via Email", "Both (Local + Email)"):
                app.var_delivery_mode.set(mode)
                app._refresh_delivery_panels()
                app.update()

            for em in ("Direct TLS SMTP (with attachments)", "Passwordless Quick Draft (Gmail / Outlook / Mail)"):
                app.var_email_method.set(em)
                app._refresh_email_subpanel()
                app.update()

            app._on_smtp_provider_change("Yahoo Mail")
            self.assertEqual(app.var_smtp_port.get(), "465")
            self.assertEqual(app.var_smtp_security.get(), "SSL")
            app._on_smtp_provider_change("Gmail")
            self.assertEqual(app.var_smtp_port.get(), "587")

            # Password widget must mask typed input and clear cleanly
            app.smtp_password_entry.insert(0, "temp-secret")
            self.assertEqual(app.smtp_password_entry.cget("show"), "•")
            app._clear_smtp_password()
            self.assertEqual(app.smtp_password_entry.get(), "")

            app.var_prefix.set("smoke-pc")
            app._refresh_filename_preview()
            self.assertIn("smoke-pc-install.sh", app.filename_preview_label.cget("text"))

            # Script preview modal & About/Legal modal
            preview_win = app.open_script_preview_modal()
            self.assertIsNotNone(preview_win)
            app.update()
            if preview_win is not None:
                preview_win.destroy()

            about_win = app.open_about_legal_dialog()
            self.assertIsNotNone(about_win)
            app.update()
            about_win.destroy()

            guide_win = app.open_how_it_works_dialog()
            self.assertIsNotNone(guide_win)
            app.update()
            guide_win.destroy()

            # Linux Mode tab: save demo plan, load it, verify inspection & dry-run
            prefix, plan, _script, _html = app._build_current_artifacts()
            self.assertEqual(prefix, "smoke-pc")

            app.switch_mode("linux")
            app.update()
            with tempfile.TemporaryDirectory() as tmp:
                plan_file = Path(tmp) / "smoke-pc-plan.json"
                plan_file.write_text(json.dumps(plan), encoding="utf-8")
                loaded = app.load_plan_file(str(plan_file))
                self.assertTrue(loaded)
                self.assertIsNotNone(app.loaded_plan)
                app.update()
                self.assertIn("Loaded", app.linux_plan_summary_label.cget("text"))

                # Oversized (>5 MB) plan must be rejected cleanly
                oversized = Path(tmp) / "huge-plan.json"
                oversized.write_bytes(b" " * (5 * 1024 * 1024 + 16))
                with mock.patch("tuxharbor.gui.messagebox.showerror") as mock_err:
                    self.assertFalse(app.load_plan_file(str(oversized)))
                    mock_err.assert_called_once()

            app.switch_mode("planner")
            app.update()

            # Zero HTTP server even after full GUI lifecycle
            self.assertNotIn("http.server", sys.modules)
        finally:
            try:
                app.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
