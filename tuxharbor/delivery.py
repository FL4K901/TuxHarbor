"""Secure file saving (local/USB/cloud folders + Save As custom prefix) and verified TLS SMTP / Webmail delivery."""

from __future__ import annotations

import base64
import ctypes
import email.message
import json
import os
import platform
import re
import shutil
import smtplib
import ssl
import stat
import subprocess
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

from tuxharbor import __version__
from tuxharbor.models import (
    contains_control_or_crlf,
    is_safe_email,
    is_safe_hostname,
    sanitize_filename_prefix,
)


SMTP_PRESETS: dict[str, dict[str, Any]] = {
    "gmail": {"host": "smtp.gmail.com", "port": 587, "security": "starttls", "label": "Gmail"},
    "outlook": {"host": "smtp-mail.outlook.com", "port": 587, "security": "starttls", "label": "Outlook / Hotmail"},
    "yahoo": {"host": "smtp.mail.yahoo.com", "port": 465, "security": "ssl", "label": "Yahoo Mail"},
    "icloud": {"host": "smtp.mail.me.com", "port": 587, "security": "starttls", "label": "iCloud Mail"},
    "custom": {"host": "", "port": 587, "security": "starttls", "label": "Custom SMTP"},
}


def detect_save_locations() -> list[dict[str, str]]:
    """Auto-detect helpful save targets: connected USB drives, cloud sync folders, Desktop & Documents."""
    locations: list[dict[str, str]] = []
    home = Path.home()

    # 1. Detect removable USB drives on Windows
    if platform.system() == "Windows":
        try:
            kernel32 = ctypes.windll.kernel32
            bitmask = kernel32.GetLogicalDrives()
            for i in range(26):
                if bitmask & (1 << i):
                    letter = chr(65 + i)
                    root = f"{letter}:\\"
                    drive_type = kernel32.GetDriveTypeW(root)
                    if drive_type == 2:  # DRIVE_REMOVABLE
                        vol_buf = ctypes.create_unicode_buffer(256)
                        kernel32.GetVolumeInformationW(
                            root, vol_buf, 256, None, None, None, None, 0
                        )
                        vol_name = vol_buf.value or "USB Drive"
                        locations.append(
                            {
                                "kind": "usb",
                                "label": f"USB Drive ({letter}:\\ {vol_name})",
                                "path": str(Path(root) / "TuxHarbor"),
                            }
                        )
        except Exception:
            pass
    else:
        # Linux removable media mounts (strictly validate username against path traversal)
        user = os.environ.get("USER", "")
        if user and user not in (".", "..") and re.fullmatch(r"\A[a-zA-Z0-9._-]+\Z", user):
            for base in [Path("/media") / user, Path("/run/media") / user]:
                if base.is_dir() and not base.is_symlink():
                    try:
                        for sub in base.iterdir():
                            if sub.is_dir() and not sub.is_symlink():
                                locations.append(
                                    {
                                        "kind": "usb",
                                        "label": f"USB Drive ({sub.name})",
                                        "path": str(sub / "TuxHarbor"),
                                    }
                                )
                    except OSError:
                        pass

    # 2. Detect Cloud sync folders
    cloud_candidates = [
        ("OneDrive", os.environ.get("OneDrive")),
        ("OneDrive", str(home / "OneDrive")),
        ("Google Drive", str(home / "Google Drive")),
        ("Google Drive", str(home / "My Drive")),
        ("Dropbox", str(home / "Dropbox")),
        ("iCloud Drive", str(home / "iCloudDrive")),
    ]
    seen_paths: set[str] = set()
    for name, raw_p in cloud_candidates:
        if not raw_p:
            continue
        p = Path(raw_p)
        if p.is_dir():
            try:
                key = str(p.resolve()).lower()
            except OSError:
                continue
            if key not in seen_paths:
                seen_paths.add(key)
                locations.append(
                    {
                        "kind": "cloud",
                        "label": f"{name} (Cloud Sync)",
                        "path": str(p / "TuxHarbor"),
                    }
                )

    # 3. Standard user folders
    for folder_name, label in [
        ("Desktop", "Desktop"),
        ("Documents", "Documents"),
        ("Downloads", "Downloads"),
    ]:
        p = home / folder_name
        if p.is_dir():
            locations.append(
                {
                    "kind": "local",
                    "label": label,
                    "path": str(p / "TuxHarbor"),
                }
            )

    return locations


