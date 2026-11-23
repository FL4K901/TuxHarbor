"""Windows installed applications scanner (Registry + winget + read-only Steam + Scoop/Choco)."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from tuxharbor.models import InstalledApp, contains_control_or_crlf, is_safe_steam_app_id


# Invisible Unicode BiDi marks frequently emitted in localized Windows display names
BIDI_CONTROL_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
HEADER_COL_RE = re.compile(r"(?:^|\s{2,})(\S+)")
MULTI_SPACE_RE = re.compile(r"\s{2,}")
VERSION_PREFIX_RE = re.compile(r"\A[<>]=?\s*")

# Strictly read-only, OWASP-bounded Steam manifest scanning constants
MAX_VDF_BYTES = 2 * 1024 * 1024  # 2 MB cap for libraryfolders.vdf
MAX_ACF_BYTES = 512 * 1024       # 512 KB cap for appmanifest_*.acf
MAX_STEAM_LIBRARIES = 32
MAX_STEAM_MANIFESTS = 500
MAX_STEAM_DIR_ENTRIES = 2000
LOCAL_WIN_DRIVE_RE = re.compile(r"\A[A-Za-z]:[\\/]")
VDF_PATH_RE = re.compile(r'"path"\s+"([^"\r\n]{1,500})"')
ACF_APPID_RE = re.compile(r'"appid"\s+"([0-9]{1,10})"')
ACF_NAME_RE = re.compile(r'"name"\s+"([^"\r\n]{1,200})"')

# Non-game Steam runtime/tool entries that should not appear as PC games
STEAM_TOOL_PREFIXES = (
    "proton ",
    "steam linux runtime",
    "steamworks common redistributables",
    "steamvr",
)
STEAM_TOOL_EXACT = frozenset(
    {
        "proton experimental",
        "proton hotfix",
        "steamworks common redistributables",
        "steamvr",
    }
)

# Hidden internal MSI sub-fragments (e.g. Python sub-MSIs, Visual Studio installer shards)
INTERNAL_MSI_FRAGMENTS = (
    re.compile(r"\Apython 3\.\d+\.\d+ (?:core|development|documentation|executables|pip|standard library|tcl|test suite|utility|add to path)", re.IGNORECASE),
    re.compile(r"\Avs_[a-z0-9_]+(?:msi|community|minshell)", re.IGNORECASE),
    re.compile(r"icecap_collection", re.IGNORECASE),
    re.compile(r"intellitrace", re.IGNORECASE),
    re.compile(r"kits configuration installer", re.IGNORECASE),
    re.compile(r"clickonce bootstrapper", re.IGNORECASE),
)


def strip_bidi(text: str) -> str:
    """Remove invisible BiDi formatting marks and trim surrounding whitespace."""
    if not isinstance(text, str):
        return ""
    return BIDI_CONTROL_RE.sub("", text).strip()


def normalize_app_key(name: str) -> str:
    """Canonical deduplication key (strips BiDi, lowercases, normalizes Greek/micro mu, collapses spaces)."""
    cleaned = strip_bidi(name).lower()
    cleaned = cleaned.replace("\u03bc", "u").replace("\u00b5", "u")
    return " ".join(cleaned.split())


def _char_display_width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _display_width(text: str) -> int:
    return sum(_char_display_width(ch) for ch in text)


def _clean_version(raw: str) -> str:
    """Normalize version strings and reject bogus placeholders like Unknown, >, <, or *_is1."""
    cleaned = strip_bidi(raw)
    if not cleaned or cleaned.lower() == "unknown":
        return ""
    cleaned = VERSION_PREFIX_RE.sub("", cleaned).strip()
    if not cleaned or all(ch in "<>=.-_ " for ch in cleaned):
        return ""
    upper = cleaned.upper()
    if upper.endswith("_IS1") or upper.startswith(("ARP\\", "MSIX\\")):
        return ""
    return cleaned[:80]


def _package_id_priority(pkg_id: str) -> int:
    """Rank package ID informativeness when merging duplicate entries across sources."""
    if not pkg_id:
        return 0
    low = pkg_id.lower()
    if "steam app " in low:
        return 5
    if low.startswith("msix\\"):
        return 4
    if "." in pkg_id and "\\" not in pkg_id and not pkg_id.startswith("{"):
        return 3
    if not pkg_id.startswith("{"):
        return 2
    return 1


def _pick_better_package_id(existing_id: str, new_id: str) -> str:
    if not new_id:
        return existing_id
    if not existing_id:
        return new_id
    if _package_id_priority(new_id) > _package_id_priority(existing_id):
        return new_id
    return existing_id


def _merge_app(existing: InstalledApp, incoming: InstalledApp) -> None:
    """Enrich an existing InstalledApp record with non-empty fields from another scanner source."""
    if incoming.winget_id and not existing.winget_id:
        existing.winget_id = incoming.winget_id
    if incoming.version and not existing.version:
        existing.version = incoming.version
    if incoming.publisher and not existing.publisher:
        existing.publisher = incoming.publisher
    if incoming.install_location and not existing.install_location:
        existing.install_location = incoming.install_location
    if incoming.uninstall_string and not existing.uninstall_string:
        existing.uninstall_string = incoming.uninstall_string
    existing.package_id = _pick_better_package_id(existing.package_id, incoming.package_id)


def _is_internal_msi_fragment(name: str, system_component: int = 0) -> bool:
    if system_component == 1:
        return True
    stripped = strip_bidi(name)
    if not stripped or len(stripped) < 2:
        return True
    return any(rx.search(stripped) for rx in INTERNAL_MSI_FRAGMENTS)


def _reg_str(winreg_mod, key, value_name: str) -> str:
    try:
        val, _ = winreg_mod.QueryValueEx(key, value_name)
        return str(val) if val is not None else ""
    except OSError:
        return ""


def _reg_int(winreg_mod, key, value_name: str) -> int:
    try:
        val, _ = winreg_mod.QueryValueEx(key, value_name)
        return int(val)
    except (OSError, ValueError, TypeError):
        return 0


def _scan_windows_registry(include_system_noise: bool = False) -> list[InstalledApp]:
    if platform.system() != "Windows":
        return []

    import winreg  # type: ignore

    locations = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    combined: dict[str, InstalledApp] = {}

    for root, subkey_path in locations:
        try:
            key = winreg.OpenKey(root, subkey_path)
        except OSError:
            continue

        try:
            count = winreg.QueryInfoKey(key)[0]
            for idx in range(count):
                try:
                    sub_name = winreg.EnumKey(key, idx)
                    with winreg.OpenKey(key, sub_name) as item:
                        display_name = strip_bidi(_reg_str(winreg, item, "DisplayName"))
                        if not display_name:
                            continue
                        sys_comp = _reg_int(winreg, item, "SystemComponent")
                        if not include_system_noise and _is_internal_msi_fragment(display_name, sys_comp):
                            continue

                        app = InstalledApp(
                            name=display_name,
                            version=_clean_version(_reg_str(winreg, item, "DisplayVersion")),
                            publisher=strip_bidi(_reg_str(winreg, item, "Publisher")),
                            source="registry",
                            install_location=strip_bidi(_reg_str(winreg, item, "InstallLocation")),
                            package_id=strip_bidi(sub_name),
                            uninstall_string=_reg_str(winreg, item, "UninstallString").strip()[:512],
                            system_component=sys_comp,
                        )
                        dedup_key = normalize_app_key(display_name)
                        if dedup_key in combined:
                            _merge_app(combined[dedup_key], app)
                        else:
                            combined[dedup_key] = app
                except OSError:
                    continue
        finally:
            winreg.CloseKey(key)

    return list(combined.values())


def _slice_row_by_display_width(line: str, col_starts: list[int]) -> tuple[list[str], bool]:
    """Slice a fixed-width console table row using CJK-aware display column positions."""
    idxs: list[int] = []
    width = 0
    pos = 0
    line_len = len(line)

    for target_col in col_starts:
        while pos < line_len and width < target_col:
            width += _char_display_width(line[pos])
            pos += 1
        idxs.append(pos)

    # Verify Id and Version boundaries did not slice mid-token (overflow detection)
    clean_cut = True
    for boundary_idx in idxs[1:3]:
        if 0 < boundary_idx < line_len:
            if not line[boundary_idx - 1].isspace() and not line[boundary_idx].isspace():
                clean_cut = False
                break

    slices: list[str] = []
    for i, start_i in enumerate(idxs):
        end_i = idxs[i + 1] if i + 1 < len(idxs) else line_len
        slices.append(line[start_i:end_i])
    return slices, clean_cut


def _parse_winget_output(stdout: str) -> list[InstalledApp]:
    """Parse `winget list` stdout language-independently while preserving MSIX/ARP package IDs."""
    if not stdout:
        return []

    lines: list[str] = []
    for raw_ln in stdout.splitlines():
        # Winget emits carriage-return progress spinner fragments before table headers
        if "\r" in raw_ln:
            parts = [p for p in raw_ln.split("\r") if p.strip()]
            ln = parts[-1].rstrip() if parts else ""
        else:
            ln = raw_ln.rstrip()
        if ln.strip():
            lines.append(ln)

    sep_idx = -1
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if len(stripped) >= 20 and set(stripped) == {"-"}:
            sep_idx = i
            break
    if sep_idx <= 0:
        return []

    header = lines[sep_idx - 1]
    col_starts = [_display_width(header[: m.start(1)]) for m in HEADER_COL_RE.finditer(header)]
    if len(col_starts) < 3:
        return []

    deduped: dict[str, InstalledApp] = {}
    for ln in lines[sep_idx + 1 :]:
        if len(ln.strip()) < 3:
            continue

        slices, clean_cut = _slice_row_by_display_width(ln, col_starts)
        if clean_cut:
            raw_name = slices[0]
            raw_id = slices[1] if len(slices) > 1 else ""
            raw_ver = slices[2] if len(slices) > 2 else ""
        else:
            # Overflow / BiDi-shift fallback: prefer 2+ space split when it yields Name/Id/Version
            tokens = MULTI_SPACE_RE.split(ln.strip())
            if len(tokens) >= 3 and ("." in tokens[1] or "\\" in tokens[1]):
                raw_name, raw_id, raw_ver = tokens[0], tokens[1], tokens[2]
            else:
                # Snap boundaries forward to whitespace transitions when columns shifted slightly
                snapped: list[int] = [0]
                shift = 0
                line_len = len(ln)
                base_idxs: list[int] = []
                w = 0
                p = 0
                for cpos in col_starts:
                    while p < line_len and w < cpos:
                        w += _char_display_width(ln[p])
                        p += 1
                    base_idxs.append(p)
                for b_idx in base_idxs[1:]:
                    cur = min(line_len, b_idx + shift)
                    if 0 < cur < line_len and not ln[cur - 1].isspace() and not ln[cur].isspace():
                        old = cur
                        while cur < line_len and not ln[cur].isspace():
                            cur += 1
                        while cur < line_len and ln[cur].isspace():
                            cur += 1
                        shift += cur - old
                    snapped.append(cur)
                raw_name = ln[snapped[0] : snapped[1]] if len(snapped) > 1 else ln
                raw_id = ln[snapped[1] : snapped[2]] if len(snapped) > 2 else (ln[snapped[1] :] if len(snapped) > 1 else "")
                raw_ver = (
                    ln[snapped[2] : snapped[3]]
                    if len(snapped) > 3
                    else (ln[snapped[2] :] if len(snapped) > 2 else "")
                )

        name = strip_bidi(raw_name)
        package_id = strip_bidi(raw_id)
        version = _clean_version(raw_ver)

        # Skip trailing summary lines (e.g. "12 upgrades available.") that lack an Id column
        if not name or not package_id:
            continue

        upper_id = package_id.upper()
        winget_id = "" if upper_id.startswith(("ARP\\", "MSIX\\")) else package_id

        app = InstalledApp(
            name=name,
            version=version,
            source="winget",
            winget_id=winget_id,
            package_id=package_id,
        )
        key = normalize_app_key(name)
        if key in deduped:
            _merge_app(deduped[key], app)
        else:
            deduped[key] = app

    return list(deduped.values())


def _scan_winget(include_system_noise: bool = False) -> list[InstalledApp]:
    """Enrich discovery with winget list (preserves both winget catalog IDs and MSIX/ARP IDs)."""
    if platform.system() != "Windows":
        return []
    winget_bin = shutil.which("winget")
    if not winget_bin:
        return []
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        res = subprocess.run(
            [winget_bin, "list", "--accept-source-agreements", "--disable-interactivity"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=15,
            shell=False,
            creationflags=creationflags,
        )
        if res.returncode != 0 or not res.stdout:
            return []
    except (OSError, subprocess.TimeoutExpired):
        return []

    parsed = _parse_winget_output(res.stdout)
    if include_system_noise:
        return parsed
    return [app for app in parsed if not _is_internal_msi_fragment(app.name, app.system_component)]


def _is_reparse_link(path: Path) -> bool:
    """Return True if path is a POSIX/Windows symlink or a Windows NTFS junction."""
    try:
        if path.is_symlink():
            return True
        is_junc = getattr(path, "is_junction", None)
        if callable(is_junc) and is_junc():
            return True
    except OSError:
        return True
    return False


def _is_safe_local_dir(raw_path: str, *, require_win_drive: bool | None = None) -> Path | None:
    """Validate a local directory path strictly, blocking UNC/SMB network paths, symlinks, and junctions."""
    if not isinstance(raw_path, str):
        return None
    cleaned = raw_path.strip()
    if not cleaned or contains_control_or_crlf(cleaned):
        return None
    if cleaned.startswith(("\\\\", "//")):
        return None
    win_mode = (platform.system() == "Windows") if require_win_drive is None else require_win_drive
    if win_mode and not LOCAL_WIN_DRIVE_RE.match(cleaned):
        return None
    p = Path(cleaned)
    if ".." in p.parts:
        return None
    try:
        if _is_reparse_link(p) or not p.is_dir():
            return None
    except OSError:
        return None
    return p


def _read_bounded_text(file_path: Path, max_bytes: int) -> str:
    """Read a regular non-link UTF-8 file with TOCTOU-safe byte limit enforcement."""
    try:
        if _is_reparse_link(file_path) or not file_path.is_file():
            return ""
        if file_path.stat().st_size > max_bytes:
            return ""
        with file_path.open("rb") as fh:
            data = fh.read(max_bytes + 1)
        if len(data) > max_bytes:
            return ""
        return data.decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _parse_steam_library_folders_vdf(content: str) -> list[str]:
    """Extract raw library folder paths from Steam's libraryfolders.vdf (pure helper)."""
    if not content:
        return []
    paths: list[str] = []
    for match in VDF_PATH_RE.finditer(content):
        unescaped = match.group(1).replace("\\\\", "\\").strip()
        if unescaped and len(paths) < MAX_STEAM_LIBRARIES:
            paths.append(unescaped)
    return paths


