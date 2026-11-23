"""Catalog loading, 5-bucket Windows-to-Linux classification, and readiness scoring."""

from __future__ import annotations

import functools
import json
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

from tuxharbor.models import InstalledApp, is_safe_https_url, is_safe_steam_app_id
from tuxharbor.scanners.windows_apps import normalize_app_key, strip_bidi


DRIVER_STATUS_LABELS: dict[str, str] = {
    "official_driver": "Official Linux Driver",
    "kernel_builtin": "Built into Linux Kernel",
    "oem_utility": "Hardware / OEM Utility",
}

DRIVER_STATUS_RANK: dict[str, int] = {
    "official_driver": 0,
    "kernel_builtin": 1,
    "oem_utility": 2,
}

GAME_STATUS_LABELS: dict[str, str] = {
    "anticheat_blocked": "Blocked by Anti-Cheat",
    "anticheat_caution": "Online Anti-Cheat Caution",
    "check_protondb": "Check ProtonDB",
}

GAME_STATUS_RANK: dict[str, int] = {
    "anticheat_blocked": 0,
    "anticheat_caution": 1,
    "check_protondb": 2,
}

# Step 1: Pre-exclusion OS/app subcomponents that would otherwise hijack real apps or pollute unmatched
PRE_EXCLUSION_RUNTIME_TOKENS: tuple[str, ...] = (
    "edgewebview",
    "edge webview2",
    "microsoft.windowsappruntime",
    "winappruntime.",
    "windowsappruntime.",
    "microsoft.dotnet.desktopruntime",
    "microsoft.dotnet.runtime",
    "microsoft.dotnet.aspnetcore",
    "microsoft.dotnet.native",
    "microsoft windows desktop runtime",
    "microsoft .net native",
    "microsoft .net runtime",
    "microsoft .net host",
    "microsoft .net targeting",
    "microsoft .net app host",
    "microsoft asp.net core",
    "microsoft.vcredist",
    "microsoft.vclibs",
    "microsoft.ui.xaml",
    "python.launcher",
    "python launcher",
)

PRE_EXCLUSION_HELPER_TOKENS: tuple[str, ...] = (
    "microsoft.edge.gameassist",
    "microsoft.onedrive.photos",
    "odphotosonedrivesetup",
    "microsoft.office.actionsserver",
    "microsoft.officepushnotificationutility",
    "officepushnotificationsutility",
    "microsoft.m365companions",
    "msix\\aimgr_",
    "microsoft.office.2010.filterpacks",
    "microsoft filter pack",
    "teams meeting add-in",
    "application compatibility fix database",
    "windows package manager source",
)

# Step 5: Language-independent Windows OS built-in & runtime markers
OS_BUILTIN_MSIX_PREFIXES: tuple[str, ...] = (
    "msix\\microsoft.",
    "msix\\microsoftwindows.",
    "msix\\microsoftcorporationii.",
)

OS_BUILTIN_FAMILY_SUFFIXES: tuple[str, ...] = (
    "__8wekyb3d8bbwe",
    "__cw5n1h2txyewy",
)

OS_BUILTIN_ID_TOKENS: tuple[str, ...] = (
    "microsoft.appinstaller",
    "microsoft.365copilot",
    "microsoft.copilot",
    "xp9cxngppj97xx",
    "microsoft.windowsappruntime",
    "microsoft.dotnet.desktopruntime",
    "microsoft.dotnet.runtime",
    "microsoft.dotnet.aspnetcore",
    "microsoft.dotnet.native",
    "microsoft.vcredist",
    "microsoft.vclibs",
    "microsoft.ui.xaml",
    "microsoft.edgewebview",
)

OS_BUILTIN_FALLBACK_NAME_TOKENS: tuple[str, ...] = (
    "microsoft copilot",
    "windows app runtime",
    "winappruntime",
    "windowsappruntime",
    "windows software development kit",
    "windows sdk",
    "universal crt",
    "update for windows",
    "security update for",
    "hotfix for",
    "microsoft update health",
    "local experience pack",
    "widgets platform runtime",
    "windows web experience pack",
    "engagement framework",
    "xbox identity provider",
    "xbox tcui",
    "game bar",
    "game speech window",
    "microsoft gameinput",
    "dev home",
    "power automate",
    "microsoft bing",
    "microsoft news",
    "microsoft store",
    "ink.handwriting.",
    "microsoft ink handwriting",
    "solitaire & casual games",
    "av1 video extension",
    "hevc video extensions",
    "vp9 video extensions",
    "mpeg-2 video extension",
    "raw image extension",
    "webp image extensions",
    "heif image extensions",
    "web media extensions",
    "windows app certification",
    "application verifier",
    "diagnostics hub",
    "microsoft edge update",
)