def _write_text_no_symlink(target: Path, dest_root: Path, content: str) -> None:
    """Safely write UTF-8 LF text while preventing symlink overwrite or path escape."""
    if target.is_symlink():
        raise ValueError(f"Refusing to write through symbolic link: {target.name}")
    resolved_parent = target.parent.resolve()
    if resolved_parent != dest_root:
        raise ValueError("Target file escapes destination directory.")
    target.write_text(content, encoding="utf-8", newline="\n")


def save_migration_bundle(
    destination_dir: str,
    filename_prefix: str,
    report_html: str,
    linux_script: str,
    plan: dict[str, Any],
    create_zip: bool = True,
) -> dict[str, Any]:
    """Write report HTML, LF-normalized executable Linux script, plan JSON, and optional ZIP."""
    if not destination_dir or not isinstance(destination_dir, str) or not destination_dir.strip() or contains_control_or_crlf(destination_dir):
        raise ValueError("A valid destination folder is required.")

    prefix = sanitize_filename_prefix(filename_prefix, default="tuxharbor-migration")
    dest_raw = Path(destination_dir).expanduser()
    if dest_raw.is_symlink():
        raise ValueError("Refusing to write into a symbolic link directory.")
    dest = dest_raw.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    report_path = dest / f"{prefix}-report.html"
    script_path = dest / f"{prefix}-install.sh"
    plan_path = dest / f"{prefix}-plan.json"

    lf_script = linux_script.replace("\r\n", "\n").replace("\r", "\n")
    plan_json_str = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"

    _write_text_no_symlink(report_path, dest, report_html)
    _write_text_no_symlink(script_path, dest, lf_script)
    _write_text_no_symlink(plan_path, dest, plan_json_str)

    # Set executable bit on POSIX systems
    if platform.system() != "Windows":
        try:
            mode = script_path.stat().st_mode
            script_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass

    saved_files = [str(report_path), str(script_path), str(plan_path)]
    zip_path_str = ""

    if create_zip:
        zip_path = dest / f"{prefix}-bundle.zip"
        if zip_path.is_symlink():
            raise ValueError(f"Refusing to write through symbolic link: {zip_path.name}")
        for arc in (report_path.name, plan_path.name, script_path.name):
            if "/" in arc or "\\" in arc or ".." in arc:
                raise ValueError(f"Invalid archive entry name: {arc}")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Bare basenames only — prevents ZIP Slip path traversal
            zf.writestr(report_path.name, report_html.encode("utf-8"))
            zf.writestr(plan_path.name, plan_json_str.encode("utf-8"))
            # Store .sh inside ZIP with POSIX 0755 executable permissions!
            zi = zipfile.ZipInfo(script_path.name)
            zi.create_system = 3  # Unix
            zi.external_attr = 0o100755 << 16
            zf.writestr(zi, lf_script.encode("utf-8"))
        zip_path_str = str(zip_path)
        saved_files.append(zip_path_str)

    return {
        "destination_dir": str(dest),
        "prefix": prefix,
        "report_path": str(report_path),
        "script_path": str(script_path),
        "plan_path": str(plan_path),
        "zip_path": zip_path_str,
        "files": saved_files,
    }


def open_saved_path(path_str: str, allowed_dir: str | None = None) -> bool:
    """Safely open a saved bundle directory or HTML report using the OS default handler."""
    if not path_str or not isinstance(path_str, str) or contains_control_or_crlf(path_str):
        return False
    raw_target = Path(path_str)
    if raw_target.is_symlink():
        return False
    target = raw_target.resolve()
    if not target.exists():
        return False
    if allowed_dir:
        allowed_root = Path(allowed_dir).resolve()
        if target != allowed_root and allowed_root not in target.parents:
            return False
    if target.is_file() and target.suffix.lower() not in (".html", ".htm"):
        return False
    try:
        if platform.system() == "Windows":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            opener = shutil.which("open")
            if not opener:
                return False
            subprocess.Popen([opener, str(target)], shell=False)
        else:
            opener = shutil.which("xdg-open")
            if not opener:
                return False
            subprocess.Popen([opener, str(target)], shell=False)
        return True
    except OSError:
        return False