def _parse_steam_appmanifest_acf(content: str) -> tuple[str, str] | None:
    """Extract validated (appid, name) from a Steam appmanifest_*.acf file (pure helper)."""
    if not content:
        return None
    id_match = ACF_APPID_RE.search(content)
    name_match = ACF_NAME_RE.search(content)
    if not id_match or not name_match:
        return None
    appid = id_match.group(1).strip()
    name = strip_bidi(name_match.group(1))
    if not is_safe_steam_app_id(appid) or not name:
        return None
    return appid, name


def _is_steam_non_game_tool(name: str) -> bool:
    low = name.lower().strip()
    return low in STEAM_TOOL_EXACT or low.startswith(STEAM_TOOL_PREFIXES)


def _discover_steam_roots() -> list[Path]:
    """Locate local Steam installation directories from Windows Registry and default path."""
    if platform.system() != "Windows":
        return []

    import winreg  # type: ignore

    raw_candidates: list[str] = []
    reg_queries = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ]
    for root, subkey, val_name in reg_queries:
        try:
            with winreg.OpenKey(root, subkey) as key:
                val = _reg_str(winreg, key, val_name)
                if val:
                    raw_candidates.append(val.replace("/", "\\"))
        except OSError:
            continue

    raw_candidates.append(r"C:\Program Files (x86)\Steam")

    roots: list[Path] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        safe_dir = _is_safe_local_dir(raw, require_win_drive=True)
        if not safe_dir:
            continue
        try:
            norm = str(safe_dir.resolve()).lower()
        except OSError:
            continue
        if norm not in seen:
            seen.add(norm)
            roots.append(safe_dir)
    return roots