# Step 3: High-confidence PC game detection heuristics (linear-time regexes only)
STEAM_APP_PKG_RE = re.compile(r"\A(?:arp\\[^\\]{1,40}\\[^\\]{1,40}\\){0,1}steam app ([0-9]{1,10})\Z", re.IGNORECASE)
STEAM_UNINSTALL_RE = re.compile(r"steam://rungameid/([0-9]{1,10})", re.IGNORECASE)
GENERIC_OEM_DRIVER_RE = re.compile(
    r"\b(?:bus|usb|keyboard|mouse|audio|sound|chipset|webcam|camera|printer|scanner|"
    r"bluetooth|wireless|wi-fi|wifi|wlan|ethernet|network|touchpad|trackpad|"
    r"fingerprint|biometric|thunderbolt|nvme|raid|smbus|graphics|display|video|"
    r"card reader|dock|hotkey|firmware)\s+(?:driver|drivers|controller|utility|package|service)\b"
    r"|\b(?:driver|drivers)\s+(?:package|installer|updater|assistant|support)\b",
    re.IGNORECASE,
)

GAME_LAUNCHER_EXCLUSION_SUBSTRINGS: tuple[str, ...] = (
    "launcher",
    " sdk",
    "social club",
    "riot client",
    "riot vanguard",
    "steamvr",
    "steamworks",
    "proton ",
    "redistributable",
    "xbox identity",
    "xbox tcui",
    "game bar",
    "game speech",
    "solitaire",
    "anti-cheat",
    "anticheat",
    "battleye",
    "easy anti-cheat",
    "directx",
)

GAME_LAUNCHER_EXACT_NAMES: frozenset[str] = frozenset(
    {
        "steam",
        "xbox",
        "xbox app",
        "epic games",
        "gog galaxy",
        "origin",
        "ea app",
        "ubisoft connect",
        "battle.net",
        "riot client",
        "riot vanguard",
    }
)

GAME_PATH_SEGMENTS: tuple[str, ...] = (
    "\\games\\",
    "/games/",
    "\\steamapps\\common\\",
    "/steamapps/common/",
    "\\epic games\\",
    "\\gog games\\",
    "\\riot games\\",
    "\\rockstar games\\",
    "\\ubisoft game launcher\\games\\",
    "\\ea games\\",
    "\\xboxgames\\",
)

KNOWN_GAME_PUBLISHERS: tuple[str, ...] = (
    "rockstar games",
    "riot games",
    "fromsoftware",
    "bandai namco",
    "cd projekt",
    "bethesda softworks",
    "electronic arts",
    "ubisoft",
    "capcom",
    "square enix",
    "larian studios",
    "hoyoverse",
    "mihoyo",
    "bungie",
    "2k games",
    "remedy entertainment",
    "devolver digital",
    "paradox interactive",
    "supergiant games",
    "activision",
    "blizzard entertainment",
)


def _norm(text: str) -> str:
    """Normalize display strings for matching (BiDi-free, lowercase, mu->u, trademark-free)."""
    cleaned = strip_bidi(text).lower()
    cleaned = cleaned.replace("\u03bc", "u").replace("\u00b5", "u")
    cleaned = cleaned.replace("\u00ae", " ").replace("\u2122", " ").replace("(r)", " ")
    return " ".join(cleaned.split())


@functools.lru_cache(maxsize=512)
def _compile_word_regex(pattern: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + re.escape(pattern) + r"(?![a-z0-9])")


def _word_match(pattern: str, haystack: str) -> bool:
    if not pattern or not haystack:
        return False
    return bool(_compile_word_regex(pattern).search(haystack))


