"""Standalone, 100% English, offline static HTML Migration Report generator (zero JavaScript)."""

from __future__ import annotations

import datetime as dt
import html
import urllib.parse
from typing import Any

from tuxharbor import LEGAL_NOTICE_LINES, __version__
from tuxharbor.models import is_safe_https_url, is_safe_https_url_for_hosts, is_safe_steam_app_id

PROTONDB_ALLOWED_HOSTS: tuple[str, ...] = ("www.protondb.com", "protondb.com")
ANTICHEAT_ALLOWED_HOSTS: tuple[str, ...] = ("areweanticheatyet.com",)


CATEGORY_ORDER: tuple[str, ...] = (
    "browsers",
    "dev",
    "runtimes",
    "communication",
    "productivity",
    "creative",
    "utilities",
    "security",
)

DEFAULT_CATEGORY_LABELS: dict[str, str] = {
    "browsers": "Web Browsers",
    "dev": "Development & IDEs",
    "runtimes": "Runtimes & CLIs",
    "communication": "Communication",
    "productivity": "Office & Productivity",
    "creative": "Creative & Media",
    "utilities": "Utilities & System",
    "security": "Security & Privacy",
    "gaming": "Gaming",
}


def _e(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _render_app_row(item: dict[str, Any], status_meta: dict[str, tuple[str, str]]) -> str:
    st = str(item.get("status", "native"))
    cls, st_label = status_meta.get(st, status_meta["native"])
    selected = bool(item.get("selected"))
    no_install = bool(item.get("no_install_needed"))

    target_name = str(item.get("name", ""))
    target_url = ""
    alts = item.get("alternatives") or []
    if no_install:
        target_name = "Native Linux Environment"
        pkgs: dict[str, Any] = {}
    elif st != "native" and alts:
        chosen = next((a for a in alts if a.get("id") == item.get("selected_alternative_id")), alts[0])
        target_name = str(chosen.get("name", target_name))
        pkgs = chosen.get("packages", {}) or {}
    else:
        pkgs = item.get("linux_packages", {}) or {}

    raw_url = str(pkgs.get("official_url", "")).strip()
    if is_safe_https_url(raw_url):
        target_url = raw_url

    target_pkg = str(pkgs.get("flatpak") or pkgs.get("apt") or pkgs.get("dnf") or pkgs.get("pacman") or "")
    if target_pkg:
        target_sub_html = f'<div class="mono">{_e(target_pkg)}</div>'
    elif target_url:
        target_sub_html = (
            f'<div class="mono"><a href="{_e(target_url)}" target="_blank" '
            f'rel="noopener noreferrer">{_e(target_url)}</a></div>'
        )
    else:
        target_sub_html = ""

    summary = str(item.get("summary") or "")
    if no_install:
        sel_label = "Handled by Linux"
        sel_cls = "pill-handled"
    elif selected:
        sel_label = "Included"
        sel_cls = "pill-on"
    else:
        sel_label = "Skipped"
        sel_cls = "pill-off"

    return f"""
            <tr>
              <td><strong>{_e(item.get('name'))}</strong><div class="sub">{_e(item.get('detected_version', ''))}</div></td>
              <td><span class="badge {cls}">{_e(st_label)}</span></td>
              <td><strong>{_e(target_name)}</strong>{target_sub_html}</td>
              <td class="desc">{_e(summary)}</td>
              <td><span class="pill {sel_cls}">{sel_label}</span></td>
            </tr>"""


def generate_html_report(
    payload: dict[str, Any],
    plan: dict[str, Any],
    script_filename: str = "tuxharbor-migration-install.sh",
) -> str:
    """Create a rich, categorized, self-contained static offline HTML report in clean English."""
    score = max(0, min(100, _safe_int(payload.get("readiness_score", plan.get("readiness_score", 100)), 100)))
    counts = payload.get("counts", {}) if isinstance(payload.get("counts"), dict) else {}
    categories_meta = payload.get("categories", {}) if isinstance(payload.get("categories"), dict) else {}

    matched = [m for m in (payload.get("matched") or []) if isinstance(m, dict)]
    hardware_drivers = [h for h in (payload.get("hardware_drivers") or []) if isinstance(h, dict)]
    games = [g for g in (payload.get("games") or []) if isinstance(g, dict)]
    os_builtins = [b for b in (payload.get("os_builtins") or []) if isinstance(b, dict)]
    unmatched = [u for u in (payload.get("unmatched") or []) if isinstance(u, dict)]
    projects = [p for p in (payload.get("projects") or []) if isinstance(p, dict)]
    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    status_meta = {
        "native": ("badge-native", "Native on Linux"),
        "alternative": ("badge-alt", "Great Alternative"),
        "compat": ("badge-compat", "Compatibility Layer"),
        "attention": ("badge-attn", "Needs Attention"),
    }

    # Split matched into non-gaming applications (grouped by category) and game launchers
    regular_apps = [m for m in matched if str(m.get("category", "")) != "gaming"]
    gaming_launchers = [m for m in matched if str(m.get("category", "")) == "gaming"]

    # Bucket 1: Applications & Developer Tools grouped cleanly by category
    grouped_apps: dict[str, list[dict[str, Any]]] = {}
    for item in regular_apps:
        cat_id = str(item.get("category", "utilities") or "utilities")
        grouped_apps.setdefault(cat_id, []).append(item)

    ordered_cats = [c for c in CATEGORY_ORDER if c in grouped_apps]
    for c in sorted(grouped_apps.keys()):
        if c not in ordered_cats:
            ordered_cats.append(c)

    app_cat_blocks: list[str] = []
    for cat_id in ordered_cats:
        cat_items = grouped_apps[cat_id]
        cat_label = (
            str(categories_meta.get(cat_id, {}).get("label") or "")
            if isinstance(categories_meta.get(cat_id), dict)
            else ""
        ) or DEFAULT_CATEGORY_LABELS.get(cat_id, cat_id.replace("_", " ").title())
        rows_html = "".join(_render_app_row(item, status_meta) for item in cat_items)
        app_cat_blocks.append(
            f"""
        <div class="cat-group">
          <h3 class="cat-heading">{_e(cat_label)} <span class="cat-count">{len(cat_items)}</span></h3>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Windows App</th>
                  <th>Status</th>
                  <th>Linux Target</th>
                  <th>Details</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>{rows_html}</tbody>
            </table>
          </div>
        </div>"""
        )

    apps_section_body = (
        "".join(app_cat_blocks)
        if app_cat_blocks
        else '<p class="muted">No cataloged desktop applications were detected in this scan.</p>'
    )

    # Bucket 2: Hardware & Drivers
    driver_status_meta = {
        "official_driver": ("badge-driver", "Official Linux Driver"),
        "kernel_builtin": ("badge-native", "Built into Linux Kernel"),
        "oem_utility": ("badge-oem", "Hardware / OEM Utility"),
    }
    hw_profile = payload.get("hardware_profile") if isinstance(payload.get("hardware_profile"), dict) else {}
    hw_profile_html = ""
    if hw_profile:
        bits: list[str] = []
        arch_val = str(hw_profile.get("arch") or "").strip()
        if arch_val:
            bits.append(f"<strong>Architecture:</strong> {_e(arch_val)}")
        cpu_val = str(hw_profile.get("cpu") or "").strip()
        if cpu_val:
            bits.append(f"<strong>CPU:</strong> {_e(cpu_val)}")
        gpus_val = [str(g) for g in (hw_profile.get("gpus") or []) if g]
        if gpus_val:
            bits.append(f"<strong>GPU(s):</strong> {_e(', '.join(gpus_val))}")
        oem_val = " ".join(
            p for p in (str(hw_profile.get("manufacturer") or "").strip(), str(hw_profile.get("model") or "").strip()) if p
        )
        if oem_val:
            bits.append(f"<strong>System:</strong> {_e(oem_val)}")
        if bits:
            arm_alert = ""
            if hw_profile.get("is_arm64"):
                arm_alert = (
                    '<div class="warn-line" style="margin-top:8px;">&#9888; <strong>ARM64 / Windows-on-ARM Detected:</strong> '
                    "Download an <strong>ARM64 (aarch64)</strong> Linux ISO with a recent kernel (Linux 6.11+) and verify laptop model support on a Live USB before installing.</div>"
                )
            hw_profile_html = f'<div class="hw-profile-bar">{" &nbsp;&middot;&nbsp; ".join(bits)}{arm_alert}</div>'

    hardware_section = ""
    if hardware_drivers or hw_profile_html:
        hw_rows: list[str] = []
        for hw in hardware_drivers:
            d_st = str(hw.get("driver_status", "oem_utility"))
            d_cls, d_default_lbl = driver_status_meta.get(d_st, driver_status_meta["oem_utility"])
            d_label = str(hw.get("driver_status_label") or d_default_lbl)
            comps = [str(c) for c in (hw.get("detected_components") or []) if c]
            comp_count = _safe_int(hw.get("component_count", len(comps)), len(comps))
            comp_preview = ", ".join(comps[:6]) + (f" (+{len(comps) - 6} more)" if len(comps) > 6 else "")

            raw_url = str(hw.get("official_url", "")).strip()
            link_html = ""
            if is_safe_https_url(raw_url):
                link_html = (
                    f'<div class="hw-link"><a href="{_e(raw_url)}" target="_blank" '
                    f'rel="noopener noreferrer">Official Linux Driver Documentation &rarr;</a></div>'
                )

            hw_rows.append(
                f"""
                <tr>
                  <td><strong>{_e(hw.get('name'))}</strong></td>
                  <td><span class="badge {d_cls}">{_e(d_label)}</span></td>
                  <td><div class="pill pill-off">{comp_count} detected</div><div class="sub">{_e(comp_preview)}</div></td>
                  <td class="desc">{_e(hw.get('summary', ''))}{link_html}</td>
                </tr>"""
            )
        hw_table = (
            f"""
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Hardware / Subsystem</th>
                  <th>Linux Driver Status</th>
                  <th>Detected Components</th>
                  <th>Linux Guidance</th>
                </tr>
              </thead>
              <tbody>{''.join(hw_rows)}</tbody>
            </table>
          </div>"""
            if hw_rows
            else ""
        )
        hardware_section = f"""
        <section class="card">
          <h2>Hardware &amp; Drivers ({len(hardware_drivers)})</h2>
          {hw_profile_html}
          <p class="muted">GPU, CPU platform, Wi-Fi, audio, printer, and peripheral drivers are handled differently on Linux than regular apps. For system safety, TuxHarbor&#x27;s installer script never automatically modifies kernel or GPU driver packages — use your distribution&#x27;s driver manager or official vendor guidance below. <strong>Pro tip:</strong> Boot a Linux Live USB first (without installing) to verify Wi-Fi, Bluetooth, audio, sleep, and touchpad on your exact hardware.</p>
          {hw_table}
        </section>"""

    # Bucket 3: PC Games & Launchers
    game_status_meta = {
        "anticheat_blocked": ("badge-attn", "Blocked by Anti-Cheat"),
        "anticheat_caution": ("badge-compat", "Online Anti-Cheat Caution"),
        "check_protondb": ("badge-alt", "Check ProtonDB"),
    }
    gaming_section = ""
    if gaming_launchers or games:
        launchers_html = ""
        if gaming_launchers:
            l_rows = "".join(_render_app_row(item, status_meta) for item in gaming_launchers)
            launchers_html = f"""
            <div class="cat-group">
              <h3 class="cat-heading">Game Launchers &amp; Platforms <span class="cat-count">{len(gaming_launchers)}</span></h3>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Launcher</th>
                      <th>Status</th>
                      <th>Linux Target</th>
                      <th>Details</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>{l_rows}</tbody>
                </table>
              </div>
            </div>"""

        games_html = ""
        if games:
            g_rows: list[str] = []
            for g in games:
                g_name = str(g.get("name", ""))
                g_st = str(g.get("status", "check_protondb"))
                g_cls, g_default_lbl = game_status_meta.get(g_st, game_status_meta["check_protondb"])
                g_label = str(g.get("status_label") or g_default_lbl)

                # Defense-in-depth URL validation + strict host pinning & safe query construction
                encoded_q = urllib.parse.quote_plus(g_name)
                steam_id = str(g.get("steam_app_id", "")).strip()
                cand_proton = str(g.get("protondb_url", "")).strip()
                if not is_safe_https_url_for_hosts(cand_proton, PROTONDB_ALLOWED_HOSTS):
                    cand_proton = (
                        f"https://www.protondb.com/app/{steam_id}"
                        if is_safe_steam_app_id(steam_id)
                        else f"https://www.protondb.com/search?q={encoded_q}"
                    )
                cand_ac = str(g.get("anticheat_url", "")).strip()
                if not is_safe_https_url_for_hosts(cand_ac, ANTICHEAT_ALLOWED_HOSTS):
                    cand_ac = f"https://areweanticheatyet.com/?search={encoded_q}"

                links_parts: list[str] = []
                if is_safe_https_url_for_hosts(cand_proton, PROTONDB_ALLOWED_HOSTS):
                    links_parts.append(
                        f'<a href="{_e(cand_proton)}" target="_blank" rel="noopener noreferrer">ProtonDB</a>'
                    )
                if is_safe_https_url_for_hosts(cand_ac, ANTICHEAT_ALLOWED_HOSTS):
                    links_parts.append(
                        f'<a href="{_e(cand_ac)}" target="_blank" rel="noopener noreferrer">AreWeAntiCheatYet</a>'
                    )

                pub_ver = " &middot; ".join(
                    part for part in (_e(g.get("publisher", "")), _e(g.get("version", ""))) if part
                )
                sub_line = f'<div class="sub">{pub_ver}</div>' if pub_ver else ""

                g_rows.append(
                    f"""
                    <tr>
                      <td><strong>{_e(g_name)}</strong>{sub_line}</td>
                      <td><span class="pill pill-off">{_e(g.get('platform', 'PC Game'))}</span></td>
                      <td><span class="badge {g_cls}">{_e(g_label)}</span></td>
                      <td class="desc">{_e(g.get('note', ''))}</td>
                      <td>{' &middot; '.join(links_parts)}</td>
                    </tr>"""
                )

            games_html = f"""
            <div class="cat-group">
              <h3 class="cat-heading">Detected PC Games <span class="cat-count">{len(games)}</span></h3>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Game</th>
                      <th>Platform</th>
                      <th>Linux Status</th>
                      <th>Compatibility Notes</th>
                      <th>Community Lookup</th>
                    </tr>
                  </thead>
                  <tbody>{''.join(g_rows)}</tbody>
                </table>
              </div>
              <p class="muted db-note">Note: ProtonDB and AreWeAntiCheatYet are independent, community-maintained compatibility databases — not official vendor or publisher guarantees.</p>
            </div>"""

        total_gaming = len(gaming_launchers) + len(games)
        gaming_section = f"""
        <section class="card">
          <h2>PC Games &amp; Launchers ({total_gaming})</h2>
          {launchers_html}
          {games_html}
        </section>"""

    # Projects table
    project_rows_html: list[str] = []
    for proj in projects:
        backup_w = proj.get("backup_warnings", []) or []
        linux_w = proj.get("linux_warnings", []) or []
        compat = str(proj.get("compatibility", "ready"))
        if compat not in ("ready", "warning", "blocker"):
            compat = "ready"
        compat_cls = {"ready": "badge-native", "warning": "badge-compat", "blocker": "badge-attn"}[compat]
        compat_label = {"ready": "Linux Ready", "warning": "Minor Tweaks", "blocker": "Windows-Specific"}[compat]

        warnings_bits: list[str] = []
        for w in linux_w:
            msg = w.get("message") or ""
            warnings_bits.append(f'<div class="warn-line">&#9888; {_e(msg)}</div>')
        for bw in backup_w:
            msg = bw.get("message") or ""
            warnings_bits.append(f'<div class="backup-line">&#128190; {_e(msg)}</div>')

        project_rows_html.append(
            f"""
            <tr>
              <td><strong>{_e(proj.get('name'))}</strong><div class="mono">{_e(proj.get('path'))}</div></td>
              <td>{_e(', '.join(proj.get('stacks', [])) or '—')}</td>
              <td><span class="badge {compat_cls}">{_e(compat_label)}</span></td>
              <td>{''.join(warnings_bits) or '<span class="muted">—</span>'}</td>
            </tr>"""
        )

    projects_section = ""
    if projects:
        projects_section = f"""
        <section class="card">
          <h2>Projects Compatibility &amp; Backup Safety ({len(projects)})</h2>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Tech Stack</th>
                  <th>Linux Status</th>
                  <th>Notes &amp; Backup Alerts</th>
                </tr>
              </thead>
              <tbody>{''.join(project_rows_html)}</tbody>
            </table>
          </div>
        </section>"""

    # VS Code extensions section
    exts = plan.get("vscode_extensions", []) or []
    ext_section = ""
    if exts:
        chips = "".join(f'<span class="chip">{_e(e)}</span>' for e in exts)
        ext_section = f"""
        <section class="card">
          <h2>VS Code Extensions Included ({len(exts)})</h2>
          <div class="chips">{chips}</div>
        </section>"""

    # Global npm packages section
    npm_globals = plan.get("npm_globals", []) or []
    npm_section = ""
    if npm_globals:
        chips = "".join(f'<span class="chip">{_e(p)}</span>' for p in npm_globals)
        npm_section = f"""
        <section class="card">
          <h2>Global npm Packages Included ({len(npm_globals)})</h2>
          <div class="chips">{chips}</div>
        </section>"""

    # Bucket 4: Windows OS Built-ins & System Runtimes (pure HTML5 collapsed <details>, zero JS)
    os_builtins_section = ""
    if os_builtins:
        b_rows: list[str] = []
        for b in os_builtins:
            b_rows.append(
                f"""<tr>
                  <td>{_e(b.get('name', ''))}</td>
                  <td class="mono">{_e(b.get('version', ''))}</td>
                  <td class="sub">{_e(b.get('reason', 'Windows Built-in App / Codec'))}</td>
                </tr>"""
            )
        os_builtins_section = f"""
        <section class="card os-card">
          <details class="os-details">
            <summary><strong>{len(os_builtins)} Windows built-in apps, codecs &amp; runtimes excluded</strong> — handled natively by Linux (click to inspect)</summary>
            <p class="muted" style="margin-top: 10px;">Standard Windows Store built-ins, media codec packs, language experience packs, and Windows-only runtime redistributables are replaced natively by your Linux desktop environment and system libraries.</p>
            <div class="table-wrap">
              <table>
                <thead><tr>
                  <th>Windows Component</th>
                  <th>Version</th>
                  <th>Classification</th>
                </tr></thead>
                <tbody>{''.join(b_rows)}</tbody>
              </table>
            </div>
          </details>
        </section>"""

    # Bucket 5: Other / Niche Applications (strict urllib.parse.quote_plus URL encoding!)
    unmatched_section = ""
    if unmatched:
        u_rows: list[str] = []
        for u in unmatched:
            raw_name = str(u.get("name", ""))
            encoded_q = urllib.parse.quote_plus(raw_name)
            flathub_url = f"https://flathub.org/apps/search?q={encoded_q}"
            alt_url = f"https://alternativeto.net/browse/search/?q={encoded_q}&platform=linux"
            u_rows.append(
                f"""<tr>
                  <td><strong>{_e(raw_name)}</strong></td>
                  <td>{_e(u.get('publisher', ''))}</td>
                  <td>{_e(u.get('version', ''))}</td>
                  <td>
                    <a href="{_e(flathub_url)}" target="_blank" rel="noopener noreferrer">Flathub</a> &middot;
                    <a href="{_e(alt_url)}" target="_blank" rel="noopener noreferrer">AlternativeTo</a>
                  </td>
                </tr>"""
            )
        unmatched_section = f"""
        <section class="card">
          <h2>Other / Niche Applications ({len(unmatched)})</h2>
          <p class="muted">These applications were not matched in the built-in catalog. Look up Linux equivalents using the links below or contribute entries via GitHub.</p>
          <div class="table-wrap">
            <table>
              <thead><tr>
                <th>Application</th>
                <th>Publisher</th>
                <th>Version</th>
                <th>Find Linux Equivalent</th>
              </tr></thead>
              <tbody>{''.join(u_rows)}</tbody>
            </table>
          </div>
        </section>"""

    legal_footer_html = "<br />".join(_e(line) for line in LEGAL_NOTICE_LINES)
    total_gaming_pill = len(gaming_launchers) + len(games)

    return f"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none';" />
  <title>TuxHarbor — Linux Migration Report</title>
  <style>
    :root {{
      --bg: #0b1220; --card: #111b2e; --card-alt: #162238; --border: #23324d; --text: #e6eefb;
      --muted: #93a6c4; --accent: #14b8a6; --blue: #38bdf8; --amber: #f59e0b; --red: #ef4444; --green: #22c55e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.55; padding: 28px 18px 60px;
    }}
    .wrap {{ max-width: 1120px; margin: 0 auto; }}
    header {{
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;
      margin-bottom: 22px; padding-bottom: 18px; border-bottom: 1px solid var(--border);
    }}
    .brand {{ display: flex; align-items: center; gap: 12px; }}
    .logo {{
      width: 44px; height: 44px; border-radius: 12px; background: linear-gradient(135deg, #14b8a6, #0ea5e9);
      display: grid; place-items: center; font-weight: 800; color: #05131f; font-size: 20px;
    }}
    h1 {{ margin: 0; font-size: 1.6rem; }}
    h2 {{ margin: 0 0 12px; font-size: 1.2rem; }}
    .cat-group {{ margin-top: 16px; }}
    .cat-group:first-of-type {{ margin-top: 4px; }}
    .cat-heading {{
      margin: 0 0 8px; font-size: 0.96rem; color: var(--accent); display: flex; align-items: center; gap: 8px;
      padding: 6px 10px; background: var(--card-alt); border-radius: 8px; border-left: 3px solid var(--accent);
    }}
    .cat-count {{
      display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 0.76rem;
      background: rgba(20,184,166,.18); color: #5eead4; font-weight: 700;
    }}
    .sub, .muted {{ color: var(--muted); font-size: 0.9rem; }}
    .hw-profile-bar {{
      background: var(--card-alt); border: 1px solid var(--border); border-radius: 10px;
      padding: 10px 14px; margin-bottom: 12px; font-size: 0.88rem; color: var(--text);
    }}
    .db-note {{ margin-top: 10px; font-size: 0.84rem; }}
    .backup-alert {{
      background: linear-gradient(135deg, rgba(245, 158, 11, 0.16), rgba(239, 68, 68, 0.12));
      border: 1.5px solid rgba(245, 158, 11, 0.65); border-radius: 16px; padding: 20px 22px; margin-bottom: 22px;
    }}
    .backup-alert h2 {{ color: #fbbf24; margin-bottom: 8px; }}
    .backup-alert ul {{ margin: 10px 0 0; padding-left: 20px; }}
    .backup-alert li {{ margin-bottom: 6px; }}
    .stats {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 14px; margin-bottom: 12px;
    }}
    .stat {{
      background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 16px;
    }}
    .stat .val {{ font-size: 1.9rem; font-weight: 800; }}
    .bucket-strip {{
      display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 22px;
    }}
    .bucket-pill {{
      background: var(--card); border: 1px solid var(--border); border-radius: 999px;
      padding: 6px 14px; font-size: 0.84rem; color: var(--muted);
    }}
    .bucket-pill strong {{ color: var(--text); }}
    .card {{
      background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 20px 22px; margin-bottom: 20px;
    }}
    .os-card {{ padding: 14px 20px; }}
    .os-details summary {{
      cursor: pointer; color: var(--muted); font-size: 0.94rem; list-style-position: inside;
    }}
    .os-details summary strong {{ color: var(--text); }}
    .hw-link {{ margin-top: 6px; font-size: 0.84rem; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
    th, td {{ padding: 11px 12px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; font-size: 0.82rem; text-transform: uppercase; }}
    .badge {{
      display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 0.78rem; font-weight: 700; white-space: nowrap;
    }}
    .badge-native {{ background: rgba(34,197,94,.16); color: #4ade80; }}
    .badge-driver {{ background: rgba(20,184,166,.18); color: #2dd4bf; }}
    .badge-alt {{ background: rgba(56,189,248,.16); color: #38bdf8; }}
    .badge-compat {{ background: rgba(245,158,11,.16); color: #fbbf24; }}
    .badge-oem {{ background: rgba(148,163,184,.18); color: #cbd5e1; }}
    .badge-attn {{ background: rgba(239,68,68,.16); color: #f87171; }}
    .pill {{ display: inline-block; padding: 3px 9px; border-radius: 8px; font-size: 0.78rem; font-weight: 600; white-space: nowrap; }}
    .pill-on {{ background: rgba(20,184,166,.2); color: #2dd4bf; }}
    .pill-handled {{ background: rgba(34,197,94,.16); color: #4ade80; }}
    .pill-off {{ background: rgba(148,163,184,.15); color: var(--muted); }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.82rem; color: var(--muted); word-break: break-all; }}
    .warn-line {{ color: #fbbf24; font-size: 0.86rem; margin-bottom: 4px; }}
    .backup-line {{ color: #f87171; font-size: 0.86rem; margin-bottom: 4px; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .chip {{ background: #182741; border: 1px solid var(--border); padding: 4px 10px; border-radius: 8px; font-family: monospace; font-size: 0.82rem; }}
    pre {{
      background: #070d18; border: 1px solid var(--border); padding: 14px 16px; border-radius: 12px;
      overflow-x: auto; direction: ltr; text-align: left; color: #7dd3fc; font-size: 0.9rem;
    }}
    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    footer {{
      text-align: center; color: var(--muted); font-size: 0.82rem; margin-top: 28px;
      padding-top: 18px; border-top: 1px solid var(--border); line-height: 1.65;
    }}
    .legal {{ margin-top: 8px; font-size: 0.78rem; opacity: 0.88; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="brand">
        <div class="logo">TH</div>
        <div>
          <h1>TuxHarbor — Linux Migration Report</h1>
          <div class="sub">Generated {_e(generated_at)} &middot; TuxHarbor v{_e(__version__)}</div>
        </div>
      </div>
    </header>

    <section class="backup-alert">
      <h2>&#9888; IMPORTANT: Don't Forget to Back Up Your Projects &amp; Personal Files!</h2>
      <p>TuxHarbor migrates your tools, development environments, and Linux alternatives ONLY — it does NOT back up your personal files or project source code.</p>
      <ul>
        <li>Copy all project folders, Documents, Desktop, and Pictures to an external USB/SSD drive or cloud storage (Google Drive / OneDrive / Nextcloud).</li>
        <li>Run <code>git push</code> on all repositories so no local commits are lost.</li>
        <li>Safely back up hidden configuration and secrets: <code>.env</code> files, SSH keys (<code>~/.ssh</code>), browser bookmarks, and password manager vaults.</li>
      </ul>
    </section>

    <div class="stats">
      <div class="stat">
        <div class="sub">Linux Readiness</div>
        <div class="val" style="color: var(--accent);">{score}%</div>
      </div>
      <div class="stat">
        <div class="sub">Native on Linux</div>
        <div class="val" style="color: var(--green);">{_safe_int(counts.get('native', 0))}</div>
      </div>
      <div class="stat">
        <div class="sub">Great Alternatives</div>
        <div class="val" style="color: var(--blue);">{_safe_int(counts.get('alternative', 0))}</div>
      </div>
      <div class="stat">
        <div class="sub">Compatibility Layer</div>
        <div class="val" style="color: var(--amber);">{_safe_int(counts.get('compat', 0))}</div>
      </div>
      <div class="stat">
        <div class="sub">Needs Attention</div>
        <div class="val" style="color: var(--red);">{_safe_int(counts.get('attention', 0))}</div>
      </div>
    </div>

    <div class="bucket-strip">
      <div class="bucket-pill">Applications &amp; Dev Tools: <strong>{len(regular_apps)}</strong></div>
      <div class="bucket-pill">Hardware &amp; Drivers: <strong>{len(hardware_drivers)}</strong></div>
      <div class="bucket-pill">PC Games &amp; Launchers: <strong>{total_gaming_pill}</strong></div>
      <div class="bucket-pill">Windows OS Built-ins Excluded: <strong>{len(os_builtins)}</strong></div>
      <div class="bucket-pill">Other / Niche Apps: <strong>{len(unmatched)}</strong></div>
    </div>

    <section class="card">
      <h2>How to Run Your Setup on Linux</h2>
      <p class="muted">Once you install Linux, open a terminal in the folder containing your TuxHarbor installer script and run:</p>
      <pre>chmod +x {_e(script_filename)}
./{_e(script_filename)} --dry-run   # Optional: preview commands first
./{_e(script_filename)}             # Install all selected apps &amp; alternatives</pre>
    </section>

    <section class="card">
      <h2>Applications &amp; Developer Tools ({len(regular_apps)})</h2>
      {apps_section_body}
    </section>

    {hardware_section}
    {gaming_section}
    {projects_section}
    {ext_section}
    {npm_section}
    {os_builtins_section}
    {unmatched_section}

    <footer>
      <div>Generated locally by <strong>TuxHarbor</strong> (Open Source &middot; Privacy First &middot; Zero Telemetry)</div>
      <div class="legal">{legal_footer_html}</div>
    </footer>
  </div>
</body>
</html>
"""