def _scan_steam_games(steam_roots: list[Path] | None = None) -> list[InstalledApp]:
    """Read-only Steam library scanner reading bounded libraryfolders.vdf and appmanifest_*.acf files."""
    if steam_roots is None:
        if platform.system() != "Windows":
            return []
        roots = _discover_steam_roots()
        require_win = True
    else:
        roots = steam_roots
        require_win = platform.system() == "Windows"

    if not roots:
        return []

    lib_dirs: list[Path] = []
    seen_libs: set[str] = set()

    def add_lib(candidate: Path) -> None:
        if len(lib_dirs) >= MAX_STEAM_LIBRARIES:
            return
        try:
            if _is_reparse_link(candidate) or not candidate.is_dir():
                return
            norm = str(candidate.resolve()).lower()
        except OSError:
            return
        if norm not in seen_libs:
            seen_libs.add(norm)
            lib_dirs.append(candidate)

    for root in roots:
        add_lib(root)
        steamapps = root / "steamapps"
        try:
            if _is_reparse_link(steamapps) or not steamapps.is_dir():
                continue
        except OSError:
            continue
        vdf_text = _read_bounded_text(steamapps / "libraryfolders.vdf", MAX_VDF_BYTES)
        for raw_lib in _parse_steam_library_folders_vdf(vdf_text):
            safe_lib = _is_safe_local_dir(raw_lib, require_win_drive=require_win)
            if safe_lib:
                add_lib(safe_lib)

    games: list[InstalledApp] = []
    seen_appids: set[str] = set()
    manifests_checked = 0
    dir_entries_checked = 0

    for lib in lib_dirs:
        steamapps = lib / "steamapps"
        try:
            if _is_reparse_link(steamapps) or not steamapps.is_dir():
                continue
            entries_iter = steamapps.iterdir()
        except OSError:
            continue

        try:
            for entry in entries_iter:
                dir_entries_checked += 1
                if dir_entries_checked > MAX_STEAM_DIR_ENTRIES or manifests_checked >= MAX_STEAM_MANIFESTS:
                    return games
                if not (entry.name.startswith("appmanifest_") and entry.name.endswith(".acf")):
                    continue
                manifests_checked += 1
                acf_text = _read_bounded_text(entry, MAX_ACF_BYTES)
                parsed = _parse_steam_appmanifest_acf(acf_text)
                if not parsed:
                    continue
                appid, name = parsed
                if appid in seen_appids or _is_steam_non_game_tool(name):
                    continue
                seen_appids.add(appid)
                games.append(
                    InstalledApp(
                        name=name,
                        publisher="Steam",
                        source="steam",
                        package_id=f"Steam App {appid}",
                    )
                )
        except OSError:
            continue

    return games