def get_resource_path(relative_path: str) -> Path:
    """Resolve bundled data paths in both source mode and PyInstaller onefile mode."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "tuxharbor" / relative_path
    return Path(__file__).resolve().parent / relative_path


class CatalogEngine:
    def __init__(self, catalog_path: Path | None = None) -> None:
        path = catalog_path or get_resource_path("data/catalog.json")
        with path.open("r", encoding="utf-8") as fh:
            self.raw: dict[str, Any] = json.load(fh)
        self.categories: dict[str, dict[str, str]] = self.raw.get("categories", {})
        self.entries: list[dict[str, Any]] = self.raw.get("apps", [])
        self.hardware_driver_rules: list[dict[str, Any]] = self.raw.get("hardware_drivers", [])
        self.known_games: list[dict[str, Any]] = self.raw.get("known_games", [])
        self.by_id: dict[str, dict[str, Any]] = {e["id"]: e for e in self.entries}
        self.hw_by_id: dict[str, dict[str, Any]] = {h["id"]: h for h in self.hardware_driver_rules}

    def match_app(self, app: InstalledApp) -> dict[str, Any] | None:
        """Match a discovered Windows app against the curated applications catalog."""
        haystack_name = _norm(app.name)
        haystack_wid = _norm(app.winget_id)
        haystack_pid = _norm(app.package_id)
        combined = " ".join(part for part in (haystack_name, haystack_wid, haystack_pid) if part)
        if not combined:
            return None

        best_entry: dict[str, Any] | None = None
        best_score = 0

        for entry in self.entries:
            excludes = entry.get("exclude_patterns", [])
            if any(_norm(ex) in combined for ex in excludes):
                continue

            # 1. Exact full-name patterns (e.g. "git", "xbox")
            for exact in entry.get("exact_patterns", []):
                ep = _norm(exact)
                if ep and haystack_name == ep:
                    score = len(ep) + 80
                    if score > best_score:
                        best_score = score
                        best_entry = entry

            # 2. Word-bounded patterns (e.g. "deno", "nmap", "ollama", "antigravity")
            for wpat in entry.get("word_patterns", []):
                wp = _norm(wpat)
                if wp and (
                    _word_match(wp, haystack_name)
                    or (haystack_wid and _word_match(wp, haystack_wid))
                ):
                    score = len(wp) + 30
                    if haystack_name == wp:
                        score += 50
                    if score > best_score:
                        best_score = score
                        best_entry = entry

            # 3. Substring match patterns across name, winget_id, and package_id
            for pat in entry.get("match_patterns", []):
                p = _norm(pat)
                if not p:
                    continue
                if (
                    p in haystack_name
                    or (haystack_wid and p in haystack_wid)
                    or (haystack_pid and p in haystack_pid)
                ):
                    score = len(p)
                    if haystack_name == p:
                        score += 50
                    if score > best_score:
                        best_score = score
                        best_entry = entry

        return best_entry

    def _classify_pre_exclusion_builtin(self, app: InstalledApp) -> str | None:
        """Step 1: Catch noisy OS/app sub-components before they collide with real apps."""
        name = _norm(app.name)
        wid = _norm(app.winget_id)
        pid = _norm(app.package_id)
        combined = f"{name} {wid} {pid}"

        if "visual c++" in name and ("redistributable" in name or "runtime" in name):
            return "Windows System Runtime / Framework"
        if pid.endswith(".sdb"):
            return "Windows OS Helper / Component"
        if any(tok in combined for tok in PRE_EXCLUSION_RUNTIME_TOKENS):
            return "Windows System Runtime / Framework"
        if any(tok in combined for tok in PRE_EXCLUSION_HELPER_TOKENS):
            return "Windows OS Helper / Component"
        return None

    def _match_hardware_driver(self, app: InstalledApp) -> dict[str, Any] | None:
        """Step 2: Match hardware drivers and OEM utilities language-independently."""
        name = _norm(app.name)
        wid = _norm(app.winget_id)
        pid = _norm(app.package_id)
        pub = _norm(app.publisher)
        combined = f"{name} {wid} {pid} {pub}"

        for rule in self.hardware_driver_rules:
            excludes = rule.get("exclude_patterns", [])
            if any(_norm(ex) in combined for ex in excludes):
                continue

            if pid and any(_norm(sub) in pid for sub in rule.get("package_id_substrings", [])):
                return rule
            if any(
                (wid and wid.startswith(_norm(pref))) or (pid and pid.startswith(_norm(pref)))
                for pref in rule.get("winget_prefixes", [])
            ):
                return rule
            if pub and any(_word_match(_norm(pw), pub) for pw in rule.get("publisher_words", [])):
                return rule
            if name and any(_norm(np) in name for np in rule.get("name_patterns", [])):
                return rule
            if name and any(_word_match(_norm(nwp), name) for nwp in rule.get("name_word_patterns", [])):
                return rule

        return None

    def _match_known_game(self, app: InstalledApp) -> dict[str, Any] | None:
        name = _norm(app.name)
        pid = _norm(app.package_id)
        for game in self.known_games:
            for pat in game.get("match_patterns", []):
                p = _norm(pat)
                if p and (p in name or (pid and p in pid)):
                    return game
        return None

    def _classify_game(self, app: InstalledApp) -> dict[str, Any] | None:
        """Step 3: Detect individual PC games (excluding launchers, SDKs, and anti-cheat services)."""
        name = _norm(app.name)
        if not name or name in GAME_LAUNCHER_EXACT_NAMES:
            return None
        if any(ex in name for ex in GAME_LAUNCHER_EXCLUSION_SUBSTRINGS):
            return None

        pid_raw = strip_bidi(app.package_id)
        pid = _norm(pid_raw)
        pub = _norm(app.publisher)
        ver = _norm(app.version)
        inst_loc = _norm(app.install_location)
        uninst = _norm(app.uninstall_string)

        # Extract numeric Steam AppID if present
        steam_app_id = ""
        m_pkg = STEAM_APP_PKG_RE.match(pid_raw)
        if m_pkg and is_safe_steam_app_id(m_pkg.group(1)):
            steam_app_id = m_pkg.group(1)
        elif app.uninstall_string:
            m_uninst = STEAM_UNINSTALL_RE.search(app.uninstall_string)
            if m_uninst and is_safe_steam_app_id(m_uninst.group(1)):
                steam_app_id = m_uninst.group(1)

        is_steam_signal = bool(steam_app_id) or app.source == "steam"
        is_riot_game_signal = (
            ("riot game " in pid and "riot_client" not in pid)
            or (
                "riotclientservices.exe" in uninst
                and "--uninstall-product=" in uninst
                and "riot_client" not in uninst
            )
        )
        is_version_game_signal = ver == "game"
        is_game_path_signal = any(seg in inst_loc or seg in uninst for seg in GAME_PATH_SEGMENTS)
        is_game_pub_signal = bool(pub) and any(gp in pub for gp in KNOWN_GAME_PUBLISHERS)
        known_game = self._match_known_game(app)

        if not (
            known_game
            or is_steam_signal
            or is_riot_game_signal
            or is_version_game_signal
            or is_game_path_signal
            or is_game_pub_signal
        ):
            return None

        # Determine platform label
        if is_steam_signal:
            platform_label = "Steam"
        elif is_riot_game_signal or "riot games" in pub:
            platform_label = "Riot Games"
        elif "rockstar" in pub or "\\rockstar games\\" in inst_loc:
            platform_label = "Rockstar Games"
        elif "\\epic games\\" in inst_loc:
            platform_label = "Epic Games"
        elif "\\gog games\\" in inst_loc:
            platform_label = "GOG"
        elif "\\ubisoft" in inst_loc or "ubisoft" in pub:
            platform_label = "Ubisoft"
        elif "\\ea games\\" in inst_loc or "electronic arts" in pub:
            platform_label = "EA"
        elif known_game and known_game.get("platform"):
            platform_label = str(known_game["platform"])
        else:
            platform_label = "PC Game"

        if known_game:
            status = str(known_game.get("status", "check_protondb"))
            note = str(known_game.get("note", ""))
        elif is_riot_game_signal:
            status = "anticheat_blocked"
            note = (
                "Riot Games PC titles requiring Riot Vanguard (Windows kernel-mode anti-cheat) are not supported "
                "on Linux. Do not attempt to bypass anti-cheat protections."
            )
        else:
            status = "check_protondb"
            note = (
                "Check community Proton compatibility reports on ProtonDB and multiplayer anti-cheat status "
                "on AreWeAntiCheatYet before switching."
            )

        clean_name = strip_bidi(app.name)
        encoded_q = urllib.parse.quote_plus(clean_name)
        protondb_url = (
            f"https://www.protondb.com/app/{steam_app_id}"
            if is_safe_steam_app_id(steam_app_id)
            else f"https://www.protondb.com/search?q={encoded_q}"
        )
        anticheat_url = f"https://areweanticheatyet.com/?search={encoded_q}"

        return {
            "name": clean_name,
            "publisher": strip_bidi(app.publisher),
            "version": "" if ver == "game" else strip_bidi(app.version),
            "platform": platform_label,
            "steam_app_id": steam_app_id,
            "status": status,
            "status_label": GAME_STATUS_LABELS.get(status, "Check ProtonDB"),
            "note": note,
            "protondb_url": protondb_url,
            "anticheat_url": anticheat_url,
        }

    def _classify_os_builtin(self, app: InstalledApp) -> str | None:
        """Step 5: Language-independent Windows OS built-in & runtime classification."""
        name = _norm(app.name)
        wid = _norm(app.winget_id)
        pid = _norm(app.package_id)
        pub = _norm(app.publisher)
        combined_ids = f"{wid} {pid}"

        # 100% language-independent Windows Store / AppX publisher & family ID checks
        if pid.startswith(OS_BUILTIN_MSIX_PREFIXES) or pid.endswith(OS_BUILTIN_FAMILY_SUFFIXES):
            if any(rt in pid for rt in ("runtime", "vclibs", "xaml", "dotnet", "net.native")):
                return "Windows System Runtime / Framework"
            return "Windows Built-in App / Codec"

        if any(tok in combined_ids for tok in OS_BUILTIN_ID_TOKENS):
            if any(rt in combined_ids for rt in ("runtime", "vcredist", "vclibs", "xaml", "dotnet", "webview")):
                return "Windows System Runtime / Framework"
            return "Windows Built-in App / Codec"

        if name == "copilot" and "microsoft" in pub:
            return "Windows Built-in App / Codec"

        if any(tok in name for tok in OS_BUILTIN_FALLBACK_NAME_TOKENS):
            if any(rt in name for rt in ("runtime", "sdk", "crt", "update", "hotfix", "framework", "verifier", "certification")):
                return "Windows System Runtime / Framework"
            return "Windows Built-in App / Codec"

        return None

    def analyze_apps(
        self,
        installed_apps: list[InstalledApp],
        detected_runtime_ids: list[str] | None = None,
        hardware_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Classify installed Windows apps + dev runtimes into 5 structured migration buckets."""
        matched_map: dict[str, dict[str, Any]] = {}
        hw_map: dict[str, dict[str, Any]] = {}
        games_map: dict[str, dict[str, Any]] = {}
        os_builtins_map: dict[str, dict[str, Any]] = {}
        unmatched_map: dict[str, dict[str, Any]] = {}

        def add_hardware(rule: dict[str, Any], app: InstalledApp) -> None:
            rid = rule["id"]
            comp_name = strip_bidi(app.name)
            if rid not in hw_map:
                raw_url = str(rule.get("official_url", "")).strip()
                safe_url = raw_url if is_safe_https_url(raw_url) else ""
                d_status = str(rule.get("driver_status", "oem_utility"))
                hw_map[rid] = {
                    "id": rid,
                    "name": rule["name"],
                    "driver_status": d_status,
                    "driver_status_label": DRIVER_STATUS_LABELS.get(d_status, "Hardware / OEM Utility"),
                    "summary": rule.get("summary", ""),
                    "official_url": safe_url,
                    "detected_components": [comp_name] if comp_name else [],
                    "component_count": 1 if comp_name else 0,
                }
            else:
                if comp_name and comp_name not in hw_map[rid]["detected_components"]:
                    hw_map[rid]["detected_components"].append(comp_name)
                    hw_map[rid]["component_count"] = len(hw_map[rid]["detected_components"])

        def add_os_builtin(app: InstalledApp, reason: str) -> None:
            key = normalize_app_key(app.name)
            if not key:
                return
            if key not in os_builtins_map:
                os_builtins_map[key] = {
                    "name": strip_bidi(app.name),
                    "version": strip_bidi(app.version),
                    "package_id": strip_bidi(app.package_id),
                    "reason": reason,
                }
            elif not os_builtins_map[key]["version"] and app.version:
                os_builtins_map[key]["version"] = strip_bidi(app.version)

        for app in installed_apps:
            # Step 1: Pre-exclusion OS/app sub-components
            pre_reason = self._classify_pre_exclusion_builtin(app)
            if pre_reason:
                add_os_builtin(app, pre_reason)
                continue

            # Step 2: Hardware & Drivers (consolidated by vendor/subsystem)
            hw_rule = self._match_hardware_driver(app)
            if hw_rule:
                add_hardware(hw_rule, app)
                continue

            # Step 3: Detected PC Games (launchers/SDKs/anti-cheat skip to Step 4)
            game_item = self._classify_game(app)
            if game_item:
                gkey = normalize_app_key(game_item["name"])
                if gkey not in games_map:
                    games_map[gkey] = game_item
                else:
                    # Enrich with Steam AppID / direct ProtonDB link if a second source found it
                    if game_item["steam_app_id"] and not games_map[gkey]["steam_app_id"]:
                        games_map[gkey]["steam_app_id"] = game_item["steam_app_id"]
                        games_map[gkey]["protondb_url"] = game_item["protondb_url"]
                        games_map[gkey]["platform"] = "Steam"
                    if game_item["publisher"] and not games_map[gkey]["publisher"]:
                        games_map[gkey]["publisher"] = game_item["publisher"]
                continue

            # Step 4: Curated Applications & Dev Tools
            entry = self.match_app(app)
            if entry:
                eid = entry["id"]
                if eid not in matched_map:
                    matched_map[eid] = self._build_matched_item(entry, [app])
                else:
                    matched_map[eid]["detected_instances"].append(app.to_dict())
                    if not matched_map[eid]["detected_version"] and app.version:
                        matched_map[eid]["detected_version"] = strip_bidi(app.version)
                continue

            # Step 5: Language-independent Windows OS Built-ins & System Runtimes
            builtin_reason = self._classify_os_builtin(app)
            if builtin_reason:
                add_os_builtin(app, builtin_reason)
                continue

            # Step 5b: Generic OEM peripheral driver fallback -> Hardware & Drivers
            if GENERIC_OEM_DRIVER_RE.search(_norm(app.name)) and "hw-keyboard-oem" in self.hw_by_id:
                add_hardware(self.hw_by_id["hw-keyboard-oem"], app)
                continue

            # Step 6: Genuine Other / Niche User Apps
            ukey = normalize_app_key(app.name)
            if ukey and ukey not in unmatched_map:
                unmatched_map[ukey] = {
                    "name": strip_bidi(app.name),
                    "version": strip_bidi(app.version),
                    "publisher": strip_bidi(app.publisher),
                    "source": app.source,
                    "winget_id": strip_bidi(app.winget_id),
                    "package_id": strip_bidi(app.package_id),
                }

        # Merge detected CLI/project runtimes (git, node, python, deno, ollama, docker, etc.)
        for rt_id in detected_runtime_ids or []:
            if rt_id in self.by_id and rt_id not in matched_map:
                entry = self.by_id[rt_id]
                synthetic = InstalledApp(
                    name=entry["name"],
                    source="dev_env",
                )
                matched_map[rt_id] = self._build_matched_item(entry, [synthetic])

        # Merge directly probed system hardware (GPUs, CPU arch/Snapdragon ARM64) even if no OEM app was installed
        hw_prof = hardware_profile if isinstance(hardware_profile, dict) else {}
        if hw_prof:
            if hw_prof.get("is_arm64") and "hw-qualcomm-snapdragon" in self.hw_by_id:
                cpu_label = strip_bidi(str(hw_prof.get("cpu") or "ARM64 Processor"))
                add_hardware(
                    self.hw_by_id["hw-qualcomm-snapdragon"],
                    InstalledApp(name=f"{cpu_label} (ARM64)", source="hardware"),
                )
            for gpu_desc in hw_prof.get("gpus") or []:
                g_str = strip_bidi(str(gpu_desc))
                g_low = _norm(g_str)
                if not g_low:
                    continue
                if "nvidia" in g_low and "hw-nvidia" in self.hw_by_id:
                    add_hardware(self.hw_by_id["hw-nvidia"], InstalledApp(name=g_str, source="hardware"))
                elif ("amd" in g_low or "radeon" in g_low) and "hw-amd" in self.hw_by_id:
                    add_hardware(self.hw_by_id["hw-amd"], InstalledApp(name=g_str, source="hardware"))
                elif "intel" in g_low and "hw-intel" in self.hw_by_id:
                    add_hardware(self.hw_by_id["hw-intel"], InstalledApp(name=g_str, source="hardware"))
                elif ("qualcomm" in g_low or "adreno" in g_low) and "hw-qualcomm-snapdragon" in self.hw_by_id:
                    add_hardware(self.hw_by_id["hw-qualcomm-snapdragon"], InstalledApp(name=g_str, source="hardware"))

        # Sort each bucket predictably
        status_rank = {"native": 0, "alternative": 1, "compat": 2, "attention": 3}
        matched_items = sorted(
            matched_map.values(),
            key=lambda x: (status_rank.get(x["status"], 9), x["category"], x["name"].lower()),
        )
        hardware_items = sorted(
            hw_map.values(),
            key=lambda x: (DRIVER_STATUS_RANK.get(x["driver_status"], 9), x["name"].lower()),
        )
        game_items = sorted(
            games_map.values(),
            key=lambda x: (GAME_STATUS_RANK.get(x["status"], 9), x["name"].lower()),
        )
        os_builtin_items = sorted(os_builtins_map.values(), key=lambda x: x["name"].lower())
        unmatched_items = sorted(unmatched_map.values(), key=lambda x: x["name"].lower())

        counts = {
            "native": sum(1 for m in matched_items if m["status"] == "native"),
            "alternative": sum(1 for m in matched_items if m["status"] == "alternative"),
            "compat": sum(1 for m in matched_items if m["status"] == "compat"),
            "attention": sum(1 for m in matched_items if m["status"] == "attention"),
            "total_matched": len(matched_items),
            "hardware_drivers": len(hardware_items),
            "games": len(game_items),
            "games_anticheat_blocked": sum(1 for g in game_items if g["status"] == "anticheat_blocked"),
            "os_builtins": len(os_builtin_items),
            "unmatched": len(unmatched_items),
        }

        readiness_score = self._compute_readiness_score(counts)

        return {
            "categories": self.categories,
            "matched": matched_items,
            "hardware_drivers": hardware_items,
            "hardware_profile": hw_prof,
            "games": game_items,
            "os_builtins": os_builtin_items,
            "unmatched": unmatched_items,
            "counts": counts,
            "readiness_score": readiness_score,
        }

    def _build_matched_item(
        self,
        entry: dict[str, Any],
        instances: list[InstalledApp],
    ) -> dict[str, Any]:
        alternatives = entry.get("alternatives", [])
        default_alt_id = None
        if alternatives:
            rec = next((a for a in alternatives if a.get("recommended")), alternatives[0])
            default_alt_id = rec["id"]

        status = entry["status"]
        no_install_needed = bool(entry.get("no_install_needed", False))
        # Auto-select native, alternative, and compat items unless no install is needed (e.g. WSL)
        default_selected = (not no_install_needed) and status in ("native", "alternative", "compat")
        cat_id = entry["category"]
        cat_label = self.categories.get(cat_id, {}).get("label", cat_id.title())

        return {
            "id": entry["id"],
            "name": entry["name"],
            "category": cat_id,
            "category_label": cat_label,
            "status": status,
            "no_install_needed": no_install_needed,
            "summary": entry.get("summary", ""),
            "linux_packages": entry.get("linux_packages", {}),
            "alternatives": alternatives,
            "selected": default_selected,
            "selected_alternative_id": default_alt_id,
            "detected_name": strip_bidi(instances[0].name),
            "detected_version": strip_bidi(instances[0].version),
            "detected_publisher": strip_bidi(instances[0].publisher),
            "detected_instances": [i.to_dict() for i in instances],
        }

    @staticmethod
    def _compute_readiness_score(counts: dict[str, int]) -> int:
        total = counts["total_matched"]
        extra_attn = 1 if counts.get("games_anticheat_blocked", 0) > 0 and counts["attention"] == 0 else 0
        denom = total + extra_attn
        if denom == 0:
            return 100
        weighted = (
            counts["native"] * 1.0
            + counts["alternative"] * 0.88
            + counts["compat"] * 0.72
            + (counts["attention"] + extra_attn) * 0.25
        )
        return max(0, min(100, round((weighted / denom) * 100)))
