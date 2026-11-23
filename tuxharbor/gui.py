"""Native cross-platform Desktop GUI for TuxHarbor built with CustomTkinter (zero HTTP server, zero open ports)."""

from __future__ import annotations

import json
import platform
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

import customtkinter as ctk

from tuxharbor import LEGAL_NOTICE_LINES, LEGAL_NOTICE_TEXT, __app_name__, __repo_url__, __version__
from tuxharbor.catalog import CatalogEngine
from tuxharbor.delivery import (
    SMTP_PRESETS,
    build_webmail_draft_urls,
    detect_save_locations,
    open_saved_path,
    save_migration_bundle,
    send_migration_email_smtp,
)
from tuxharbor.generators.html_report import (
    ANTICHEAT_ALLOWED_HOSTS,
    CATEGORY_ORDER,
    DEFAULT_CATEGORY_LABELS,
    PROTONDB_ALLOWED_HOSTS,
    generate_html_report,
)
from tuxharbor.generators.linux_script import build_migration_plan, generate_linux_script
from tuxharbor.linux_runner import apply_plan_on_linux, detect_linux_environment, inspect_plan_on_linux
from tuxharbor.models import (
    DevEnvironment,
    is_safe_external_link,
    is_safe_https_url,
    is_safe_https_url_for_hosts,
    is_safe_steam_app_id,
    sanitize_filename_prefix,
)
from tuxharbor.scanners.dev_tools import scan_dev_environment
from tuxharbor.scanners.projects import detect_suggested_project_dirs, scan_projects_folders
from tuxharbor.scanners.windows_apps import detect_system_hardware, scan_installed_apps


# Sleek dark slate & teal desktop palette
PALETTE = {
    "bg": "#0b1220",
    "surface": "#111b2e",
    "surface_alt": "#162238",
    "surface_hover": "#1d2d4a",
    "border": "#23324d",
    "text": "#e6eefb",
    "muted": "#93a6c4",
    "teal": "#14b8a6",
    "teal_hover": "#0d9488",
    "teal_dark": "#072e2b",
    "blue": "#38bdf8",
    "blue_dark": "#0c283e",
    "green": "#22c55e",
    "green_dark": "#0d2b1c",
    "amber": "#f59e0b",
    "amber_dark": "#2c1e09",
    "red": "#ef4444",
    "red_dark": "#2e1217",
    "code_bg": "#070d18",
}

DISTRO_OPTIONS = [
    ("Auto-detect", "auto"),
    ("Ubuntu / Mint (apt)", "apt"),
    ("Fedora (dnf)", "dnf"),
    ("Arch (pacman)", "pacman"),
    ("openSUSE (zypper)", "zypper"),
]
DISTRO_LABEL_TO_ID = dict(DISTRO_OPTIONS)
DISTRO_ID_TO_LABEL = {v: k for k, v in DISTRO_OPTIONS}

SMTP_PROVIDER_OPTIONS = [
    ("Gmail", "gmail"),
    ("Outlook / Hotmail", "outlook"),
    ("Yahoo Mail", "yahoo"),
    ("iCloud Mail", "icloud"),
    ("Custom SMTP", "custom"),
]
SMTP_LABEL_TO_ID = dict(SMTP_PROVIDER_OPTIONS)

MAX_PLAN_FILE_BYTES = 5 * 1024 * 1024  # 5 MB safety limit for loading *-plan.json


def _safe_open_url(url: str) -> bool:
    """Open an external https:// or mailto: URL safely via the OS browser."""
    if not is_safe_external_link(url):
        return False
    try:
        webbrowser.open(url, new=2)
        return True
    except Exception:
        return False