def _scan_scoop_and_choco() -> list[InstalledApp]:
    apps: list[InstalledApp] = []
    scoop_dir = Path.home() / "scoop" / "apps"
    if scoop_dir.is_dir() and not _is_reparse_link(scoop_dir):
        try:
            for child in scoop_dir.iterdir():
                if child.is_dir() and not _is_reparse_link(child) and child.name.lower() != "scoop":
                    apps.append(InstalledApp(name=child.name, source="scoop", package_id=child.name))
        except OSError:
            pass

    choco_dir = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "chocolatey" / "lib"
    if choco_dir.is_dir() and not _is_reparse_link(choco_dir):
        try:
            for child in choco_dir.iterdir():
                if child.is_dir() and not _is_reparse_link(child) and not child.name.lower().startswith("chocolatey"):
                    apps.append(InstalledApp(name=child.name, source="choco", package_id=child.name))
        except OSError:
            pass
    return apps


def scan_installed_apps(
    include_winget: bool = True,
    include_system_noise: bool = False,
    demo_mode: bool = False,
) -> list[InstalledApp]:
    """Scan installed Windows applications, drivers, and Steam games and deduplicate cleanly."""
    if demo_mode or platform.system() != "Windows":
        if demo_mode:
            return get_demo_apps()
        return []

    combined: dict[str, InstalledApp] = {}

    def ingest(items: list[InstalledApp]) -> None:
        for app in items:
            key = normalize_app_key(app.name)
            if not key:
                continue
            if key in combined:
                _merge_app(combined[key], app)
            else:
                combined[key] = app

    ingest(_scan_windows_registry(include_system_noise=include_system_noise))
    if include_winget:
        ingest(_scan_winget(include_system_noise=include_system_noise))
    ingest(_scan_steam_games())
    ingest(_scan_scoop_and_choco())

    return sorted(combined.values(), key=lambda a: a.name.lower())


