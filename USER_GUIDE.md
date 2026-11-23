# TuxHarbor User Guide & Technical Architecture

This guide explains **how to use TuxHarbor**, **whether an internet connection is required**, **exactly what TuxHarbor scans (and never touches)**, **how the matching engine works**, and **how TuxHarbor handles hardware across Intel, AMD, NVIDIA, Qualcomm Snapdragon (ARM64), and major PC/peripheral vendors**.

---

## 1. Quick Start (4 Steps)

1. **Download `TuxHarbor.exe`** (Windows) from GitHub Releases — no installation required, no local web server, and no background services.
2. **Double-click `TuxHarbor.exe`** to open the native desktop window.
3. **Follow the 4-step wizard:**
   - **Step 1 — Scan:** Choose whether to scan installed apps, developer tools, and (optionally) your local project folders. Click **Start Scan** (or **Try Demo Mode**).
   - **Step 2 — Report & Alternatives:** Review your Linux Readiness Score, categorized apps, Hardware & Drivers section, and PC Games section. Toggle apps on/off, pick your preferred Linux alternative where multiple options exist, and choose your target Linux distro (or leave on **Auto-detect**).
   - **Step 3 — Backup Safety Checklist:** Review any detected projects with uncommitted/unpushed Git work or `.env` files, and confirm your external drive / cloud backups before switching.
   - **Step 4 — Choose Delivery (Before Generating):** Choose **Save Locally (PC / USB / Cloud)**, **Send Securely via Email** (direct TLS SMTP or passwordless Gmail/Outlook draft), or **Both**. Customize your filename prefix (**Save As**) and optionally preview the exact `install.sh` script before generating.
4. **Run on Linux:** After installing Linux, copy your generated files over (or download them from your email/USB) and run:
   ```bash
   chmod +x tuxharbor-migration-install.sh
   ./tuxharbor-migration-install.sh --dry-run   # Optional: preview every command first
   ./tuxharbor-migration-install.sh             # Install all selected tools & alternatives
   ```
   Alternatively, open **`TuxHarbor`** on Linux in **Linux Mode (Apply Plan)** and load your `*-plan.json` file.

---

## 2. Does TuxHarbor Require an Internet Connection?

| Stage / Feature | Internet Needed? | Why |
|---|---|---|
| Running `TuxHarbor.exe` & scanning your Windows PC | **No (100% Offline)** | Reads only local Registry, `winget`, Steam manifests, and dev CLIs. |
| Matching apps, drivers, games & computing Readiness Score | **No (100% Offline)** | Uses the curated `catalog.json` bundled directly inside `TuxHarbor.exe`. |
| Generating `*-report.html`, `*-install.sh`, `*-plan.json`, `.zip` | **No (100% Offline)** | All files are generated locally on your computer. |
| Saving to local folder / USB flash drive | **No (100% Offline)** | Writes directly to your selected folder or removable drive. |
| Sending files via Email (Step 4) | **Optional (Online)** | Connects directly from your PC to your SMTP mail server via TLS 1.2+ (or opens Gmail/Outlook draft). |
| Clicking ProtonDB / AreWeAntiCheatYet / Flathub links | **Optional (Online)** | Opens your browser only if you explicitly click a link. |
| Running `*-install.sh` later on Linux | **Yes (Online)** | Linux downloads your selected packages from official distro repos (`apt`/`dnf`/`pacman`/`zypper`) and Flathub. |

TuxHarbor has **zero telemetry**, **zero analytics**, **zero cloud backend**, and **zero open network ports**.

---

## 3. Exactly What Does TuxHarbor Scan?

All scanning on Windows is **strictly read-only** — TuxHarbor never modifies your Windows Registry, system files, or projects.

### What TuxHarbor Reads
- **Installed Applications:**
  - Windows Registry Uninstall keys (`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall`, `WOW6432Node`, and `HKCU\...\Uninstall`).
  - `winget list` output (when enabled) to retrieve language-independent `MSIX\` and Winget package IDs.
  - Local `Scoop` (`~/scoop/apps`) and `Chocolatey` (`%ProgramData%\chocolatey\lib`) folder names if present.
- **System Hardware Profile (Read-Only):**
  - CPU architecture (`x86_64` vs. `ARM64` / Snapdragon) and CPU model string (`HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0`).
  - Display adapters / GPUs (`HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}`).
  - PC manufacturer and model (`HKLM\HARDWARE\DESCRIPTION\System\BIOS`).
- **Developer Environment:**
  - CLI version checks on your `PATH` (`git`, `gh`, `node`, `python`, `docker`, `go`, `rustc`, `dotnet`, `java`, `ffmpeg`, `deno`, `ollama`, `nmap`, `yt-dlp`, `conda`, `code`).
  - VS Code extension IDs (`~/.vscode/extensions/extensions.json` or `code --list-extensions`), global `npm` package folder names, and `git config --global user.name` / `user.email`.
- **Installed PC Games (Read-Only):**
  - Registry game metadata and local Steam `libraryfolders.vdf` / `appmanifest_*.acf` titles (with strict size caps, UNC network path blocking, and NTFS junction/symlink checks).
- **Optional Project Folders (Only folders you explicitly select):**
  - Detects project manifests (`package.json`, `requirements.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `.csproj`, `Dockerfile`, etc.) to identify needed Linux runtimes and Windows-only frameworks (such as WPF/WinForms).
  - Runs `git -c core.fsmonitor=false --no-optional-locks status` to alert you to uncommitted changes, unpushed commits, or local-only repos.

