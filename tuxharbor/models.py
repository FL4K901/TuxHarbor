"""Data models and strict security validation helpers for TuxHarbor."""

from __future__ import annotations

import ipaddress
import re
import urllib.parse
from dataclasses import dataclass, field, asdict
from typing import Any


# Strict allowlists anchored with \A...\Z (blocks trailing-newline $ bypass in Python re!)
SAFE_PKG_RE = re.compile(r"\A[a-zA-Z0-9][a-zA-Z0-9._+-]*\Z")
SAFE_FLATPAK_RE = re.compile(r"\A[a-zA-Z0-9_][a-zA-Z0-9_-]*(?:\.[a-zA-Z0-9_-]+){2,}\Z")
SAFE_NPM_RE = re.compile(r"\A(?:@[a-zA-Z0-9][a-zA-Z0-9._-]*/)?[a-zA-Z0-9][a-zA-Z0-9._-]*\Z")
SAFE_EXT_RE = re.compile(r"\A[a-zA-Z0-9][a-zA-Z0-9_-]*\.[a-zA-Z0-9][a-zA-Z0-9._-]*\Z")
SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")
SAFE_HOST_RE = re.compile(r"\A[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?\Z")
SAFE_EMAIL_RE = re.compile(r"\A[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+\Z")
SAFE_STEAM_APP_ID_RE = re.compile(r"\A[0-9]{1,10}\Z")

WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def contains_control_or_crlf(value: str) -> bool:
    """Return True if value is not a str or contains CR, LF, NUL, or any ASCII control char."""
    if not isinstance(value, str):
        return True
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def is_safe_package_name(name: str) -> bool:
    """Validate native Linux distro package names (apt/dnf/pacman/zypper) against shell/option/path injection."""
    if not isinstance(name, str) or not name or len(name) > 160:
        return False
    if contains_control_or_crlf(name) or ".." in name:
        return False
    return bool(SAFE_PKG_RE.match(name))


def is_safe_flatpak_id(app_id: str) -> bool:
    """Validate reverse-DNS Flathub/Flatpak application IDs (e.g. com.visualstudio.code)."""
    if not isinstance(app_id, str) or not app_id or len(app_id) > 160:
        return False
    if contains_control_or_crlf(app_id) or ".." in app_id:
        return False
    return bool(SAFE_FLATPAK_RE.match(app_id))


def is_safe_npm_package(pkg: str) -> bool:
    """Validate npm global package names (unscoped or @scope/pkg) without path/option/shell injection."""
    if not isinstance(pkg, str) or not pkg or len(pkg) > 160:
        return False
    if contains_control_or_crlf(pkg) or ".." in pkg:
        return False
    return bool(SAFE_NPM_RE.match(pkg))


def is_safe_vscode_extension(ext_id: str) -> bool:
    """Validate VS Code extension IDs (publisher.extension), rejecting leading dashes and control chars."""
    if not isinstance(ext_id, str) or not ext_id or len(ext_id) > 160:
        return False
    if contains_control_or_crlf(ext_id) or ".." in ext_id:
        return False
    return bool(SAFE_EXT_RE.match(ext_id))


def is_safe_email(addr: str) -> bool:
    """Validate email addresses strictly and block SMTP header injection (CR/LF/control chars)."""
    if not isinstance(addr, str) or not addr or len(addr) > 254:
        return False
    if contains_control_or_crlf(addr) or ".." in addr:
        return False
    if not SAFE_EMAIL_RE.match(addr):
        return False
    local, _, domain = addr.partition("@")
    if not local or len(local) > 64 or local.startswith(".") or local.endswith("."):
        return False
    return "." in domain and is_safe_hostname(domain)


def is_safe_hostname(host: str) -> bool:
    """Validate an RFC 1123 hostname or IP address strictly without control characters."""
    if not isinstance(host, str) or not host or len(host) > 253:
        return False
    if contains_control_or_crlf(host) or ".." in host:
        return False
    # Accept literal IPv4/IPv6 addresses cleanly
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if not SAFE_HOST_RE.match(host):
        return False
    labels = host.split(".")
    return all(1 <= len(lbl) <= 63 and not lbl.startswith("-") and not lbl.endswith("-") for lbl in labels)