def detect_system_hardware(demo_mode: bool = False) -> dict[str, object]:
    """Read-only hardware probe (CPU architecture/model, GPUs, system OEM) via stdlib winreg & platform.

    Detects x86_64 vs ARM64 (e.g. Qualcomm Snapdragon), NVIDIA/AMD/Intel/Adreno GPUs, and PC OEM
    with zero subprocesses, zero elevation, and zero network access.
    """
    if demo_mode:
        return {
            "arch": "x86_64",
            "is_arm64": False,
            "cpu": "Demo x86-64 Processor",
            "gpus": ["NVIDIA GeForce RTX 4070", "Intel(R) UHD Graphics"],
            "manufacturer": "Demo PC",
            "model": "Demo Workstation",
        }

    raw_machine = (platform.machine() or "").strip()
    machine_low = raw_machine.lower()
    is_arm64 = any(tok in machine_low for tok in ("arm64", "aarch64"))
    arch = "ARM64" if is_arm64 else ("x86_64" if machine_low in ("amd64", "x86_64", "x64") else (raw_machine or "Unknown"))

    cpu = strip_bidi(platform.processor() or "")
    gpus: list[str] = []
    manufacturer = ""
    model = ""

    if platform.system() == "Windows":
        import winreg  # type: ignore

        # 1. CPU brand string
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as cpu_key:
                cpu_name = strip_bidi(_reg_str(winreg, cpu_key, "ProcessorNameString"))
                if cpu_name:
                    cpu = cpu_name
        except OSError:
            pass

        # 2. System BIOS Manufacturer & Product Name
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\BIOS",
            ) as bios_key:
                manufacturer = strip_bidi(_reg_str(winreg, bios_key, "SystemManufacturer"))
                model = strip_bidi(_reg_str(winreg, bios_key, "SystemProductName"))
        except OSError:
            pass

        # 3. Display Adapters (GPU class GUID {4d36e968-e325-11ce-bfc1-08002be10318})
        gpu_class_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, gpu_class_path) as gpu_root:
                sub_count = min(winreg.QueryInfoKey(gpu_root)[0], 16)
                seen_gpus: set[str] = set()
                for idx in range(sub_count):
                    try:
                        sub_name = winreg.EnumKey(gpu_root, idx)
                        if not sub_name.isdigit():
                            continue
                        with winreg.OpenKey(gpu_root, sub_name) as dev_key:
                            desc = strip_bidi(_reg_str(winreg, dev_key, "DriverDesc"))
                            if desc and desc.lower() not in seen_gpus and "basic display" not in desc.lower():
                                seen_gpus.add(desc.lower())
                                gpus.append(desc)
                    except OSError:
                        continue
        except OSError:
            pass

        if "snapdragon" in cpu.lower() or "qualcomm" in cpu.lower():
            is_arm64 = True
            arch = "ARM64"

    return {
        "arch": arch,
        "is_arm64": is_arm64,
        "cpu": cpu[:160],
        "gpus": gpus[:8],
        "manufacturer": manufacturer[:120],
        "model": model[:120],
    }