def _sanitize_error_without_secret(exc: Exception, secret: str, username: str = "") -> str:
    """Return a clean user-facing error message guaranteed never to leak the SMTP password (plain or base64)."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "SMTP authentication failed — verify your email address and App Password."
    if isinstance(exc, ssl.SSLError):
        return "TLS certificate verification failed — refusing insecure SMTP connection."
    msg = str(exc) or exc.__class__.__name__
    if secret:
        msg = msg.replace(secret, "[REDACTED]")
        try:
            b64_secret = base64.b64encode(secret.encode("utf-8")).decode("ascii")
            msg = msg.replace(b64_secret, "[REDACTED]")
            if username:
                b64_plain = base64.b64encode(f"\x00{username}\x00{secret}".encode("utf-8")).decode("ascii")
                msg = msg.replace(b64_plain, "[REDACTED]")
        except Exception:
            pass
    return msg


def send_migration_email_smtp(
    smtp_config: dict[str, Any],
    filename_prefix: str,
    report_html: str,
    linux_script: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Send migration files directly via TLS-verified SMTP without storing or logging credentials."""
    preset_key = str(smtp_config.get("preset", "gmail")).lower().strip()
    preset = SMTP_PRESETS.get(preset_key, {})

    raw_host = str(smtp_config.get("host") or preset.get("host") or "")
    raw_username = str(smtp_config.get("username", ""))
    raw_recipient = str(smtp_config.get("recipient") or raw_username)
    password = str(smtp_config.get("password", ""))
    security = str(smtp_config.get("security") or preset.get("security") or "starttls").lower().strip()

    # Block SMTP header injection (CR/LF/control chars) BEFORE stripping!
    if contains_control_or_crlf(raw_host):
        raise ValueError("Invalid SMTP host (control characters are not permitted).")
    if contains_control_or_crlf(raw_username):
        raise ValueError("Invalid sender email (control characters are not permitted).")
    if contains_control_or_crlf(raw_recipient):
        raise ValueError("Invalid recipient email (control characters are not permitted).")
    if contains_control_or_crlf(filename_prefix or ""):
        raise ValueError("Invalid filename prefix (control characters are not permitted).")
    if contains_control_or_crlf(password):
        raise ValueError("Invalid SMTP password (control characters are not permitted).")

    host = raw_host.strip()
    username = raw_username.strip()
    recipient = raw_recipient.strip()

    raw_port = smtp_config.get("port")
    if raw_port is None or raw_port == "":
        raw_port = preset.get("port", 587)
    if isinstance(raw_port, bool):
        raise ValueError("SMTP port must be an integer between 1 and 65535.")
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("SMTP port must be an integer between 1 and 65535.") from exc
    if not (1 <= port <= 65535):
        raise ValueError("SMTP port must be between 1 and 65535.")

    if not is_safe_hostname(host):
        raise ValueError("Invalid SMTP hostname.")
    if not is_safe_email(username):
        raise ValueError("Invalid sender email address.")
    if not is_safe_email(recipient):
        raise ValueError("Invalid recipient email address.")
    if not password:
        raise ValueError("SMTP password or App Password is required.")
    if security not in ("starttls", "ssl"):
        raise ValueError("Only encrypted TLS connections (STARTTLS or SSL) are permitted.")

    prefix = sanitize_filename_prefix(filename_prefix, default="tuxharbor-migration")
    app_count = len(plan.get("apps", [])) if isinstance(plan, dict) else 0
    ext_count = len(plan.get("vscode_extensions", [])) if isinstance(plan, dict) else 0
    try:
        score = max(0, min(100, int(plan.get("readiness_score", 100)))) if isinstance(plan, dict) else 100
    except (TypeError, ValueError):
        score = 100

    msg = email.message.EmailMessage()
    msg["From"] = username
    msg["To"] = recipient
    msg["Subject"] = f"TuxHarbor — Your Linux Migration Kit ({prefix})"

    body = (
        f"Hello!\n\n"
        f"Attached are your Linux migration files generated locally by TuxHarbor v{__version__}:\n"
        f"- {prefix}-report.html : Detailed readiness report & alternatives ({score}% readiness)\n"
        f"- {prefix}-install.sh  : Automated Linux installer script ({app_count} apps/tools, {ext_count} VS Code extensions)\n"
        f"- {prefix}-plan.json   : Portable plan for TuxHarbor Linux Mode\n\n"
        f"IMPORTANT BACKUP REMINDER:\n"
        f"TuxHarbor migrates tools and alternatives ONLY — NOT your personal files or project source code.\n"
        f"Back up all projects, .env files, SSH keys, and documents to an external drive or cloud storage before switching!\n\n"
        f"Run on Linux:\n"
        f"  chmod +x {prefix}-install.sh\n"
        f"  ./{prefix}-install.sh --dry-run   # Optional preview\n"
        f"  ./{prefix}-install.sh\n"
    )

    msg.set_content(body, subtype="plain", charset="utf-8")

    lf_script = linux_script.replace("\r\n", "\n").replace("\r", "\n")
    msg.add_attachment(
        report_html.encode("utf-8"),
        maintype="text",
        subtype="html",
        filename=f"{prefix}-report.html",
    )
    msg.add_attachment(
        lf_script.encode("utf-8"),
        maintype="text",
        subtype="x-shellscript",
        filename=f"{prefix}-install.sh",
    )
    msg.add_attachment(
        (json.dumps(plan, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        maintype="application",
        subtype="json",
        filename=f"{prefix}-plan.json",
    )

    # Mandatory verified TLS >= 1.2 context
    tls_ctx = ssl.create_default_context()
    tls_ctx.check_hostname = True
    tls_ctx.verify_mode = ssl.CERT_REQUIRED
    if hasattr(ssl, "TLSVersion"):
        tls_ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    try:
        if security == "ssl":
            with smtplib.SMTP_SSL(host, port, timeout=20, context=tls_ctx) as server:
                server.login(username, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.ehlo()
                if not server.has_extn("starttls"):
                    raise RuntimeError("SMTP server does not advertise STARTTLS; refusing unencrypted connection.")
                server.starttls(context=tls_ctx)
                server.ehlo()
                server.login(username, password)
                server.send_message(msg)
    except Exception as exc:
        safe_msg = _sanitize_error_without_secret(exc, password, username=username)
        raise RuntimeError(f"SMTP delivery failed: {safe_msg}") from None
    finally:
        password = ""

    return {
        "sent": True,
        "recipient": recipient,
        "host": host,
        "attachments": [f"{prefix}-report.html", f"{prefix}-install.sh", f"{prefix}-plan.json"],
    }


def build_webmail_draft_urls(
    recipient: str,
    filename_prefix: str,
    plan: dict[str, Any],
) -> dict[str, str]:
    """Build passwordless email draft URLs (Gmail Web, Outlook Web, and mailto:) for zero-credential workflow."""
    raw_recipient = recipient or ""
    if contains_control_or_crlf(raw_recipient):
        raise ValueError("Invalid recipient email (control characters are not permitted).")
    clean_recipient = raw_recipient.strip()
    prefix = sanitize_filename_prefix(filename_prefix, default="tuxharbor-migration")
    apps = [str(a.get("target_linux_app", "")) for a in plan.get("apps", [])]
    app_preview = ", ".join(apps[:18]) + ("..." if len(apps) > 18 else "")

    subject = f"TuxHarbor — My Linux Migration Kit ({prefix})"
    body = (
        f"My Linux migration kit ({len(apps)} apps & alternatives):\n"
        f"{app_preview}\n\n"
        f"Attach your saved files ({prefix}-bundle.zip or {prefix}-install.sh & {prefix}-report.html) to this email.\n\n"
        f"Reminder: Back up all projects and personal files to an external drive or cloud storage!"
    )

    to_q = urllib.parse.quote(clean_recipient, safe="")
    su_q = urllib.parse.quote(subject, safe="")
    body_q = urllib.parse.quote(body, safe="")

    return {
        "gmail": f"https://mail.google.com/mail/?view=cm&fs=1&to={to_q}&su={su_q}&body={body_q}",
        "outlook": f"https://outlook.live.com/mail/0/deeplink/compose?to={to_q}&subject={su_q}&body={body_q}",
        "mailto": f"mailto:{to_q}?subject={su_q}&body={body_q}",
    }