### What TuxHarbor NEVER Reads or Touches
- **Never reads `.env` contents** (only checks whether a `.env` file *exists* so it can warn you to back it up!).
- **Never copies or uploads** your source code, documents, photos, downloads, or personal files.
- **Never reads** browser passwords, cookies, history, or private SSH keys (`~/.ssh/id_*`).
- **Never stores** SMTP passwords on disk or in logs.

---

## 4. How the 5-Stage Cross-Referencing Engine Works

When you click **Start Scan**, TuxHarbor runs a deterministic, transparent 5-stage pipeline locally using the bundled [`tuxharbor/data/catalog.json`](tuxharbor/data/catalog.json):

```
[Windows Registry + winget + Steam + Dev CLIs + Direct Hardware Probe]
                                │
                                ▼
  Stage 1 · Normalization & Deduplication
            Merges duplicates across Registry & winget, normalizes Unicode
            (e.g. Greek μ / micro µ, BiDi marks), preserves MSIX/ARP IDs.
                                │
                                ▼
  Stage 2 · Pre-Exclusion of OS Subcomponents & Runtimes
            Filters language-independent Windows runtimes (WebView2,
            WinAppRuntime, .NET Desktop Runtime, VC++ Redistributables, helpers).
                                │
                                ▼
  Stage 3 · Hardware & Drivers Consolidation
            Matches CPU/GPU/Wi-Fi/Audio/OEM/Printer/Tablet/SSD entries AND
            direct GPU/ARM64 hardware probes into unified Hardware cards.
            (Never auto-modifies Linux kernel/GPU drivers in install.sh.)
                                │
                                ▼
  Stage 4 · PC Games Detection & Anti-Cheat Lookup
            Identifies Steam, Riot, Rockstar, and Registry games separately;
            flags known kernel anti-cheat titles and links to ProtonDB &
            AreWeAntiCheatYet (never sends games to Flathub).
                                │
                                ▼
  Stage 5 · Curated Catalog Scoring + Remaining Niche Apps
            Matches apps using exact > word-boundary > substring scoring with
            exclude_patterns, classifies any leftover OS built-ins via MSIX
            PackageFamilyName (works on ANY Windows UI language!), and lists
            only genuine niche user apps under "Other / Niche Applications".
```

---

## 5. Universal Hardware Compatibility Guide

TuxHarbor is designed for **every Windows PC architecture and vendor**, not just one hardware setup:

- **Intel (CPUs, Integrated/Arc GPUs, Wi-Fi/Bluetooth, Chipsets):** Supported directly inside the Linux kernel (`i915`/`xe`, `iwlwifi`) + Mesa. Updates automatically with your Linux distribution.
- **AMD (Ryzen CPUs, Radeon GPUs, Chipsets):** Supported directly inside the Linux kernel (`amdgpu`) + Mesa/RADV out of the box.
- **NVIDIA (GeForce / RTX GPUs):** Supported via NVIDIA's official native Linux drivers (including open-kernel modules for RTX 20-series / Turing and newer). Most beginner-friendly distributions (Ubuntu, Linux Mint, Pop!_OS, Fedora, Arch) install them cleanly via their built-in Driver Manager.
- **Qualcomm Snapdragon / Windows on ARM (`ARM64`):** TuxHarbor automatically detects `ARM64` / Snapdragon processors and Adreno GPUs and alerts you to download an **`ARM64` (`aarch64`) Linux ISO** with a recent kernel (Linux 6.11+) and verify laptop model support on a Live USB first.
- **Wi-Fi & Bluetooth (Intel, MediaTek, Qualcomm Atheros/Killer, Realtek, Broadcom):** Intel, Realtek, MediaTek (`mt7921e`/`mt7925e`), and Qualcomm (`ath11k`/`ath12k`) are broadly supported in modern Linux kernels. Some Broadcom Wi-Fi chips need a distro firmware package (`broadcom-wl`) — having Ethernet or phone USB tethering handy during installation is a great precaution.
- **Laptop OEMs (Lenovo, Dell/Alienware, HP/OMEN, ASUS/ROG, MSI, Acer, Gigabyte, Microsoft Surface, Apple Boot Camp):** Standard hotkeys work via Linux ACPI/WMI, BIOS/UEFI firmware updates are handled natively via `fwupd` (LVFS) on Lenovo/Dell/HP and others, and community tools exist for specialty hardware (`asusctl`, `linux-surface`, `t2linux`, `OpenRGB`, `Solaar`).
- **Printers, Drawing Tablets, SSDs & Audio:** Modern printers work driverless via CUPS (AirPrint/IPP Everywhere); Wacom/Huion/XP-Pen work via kernel drivers + `OpenTabletDriver`; SSD health works via GNOME Disks / `nvme-cli` / `smartmontools`; class-compliant USB audio interfaces work natively via PipeWire/ALSA.
- **Unknown Vendors:** Even if a hardware vendor is not listed explicitly, TuxHarbor's generic hardware/driver heuristic groups vendor drivers under **Hardware & Drivers** rather than polluting your application list.

> **Golden Rule Before Wiping Windows — The Live USB Test:**
> Flash your chosen Linux distro onto a USB stick (e.g., using Rufus or Ventoy) and boot into **"Try Linux"** (Live mode — touches nothing on your hard drive). Spend 5 minutes checking Wi-Fi, Bluetooth, speakers/mic, brightness keys, touchpad, and external monitors. If they work in Live mode, you're ready!

---

## 6. Contributing New Apps or Hardware Rules

Missing an app, game, or hardware vendor? Every mapping lives in [`tuxharbor/data/catalog.json`](tuxharbor/data/catalog.json). See [`CONTRIBUTING.md`](CONTRIBUTING.md) to open a pull request — automated tests verify schema integrity and package safety on every PR!