def get_demo_apps() -> list[InstalledApp]:
    """Realistic demo Windows PC app set showcasing all 5 smart classification buckets."""
    return [
        # Applications & Dev Tools
        InstalledApp("Google Chrome", "131.0.6778", "Google LLC", "registry", winget_id="Google.Chrome", package_id="Google.Chrome"),
        InstalledApp("Visual Studio Code", "1.95.3", "Microsoft Corporation", "registry", winget_id="Microsoft.VisualStudioCode", package_id="Microsoft.VisualStudioCode"),
        InstalledApp("Notepad++ (64-bit x64)", "8.7.1", "Notepad++ Team", "registry", winget_id="Notepad++.Notepad++", package_id="Notepad++.Notepad++"),
        InstalledApp("Docker Desktop", "4.36.0", "Docker Inc.", "registry", winget_id="Docker.DockerDesktop", package_id="Docker.DockerDesktop"),
        InstalledApp("Git", "2.47.1", "The Git Development Community", "registry", winget_id="Git.Git", package_id="Git.Git"),
        InstalledApp("Node.js", "22.11.0", "Node.js Foundation", "registry", winget_id="OpenJS.NodeJS", package_id="OpenJS.NodeJS"),
        InstalledApp("Python 3.13.1", "3.13.1", "Python Software Foundation", "registry", package_id="Python.Python.3.13"),
        InstalledApp("Deno", "2.1.0", "Deno Land Inc.", "winget", winget_id="DenoLand.Deno", package_id="DenoLand.Deno"),
        InstalledApp("Ollama", "0.5.0", "Ollama", "registry", winget_id="Ollama.Ollama", package_id="Ollama.Ollama"),
        InstalledApp("Microsoft 365 Apps for enterprise", "16.0.18129", "Microsoft Corporation", "registry", package_id="O365ProPlusRetail - en-us"),
        InstalledApp("Adobe Photoshop 2025", "26.1", "Adobe Inc.", "registry"),
        InstalledApp("Paint.NET", "5.1", "dotPDN LLC", "registry"),
        InstalledApp("ShareX", "16.1.0", "ShareX Team", "registry"),
        InstalledApp("7-Zip 24.08 (x64)", "24.08", "Igor Pavlov", "registry"),
        InstalledApp("Everything 1.4.1", "1.4.1", "voidtools", "registry"),
        InstalledApp("Discord", "1.0.9173", "Discord Inc.", "registry"),
        InstalledApp("Spotify", "1.2.50", "Spotify AB", "registry"),
        InstalledApp("WhatsApp", "2.2448", "WhatsApp Inc.", "winget"),
        InstalledApp("Obsidian", "1.7.7", "Obsidian", "registry"),
        InstalledApp("Postman", "11.21.0", "Postman", "registry"),
        InstalledApp("HeidiSQL 12.8", "12.8", "Ansgar Becker", "registry"),
        InstalledApp("VLC media player", "3.0.21", "VideoLAN", "registry"),
        InstalledApp("Rufus", "4.6", "Pete Batard", "winget"),
        InstalledApp("KeePassXC", "2.7.9", "KeePassXC Team", "registry"),
        # Hardware & Drivers
        InstalledApp("NVIDIA Graphics Driver 566.14", "566.14", "NVIDIA Corporation", "registry", package_id="{B2FE1952-0186-46C3-BAEC-A80AA35AC5B8}_Display.Driver"),
        InstalledApp("NVIDIA App", "11.0.1", "NVIDIA Corporation", "registry", winget_id="Nvidia.NvidiaApp", package_id="Nvidia.NvidiaApp"),
        InstalledApp("Intel Graphics Software", "26.1.0", "Intel Corporation", "registry", package_id="Intel.GraphicsSoftware"),
        # Game Launchers & Detected PC Games
        InstalledApp("Steam", "2.10.91", "Valve Corporation", "registry", winget_id="Valve.Steam", package_id="Valve.Steam"),
        InstalledApp("Epic Games Launcher", "1.3.128", "Epic Games, Inc.", "registry"),
        InstalledApp("Riot Vanguard", "1.0", "Riot Games", "registry"),
        InstalledApp("ELDEN RING", "", "FromSoftware", "steam", package_id="Steam App 1245620"),
        InstalledApp("Teamfight Tactics", "Game", "Riot Games, Inc", "registry", package_id="Riot Game teamfighttactics.live"),
        # Windows OS Built-ins & System Runtimes (auto-collapsed)
        InstalledApp("Windows Calculator", "11.2405.2.0", "Microsoft Corporation", "winget", package_id="MSIX\\Microsoft.WindowsCalculator_11.2405.2.0_x64__8wekyb3d8bbwe"),
        InstalledApp("Microsoft Windows Desktop Runtime - 8.0.14 (x64)", "8.0.14", "Microsoft Corporation", "registry", package_id="Microsoft.DotNet.DesktopRuntime.8"),
        # Genuine Niche App (Unmatched)
        InstalledApp("MyCustomCompanyVPNTool", "2.4.1", "Internal Corp", "registry"),
    ]