def is_safe_https_url(url: str) -> bool:
    """Allow only clean, non-whitespace HTTPS URLs (blocks javascript:, file:, data:, userinfo, CR/LF)."""
    if not isinstance(url, str) or not url or len(url) > 2048:
        return False
    if contains_control_or_crlf(url) or any(ch.isspace() for ch in url):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if port is not None and not (1 <= port <= 65535):
        return False
    host = parsed.hostname or ""
    return bool(host) and "." in host and is_safe_hostname(host)


def is_safe_external_link(url: str) -> bool:
    """Allow only https:// or mailto: links before passing to webbrowser.open()."""
    if not isinstance(url, str) or not url or len(url) > 4096:
        return False
    if contains_control_or_crlf(url) or any(ch.isspace() for ch in url):
        return False
    if is_safe_https_url(url):
        return True
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "mailto" and (bool(parsed.path) or bool(parsed.query))


def sanitize_filename_prefix(raw: str, default: str = "tuxharbor-migration") -> str:
    """Sanitize a user-provided filename prefix against path traversal, shells, and Windows reserved names."""
    if not isinstance(raw, str):
        return default
    cleaned = raw.replace("\r", "").replace("\n", "").replace("\x00", "").strip()
    cleaned = cleaned.replace(" ", "-")
    cleaned = SAFE_FILENAME_RE.sub("", cleaned)
    while ".." in cleaned:
        cleaned = cleaned.replace("..", "-")
    cleaned = cleaned.strip(".-_")
    if not cleaned or len(cleaned) > 80:
        return default
    # Reject Windows reserved device filenames (exact match or stem before dot)
    stem = cleaned.split(".", 1)[0].upper()
    if cleaned.upper() in WINDOWS_RESERVED_NAMES or stem in WINDOWS_RESERVED_NAMES:
        return default
    return cleaned


def is_safe_steam_app_id(val: str) -> bool:
    """Validate numeric Steam AppIDs strictly (1..10 ASCII digits, no trailing newline)."""
    if not isinstance(val, str) or not val:
        return False
    return bool(SAFE_STEAM_APP_ID_RE.match(val))


def is_safe_https_url_for_hosts(url: str, allowed_hosts: tuple[str, ...]) -> bool:
    """Validate an HTTPS URL and pin its hostname strictly to an explicit allowlist."""
    if not is_safe_https_url(url):
        return False
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in allowed_hosts


@dataclass
class InstalledApp:
    name: str
    version: str = ""
    publisher: str = ""
    source: str = "registry"  # registry, winget, scoop, choco, steam, dev_env
    install_location: str = ""
    winget_id: str = ""
    package_id: str = ""
    uninstall_string: str = ""  # Internal read-only heuristic signal; never serialized or executed
    system_component: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "publisher": self.publisher,
            "source": self.source,
            "install_location": self.install_location,
            "winget_id": self.winget_id,
            "package_id": self.package_id,
        }


@dataclass
class ProjectFinding:
    name: str
    path: str
    stacks: list[str] = field(default_factory=list)
    recommended_runtimes: list[str] = field(default_factory=list)
    linux_warnings: list[dict[str, str]] = field(default_factory=list)
    backup_warnings: list[dict[str, str]] = field(default_factory=list)
    is_git_repo: bool = False
    has_remote: bool = False
    uncommitted_count: int = 0
    unpushed_count: int = 0
    has_env_files: bool = False
    compatibility: str = "ready"  # ready, warning, blocker

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DevEnvironment:
    runtimes: list[dict[str, Any]] = field(default_factory=list)
    vscode_installed: bool = False
    vscode_extensions: list[str] = field(default_factory=list)
    npm_globals: list[str] = field(default_factory=list)
    git_user_name: str = ""
    git_user_email: str = ""
    wsl_installed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