class TuxHarborApp(ctk.CTk):
    """Main native desktop window for TuxHarbor."""

    def __init__(self, demo_mode: bool = False) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        super().__init__(fg_color=PALETTE["bg"])

        self.title(f"{__app_name__} v{__version__} — Windows to Linux Migration Assistant")
        self.geometry("1080x740")
        self.minsize(940, 650)

        self.demo_mode_default = bool(demo_mode)
        self.catalog = CatalogEngine()
        self.linux_env = detect_linux_environment()

        # Core state
        self.current_mode = "planner"  # "planner" | "linux"
        self.current_step = 1  # 1..4
        self.is_busy = False
        self.project_dirs: list[str] = []
        self.analysis: dict[str, Any] | None = None
        self.last_saved_bundle: dict[str, Any] | None = None
        self.last_draft_urls: dict[str, str] | None = None
        self.os_builtins_expanded = False
        self.unmatched_expanded = False

        # Linux mode state
        self.loaded_plan: dict[str, Any] | None = None
        self.loaded_plan_path: str = ""

        # Shared fonts (allocated once for crisp, lightweight rendering)
        self.font_title = ctk.CTkFont(size=20, weight="bold")
        self.font_h2 = ctk.CTkFont(size=16, weight="bold")
        self.font_h3 = ctk.CTkFont(size=13, weight="bold")
        self.font_body = ctk.CTkFont(size=12)
        self.font_small = ctk.CTkFont(size=11)
        self.font_badge = ctk.CTkFont(size=11, weight="bold")
        self.font_stat = ctk.CTkFont(size=24, weight="bold")
        self.font_mono = ctk.CTkFont(family="Consolas" if platform.system() == "Windows" else "DejaVu Sans Mono", size=11)

        # Tk variables
        self.var_scan_apps = tk.BooleanVar(value=True)
        self.var_include_winget = tk.BooleanVar(value=True)
        self.var_scan_dev = tk.BooleanVar(value=True)

        self.var_distro = tk.StringVar(value="Auto-detect")
        self.var_prefer_flatpak = tk.BooleanVar(value=True)
        self.var_search = tk.StringVar(value="")
        self.var_category_filter = tk.StringVar(value="All Categories")
        self.var_status_filter = tk.StringVar(value="All")
        self.var_inc_vscode = tk.BooleanVar(value=True)
        self.var_inc_npm = tk.BooleanVar(value=False)
        self.var_inc_git = tk.BooleanVar(value=False)

        self.var_chk_external = tk.BooleanVar(value=False)
        self.var_chk_gitpush = tk.BooleanVar(value=False)
        self.var_chk_secrets = tk.BooleanVar(value=False)
        self.var_chk_media = tk.BooleanVar(value=False)

        self.var_delivery_mode = tk.StringVar(value="Save Locally (PC / USB / Cloud)")
        self.var_prefix = tk.StringVar(value="tuxharbor-migration")
        self.var_dest_dir = tk.StringVar(value=str(Path.home() / "Desktop" / "TuxHarbor"))
        self.var_create_zip = tk.BooleanVar(value=True)

        self.var_email_method = tk.StringVar(value="Direct TLS SMTP (with attachments)")
        self.var_smtp_provider = tk.StringVar(value="Gmail")
        self.var_smtp_host = tk.StringVar(value=SMTP_PRESETS["gmail"]["host"])
        self.var_smtp_port = tk.StringVar(value=str(SMTP_PRESETS["gmail"]["port"]))
        self.var_smtp_security = tk.StringVar(value="STARTTLS")
        self.var_smtp_user = tk.StringVar(value="")
        self.var_smtp_recipient = tk.StringVar(value="")
        self.var_draft_recipient = tk.StringVar(value="")

        # Widget refs updated dynamically
        self._step_frames: dict[int, ctk.CTkFrame] = {}
        self._step_buttons: dict[int, ctk.CTkButton] = {}
        self._search_after_id: str | None = None

        self._build_layout()

        # Bind dynamic reactive traces
        self.var_search.trace_add("write", self._on_search_changed)
        self.var_prefix.trace_add("write", lambda *_: self._refresh_filename_preview())

        # Start on Linux Mode automatically if launched on Linux (unless --demo is passed)
        if self.linux_env["is_linux"] and not self.demo_mode_default:
            self.switch_mode("linux")
        else:
            self.switch_mode("planner")
            self.go_to_step(1)

        if self.demo_mode_default:
            # Schedule a quick demo scan banner note without auto-blocking __init__
            self.after(150, self._show_demo_hint)

    # ------------------------------------------------------------------
    # Top-Level Layout
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Top navigation bar
        topbar = ctk.CTkFrame(
            self,
            fg_color=PALETTE["surface"],
            corner_radius=0,
            border_width=1,
            border_color=PALETTE["border"],
            height=64,
        )
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_columnconfigure(1, weight=1)

        # Brand block
        brand_frame = ctk.CTkFrame(topbar, fg_color="transparent")
        brand_frame.grid(row=0, column=0, padx=16, pady=10, sticky="w")

        logo = ctk.CTkLabel(
            brand_frame,
            text="TH",
            width=38,
            height=38,
            corner_radius=10,
            fg_color=PALETTE["teal"],
            text_color="#04151c",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        logo.grid(row=0, column=0, rowspan=2, padx=(0, 10))

        ctk.CTkLabel(
            brand_frame,
            text=__app_name__,
            font=self.font_h2,
            text_color=PALETTE["text"],
        ).grid(row=0, column=1, sticky="w")

        ctk.CTkLabel(
            brand_frame,
            text="100% Local · Zero Ports · Zero Telemetry",
            font=self.font_small,
            text_color=PALETTE["muted"],
        ).grid(row=1, column=1, sticky="w")

        # Mode switcher
        self.mode_segment = ctk.CTkSegmentedButton(
            topbar,
            values=["Windows → Linux Planner", "Linux Mode (Apply Plan)"],
            command=self._on_mode_segment,
            fg_color=PALETTE["bg"],
            selected_color=PALETTE["teal"],
            selected_hover_color=PALETTE["teal_hover"],
            unselected_color=PALETTE["surface_alt"],
            unselected_hover_color=PALETTE["surface_hover"],
            text_color=PALETTE["text"],
            font=self.font_h3,
            height=34,
        )
        self.mode_segment.set("Windows → Linux Planner")
        self.mode_segment.grid(row=0, column=1, padx=12, pady=12)

        # Right status & About/Legal button
        right_bar = ctk.CTkFrame(topbar, fg_color="transparent")
        right_bar.grid(row=0, column=2, padx=16, pady=10, sticky="e")

        os_label = self._detect_os_badge()
        ctk.CTkLabel(
            right_bar,
            text=os_label,
            fg_color=PALETTE["surface_alt"],
            text_color=PALETTE["blue"],
            corner_radius=8,
            padx=10,
            pady=4,
            font=self.font_badge,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            right_bar,
            text="How It Works",
            width=100,
            height=30,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["surface_hover"],
            border_width=1,
            border_color=PALETTE["border"],
            text_color=PALETTE["text"],
            font=self.font_small,
            command=self.open_how_it_works_dialog,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            right_bar,
            text="About / Legal",
            width=105,
            height=30,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["surface_hover"],
            border_width=1,
            border_color=PALETTE["border"],
            text_color=PALETTE["text"],
            font=self.font_small,
            command=self.open_about_legal_dialog,
        ).pack(side="left")

        # Main workspace container
        self.main_container = ctk.CTkFrame(self, fg_color=PALETTE["bg"], corner_radius=0)
        self.main_container.grid(row=1, column=0, sticky="nsew")
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)

        # Planner container (with stepper + 4 steps)
        self.planner_container = ctk.CTkFrame(self.main_container, fg_color=PALETTE["bg"], corner_radius=0)
        self.planner_container.grid(row=0, column=0, sticky="nsew")
        self.planner_container.grid_columnconfigure(0, weight=1)
        self.planner_container.grid_rowconfigure(1, weight=1)

        self._build_stepper(self.planner_container)

        self.step_host = ctk.CTkFrame(self.planner_container, fg_color=PALETTE["bg"], corner_radius=0)
        self.step_host.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 14))
        self.step_host.grid_columnconfigure(0, weight=1)
        self.step_host.grid_rowconfigure(0, weight=1)

        self._build_step1()
        self._build_step2()
        self._build_step3()
        self._build_step4()

        # Linux mode container
        self.linux_container = ctk.CTkFrame(self.main_container, fg_color=PALETTE["bg"], corner_radius=0)
        self.linux_container.grid(row=0, column=0, sticky="nsew", padx=18, pady=14)
        self.linux_container.grid_columnconfigure(0, weight=1)
        self.linux_container.grid_rowconfigure(2, weight=1)
        self._build_linux_mode()

    def _detect_os_badge(self) -> str:
        sys_name = platform.system()
        if sys_name == "Windows":
            return f"Windows {platform.release()}"
        if sys_name == "Linux":
            distro = self.linux_env.get("distro_name") or "Linux"
            return distro[:28]
        return sys_name or "Desktop"

    def _show_demo_hint(self) -> None:
        if self.winfo_exists() and hasattr(self, "scan_status_label"):
            self.scan_status_label.configure(
                text="Demo mode flag detected — click 'Try Demo Mode' to preview with sample Windows data.",
                text_color=PALETTE["blue"],
            )

    def _on_mode_segment(self, value: str) -> None:
        if "Linux Mode" in value:
            self.switch_mode("linux")
        else:
            self.switch_mode("planner")

    def switch_mode(self, mode: str) -> None:
        """Switch between 'planner' and 'linux' modes."""
        self.current_mode = "linux" if mode == "linux" else "planner"
        if self.current_mode == "linux":
            self.mode_segment.set("Linux Mode (Apply Plan)")
            self.planner_container.grid_remove()
            self.linux_container.grid()
        else:
            self.mode_segment.set("Windows → Linux Planner")
            self.linux_container.grid_remove()
            self.planner_container.grid()

    # ------------------------------------------------------------------
    # Stepper Bar
    # ------------------------------------------------------------------
    def _build_stepper(self, parent: ctk.CTkFrame) -> None:
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 10))
        for col in range(4):
            bar.grid_columnconfigure(col, weight=1)

        steps = [
            (1, "1. Scan System"),
            (2, "2. Report & Alternatives"),
            (3, "3. Backup Reminder"),
            (4, "4. Save / Email"),
        ]
        for idx, (num, title) in enumerate(steps):
            btn = ctk.CTkButton(
                bar,
                text=title,
                height=34,
                corner_radius=10,
                fg_color=PALETTE["surface"],
                hover_color=PALETTE["surface_hover"],
                border_width=1,
                border_color=PALETTE["border"],
                text_color=PALETTE["muted"],
                font=self.font_h3,
                command=lambda n=num: self._on_step_button(n),
            )
            btn.grid(row=0, column=idx, sticky="ew", padx=4)
            self._step_buttons[num] = btn

    def _on_step_button(self, step: int) -> None:
        if step > 1 and self.analysis is None:
            messagebox.showinfo(
                __app_name__,
                "Please run a scan (or click 'Try Demo Mode') in Step 1 first.",
                parent=self,
            )
            return
        self.go_to_step(step)

    def go_to_step(self, step: int) -> None:
        """Navigate cleanly to wizard step 1..4 and refresh step-specific panels."""
        step = max(1, min(4, int(step)))
        self.current_step = step

        for num, frame in self._step_frames.items():
            if num == step:
                frame.grid()
            else:
                frame.grid_remove()

        for num, btn in self._step_buttons.items():
            if num == step:
                btn.configure(
                    fg_color=PALETTE["teal"],
                    hover_color=PALETTE["teal_hover"],
                    border_color=PALETTE["teal"],
                    text_color="#04151c",
                )
            elif num < step or (self.analysis is not None):
                btn.configure(
                    fg_color=PALETTE["surface_alt"],
                    hover_color=PALETTE["surface_hover"],
                    border_color=PALETTE["border"],
                    text_color=PALETTE["text"],
                )
            else:
                btn.configure(
                    fg_color=PALETTE["surface"],
                    hover_color=PALETTE["surface_hover"],
                    border_color=PALETTE["border"],
                    text_color=PALETTE["muted"],
                )

        if step == 2 and self.analysis is not None:
            self._render_step2()
        elif step == 3 and self.analysis is not None:
            self._render_step3_risks()
        elif step == 4:
            self._refresh_filename_preview()
            self._refresh_delivery_panels()

    # ------------------------------------------------------------------
    # STEP 1: Scan System & Optional Project Folders
    # ------------------------------------------------------------------
    def _build_step1(self) -> None:
        frame = ctk.CTkFrame(self.step_host, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self._step_frames[1] = frame

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        # Hero Card
        hero = ctk.CTkFrame(
            scroll,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=14,
        )
        hero.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        hero.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            hero,
            text="Plan Your Windows → Linux Switch With Confidence",
            font=self.font_title,
            text_color=PALETTE["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))

        ctk.CTkLabel(
            hero,
            text=(
                "TuxHarbor inspects your installed apps, developer tools, and optional project folders locally — "
                "maps each tool to its native Linux version or curated alternative — and generates a transparent "
                "offline HTML report and safe Linux installer script."
            ),
            font=self.font_body,
            text_color=PALETTE["muted"],
            anchor="w",
            justify="left",
            wraplength=920,
        ).grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 16))

        # Scan Options Card
        opts = ctk.CTkFrame(
            scroll,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=14,
        )
        opts.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        opts.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            opts,
            text="1. Select What to Scan",
            font=self.font_h2,
            text_color=PALETTE["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(14, 8))

        ctk.CTkCheckBox(
            opts,
            text="Windows Applications (Registry HKLM/HKCU, Scoop, Chocolatey)",
            variable=self.var_scan_apps,
            font=self.font_body,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
        ).grid(row=1, column=0, sticky="w", padx=22, pady=5)

        ctk.CTkCheckBox(
            opts,
            text="Enrich with Winget package IDs (improves accuracy; takes a few extra seconds)",
            variable=self.var_include_winget,
            font=self.font_body,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
        ).grid(row=2, column=0, sticky="w", padx=44, pady=5)

        ctk.CTkCheckBox(
            opts,
            text="Developer Environments & VS Code Extensions (Git, Node.js, Python, Docker, Go, Rust, .NET, Java, npm)",
            variable=self.var_scan_dev,
            font=self.font_body,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
        ).grid(row=3, column=0, sticky="w", padx=22, pady=(5, 16))

        # Optional Projects Folder Card
        proj_card = ctk.CTkFrame(
            scroll,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=14,
        )
        proj_card.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        proj_card.grid_columnconfigure(0, weight=1)

        p_hdr = ctk.CTkFrame(proj_card, fg_color="transparent")
        p_hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 6))

        ctk.CTkLabel(
            p_hdr,
            text="2. Optional: Audit Project Folders for Linux Readiness & Git Backup Risks",
            font=self.font_h2,
            text_color=PALETTE["text"],
        ).pack(side="left")

        ctk.CTkLabel(
            p_hdr,
            text="READ-ONLY · Never reads .env contents",
            fg_color=PALETTE["green_dark"],
            text_color=PALETTE["green"],
            corner_radius=8,
            padx=10,
            pady=3,
            font=self.font_badge,
        ).pack(side="right")

        ctk.CTkLabel(
            proj_card,
            text="Checks project manifests for required Linux runtimes, Windows-only targets (WPF/WinForms/.bat), and uncommitted/unpushed Git work.",
            font=self.font_small,
            text_color=PALETTE["muted"],
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 10))

        # Add Folder + Suggested Dirs
        p_btn_row = ctk.CTkFrame(proj_card, fg_color="transparent")
        p_btn_row.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 8))

        ctk.CTkButton(
            p_btn_row,
            text="+ Add Folder",
            width=120,
            height=32,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["surface_hover"],
            border_width=1,
            border_color=PALETTE["teal"],
            text_color=PALETTE["teal"],
            font=self.font_h3,
            command=self._browse_project_folder,
        ).pack(side="left", padx=(0, 10))

        suggested = detect_suggested_project_dirs()[:5]
        if suggested:
            ctk.CTkLabel(
                p_btn_row,
                text="Quick add:",
                font=self.font_small,
                text_color=PALETTE["muted"],
            ).pack(side="left", padx=(0, 6))
            for sdir in suggested:
                short_name = Path(sdir).name or sdir
                ctk.CTkButton(
                    p_btn_row,
                    text=f"+ {short_name}",
                    width=80,
                    height=28,
                    fg_color=PALETTE["surface_alt"],
                    hover_color=PALETTE["surface_hover"],
                    text_color=PALETTE["text"],
                    font=self.font_small,
                    command=lambda d=sdir: self.add_project_dir(d),
                ).pack(side="left", padx=3)

        # Selected folder tags container
        self.project_tags_frame = ctk.CTkFrame(proj_card, fg_color="transparent")
        self.project_tags_frame.grid(row=3, column=0, sticky="ew", padx=20, pady=(2, 14))
        self._render_project_tags()

        # Action & Progress Card
        action_card = ctk.CTkFrame(
            scroll,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=14,
        )
        action_card.grid(row=3, column=0, sticky="ew")
        action_card.grid_columnconfigure(0, weight=1)

        btn_box = ctk.CTkFrame(action_card, fg_color="transparent")
        btn_box.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 10))

        self.btn_start_scan = ctk.CTkButton(
            btn_box,
            text="Start Scan",
            width=210,
            height=44,
            corner_radius=10,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
            text_color="#04151c",
            font=ctk.CTkFont(size=15, weight="bold"),
            command=lambda: self.start_scan(demo_mode=False),
        )
        self.btn_start_scan.pack(side="left", padx=(0, 12))

        self.btn_demo_scan = ctk.CTkButton(
            btn_box,
            text="Try Demo Mode",
            width=165,
            height=44,
            corner_radius=10,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["surface_hover"],
            border_width=1,
            border_color=PALETTE["blue"],
            text_color=PALETTE["blue"],
            font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda: self.start_scan(demo_mode=True),
        )
        self.btn_demo_scan.pack(side="left")

        self.scan_progress = ctk.CTkProgressBar(
            action_card,
            mode="indeterminate",
            progress_color=PALETTE["teal"],
            fg_color=PALETTE["bg"],
            height=8,
        )
        self.scan_progress.grid(row=1, column=0, sticky="ew", padx=20, pady=(4, 6))
        self.scan_progress.grid_remove()

        self.scan_status_label = ctk.CTkLabel(
            action_card,
            text="Ready to scan. All analysis runs 100% locally with zero network requests.",
            font=self.font_small,
            text_color=PALETTE["muted"],
            anchor="w",
        )
        self.scan_status_label.grid(row=2, column=0, sticky="w", padx=20, pady=(0, 14))

    def _browse_project_folder(self) -> None:
        selected = filedialog.askdirectory(parent=self, title="Select Project Folder (Read-Only Scan)")
        if selected:
            self.add_project_dir(selected)

    def add_project_dir(self, folder: str) -> None:
        norm = str(Path(folder).expanduser().resolve())
        if norm.lower() not in {p.lower() for p in self.project_dirs}:
            self.project_dirs.append(norm)
            self._render_project_tags()

    def remove_project_dir(self, folder: str) -> None:
        self.project_dirs = [p for p in self.project_dirs if p != folder]
        self._render_project_tags()

    def _render_project_tags(self) -> None:
        for child in self.project_tags_frame.winfo_children():
            child.destroy()

        if not self.project_dirs:
            ctk.CTkLabel(
                self.project_tags_frame,
                text="No project folders selected (optional — you can still scan Windows apps & dev environments).",
                font=self.font_small,
                text_color=PALETTE["muted"],
            ).pack(anchor="w")
            return

        for pdir in self.project_dirs:
            chip = ctk.CTkFrame(
                self.project_tags_frame,
                fg_color=PALETTE["surface_alt"],
                border_width=1,
                border_color=PALETTE["border"],
                corner_radius=8,
            )
            chip.pack(side="top", anchor="w", pady=3, fill="x")
            ctk.CTkLabel(
                chip,
                text=pdir,
                font=self.font_mono,
                text_color=PALETTE["text"],
                anchor="w",
            ).pack(side="left", padx=10, pady=4, fill="x", expand=True)
            ctk.CTkButton(
                chip,
                text="×",
                width=26,
                height=22,
                fg_color="transparent",
                hover_color=PALETTE["red_dark"],
                text_color=PALETTE["red"],
                font=self.font_h3,
                command=lambda d=pdir: self.remove_project_dir(d),
            ).pack(side="right", padx=4, pady=2)

    def _perform_scan_sync(self, demo_mode: bool) -> dict[str, Any]:
        """Execute read-only system scan and return analysis dict (safe to run in worker thread or tests)."""
        apps = (
            scan_installed_apps(include_winget=bool(self.var_include_winget.get()), demo_mode=demo_mode)
            if (self.var_scan_apps.get() or demo_mode)
            else []
        )
        dev_env = (
            scan_dev_environment(demo_mode=demo_mode)
            if (self.var_scan_dev.get() or demo_mode)
            else DevEnvironment()
        )
        projects = (
            scan_projects_folders(list(self.project_dirs), demo_mode=demo_mode)
            if (self.project_dirs or demo_mode)
            else []
        )

        runtime_ids = [r["catalog_id"] for r in dev_env.runtimes if r.get("catalog_id")]
        if dev_env.vscode_installed:
            runtime_ids.append("vscode")
        for p in projects:
            runtime_ids.extend(p.get("recommended_runtimes", []))

        hw_profile = detect_system_hardware(demo_mode=demo_mode)
        analysis = self.catalog.analyze_apps(
            apps,
            detected_runtime_ids=runtime_ids,
            hardware_profile=hw_profile,
        )
        analysis["dev_env"] = dev_env.to_dict()
        analysis["projects"] = projects
        analysis["demo_mode"] = demo_mode
        return analysis

    def load_demo_scan_sync(self) -> dict[str, Any]:
        """Synchronous helper to load demo scan results (useful for automated tests)."""
        self.analysis = self._perform_scan_sync(demo_mode=True)
        self._apply_scan_defaults()
        return self.analysis

    def _apply_scan_defaults(self) -> None:
        if not self.analysis:
            return
        dev = self.analysis.get("dev_env", {}) or {}
        self.var_inc_vscode.set(bool(dev.get("vscode_extensions")))
        self.var_inc_npm.set(False)
        self.var_inc_git.set(False)
        self.os_builtins_expanded = False
        self.unmatched_expanded = False
        self.var_category_filter.set("All Categories")

    def start_scan(self, demo_mode: bool = False) -> None:
        if self.is_busy:
            return
        self.is_busy = True
        self.btn_start_scan.configure(state="disabled")
        self.btn_demo_scan.configure(state="disabled")
        self.scan_progress.grid()
        self.scan_progress.start()
        self.scan_status_label.configure(
            text="Loading realistic demo Windows PC data..." if demo_mode else "Scanning Windows applications, dev runtimes, and project folders...",
            text_color=PALETTE["teal"],
        )

        def worker() -> None:
            try:
                result = self._perform_scan_sync(demo_mode=demo_mode)
                self.after(0, lambda r=result: self._on_scan_complete(r))
            except Exception as exc:
                err_msg = str(exc) or exc.__class__.__name__
                self.after(0, lambda m=err_msg: self._on_scan_error(m))

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_complete(self, result: dict[str, Any]) -> None:
        if not self.winfo_exists():
            return
        self.is_busy = False
        self.scan_progress.stop()
        self.scan_progress.grid_remove()
        self.btn_start_scan.configure(state="normal")
        self.btn_demo_scan.configure(state="normal")

        self.analysis = result
        self._apply_scan_defaults()
        c = result["counts"]
        self.scan_status_label.configure(
            text=(
                f"Scan complete! Matched {c['total_matched']} apps, {c.get('hardware_drivers', 0)} hardware groups, "
                f"{c.get('games', 0)} PC games ({c.get('os_builtins', 0)} OS built-ins excluded · Readiness: {result['readiness_score']}%)."
            ),
            text_color=PALETTE["green"],
        )
        self.go_to_step(2)

    def _on_scan_error(self, message: str) -> None:
        if not self.winfo_exists():
            return
        self.is_busy = False
        self.scan_progress.stop()
        self.scan_progress.grid_remove()
        self.btn_start_scan.configure(state="normal")
        self.btn_demo_scan.configure(state="normal")
        self.scan_status_label.configure(text=f"Scan error: {message}", text_color=PALETTE["red"])
        messagebox.showerror(__app_name__, f"Scan failed:\n{message}", parent=self)

    # ------------------------------------------------------------------
    # STEP 2: Report & Alternatives
    # ------------------------------------------------------------------
    def _build_step2(self) -> None:
        frame = ctk.CTkFrame(self.step_host, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(3, weight=1)
        self._step_frames[2] = frame

        # Top Stats Strip
        stats_row = ctk.CTkFrame(frame, fg_color="transparent")
        stats_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        for i in range(5):
            stats_row.grid_columnconfigure(i, weight=1)

        self._stat_labels: dict[str, ctk.CTkLabel] = {}
        stat_specs = [
            ("score", "Linux Readiness", PALETTE["teal"]),
            ("native", "Native on Linux", PALETTE["green"]),
            ("alternative", "Great Alternatives", PALETTE["blue"]),
            ("compat", "Compat Layer", PALETTE["amber"]),
            ("attention", "Needs Attention", PALETTE["red"]),
        ]
        for idx, (key, title, color) in enumerate(stat_specs):
            card = ctk.CTkFrame(
                stats_row,
                fg_color=PALETTE["surface"],
                border_width=1,
                border_color=PALETTE["border"],
                corner_radius=12,
            )
            card.grid(row=0, column=idx, sticky="ew", padx=4)
            ctk.CTkLabel(card, text=title, font=self.font_small, text_color=PALETTE["muted"]).pack(
                anchor="w", padx=12, pady=(6, 0)
            )
            val_lbl = ctk.CTkLabel(card, text="0", font=self.font_stat, text_color=color)
            val_lbl.pack(anchor="w", padx=12, pady=(0, 6))
            self._stat_labels[key] = val_lbl

        # Secondary 5-Bucket Summary Bar
        self.bucket_summary_label = ctk.CTkLabel(
            frame,
            text="Hardware & Drivers: 0  ·  PC Games: 0  ·  Windows OS Built-ins Excluded: 0  ·  Other / Niche: 0",
            font=self.font_small,
            text_color=PALETTE["muted"],
            anchor="w",
        )
        self.bucket_summary_label.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))

        # Filter & Target Toolbar
        toolbar = ctk.CTkFrame(
            frame,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=12,
        )
        toolbar.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        row_top = ctk.CTkFrame(toolbar, fg_color="transparent")
        row_top.pack(fill="x", padx=12, pady=(8, 4))

        ctk.CTkLabel(row_top, text="Target Distro:", font=self.font_small, text_color=PALETTE["muted"]).pack(
            side="left", padx=(0, 6)
        )
        ctk.CTkOptionMenu(
            row_top,
            values=[label for label, _ in DISTRO_OPTIONS],
            variable=self.var_distro,
            width=180,
            height=28,
            fg_color=PALETTE["surface_alt"],
            button_color=PALETTE["border"],
            button_hover_color=PALETTE["surface_hover"],
            font=self.font_small,
        ).pack(side="left", padx=(0, 14))

        ctk.CTkCheckBox(
            row_top,
            text="Prefer Flatpak (universal)",
            variable=self.var_prefer_flatpak,
            font=self.font_small,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
        ).pack(side="left", padx=(0, 14))

        ctk.CTkButton(
            row_top,
            text="Clear",
            width=64,
            height=26,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["surface_hover"],
            font=self.font_small,
            command=lambda: self._bulk_select_apps(False),
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            row_top,
            text="Select All",
            width=82,
            height=26,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["surface_hover"],
            border_width=1,
            border_color=PALETTE["teal"],
            text_color=PALETTE["teal"],
            font=self.font_small,
            command=lambda: self._bulk_select_apps(True),
        ).pack(side="right")

        row_bot = ctk.CTkFrame(toolbar, fg_color="transparent")
        row_bot.pack(fill="x", padx=12, pady=(2, 8))

        ctk.CTkEntry(
            row_bot,
            textvariable=self.var_search,
            placeholder_text="Search apps or alternatives...",
            width=220,
            height=30,
            fg_color=PALETTE["bg"],
            border_color=PALETTE["border"],
            font=self.font_small,
        ).pack(side="left", padx=(0, 8))

        self.category_menu = ctk.CTkOptionMenu(
            row_bot,
            values=["All Categories"],
            variable=self.var_category_filter,
            command=lambda _v: self._render_apps_list(),
            width=185,
            height=30,
            fg_color=PALETTE["surface_alt"],
            button_color=PALETTE["border"],
            button_hover_color=PALETTE["surface_hover"],
            font=self.font_small,
        )
        self.category_menu.pack(side="left", padx=(0, 8))

        self.filter_segment = ctk.CTkSegmentedButton(
            row_bot,
            values=["All", "Native", "Alternative", "Compat", "Attention"],
            variable=self.var_status_filter,
            command=lambda _v: self._render_apps_list(),
            fg_color=PALETTE["bg"],
            selected_color=PALETTE["teal"],
            selected_hover_color=PALETTE["teal_hover"],
            unselected_color=PALETTE["surface_alt"],
            unselected_hover_color=PALETTE["surface_hover"],
            text_color=PALETTE["text"],
            font=self.font_small,
            height=30,
        )
        self.filter_segment.pack(side="left", fill="x", expand=True)

        # Scrollable main body for Step 2 (apps + hardware + games + projects + dev env + os built-ins + unmatched)
        self.step2_scroll = ctk.CTkScrollableFrame(
            frame,
            fg_color=PALETTE["bg"],
            corner_radius=10,
        )
        self.step2_scroll.grid(row=3, column=0, sticky="nsew")
        self.step2_scroll.grid_columnconfigure(0, weight=1)

        self.apps_list_container = ctk.CTkFrame(self.step2_scroll, fg_color="transparent")
        self.apps_list_container.grid(row=0, column=0, sticky="ew")
        self.apps_list_container.grid_columnconfigure(0, weight=1)

        self.hardware_panel = ctk.CTkFrame(self.step2_scroll, fg_color="transparent")
        self.hardware_panel.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.hardware_panel.grid_columnconfigure(0, weight=1)

        self.games_panel = ctk.CTkFrame(self.step2_scroll, fg_color="transparent")
        self.games_panel.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.games_panel.grid_columnconfigure(0, weight=1)

        self.projects_panel = ctk.CTkFrame(self.step2_scroll, fg_color="transparent")
        self.projects_panel.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.projects_panel.grid_columnconfigure(0, weight=1)

        self.dev_env_panel = ctk.CTkFrame(self.step2_scroll, fg_color="transparent")
        self.dev_env_panel.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self.dev_env_panel.grid_columnconfigure(0, weight=1)

        self.os_builtins_panel = ctk.CTkFrame(self.step2_scroll, fg_color="transparent")
        self.os_builtins_panel.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        self.os_builtins_panel.grid_columnconfigure(0, weight=1)

        self.unmatched_panel = ctk.CTkFrame(self.step2_scroll, fg_color="transparent")
        self.unmatched_panel.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        self.unmatched_panel.grid_columnconfigure(0, weight=1)

        # Footer Navigation
        footer = ctk.CTkFrame(frame, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))

        ctk.CTkButton(
            footer,
            text="← Back to Scan",
            width=140,
            height=36,
            fg_color=PALETTE["surface"],
            hover_color=PALETTE["surface_hover"],
            border_width=1,
            border_color=PALETTE["border"],
            command=lambda: self.go_to_step(1),
        ).pack(side="left")

        self.step2_selected_label = ctk.CTkLabel(
            footer,
            text="0 apps selected",
            font=self.font_h3,
            text_color=PALETTE["muted"],
        )
        self.step2_selected_label.pack(side="left", padx=18)

        ctk.CTkButton(
            footer,
            text="Continue to Backup Checklist →",
            width=235,
            height=38,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
            text_color="#04151c",
            font=self.font_h3,
            command=lambda: self.go_to_step(3),
        ).pack(side="right")

    def _on_search_changed(self, *_args: Any) -> None:
        if self.current_step != 2 or self.analysis is None:
            return
        if self._search_after_id:
            try:
                self.after_cancel(self._search_after_id)
            except Exception:
                pass
        self._search_after_id = self.after(120, self._render_apps_list)

    def _bulk_select_apps(self, state: bool) -> None:
        if not self.analysis:
            return
        for item in self.analysis.get("matched", []):
            if item.get("no_install_needed"):
                item["selected"] = False
            else:
                item["selected"] = state
        self._render_apps_list()

    def _update_selected_counter(self) -> None:
        if not self.analysis:
            return
        matched = self.analysis.get("matched", [])
        sel = sum(1 for item in matched if item.get("selected") and not item.get("no_install_needed"))
        total = len(matched)
        self.step2_selected_label.configure(text=f"{sel} of {total} matched apps selected for Linux setup")

    def _category_display_label(self, cat_id: str) -> str:
        cats_meta = (self.analysis or {}).get("categories") or {}
        if isinstance(cats_meta.get(cat_id), dict) and cats_meta[cat_id].get("label"):
            return str(cats_meta[cat_id]["label"])
        return DEFAULT_CATEGORY_LABELS.get(cat_id, cat_id.replace("_", " ").title())

    def _render_step2(self) -> None:
        if not self.analysis:
            return
        counts = self.analysis.get("counts", {})
        self._stat_labels["score"].configure(text=f"{self.analysis.get('readiness_score', 100)}%")
        self._stat_labels["native"].configure(text=str(counts.get("native", 0)))
        self._stat_labels["alternative"].configure(text=str(counts.get("alternative", 0)))
        self._stat_labels["compat"].configure(text=str(counts.get("compat", 0)))
        self._stat_labels["attention"].configure(text=str(counts.get("attention", 0)))

        self.bucket_summary_label.configure(
            text=(
                f"Hardware & Drivers: {counts.get('hardware_drivers', 0)}  ·  "
                f"PC Games: {counts.get('games', 0)}  ·  "
                f"Windows OS Built-ins Excluded: {counts.get('os_builtins', 0)}  ·  "
                f"Other / Niche Apps: {counts.get('unmatched', 0)}"
            )
        )

        # Populate category filter options dynamically from detected matched apps
        present_cats = {str(m.get("category", "utilities")) for m in self.analysis.get("matched", [])}
        full_order = (*CATEGORY_ORDER, "gaming")
        ordered_cats = [c for c in full_order if c in present_cats]
        for c in sorted(present_cats):
            if c not in ordered_cats:
                ordered_cats.append(c)

        self._cat_label_to_id = {self._category_display_label(c): c for c in ordered_cats}
        cat_options = ["All Categories", *self._cat_label_to_id.keys()]
        self.category_menu.configure(values=cat_options)
        if self.var_category_filter.get() not in cat_options:
            self.var_category_filter.set("All Categories")

        self._render_apps_list()
        self._render_hardware_panel()
        self._render_games_panel()
        self._render_projects_panel()
        self._render_dev_env_panel()
        self._render_os_builtins_panel()
        self._render_unmatched_panel()

    def _render_apps_list(self) -> None:
        for w in self.apps_list_container.winfo_children():
            w.destroy()

        if not self.analysis:
            return

        query = self.var_search.get().strip().lower()
        filt = self.var_status_filter.get()
        filter_map = {
            "All": None,
            "Native": "native",
            "Alternative": "alternative",
            "Compat": "compat",
            "Attention": "attention",
        }
        want_status = filter_map.get(filt)
        cat_label_sel = self.var_category_filter.get()
        want_cat = None if cat_label_sel == "All Categories" else getattr(self, "_cat_label_to_id", {}).get(cat_label_sel)

        status_styles = {
            "native": ("Native on Linux", PALETTE["green_dark"], PALETTE["green"]),
            "alternative": ("Great Alternative", PALETTE["blue_dark"], PALETTE["blue"]),
            "compat": ("Compatibility Layer", PALETTE["amber_dark"], PALETTE["amber"]),
            "attention": ("Needs Attention", PALETTE["red_dark"], PALETTE["red"]),
        }

        items = self.analysis.get("matched", [])
        grouped: dict[str, list[dict[str, Any]]] = {}
        shown = 0

        for item in items:
            if want_status and item.get("status") != want_status:
                continue
            item_cat = str(item.get("category", "utilities") or "utilities")
            if want_cat and item_cat != want_cat:
                continue
            if query:
                hay = (
                    f"{item.get('name', '')} {item.get('summary', '')} "
                    f"{item.get('category_label', '')} "
                    f"{' '.join(a.get('name', '') for a in item.get('alternatives', []))}"
                ).lower()
                if query not in hay:
                    continue
            grouped.setdefault(item_cat, []).append(item)
            shown += 1

        full_order = (*CATEGORY_ORDER, "gaming")
        ordered_cats = [c for c in full_order if c in grouped]
        for c in sorted(grouped.keys()):
            if c not in ordered_cats:
                ordered_cats.append(c)

        for cat_id in ordered_cats:
            cat_items = grouped[cat_id]
            cat_title = self._category_display_label(cat_id)
            hdr_bar = ctk.CTkFrame(
                self.apps_list_container,
                fg_color=PALETTE["surface_alt"],
                corner_radius=8,
            )
            hdr_bar.pack(fill="x", pady=(8, 3))
            ctk.CTkLabel(
                hdr_bar,
                text=f"{cat_title}  ({len(cat_items)})",
                font=self.font_h3,
                text_color=PALETTE["teal"],
                anchor="w",
            ).pack(side="left", padx=12, pady=5)

            for item in cat_items:
                card = ctk.CTkFrame(
                    self.apps_list_container,
                    fg_color=PALETTE["surface"],
                    border_width=1,
                    border_color=PALETTE["border"],
                    corner_radius=12,
                )
                card.pack(fill="x", pady=4)
                card.grid_columnconfigure(0, weight=1)

                top_row = ctk.CTkFrame(card, fg_color="transparent")
                top_row.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))

                no_install = bool(item.get("no_install_needed"))
                ver = f"  v{item['detected_version']}" if item.get("detected_version") else ""

                if no_install:
                    ctk.CTkLabel(
                        top_row,
                        text=f"✓  {item.get('name', 'App')}{ver}",
                        font=self.font_h3,
                        text_color=PALETTE["text"],
                        anchor="w",
                    ).pack(side="left", padx=(4, 0))
                else:
                    chk_var = tk.BooleanVar(value=bool(item.get("selected")))

                    def on_toggle(it: dict[str, Any] = item, var: tk.BooleanVar = chk_var) -> None:
                        it["selected"] = bool(var.get())
                        self._update_selected_counter()

                    ctk.CTkCheckBox(
                        top_row,
                        text=f"{item.get('name', 'App')}{ver}",
                        variable=chk_var,
                        command=on_toggle,
                        font=self.font_h3,
                        fg_color=PALETTE["teal"],
                        hover_color=PALETTE["teal_hover"],
                        text_color=PALETTE["text"],
                    ).pack(side="left")

                if no_install:
                    st_text, st_bg, st_fg = ("Handled by Linux", PALETTE["green_dark"], PALETTE["green"])
                else:
                    st_text, st_bg, st_fg = status_styles.get(item.get("status", "native"), status_styles["native"])

                ctk.CTkLabel(
                    top_row,
                    text=st_text,
                    fg_color=st_bg,
                    text_color=st_fg,
                    corner_radius=8,
                    padx=10,
                    pady=2,
                    font=self.font_badge,
                ).pack(side="right")

                summary = item.get("summary") or ""
                if summary:
                    ctk.CTkLabel(
                        card,
                        text=summary,
                        font=self.font_small,
                        text_color=PALETTE["muted"],
                        anchor="w",
                        justify="left",
                        wraplength=920,
                    ).grid(row=1, column=0, sticky="ew", padx=36, pady=(0, 6))

                alts = item.get("alternatives") or []
                if alts and not no_install:
                    alt_row = ctk.CTkFrame(card, fg_color=PALETTE["surface_alt"], corner_radius=8)
                    alt_row.grid(row=2, column=0, sticky="ew", padx=36, pady=(0, 10))

                    ctk.CTkLabel(
                        alt_row,
                        text="Linux Alternative:",
                        font=self.font_badge,
                        text_color=PALETTE["blue"],
                    ).pack(side="left", padx=(10, 8), pady=6)

                    option_labels: list[str] = []
                    label_to_alt: dict[str, dict[str, Any]] = {}
                    current_label = ""
                    for alt in alts:
                        rec_suffix = " (Recommended)" if alt.get("recommended") else ""
                        lbl = f"{alt.get('name', alt['id'])}{rec_suffix}"
                        option_labels.append(lbl)
                        label_to_alt[lbl] = alt
                        if alt.get("id") == item.get("selected_alternative_id"):
                            current_label = lbl
                    if not current_label and option_labels:
                        current_label = option_labels[0]

                    alt_var = tk.StringVar(value=current_label)
                    tagline_lbl = ctk.CTkLabel(
                        alt_row,
                        text=label_to_alt[current_label].get("tagline", ""),
                        font=self.font_small,
                        text_color=PALETTE["muted"],
                        anchor="w",
                        wraplength=540,
                        justify="left",
                    )

                    def on_alt_change(
                        choice: str,
                        it: dict[str, Any] = item,
                        mapping: dict[str, dict[str, Any]] = label_to_alt,
                        t_lbl: ctk.CTkLabel = tagline_lbl,
                    ) -> None:
                        chosen_alt = mapping.get(choice)
                        if chosen_alt:
                            it["selected_alternative_id"] = chosen_alt["id"]
                            t_lbl.configure(text=chosen_alt.get("tagline", ""))

                    ctk.CTkOptionMenu(
                        alt_row,
                        values=option_labels,
                        variable=alt_var,
                        command=on_alt_change,
                        width=250,
                        height=28,
                        fg_color=PALETTE["bg"],
                        button_color=PALETTE["border"],
                        button_hover_color=PALETTE["surface_hover"],
                        font=self.font_small,
                    ).pack(side="left", padx=(0, 10), pady=6)

                    tagline_lbl.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=6)
                elif not no_install:
                    pkgs = item.get("linux_packages") or {}
                    pkg_preview = pkgs.get("flatpak") or pkgs.get("apt") or pkgs.get("pacman") or pkgs.get("official_url") or ""
                    if pkg_preview:
                        ctk.CTkLabel(
                            card,
                            text=f"Linux target: {pkg_preview}",
                            font=self.font_mono,
                            text_color=PALETTE["teal"],
                            anchor="w",
                        ).grid(row=2, column=0, sticky="w", padx=36, pady=(0, 10))

        if shown == 0:
            ctk.CTkLabel(
                self.apps_list_container,
                text="No matched applications fit the current search or filter.",
                font=self.font_body,
                text_color=PALETTE["muted"],
            ).pack(pady=24)

        self._update_selected_counter()

    def _render_hardware_panel(self) -> None:
        for w in self.hardware_panel.winfo_children():
            w.destroy()
        hw_items = (self.analysis or {}).get("hardware_drivers") or []
        if not hw_items:
            return

        card = ctk.CTkFrame(
            self.hardware_panel,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=12,
        )
        card.pack(fill="x")

        ctk.CTkLabel(
            card,
            text=f"Hardware & Drivers ({len(hw_items)})",
            font=self.font_h2,
            text_color=PALETTE["text"],
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 2))

        ctk.CTkLabel(
            card,
            text=(
                "GPU, chipset, audio, and peripheral drivers are managed by the Linux kernel or your distribution's "
                "driver manager — TuxHarbor's installer script never auto-modifies kernel or GPU drivers."
            ),
            font=self.font_small,
            text_color=PALETTE["muted"],
            anchor="w",
            wraplength=920,
            justify="left",
        ).pack(fill="x", padx=14, pady=(0, 8))

        driver_styles = {
            "official_driver": ("Official Linux Driver", PALETTE["teal_dark"], PALETTE["teal"]),
            "kernel_builtin": ("Built into Linux Kernel", PALETTE["green_dark"], PALETTE["green"]),
            "oem_utility": ("Hardware / OEM Utility", PALETTE["surface"], PALETTE["muted"]),
        }

        for hw in hw_items:
            hrow = ctk.CTkFrame(card, fg_color=PALETTE["surface_alt"], corner_radius=8)
            hrow.pack(fill="x", padx=14, pady=4)

            hdr = ctk.CTkFrame(hrow, fg_color="transparent")
            hdr.pack(fill="x", padx=10, pady=(6, 2))

            comps = hw.get("detected_components") or []
            comp_cnt = hw.get("component_count", len(comps))
            ctk.CTkLabel(
                hdr,
                text=f"{hw.get('name', 'Hardware')}   ({comp_cnt} detected)",
                font=self.font_h3,
                text_color=PALETTE["text"],
            ).pack(side="left")

            d_st = str(hw.get("driver_status", "oem_utility"))
            d_default, d_bg, d_fg = driver_styles.get(d_st, driver_styles["oem_utility"])
            d_label = str(hw.get("driver_status_label") or d_default)
            ctk.CTkLabel(
                hdr,
                text=d_label,
                fg_color=d_bg,
                text_color=d_fg,
                corner_radius=6,
                padx=8,
                pady=2,
                font=self.font_badge,
            ).pack(side="right")

            raw_url = str(hw.get("official_url", "")).strip()
            if is_safe_https_url(raw_url):
                ctk.CTkButton(
                    hdr,
                    text="Official Driver Guide",
                    width=136,
                    height=24,
                    fg_color=PALETTE["bg"],
                    hover_color=PALETTE["surface_hover"],
                    text_color=PALETTE["teal"],
                    font=self.font_small,
                    command=lambda url=raw_url: _safe_open_url(url),
                ).pack(side="right", padx=(0, 8))

            if hw.get("summary"):
                ctk.CTkLabel(
                    hrow,
                    text=str(hw["summary"]),
                    font=self.font_small,
                    text_color=PALETTE["muted"],
                    anchor="w",
                    wraplength=900,
                    justify="left",
                ).pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkFrame(card, fg_color="transparent", height=6).pack()

    def _render_games_panel(self) -> None:
        for w in self.games_panel.winfo_children():
            w.destroy()
        games = (self.analysis or {}).get("games") or []
        if not games:
            return

        card = ctk.CTkFrame(
            self.games_panel,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=12,
        )
        card.pack(fill="x")

        ctk.CTkLabel(
            card,
            text=f"Detected PC Games ({len(games)})",
            font=self.font_h2,
            text_color=PALETTE["text"],
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 2))

        ctk.CTkLabel(
            card,
            text=(
                "ProtonDB and AreWeAntiCheatYet are independent, community-maintained compatibility databases — "
                "not official vendor or publisher guarantees."
            ),
            font=self.font_small,
            text_color=PALETTE["muted"],
            anchor="w",
            wraplength=920,
            justify="left",
        ).pack(fill="x", padx=14, pady=(0, 8))

        game_styles = {
            "anticheat_blocked": ("Blocked by Anti-Cheat", PALETTE["red_dark"], PALETTE["red"]),
            "anticheat_caution": ("Online Anti-Cheat Caution", PALETTE["amber_dark"], PALETTE["amber"]),
            "check_protondb": ("Check ProtonDB", PALETTE["blue_dark"], PALETTE["blue"]),
        }

        for g in games:
            grow = ctk.CTkFrame(card, fg_color=PALETTE["surface_alt"], corner_radius=8)
            grow.pack(fill="x", padx=14, pady=4)

            hdr = ctk.CTkFrame(grow, fg_color="transparent")
            hdr.pack(fill="x", padx=10, pady=(6, 2))

            g_name = str(g.get("name", "Game"))
            g_plat = str(g.get("platform", "PC Game"))
            ctk.CTkLabel(
                hdr,
                text=f"{g_name}   [{g_plat}]",
                font=self.font_h3,
                text_color=PALETTE["text"],
            ).pack(side="left")

            g_st = str(g.get("status", "check_protondb"))
            g_default, g_bg, g_fg = game_styles.get(g_st, game_styles["check_protondb"])
            g_label = str(g.get("status_label") or g_default)
            ctk.CTkLabel(
                hdr,
                text=g_label,
                fg_color=g_bg,
                text_color=g_fg,
                corner_radius=6,
                padx=8,
                pady=2,
                font=self.font_badge,
            ).pack(side="right")

            encoded_q = urllib.parse.quote_plus(g_name)
            steam_id = str(g.get("steam_app_id", "")).strip()
            p_url = str(g.get("protondb_url", "")).strip()
            if not is_safe_https_url_for_hosts(p_url, PROTONDB_ALLOWED_HOSTS):
                p_url = (
                    f"https://www.protondb.com/app/{steam_id}"
                    if is_safe_steam_app_id(steam_id)
                    else f"https://www.protondb.com/search?q={encoded_q}"
                )
            ac_url = str(g.get("anticheat_url", "")).strip()
            if not is_safe_https_url_for_hosts(ac_url, ANTICHEAT_ALLOWED_HOSTS):
                ac_url = f"https://areweanticheatyet.com/?search={encoded_q}"

            ctk.CTkButton(
                hdr,
                text="AreWeAntiCheatYet",
                width=128,
                height=24,
                fg_color=PALETTE["bg"],
                hover_color=PALETTE["surface_hover"],
                text_color=PALETTE["amber"],
                font=self.font_small,
                command=lambda url=ac_url: _safe_open_url(url),
            ).pack(side="right", padx=(4, 8))

            ctk.CTkButton(
                hdr,
                text="ProtonDB",
                width=78,
                height=24,
                fg_color=PALETTE["bg"],
                hover_color=PALETTE["surface_hover"],
                text_color=PALETTE["blue"],
                font=self.font_small,
                command=lambda url=p_url: _safe_open_url(url),
            ).pack(side="right", padx=4)

            if g.get("note"):
                ctk.CTkLabel(
                    grow,
                    text=str(g["note"]),
                    font=self.font_small,
                    text_color=PALETTE["muted"],
                    anchor="w",
                    wraplength=900,
                    justify="left",
                ).pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkFrame(card, fg_color="transparent", height=6).pack()

    def _render_projects_panel(self) -> None:
        for w in self.projects_panel.winfo_children():
            w.destroy()
        projects = (self.analysis or {}).get("projects") or []
        if not projects:
            return

        card = ctk.CTkFrame(
            self.projects_panel,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=12,
        )
        card.pack(fill="x")

        ctk.CTkLabel(
            card,
            text=f"Projects Compatibility & Git Backup Alerts ({len(projects)})",
            font=self.font_h2,
            text_color=PALETTE["text"],
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 6))

        for proj in projects:
            prow = ctk.CTkFrame(card, fg_color=PALETTE["surface_alt"], corner_radius=8)
            prow.pack(fill="x", padx=14, pady=4)

            hdr = ctk.CTkFrame(prow, fg_color="transparent")
            hdr.pack(fill="x", padx=10, pady=(6, 2))
            stacks = ", ".join(proj.get("stacks", [])) or "General"
            ctk.CTkLabel(
                hdr,
                text=f"{proj.get('name', 'Project')}  —  {stacks}",
                font=self.font_h3,
                text_color=PALETTE["text"],
            ).pack(side="left")

            compat = proj.get("compatibility", "ready")
            c_style = {
                "ready": ("Linux Ready", PALETTE["green_dark"], PALETTE["green"]),
                "warning": ("Minor Tweaks", PALETTE["amber_dark"], PALETTE["amber"]),
                "blocker": ("Windows-Specific", PALETTE["red_dark"], PALETTE["red"]),
            }.get(compat, ("Linux Ready", PALETTE["green_dark"], PALETTE["green"]))
            ctk.CTkLabel(
                hdr,
                text=c_style[0],
                fg_color=c_style[1],
                text_color=c_style[2],
                corner_radius=6,
                padx=8,
                pady=2,
                font=self.font_badge,
            ).pack(side="right")

            for lw in proj.get("linux_warnings", []):
                ctk.CTkLabel(
                    prow,
                    text=f"⚠ {lw.get('message', '')}",
                    font=self.font_small,
                    text_color=PALETTE["amber"],
                    anchor="w",
                    wraplength=880,
                    justify="left",
                ).pack(fill="x", padx=12, pady=1)

            for bw in proj.get("backup_warnings", []):
                ctk.CTkLabel(
                    prow,
                    text=f"• Backup Alert: {bw.get('message', '')}",
                    font=self.font_small,
                    text_color=PALETTE["red"],
                    anchor="w",
                    wraplength=880,
                    justify="left",
                ).pack(fill="x", padx=12, pady=(1, 4))

        ctk.CTkFrame(card, fg_color="transparent", height=6).pack()

    def _render_dev_env_panel(self) -> None:
        for w in self.dev_env_panel.winfo_children():
            w.destroy()
        dev = (self.analysis or {}).get("dev_env") or {}
        exts = dev.get("vscode_extensions") or []
        npms = dev.get("npm_globals") or []
        gname = dev.get("git_user_name") or ""
        gemail = dev.get("git_user_email") or ""

        if not (exts or npms or gname or gemail):
            return

        card = ctk.CTkFrame(
            self.dev_env_panel,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=12,
        )
        card.pack(fill="x")

        ctk.CTkLabel(
            card,
            text="Developer Environment Extras",
            font=self.font_h2,
            text_color=PALETTE["text"],
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 6))

        if exts:
            ctk.CTkCheckBox(
                card,
                text=f"Reinstall VS Code extensions ({len(exts)} detected)",
                variable=self.var_inc_vscode,
                font=self.font_body,
                fg_color=PALETTE["teal"],
                hover_color=PALETTE["teal_hover"],
            ).pack(anchor="w", padx=16, pady=4)

        if npms:
            ctk.CTkCheckBox(
                card,
                text=f"Reinstall global npm CLI tools ({len(npms)} detected: {', '.join(npms[:5])}{'...' if len(npms) > 5 else ''})",
                variable=self.var_inc_npm,
                font=self.font_body,
                fg_color=PALETTE["teal"],
                hover_color=PALETTE["teal_hover"],
            ).pack(anchor="w", padx=16, pady=4)

        if gname or gemail:
            ctk.CTkCheckBox(
                card,
                text=f"Include Git global identity ({gname} <{gemail}>)",
                variable=self.var_inc_git,
                font=self.font_body,
                fg_color=PALETTE["teal"],
                hover_color=PALETTE["teal_hover"],
            ).pack(anchor="w", padx=16, pady=(4, 12))
        else:
            ctk.CTkFrame(card, fg_color="transparent", height=8).pack()

    def _render_os_builtins_panel(self) -> None:
        for w in self.os_builtins_panel.winfo_children():
            w.destroy()
        builtins_list = (self.analysis or {}).get("os_builtins") or []
        if not builtins_list:
            return

        card = ctk.CTkFrame(
            self.os_builtins_panel,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=12,
        )
        card.pack(fill="x")

        toggle_text = (
            f"▼ {len(builtins_list)} Windows built-in apps, codecs & runtimes excluded — handled natively by Linux"
            if self.os_builtins_expanded
            else f"▶ {len(builtins_list)} Windows built-in apps, codecs & runtimes excluded — handled natively by Linux"
        )
        ctk.CTkButton(
            card,
            text=toggle_text,
            anchor="w",
            fg_color="transparent",
            hover_color=PALETTE["surface_alt"],
            text_color=PALETTE["muted"],
            font=self.font_h3,
            command=self._toggle_os_builtins,
        ).pack(fill="x", padx=10, pady=8)

        if self.os_builtins_expanded:
            for item in builtins_list[:80]:
                row = ctk.CTkFrame(card, fg_color=PALETTE["surface_alt"], corner_radius=8)
                row.pack(fill="x", padx=14, pady=2)
                ver = f"  ({item.get('version', '')})" if item.get("version") else ""
                ctk.CTkLabel(
                    row,
                    text=f"{item.get('name', '')}{ver}",
                    font=self.font_small,
                    text_color=PALETTE["text"],
                    anchor="w",
                ).pack(side="left", padx=10, pady=4, fill="x", expand=True)
                ctk.CTkLabel(
                    row,
                    text=str(item.get("reason", "Windows Built-in App / Codec")),
                    font=self.font_small,
                    text_color=PALETTE["muted"],
                    anchor="e",
                ).pack(side="right", padx=10, pady=4)
            if len(builtins_list) > 80:
                ctk.CTkLabel(
                    card,
                    text=f"... and {len(builtins_list) - 80} additional Windows built-in components (full list in HTML report).",
                    font=self.font_small,
                    text_color=PALETTE["muted"],
                    anchor="w",
                ).pack(fill="x", padx=16, pady=(4, 6))
            ctk.CTkFrame(card, fg_color="transparent", height=6).pack()

    def _toggle_os_builtins(self) -> None:
        self.os_builtins_expanded = not self.os_builtins_expanded
        self._render_os_builtins_panel()

    def _render_unmatched_panel(self) -> None:
        for w in self.unmatched_panel.winfo_children():
            w.destroy()
        unmatched = (self.analysis or {}).get("unmatched") or []
        if not unmatched:
            return

        card = ctk.CTkFrame(
            self.unmatched_panel,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=12,
        )
        card.pack(fill="x")

        toggle_text = (
            f"▼ Hide Other / Niche Apps ({len(unmatched)})"
            if self.unmatched_expanded
            else f"▶ Show Other / Niche Apps ({len(unmatched)})"
        )
        ctk.CTkButton(
            card,
            text=toggle_text,
            anchor="w",
            fg_color="transparent",
            hover_color=PALETTE["surface_alt"],
            text_color=PALETTE["muted"],
            font=self.font_h3,
            command=self._toggle_unmatched,
        ).pack(fill="x", padx=10, pady=8)

        if self.unmatched_expanded:
            for u in unmatched[:60]:
                name = str(u.get("name", ""))
                row = ctk.CTkFrame(card, fg_color=PALETTE["surface_alt"], corner_radius=8)
                row.pack(fill="x", padx=14, pady=3)
                sub = f"  ({u.get('publisher', '')})" if u.get("publisher") else ""
                ctk.CTkLabel(
                    row,
                    text=f"{name}{sub}",
                    font=self.font_small,
                    text_color=PALETTE["text"],
                    anchor="w",
                ).pack(side="left", padx=10, pady=5, fill="x", expand=True)

                q = urllib.parse.quote_plus(name)
                fh_url = f"https://flathub.org/apps/search?q={q}"
                alt_url = f"https://alternativeto.net/browse/search/?q={q}&platform=linux"

                ctk.CTkButton(
                    row,
                    text="AlternativeTo",
                    width=96,
                    height=24,
                    fg_color=PALETTE["bg"],
                    hover_color=PALETTE["surface_hover"],
                    text_color=PALETTE["blue"],
                    font=self.font_small,
                    command=lambda url=alt_url: _safe_open_url(url),
                ).pack(side="right", padx=(4, 8), pady=4)

                ctk.CTkButton(
                    row,
                    text="Flathub",
                    width=72,
                    height=24,
                    fg_color=PALETTE["bg"],
                    hover_color=PALETTE["surface_hover"],
                    text_color=PALETTE["teal"],
                    font=self.font_small,
                    command=lambda url=fh_url: _safe_open_url(url),
                ).pack(side="right", padx=4, pady=4)

            ctk.CTkFrame(card, fg_color="transparent", height=8).pack()

    def _toggle_unmatched(self) -> None:
        self.unmatched_expanded = not self.unmatched_expanded
        self._render_unmatched_panel()

    # ------------------------------------------------------------------
    # STEP 3: Mandatory Backup Reminder & Safety Checklist
    # ------------------------------------------------------------------
    def _build_step3(self) -> None:
        frame = ctk.CTkFrame(self.step_host, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self._step_frames[3] = frame

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        # Prominent Amber/Red Warning Card
        warn_card = ctk.CTkFrame(
            scroll,
            fg_color=PALETTE["amber_dark"],
            border_width=2,
            border_color=PALETTE["amber"],
            corner_radius=14,
        )
        warn_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        ctk.CTkLabel(
            warn_card,
            text="⚠ MANDATORY BACKUP REMINDER — READ BEFORE SWITCHING OS",
            font=self.font_h2,
            text_color=PALETTE["amber"],
            anchor="w",
        ).pack(fill="x", padx=18, pady=(14, 6))

        ctk.CTkLabel(
            warn_card,
            text=(
                "TuxHarbor migrates your applications, developer tools, and Linux alternatives ONLY. "
                "It does NOT copy, upload, or back up your personal files, documents, photos, or project source code.\n\n"
                "Installing Linux over Windows can erase your disk if you format partitions. "
                "Always keep a verified backup on an external USB/SSD drive or cloud storage first!"
            ),
            font=self.font_body,
            text_color=PALETTE["text"],
            anchor="w",
            justify="left",
            wraplength=920,
        ).pack(fill="x", padx=18, pady=(0, 14))

        # Dynamic Detected Project Backup Risks Card
        self.step3_risks_card = ctk.CTkFrame(
            scroll,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=14,
        )
        self.step3_risks_card.grid(row=1, column=0, sticky="ew", pady=(0, 12))

        # 4-Item Interactive Safety Checklist
        chk_card = ctk.CTkFrame(
            scroll,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=14,
        )
        chk_card.grid(row=2, column=0, sticky="ew")

        hdr = ctk.CTkFrame(chk_card, fg_color="transparent")
        hdr.pack(fill="x", padx=18, pady=(14, 8))
        ctk.CTkLabel(
            hdr,
            text="Personal Backup Safety Checklist",
            font=self.font_h2,
            text_color=PALETTE["text"],
        ).pack(side="left")

        self.chk_counter_label = ctk.CTkLabel(
            hdr,
            text="0 / 4 checked",
            font=self.font_badge,
            text_color=PALETTE["amber"],
            fg_color=PALETTE["amber_dark"],
            corner_radius=8,
            padx=10,
            pady=3,
        )
        self.chk_counter_label.pack(side="right")

        items = [
            (
                self.var_chk_external,
                "External Drive or Cloud Backup: Documents, Desktop, Downloads, and project folders are safely copied.",
            ),
            (
                self.var_chk_gitpush,
                "Git Repositories Pushed: Run 'git push' on every active repository so no local commits are left behind.",
            ),
            (
                self.var_chk_secrets,
                "Secrets & Keys Backed Up: .env files, SSH keys (~/.ssh), GPG keys, browser bookmarks, and password vaults.",
            ),
            (
                self.var_chk_media,
                "Personal Media & Licenses: Photos, videos, local databases, and commercial license keys are archived.",
            ),
        ]
        for var, text in items:
            ctk.CTkCheckBox(
                chk_card,
                text=text,
                variable=var,
                command=self._update_backup_counter,
                font=self.font_body,
                fg_color=PALETTE["teal"],
                hover_color=PALETTE["teal_hover"],
            ).pack(anchor="w", padx=20, pady=7)

        ctk.CTkFrame(chk_card, fg_color="transparent", height=8).pack()

        # Footer Navigation
        footer = ctk.CTkFrame(frame, fg_color="transparent")
        footer.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        ctk.CTkButton(
            footer,
            text="← Back to Report",
            width=150,
            height=36,
            fg_color=PALETTE["surface"],
            hover_color=PALETTE["surface_hover"],
            border_width=1,
            border_color=PALETTE["border"],
            command=lambda: self.go_to_step(2),
        ).pack(side="left")

        ctk.CTkButton(
            footer,
            text="Continue to Save / Email →",
            width=220,
            height=38,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
            text_color="#04151c",
            font=self.font_h3,
            command=lambda: self.go_to_step(4),
        ).pack(side="right")

    def _update_backup_counter(self) -> None:
        done = sum(
            int(v.get())
            for v in (self.var_chk_external, self.var_chk_gitpush, self.var_chk_secrets, self.var_chk_media)
        )
        if done == 4:
            self.chk_counter_label.configure(
                text="4 / 4 verified ✓",
                text_color=PALETTE["green"],
                fg_color=PALETTE["green_dark"],
            )
        else:
            self.chk_counter_label.configure(
                text=f"{done} / 4 checked",
                text_color=PALETTE["amber"],
                fg_color=PALETTE["amber_dark"],
            )

    def _render_step3_risks(self) -> None:
        for w in self.step3_risks_card.winfo_children():
            w.destroy()

        projects = (self.analysis or {}).get("projects") or []
        risky = [p for p in projects if p.get("backup_warnings")]

        if not projects:
            ctk.CTkLabel(
                self.step3_risks_card,
                text="Scanned Project Backup Audit: No project folders were added in Step 1.",
                font=self.font_body,
                text_color=PALETTE["muted"],
                anchor="w",
            ).pack(fill="x", padx=18, pady=12)
            return

        if not risky:
            ctk.CTkLabel(
                self.step3_risks_card,
                text=f"✓ All {len(projects)} scanned project(s) have clean Git status and remote backups configured.",
                font=self.font_h3,
                text_color=PALETTE["green"],
                anchor="w",
            ).pack(fill="x", padx=18, pady=12)
            return

        ctk.CTkLabel(
            self.step3_risks_card,
            text=f"⚠ Attention Required — {len(risky)} Scanned Project(s) Have Backup Risks:",
            font=self.font_h3,
            text_color=PALETTE["red"],
            anchor="w",
        ).pack(fill="x", padx=18, pady=(12, 6))

        for proj in risky:
            box = ctk.CTkFrame(
                self.step3_risks_card,
                fg_color=PALETTE["red_dark"],
                border_width=1,
                border_color=PALETTE["red"],
                corner_radius=8,
            )
            box.pack(fill="x", padx=18, pady=4)
            ctk.CTkLabel(
                box,
                text=f"{proj.get('name', 'Project')}   ({proj.get('path', '')})",
                font=self.font_h3,
                text_color=PALETTE["text"],
                anchor="w",
            ).pack(fill="x", padx=12, pady=(6, 2))
            for bw in proj.get("backup_warnings", []):
                ctk.CTkLabel(
                    box,
                    text=f"  • {bw.get('message', '')}",
                    font=self.font_small,
                    text_color="#fca5a5",
                    anchor="w",
                    wraplength=880,
                    justify="left",
                ).pack(fill="x", padx=12, pady=(0, 4))

        ctk.CTkFrame(self.step3_risks_card, fg_color="transparent", height=8).pack()

    # ------------------------------------------------------------------
    # STEP 4: Choose Delivery Before Generating
    # ------------------------------------------------------------------
    def _build_step4(self) -> None:
        frame = ctk.CTkFrame(self.step_host, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self._step_frames[4] = frame

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        # Delivery Mode Selector Card
        mode_card = ctk.CTkFrame(
            scroll,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=14,
        )
        mode_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        mode_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            mode_card,
            text="Choose How to Deliver Your Migration Kit (Before Generating)",
            font=self.font_h2,
            text_color=PALETTE["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 8))

        self.delivery_segment = ctk.CTkSegmentedButton(
            mode_card,
            values=[
                "Save Locally (PC / USB / Cloud)",
                "Send Securely via Email",
                "Both (Local + Email)",
            ],
            variable=self.var_delivery_mode,
            command=lambda _v: self._refresh_delivery_panels(),
            fg_color=PALETTE["bg"],
            selected_color=PALETTE["teal"],
            selected_hover_color=PALETTE["teal_hover"],
            unselected_color=PALETTE["surface_alt"],
            unselected_hover_color=PALETTE["surface_hover"],
            text_color=PALETTE["text"],
            font=self.font_h3,
            height=36,
        )
        self.delivery_segment.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))

        # Save As (Custom Filename Prefix) Card
        name_card = ctk.CTkFrame(
            scroll,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=14,
        )
        name_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        name_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            name_card,
            text="Save As (Filename Prefix):",
            font=self.font_h3,
            text_color=PALETTE["text"],
        ).grid(row=0, column=0, padx=(18, 10), pady=(12, 4), sticky="w")

        ctk.CTkEntry(
            name_card,
            textvariable=self.var_prefix,
            width=280,
            height=32,
            fg_color=PALETTE["bg"],
            border_color=PALETTE["border"],
            font=self.font_body,
        ).grid(row=0, column=1, padx=(0, 18), pady=(12, 4), sticky="w")

        self.filename_preview_label = ctk.CTkLabel(
            name_card,
            text="",
            font=self.font_mono,
            text_color=PALETTE["teal"],
            anchor="w",
        )
        self.filename_preview_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=18, pady=(2, 12))

        # Local Save Panel
        self.local_panel = ctk.CTkFrame(
            scroll,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=14,
        )
        self.local_panel.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.local_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.local_panel,
            text="Local / USB / Cloud Destination Folder",
            font=self.font_h3,
            text_color=PALETTE["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(12, 6))

        quick_row = ctk.CTkFrame(self.local_panel, fg_color="transparent")
        quick_row.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))

        locations = detect_save_locations()
        if locations:
            self.var_dest_dir.set(locations[0]["path"])
            for loc in locations[:6]:
                badge_color = PALETTE["teal"] if loc["kind"] == "usb" else PALETTE["blue"] if loc["kind"] == "cloud" else PALETTE["text"]
                ctk.CTkButton(
                    quick_row,
                    text=loc["label"],
                    height=28,
                    fg_color=PALETTE["surface_alt"],
                    hover_color=PALETTE["surface_hover"],
                    border_width=1,
                    border_color=PALETTE["border"],
                    text_color=badge_color,
                    font=self.font_small,
                    command=lambda p=loc["path"]: self.var_dest_dir.set(p),
                ).pack(side="left", padx=(0, 6), pady=2)

        path_row = ctk.CTkFrame(self.local_panel, fg_color="transparent")
        path_row.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 8))
        path_row.grid_columnconfigure(0, weight=1)

        ctk.CTkEntry(
            path_row,
            textvariable=self.var_dest_dir,
            height=34,
            fg_color=PALETTE["bg"],
            border_color=PALETTE["border"],
            font=self.font_mono,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            path_row,
            text="Browse...",
            width=100,
            height=34,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["surface_hover"],
            border_width=1,
            border_color=PALETTE["border"],
            command=self._browse_save_dir,
        ).grid(row=0, column=1)

        ctk.CTkCheckBox(
            self.local_panel,
            text="Also create portable .zip archive (preserves Unix 0755 executable permissions on the Linux script)",
            variable=self.var_create_zip,
            font=self.font_small,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
            command=self._refresh_filename_preview,
        ).grid(row=3, column=0, sticky="w", padx=18, pady=(2, 12))

        # Secure Email Panel
        self.email_panel = ctk.CTkFrame(
            scroll,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=14,
        )
        self.email_panel.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        self.email_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.email_panel,
            text="Secure Local-Only Email Delivery",
            font=self.font_h3,
            text_color=PALETTE["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(12, 6))

        sec_notice = ctk.CTkFrame(
            self.email_panel,
            fg_color=PALETTE["teal_dark"],
            border_width=1,
            border_color=PALETTE["teal"],
            corner_radius=8,
        )
        sec_notice.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))
        ctk.CTkLabel(
            sec_notice,
            text=(
                "Privacy Guarantee: Direct SMTP connects directly from your PC over verified TLS 1.2+. "
                "Your password is NEVER stored on disk, NEVER logged, and cleared immediately from memory after sending."
            ),
            font=self.font_small,
            text_color=PALETTE["teal"],
            anchor="w",
            justify="left",
            wraplength=900,
        ).pack(fill="x", padx=12, pady=8)

        self.email_method_segment = ctk.CTkSegmentedButton(
            self.email_panel,
            values=[
                "Direct TLS SMTP (with attachments)",
                "Passwordless Quick Draft (Gmail / Outlook / Mail)",
            ],
            variable=self.var_email_method,
            command=lambda _v: self._refresh_email_subpanel(),
            fg_color=PALETTE["bg"],
            selected_color=PALETTE["blue"],
            selected_hover_color="#0284c7",
            unselected_color=PALETTE["surface_alt"],
            unselected_hover_color=PALETTE["surface_hover"],
            text_color=PALETTE["text"],
            font=self.font_small,
            height=32,
        )
        self.email_method_segment.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 10))

        # Direct TLS SMTP subpanel
        self.smtp_subpanel = ctk.CTkFrame(self.email_panel, fg_color="transparent")
        self.smtp_subpanel.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 12))
        self.smtp_subpanel.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(self.smtp_subpanel, text="Provider:", font=self.font_small, text_color=PALETTE["muted"]).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=4
        )
        ctk.CTkOptionMenu(
            self.smtp_subpanel,
            values=[lbl for lbl, _ in SMTP_PROVIDER_OPTIONS],
            variable=self.var_smtp_provider,
            command=self._on_smtp_provider_change,
            width=180,
            height=30,
            fg_color=PALETTE["bg"],
            button_color=PALETTE["border"],
            font=self.font_small,
        ).grid(row=0, column=1, sticky="ew", padx=(0, 14), pady=4)

        ctk.CTkLabel(self.smtp_subpanel, text="TLS Mode:", font=self.font_small, text_color=PALETTE["muted"]).grid(
            row=0, column=2, sticky="w", padx=(0, 8), pady=4
        )
        ctk.CTkOptionMenu(
            self.smtp_subpanel,
            values=["STARTTLS", "SSL"],
            variable=self.var_smtp_security,
            width=130,
            height=30,
            fg_color=PALETTE["bg"],
            button_color=PALETTE["border"],
            font=self.font_small,
        ).grid(row=0, column=3, sticky="ew", pady=4)

        ctk.CTkLabel(self.smtp_subpanel, text="SMTP Host:", font=self.font_small, text_color=PALETTE["muted"]).grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4
        )
        ctk.CTkEntry(
            self.smtp_subpanel,
            textvariable=self.var_smtp_host,
            height=30,
            fg_color=PALETTE["bg"],
            border_color=PALETTE["border"],
            font=self.font_small,
        ).grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=4)

        ctk.CTkLabel(self.smtp_subpanel, text="Port:", font=self.font_small, text_color=PALETTE["muted"]).grid(
            row=1, column=2, sticky="w", padx=(0, 8), pady=4
        )
        ctk.CTkEntry(
            self.smtp_subpanel,
            textvariable=self.var_smtp_port,
            width=100,
            height=30,
            fg_color=PALETTE["bg"],
            border_color=PALETTE["border"],
            font=self.font_small,
        ).grid(row=1, column=3, sticky="ew", pady=4)

        ctk.CTkLabel(self.smtp_subpanel, text="Your Email:", font=self.font_small, text_color=PALETTE["muted"]).grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=4
        )
        ctk.CTkEntry(
            self.smtp_subpanel,
            textvariable=self.var_smtp_user,
            placeholder_text="you@gmail.com",
            height=30,
            fg_color=PALETTE["bg"],
            border_color=PALETTE["border"],
            font=self.font_small,
        ).grid(row=2, column=1, sticky="ew", padx=(0, 14), pady=4)

        ctk.CTkLabel(self.smtp_subpanel, text="Recipient Email:", font=self.font_small, text_color=PALETTE["muted"]).grid(
            row=2, column=2, sticky="w", padx=(0, 8), pady=4
        )
        ctk.CTkEntry(
            self.smtp_subpanel,
            textvariable=self.var_smtp_recipient,
            placeholder_text="(defaults to your email)",
            height=30,
            fg_color=PALETTE["bg"],
            border_color=PALETTE["border"],
            font=self.font_small,
        ).grid(row=2, column=3, sticky="ew", pady=4)

        ctk.CTkLabel(self.smtp_subpanel, text="App Password:", font=self.font_small, text_color=PALETTE["muted"]).grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=4
        )
        # Do NOT bind a persistent StringVar to the password; read & clear the widget directly!
        self.smtp_password_entry = ctk.CTkEntry(
            self.smtp_subpanel,
            placeholder_text="16-character App Password (never saved)",
            show="•",
            height=30,
            fg_color=PALETTE["bg"],
            border_color=PALETTE["border"],
            font=self.font_small,
        )
        self.smtp_password_entry.grid(row=3, column=1, columnspan=3, sticky="ew", pady=4)

        tip_box = ctk.CTkFrame(self.smtp_subpanel, fg_color=PALETTE["surface_alt"], corner_radius=8)
        tip_box.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ctk.CTkLabel(
            tip_box,
            text=(
                "Gmail App Password (3 steps):  "
                "1) Turn on 2-Step Verification in your Google Account   "
                "2) Visit myaccount.google.com/apppasswords & create a password for 'TuxHarbor'   "
                "3) Paste that 16-character password above (never your regular Google password)."
            ),
            font=self.font_small,
            text_color=PALETTE["muted"],
            anchor="w",
            justify="left",
            wraplength=880,
        ).pack(fill="x", padx=10, pady=6)

        # Passwordless Quick Draft subpanel
        self.draft_subpanel = ctk.CTkFrame(self.email_panel, fg_color="transparent")
        self.draft_subpanel.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 12))
        self.draft_subpanel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self.draft_subpanel,
            text="Recipient Email (optional):",
            font=self.font_small,
            text_color=PALETTE["muted"],
        ).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
        ctk.CTkEntry(
            self.draft_subpanel,
            textvariable=self.var_draft_recipient,
            placeholder_text="you@example.com",
            height=30,
            fg_color=PALETTE["bg"],
            border_color=PALETTE["border"],
            font=self.font_small,
        ).grid(row=0, column=1, sticky="ew", pady=4)
        ctk.CTkLabel(
            self.draft_subpanel,
            text="Generates one-click compose links for Gmail Web, Outlook Web, and your default Mail app (zero passwords needed — simply attach the saved files).",
            font=self.font_small,
            text_color=PALETTE["muted"],
            anchor="w",
            wraplength=880,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        # Delivery Progress / Status + Success Panel
        self.delivery_progress = ctk.CTkProgressBar(
            scroll,
            mode="indeterminate",
            progress_color=PALETTE["teal"],
            fg_color=PALETTE["surface"],
            height=8,
        )
        self.delivery_progress.grid(row=4, column=0, sticky="ew", pady=(4, 4))
        self.delivery_progress.grid_remove()

        self.success_panel = ctk.CTkFrame(
            scroll,
            fg_color=PALETTE["green_dark"],
            border_width=1,
            border_color=PALETTE["green"],
            corner_radius=14,
        )
        self.success_panel.grid(row=5, column=0, sticky="ew", pady=(4, 10))
        self.success_panel.grid_remove()

        # Footer Buttons
        footer = ctk.CTkFrame(frame, fg_color="transparent")
        footer.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        ctk.CTkButton(
            footer,
            text="← Back to Backup",
            width=145,
            height=38,
            fg_color=PALETTE["surface"],
            hover_color=PALETTE["surface_hover"],
            border_width=1,
            border_color=PALETTE["border"],
            command=lambda: self.go_to_step(3),
        ).pack(side="left")

        self.btn_generate = ctk.CTkButton(
            footer,
            text="Generate & Save / Send",
            width=220,
            height=40,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
            text_color="#04151c",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._execute_delivery,
        )
        self.btn_generate.pack(side="right")

        ctk.CTkButton(
            footer,
            text="Preview Linux Script",
            width=175,
            height=38,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["surface_hover"],
            border_width=1,
            border_color=PALETTE["blue"],
            text_color=PALETTE["blue"],
            font=self.font_h3,
            command=self.open_script_preview_modal,
        ).pack(side="right", padx=(0, 10))

        self._refresh_filename_preview()
        self._refresh_delivery_panels()

    def _browse_save_dir(self) -> None:
        selected = filedialog.askdirectory(parent=self, title="Choose Destination Folder")
        if selected:
            self.var_dest_dir.set(selected)

    def _on_smtp_provider_change(self, label: str) -> None:
        key = SMTP_LABEL_TO_ID.get(label, "custom")
        preset = SMTP_PRESETS.get(key, {})
        if key != "custom":
            self.var_smtp_host.set(preset.get("host", ""))
            self.var_smtp_port.set(str(preset.get("port", 587)))
            self.var_smtp_security.set("SSL" if preset.get("security") == "ssl" else "STARTTLS")

    def _refresh_filename_preview(self) -> None:
        if not hasattr(self, "filename_preview_label"):
            return
        prefix = sanitize_filename_prefix(self.var_prefix.get(), default="tuxharbor-migration")
        parts = [f"{prefix}-report.html", f"{prefix}-install.sh", f"{prefix}-plan.json"]
        if self.var_create_zip.get():
            parts.append(f"{prefix}-bundle.zip")
        self.filename_preview_label.configure(text="Files:  " + "   ·   ".join(parts))

    def _refresh_delivery_panels(self) -> None:
        mode = self.var_delivery_mode.get()
        show_local = mode.startswith("Save Locally") or mode.startswith("Both")
        show_email = mode.startswith("Send Securely") or mode.startswith("Both")

        if show_local:
            self.local_panel.grid()
        else:
            self.local_panel.grid_remove()

        if show_email:
            self.email_panel.grid()
            self._refresh_email_subpanel()
        else:
            self.email_panel.grid_remove()

    def _refresh_email_subpanel(self) -> None:
        is_smtp = self.var_email_method.get().startswith("Direct TLS")
        if is_smtp:
            self.draft_subpanel.grid_remove()
            self.smtp_subpanel.grid()
        else:
            self.smtp_subpanel.grid_remove()
            self.draft_subpanel.grid()

    def _build_current_artifacts(self) -> tuple[str, dict[str, Any], str, str]:
        """Compile current GUI selections into (prefix, plan, linux_script, html_report)."""
        if not self.analysis:
            raise ValueError("Please run a scan in Step 1 before generating files.")
        payload = dict(self.analysis)
        payload["target_distro"] = DISTRO_LABEL_TO_ID.get(self.var_distro.get(), "auto")
        payload["prefer_flatpak"] = bool(self.var_prefer_flatpak.get())
        payload["include_vscode_extensions"] = bool(self.var_inc_vscode.get())
        payload["include_npm_globals"] = bool(self.var_inc_npm.get())
        payload["include_git_config"] = bool(self.var_inc_git.get())

        prefix = sanitize_filename_prefix(self.var_prefix.get(), default="tuxharbor-migration")
        plan = build_migration_plan(payload)
        script = generate_linux_script(plan)
        report_html = generate_html_report(payload, plan, script_filename=f"{prefix}-install.sh")
        return prefix, plan, script, report_html

    def open_script_preview_modal(self) -> ctk.CTkToplevel | None:
        """Open a modal showing the exact generated Linux Bash script before saving/sending."""
        try:
            prefix, _plan, script, _html = self._build_current_artifacts()
        except Exception as exc:
            messagebox.showwarning(__app_name__, str(exc), parent=self)
            return None

        win = ctk.CTkToplevel(self, fg_color=PALETTE["bg"])
        win.title(f"Preview Linux Script — {prefix}-install.sh")
        win.geometry("820x580")
        win.transient(self)

        hdr = ctk.CTkFrame(win, fg_color=PALETTE["surface"], corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(
            hdr,
            text=f"Exact Script Preview: {prefix}-install.sh (Unix LF)",
            font=self.font_h3,
            text_color=PALETTE["teal"],
        ).pack(side="left", padx=14, pady=10)

        def copy_script() -> None:
            self.clipboard_clear()
            self.clipboard_append(script)
            copy_btn.configure(text="Copied ✓")

        copy_btn = ctk.CTkButton(
            hdr,
            text="Copy Script",
            width=110,
            height=28,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
            text_color="#04151c",
            font=self.font_badge,
            command=copy_script,
        )
        copy_btn.pack(side="right", padx=14, pady=8)

        tb = ctk.CTkTextbox(
            win,
            fg_color=PALETTE["code_bg"],
            text_color="#bae6fd",
            font=self.font_mono,
            wrap="none",
        )
        tb.pack(fill="both", expand=True, padx=14, pady=12)
        tb.insert("1.0", script)
        tb.configure(state="disabled")
        return win

    def _clear_smtp_password(self) -> None:
        try:
            if self.winfo_exists() and hasattr(self, "smtp_password_entry"):
                self.smtp_password_entry.delete(0, "end")
        except Exception:
            pass

    def _execute_delivery(self) -> None:
        if self.is_busy:
            return
        try:
            prefix, plan, script, report_html = self._build_current_artifacts()
        except Exception as exc:
            messagebox.showwarning(__app_name__, str(exc), parent=self)
            return

        mode = self.var_delivery_mode.get()
        do_local = mode.startswith("Save Locally") or mode.startswith("Both")
        do_email = mode.startswith("Send Securely") or mode.startswith("Both")
        is_smtp = do_email and self.var_email_method.get().startswith("Direct TLS")
        is_draft = do_email and not is_smtp

        dest_dir = self.var_dest_dir.get().strip()
        create_zip = bool(self.var_create_zip.get())

        smtp_cfg: dict[str, Any] = {}
        if is_smtp:
            smtp_cfg = {
                "preset": SMTP_LABEL_TO_ID.get(self.var_smtp_provider.get(), "custom"),
                "host": self.var_smtp_host.get(),
                "port": self.var_smtp_port.get(),
                "security": "ssl" if self.var_smtp_security.get().upper() == "SSL" else "starttls",
                "username": self.var_smtp_user.get(),
                "recipient": self.var_smtp_recipient.get() or self.var_smtp_user.get(),
                "password": self.smtp_password_entry.get(),
            }
            # Clear password field from GUI immediately upon handing off to worker!
            self._clear_smtp_password()

        draft_recipient = self.var_draft_recipient.get()

        self.is_busy = True
        self.btn_generate.configure(state="disabled", text="Working...")
        self.success_panel.grid_remove()
        self.delivery_progress.grid()
        self.delivery_progress.start()

        def worker() -> None:
            saved_res: dict[str, Any] | None = None
            smtp_res: dict[str, Any] | None = None
            draft_urls: dict[str, str] | None = None
            try:
                if do_local:
                    saved_res = save_migration_bundle(
                        destination_dir=dest_dir,
                        filename_prefix=prefix,
                        report_html=report_html,
                        linux_script=script,
                        plan=plan,
                        create_zip=create_zip,
                    )
                if is_smtp:
                    smtp_res = send_migration_email_smtp(
                        smtp_config=smtp_cfg,
                        filename_prefix=prefix,
                        report_html=report_html,
                        linux_script=script,
                        plan=plan,
                    )
                if is_draft:
                    draft_urls = build_webmail_draft_urls(
                        recipient=draft_recipient,
                        filename_prefix=prefix,
                        plan=plan,
                    )
                self.after(
                    0,
                    lambda s=saved_res, e=smtp_res, d=draft_urls, pfx=prefix: self._on_delivery_success(s, e, d, pfx),
                )
            except Exception as exc:
                err_msg = str(exc) or exc.__class__.__name__
                self.after(0, lambda m=err_msg: self._on_delivery_error(m))
            finally:
                # Scrub transient secret from dictionary in memory
                if "password" in smtp_cfg:
                    smtp_cfg["password"] = ""
                self.after(0, self._clear_smtp_password)

        threading.Thread(target=worker, daemon=True).start()

    def _on_delivery_success(
        self,
        saved: dict[str, Any] | None,
        smtp_res: dict[str, Any] | None,
        draft_urls: dict[str, str] | None,
        prefix: str,
    ) -> None:
        if not self.winfo_exists():
            return
        self.is_busy = False
        self.delivery_progress.stop()
        self.delivery_progress.grid_remove()
        self.btn_generate.configure(state="normal", text="Generate & Save / Send")

        self.last_saved_bundle = saved
        self.last_draft_urls = draft_urls

        for w in self.success_panel.winfo_children():
            w.destroy()

        ctk.CTkLabel(
            self.success_panel,
            text="✓ Migration Kit Ready!",
            font=self.font_h2,
            text_color=PALETTE["green"],
            anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 4))

        summary_lines: list[str] = []
        if saved:
            summary_lines.append(f"Saved locally to: {saved['destination_dir']}")
            for fpath in saved["files"]:
                summary_lines.append(f"  • {Path(fpath).name}")
        if smtp_res:
            summary_lines.append(
                f"Sent via verified TLS SMTP ({smtp_res['host']}) to {smtp_res['recipient']} with 3 attachments."
            )
        if draft_urls:
            summary_lines.append("Passwordless email draft links prepared below (remember to attach your saved files).")

        ctk.CTkLabel(
            self.success_panel,
            text="\n".join(summary_lines),
            font=self.font_small,
            text_color=PALETTE["text"],
            anchor="w",
            justify="left",
        ).pack(fill="x", padx=16, pady=(0, 8))

        btn_row = ctk.CTkFrame(self.success_panel, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 8))

        if saved:
            ctk.CTkButton(
                btn_row,
                text="Open Folder",
                width=125,
                height=32,
                fg_color=PALETTE["teal"],
                hover_color=PALETTE["teal_hover"],
                text_color="#04151c",
                font=self.font_badge,
                command=lambda s=saved: open_saved_path(s["destination_dir"], allowed_dir=s["destination_dir"]),
            ).pack(side="left", padx=(0, 8))

            ctk.CTkButton(
                btn_row,
                text="Open HTML Report",
                width=145,
                height=32,
                fg_color=PALETTE["surface"],
                hover_color=PALETTE["surface_hover"],
                border_width=1,
                border_color=PALETTE["teal"],
                text_color=PALETTE["teal"],
                font=self.font_badge,
                command=lambda s=saved: open_saved_path(s["report_path"], allowed_dir=s["destination_dir"]),
            ).pack(side="left", padx=(0, 8))

        if draft_urls:
            for lbl, key in [("Open Gmail Draft", "gmail"), ("Open Outlook Draft", "outlook"), ("Open Mail App", "mailto")]:
                url = draft_urls.get(key, "")
                if url:
                    ctk.CTkButton(
                        btn_row,
                        text=lbl,
                        width=135,
                        height=32,
                        fg_color=PALETTE["surface"],
                        hover_color=PALETTE["surface_hover"],
                        border_width=1,
                        border_color=PALETTE["blue"],
                        text_color=PALETTE["blue"],
                        font=self.font_small,
                        command=lambda u=url: _safe_open_url(u),
                    ).pack(side="left", padx=(0, 8))

        # Copyable Linux run command
        cmd_text = f"chmod +x {prefix}-install.sh && ./{prefix}-install.sh"
        cmd_row = ctk.CTkFrame(self.success_panel, fg_color=PALETTE["code_bg"], corner_radius=8)
        cmd_row.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            cmd_row,
            text=f"Run on Linux:   {cmd_text}",
            font=self.font_mono,
            text_color="#7dd3fc",
            anchor="w",
        ).pack(side="left", padx=12, pady=8, fill="x", expand=True)

        def copy_cmd() -> None:
            self.clipboard_clear()
            self.clipboard_append(cmd_text)
            c_btn.configure(text="Copied ✓")

        c_btn = ctk.CTkButton(
            cmd_row,
            text="Copy Command",
            width=115,
            height=26,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["surface_hover"],
            font=self.font_small,
            command=copy_cmd,
        )
        c_btn.pack(side="right", padx=8, pady=6)

        self.success_panel.grid()

    def _on_delivery_error(self, message: str) -> None:
        if not self.winfo_exists():
            return
        self.is_busy = False
        self.delivery_progress.stop()
        self.delivery_progress.grid_remove()
        self.btn_generate.configure(state="normal", text="Generate & Save / Send")
        messagebox.showerror(__app_name__, message, parent=self)

    # ------------------------------------------------------------------
    # LINUX MODE TAB (Apply Plan)
    # ------------------------------------------------------------------
    def _build_linux_mode(self) -> None:
        env = self.linux_env
        env_card = ctk.CTkFrame(
            self.linux_container,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=14,
        )
        env_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        env_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            env_card,
            text="Linux Mode — Inspect & Apply a TuxHarbor Migration Plan",
            font=self.font_h2,
            text_color=PALETTE["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(12, 4))

        env_summary = (
            f"Detected Linux: {env['distro_name']} · Package Manager: {env['package_manager'] or 'none'} · "
            f"Flatpak: {'available' if env['has_flatpak'] else 'will install if needed'}"
            if env["is_linux"]
            else f"Running on {platform.system()} — live installation is Linux-only, but you can load and preview (Dry Run) any *-plan.json right here."
        )
        ctk.CTkLabel(
            env_card,
            text=env_summary,
            font=self.font_small,
            text_color=PALETTE["teal"] if env["is_linux"] else PALETTE["amber"],
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 10))

        picker = ctk.CTkFrame(env_card, fg_color="transparent")
        picker.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 14))
        picker.grid_columnconfigure(0, weight=1)

        self.var_plan_path = tk.StringVar(value="")
        ctk.CTkEntry(
            picker,
            textvariable=self.var_plan_path,
            placeholder_text="Select a *-plan.json file generated by TuxHarbor...",
            height=34,
            fg_color=PALETTE["bg"],
            border_color=PALETTE["border"],
            font=self.font_mono,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            picker,
            text="Browse *-plan.json",
            width=145,
            height=34,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["surface_hover"],
            border_width=1,
            border_color=PALETTE["border"],
            command=self._browse_plan_json,
        ).grid(row=0, column=1, padx=(0, 8))

        ctk.CTkButton(
            picker,
            text="Load Plan",
            width=100,
            height=34,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
            text_color="#04151c",
            font=self.font_badge,
            command=self._load_plan_from_entry,
        ).grid(row=0, column=2)

        # Action Bar
        act_bar = ctk.CTkFrame(self.linux_container, fg_color="transparent")
        act_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self.linux_plan_summary_label = ctk.CTkLabel(
            act_bar,
            text="No migration plan loaded yet.",
            font=self.font_body,
            text_color=PALETTE["muted"],
        )
        self.linux_plan_summary_label.pack(side="left")

        self.btn_linux_install = ctk.CTkButton(
            act_bar,
            text="Install Now on Linux",
            width=175,
            height=34,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
            text_color="#04151c",
            font=self.font_h3,
            state="normal" if env["is_linux"] else "disabled",
            command=lambda: self._run_linux_apply(dry_run=False),
        )
        self.btn_linux_install.pack(side="right", padx=(8, 0))

        self.btn_linux_dry = ctk.CTkButton(
            act_bar,
            text="Preview (Dry Run)",
            width=155,
            height=34,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["surface_hover"],
            border_width=1,
            border_color=PALETTE["blue"],
            text_color=PALETTE["blue"],
            font=self.font_h3,
            command=lambda: self._run_linux_apply(dry_run=True),
        )
        self.btn_linux_dry.pack(side="right")

        # Split pane: Plan items table (top) + Live Output Log (bottom)
        split = ctk.CTkFrame(self.linux_container, fg_color="transparent")
        split.grid(row=2, column=0, sticky="nsew")
        split.grid_columnconfigure(0, weight=1)
        split.grid_rowconfigure(0, weight=3)
        split.grid_rowconfigure(1, weight=2)

        self.linux_items_scroll = ctk.CTkScrollableFrame(
            split,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=12,
            label_text="Planned Packages & Status",
            label_font=self.font_h3,
        )
        self.linux_items_scroll.grid(row=0, column=0, sticky="nsew", pady=(0, 8))

        log_card = ctk.CTkFrame(
            split,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=12,
        )
        log_card.grid(row=1, column=0, sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            log_card,
            text="Execution Output Log",
            font=self.font_h3,
            text_color=PALETTE["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 4))

        self.linux_log_box = ctk.CTkTextbox(
            log_card,
            fg_color=PALETTE["code_bg"],
            text_color="#cbd5e1",
            font=self.font_mono,
            wrap="word",
        )
        self.linux_log_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))
        self.linux_log_box.insert("1.0", "Load a *-plan.json file and click 'Preview (Dry Run)' to inspect commands.\n")
        self.linux_log_box.configure(state="disabled")

    def _browse_plan_json(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="Select TuxHarbor Plan JSON",
            filetypes=[("TuxHarbor Plan JSON", "*.json"), ("All Files", "*.*")],
        )
        if selected:
            self.var_plan_path.set(selected)
            self.load_plan_file(selected)

    def _load_plan_from_entry(self) -> None:
        path = self.var_plan_path.get().strip()
        if not path:
            messagebox.showinfo(__app_name__, "Please select a *-plan.json file first.", parent=self)
            return
        self.load_plan_file(path)

    def load_plan_file(self, path_str: str) -> bool:
        """Load and validate a *-plan.json file (enforces 5 MB safety limit)."""
        p = Path(path_str).expanduser()
        if not p.is_file():
            messagebox.showerror(__app_name__, f"Plan file not found:\n{p}", parent=self)
            return False
        try:
            size = p.stat().st_size
            if size > MAX_PLAN_FILE_BYTES:
                messagebox.showerror(
                    __app_name__,
                    f"Plan file exceeds the 5 MB safety limit ({size} bytes).",
                    parent=self,
                )
                return False
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror(__app_name__, f"Could not parse JSON plan:\n{exc}", parent=self)
            return False

        if not isinstance(data, dict) or not isinstance(data.get("apps", []), list):
            messagebox.showerror(__app_name__, "Invalid TuxHarbor plan format (expected JSON object with 'apps' list).", parent=self)
            return False

        self.loaded_plan = data
        self.loaded_plan_path = str(p)
        self._render_linux_plan_inspection()
        return True

    def _render_linux_plan_inspection(self) -> None:
        for w in self.linux_items_scroll.winfo_children():
            w.destroy()
        if not self.loaded_plan:
            return

        inspected = inspect_plan_on_linux(self.loaded_plan)
        items = inspected["items"]
        installed_cnt = sum(1 for i in items if i["installed"])
        pending_cnt = len(items) - installed_cnt
        self.linux_plan_summary_label.configure(
            text=(
                f"Loaded {len(items)} items ({installed_cnt} installed, {pending_cnt} pending) · "
                f"{inspected['vscode_extensions_count']} VS Code ext(s) · {inspected['npm_globals_count']} npm tool(s)"
            ),
            text_color=PALETTE["text"],
        )

        for it in items:
            row = ctk.CTkFrame(self.linux_items_scroll, fg_color=PALETTE["surface_alt"], corner_radius=8)
            row.pack(fill="x", pady=3, padx=4)

            status_txt = "Installed ✓" if it["installed"] else "Pending"
            st_bg = PALETTE["green_dark"] if it["installed"] else PALETTE["blue_dark"]
            st_fg = PALETTE["green"] if it["installed"] else PALETTE["blue"]

            ctk.CTkLabel(
                row,
                text=status_txt,
                fg_color=st_bg,
                text_color=st_fg,
                corner_radius=6,
                width=82,
                font=self.font_badge,
            ).pack(side="right", padx=8, pady=6)

            ctk.CTkLabel(
                row,
                text=f"[{it['action']}]",
                font=self.font_mono,
                text_color=PALETTE["teal"],
                width=74,
            ).pack(side="left", padx=(8, 4), pady=6)

            ctk.CTkLabel(
                row,
                text=f"{it['target_linux_app']}   ←   {it['source_windows_app']}",
                font=self.font_body,
                text_color=PALETTE["text"],
                anchor="w",
            ).pack(side="left", padx=4, pady=6)

            if it["command_preview"]:
                ctk.CTkLabel(
                    row,
                    text=it["command_preview"][:70],
                    font=self.font_mono,
                    text_color=PALETTE["muted"],
                    anchor="e",
                ).pack(side="right", padx=8, pady=6)

    def _append_linux_log(self, line: str) -> None:
        if not self.winfo_exists():
            return
        self.linux_log_box.configure(state="normal")
        self.linux_log_box.insert("end", line + "\n")
        self.linux_log_box.see("end")
        self.linux_log_box.configure(state="disabled")

    def _run_linux_apply(self, dry_run: bool) -> None:
        if not self.loaded_plan:
            messagebox.showinfo(__app_name__, "Please load a *-plan.json file first.", parent=self)
            return
        if not dry_run:
            if not messagebox.askyesno(
                __app_name__,
                "Proceed with installing the packages listed in this migration plan on this Linux system?",
                parent=self,
            ):
                return

        self.linux_log_box.configure(state="normal")
        self.linux_log_box.delete("1.0", "end")
        self.linux_log_box.insert("end", "=== Dry-Run Preview ===\n" if dry_run else "=== Running Linux Install ===\n")
        self.linux_log_box.configure(state="disabled")

        self.btn_linux_dry.configure(state="disabled")
        self.btn_linux_install.configure(state="disabled")
        plan_copy = dict(self.loaded_plan)

        def worker() -> None:
            try:
                res = apply_plan_on_linux(
                    plan_copy,
                    dry_run=dry_run,
                    log_callback=lambda ln: self.after(0, lambda text=ln: self._append_linux_log(text)),
                )
                summary = f"\nFinished! Succeeded: {len(res['succeeded'])}, Failed: {len(res['failed'])}, Web/Manual: {len(res['manual'])}"
                self.after(0, lambda s=summary: self._on_linux_apply_done(s))
            except Exception as exc:
                err = f"\n[error] {exc}"
                self.after(0, lambda s=err: self._on_linux_apply_done(s))

        threading.Thread(target=worker, daemon=True).start()

    def _on_linux_apply_done(self, summary: str) -> None:
        if not self.winfo_exists():
            return
        self._append_linux_log(summary)
        self.btn_linux_dry.configure(state="normal")
        if self.linux_env["is_linux"]:
            self.btn_linux_install.configure(state="normal")
        if self.loaded_plan:
            self._render_linux_plan_inspection()

    # ------------------------------------------------------------------
    # How It Works / User Guide Modal
    # ------------------------------------------------------------------
    def open_how_it_works_dialog(self) -> ctk.CTkToplevel:
        """Explain offline vs. online requirements, what is scanned, and how matching works."""
        win = ctk.CTkToplevel(self, fg_color=PALETTE["bg"])
        win.title(f"How It Works — {__app_name__} v{__version__}")
        win.geometry("720x560")
        win.minsize(620, 440)
        win.transient(self)

        scroll = ctk.CTkScrollableFrame(
            win,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=14,
        )
        scroll.pack(fill="both", expand=True, padx=16, pady=(16, 10))

        ctk.CTkLabel(
            scroll,
            text=f"How {__app_name__} Works",
            font=self.font_title,
            text_color=PALETTE["teal"],
            anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 8))

        sections = [
            (
                "1. Does TuxHarbor require an internet connection?",
                "NO for scanning, analysis, report generation, and local/USB saving — everything runs 100% offline using the bundled catalog.\n"
                "Internet is ONLY needed if you choose to email your files in Step 4, click external lookup links (ProtonDB / Flathub), "
                "or run the generated install script later on Linux to download official Linux packages.",
            ),
            (
                "2. Exactly what does TuxHarbor scan (read-only)?",
                "• Installed apps: Windows Registry Uninstall keys (HKLM/HKCU), optional `winget list`, Scoop, and Chocolatey.\n"
                "• System hardware profile: Read-only CPU architecture (x86_64 vs. ARM64 / Snapdragon), GPU adapter names, and PC OEM model.\n"
                "• Developer tools: Installed CLI runtimes (Git, Node, Python, Docker, Deno, Ollama, etc.), VS Code extension IDs, and Git user name/email.\n"
                "• Games (read-only): Registry game entries and local Steam `libraryfolders.vdf` / `appmanifest_*.acf` titles.\n"
                "• Optional project audit: Only folders you choose — reads manifest files (`package.json`, `.csproj`, etc.) and `git status`.\n"
                "NEVER read or copied: `.env` secret files, personal documents, photos, browser passwords/cookies, or SSH private keys.",
            ),
            (
                "3. How does the 5-stage matching engine cross-reference your PC?",
                "Stage 1 — Deduplicate & normalize app names (including Unicode/localized names) while preserving stable `MSIX\\` / `ARP\\` IDs.\n"
                "Stage 2 — Filter Windows OS built-ins, media codecs, and system runtimes language-independently (works on any Windows UI language).\n"
                "Stage 3 — Consolidate Hardware & Drivers (Intel, AMD, NVIDIA, Qualcomm Snapdragon/ARM64, Wi-Fi, printers, OEM suites) with native Linux kernel/driver guidance — never auto-modifying kernel drivers.\n"
                "Stage 4 — Separate PC Games & launchers with community ProtonDB and AreWeAntiCheatYet lookup links.\n"
                "Stage 5 — Match desktop apps & dev tools against the local curated catalog using exact, word-boundary, and exclusion rules.",
            ),
            (
                "4. Hardware tip (Intel, AMD, NVIDIA, Snapdragon / ARM64 & OEMs)",
                "Before wiping Windows, boot a Linux Live USB ('Try Linux without installing') to verify Wi-Fi, Bluetooth, audio, sleep, and touchpad on your exact hardware. "
                "ARM64 / Snapdragon PCs require an ARM64 (aarch64) Linux ISO with a recent kernel (Linux 6.11+).",
            ),
        ]

        for heading, body in sections:
            box = ctk.CTkFrame(
                scroll,
                fg_color=PALETTE["surface_alt"],
                border_width=1,
                border_color=PALETTE["border"],
                corner_radius=10,
            )
            box.pack(fill="x", padx=14, pady=6)
            ctk.CTkLabel(
                box,
                text=heading,
                font=self.font_h3,
                text_color=PALETTE["blue"],
                anchor="w",
            ).pack(fill="x", padx=12, pady=(10, 4))
            ctk.CTkLabel(
                box,
                text=body,
                font=self.font_small,
                text_color=PALETTE["text"],
                anchor="w",
                justify="left",
                wraplength=610,
            ).pack(fill="x", padx=12, pady=(0, 10))

        foot = ctk.CTkFrame(win, fg_color="transparent")
        foot.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(
            foot,
            text="Close",
            width=96,
            height=32,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
            text_color="#04151c",
            font=self.font_badge,
            command=win.destroy,
        ).pack(side="right")
        return win

    # ------------------------------------------------------------------
    # About / Legal Modal
    # ------------------------------------------------------------------
    def open_about_legal_dialog(self) -> ctk.CTkToplevel:
        """Display TuxHarbor version, privacy guarantee, and full 3-line Trademark & As-Is Legal Notice."""
        win = ctk.CTkToplevel(self, fg_color=PALETTE["bg"])
        win.title(f"About & Legal — {__app_name__} v{__version__}")
        win.geometry("640x430")
        win.resizable(False, False)
        win.transient(self)

        card = ctk.CTkFrame(
            win,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=14,
        )
        card.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            card,
            text=f"{__app_name__} v{__version__}",
            font=self.font_title,
            text_color=PALETTE["teal"],
        ).pack(anchor="w", padx=18, pady=(16, 2))

        ctk.CTkLabel(
            card,
            text="Open-Source Windows → Linux Migration Assistant · 100% Local Native Desktop App",
            font=self.font_small,
            text_color=PALETTE["muted"],
        ).pack(anchor="w", padx=18, pady=(0, 12))

        notice_box = ctk.CTkFrame(
            card,
            fg_color=PALETTE["surface_alt"],
            border_width=1,
            border_color=PALETTE["border"],
            corner_radius=10,
        )
        notice_box.pack(fill="both", expand=True, padx=18, pady=(0, 12))

        ctk.CTkLabel(
            notice_box,
            text="Warranty, Trademark & Compliance Notice",
            font=self.font_h3,
            text_color=PALETTE["amber"],
            anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 6))

        ctk.CTkLabel(
            notice_box,
            text="\n\n".join(LEGAL_NOTICE_LINES),
            font=self.font_small,
            text_color=PALETTE["text"],
            anchor="w",
            justify="left",
            wraplength=555,
        ).pack(fill="x", padx=14, pady=(0, 12))

        foot = ctk.CTkFrame(card, fg_color="transparent")
        foot.pack(fill="x", padx=18, pady=(0, 14))

        ctk.CTkButton(
            foot,
            text="GitHub Repository",
            width=145,
            height=32,
            fg_color=PALETTE["surface_alt"],
            hover_color=PALETTE["surface_hover"],
            border_width=1,
            border_color=PALETTE["blue"],
            text_color=PALETTE["blue"],
            font=self.font_small,
            command=lambda: _safe_open_url(__repo_url__),
        ).pack(side="left")

        ctk.CTkButton(
            foot,
            text="Close",
            width=96,
            height=32,
            fg_color=PALETTE["teal"],
            hover_color=PALETTE["teal_hover"],
            text_color="#04151c",
            font=self.font_badge,
            command=win.destroy,
        ).pack(side="right")
        return win


def launch_gui(demo_mode: bool = False) -> int:
    """Start the native CustomTkinter desktop window (no HTTP server, no listening sockets)."""
    app = TuxHarborApp(demo_mode=demo_mode)
    app.mainloop()
    return 0
