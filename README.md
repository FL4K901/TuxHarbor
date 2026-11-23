# TuxHarbor

**Open-source native desktop Windows → Linux migration analyzer, alternative finder & automated setup generator.**

[![Cross-Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-0ea5e9)](#)
[![Zero Server](https://img.shields.io/badge/architecture-Native%20Desktop%20%7C%20Zero%20Open%20Ports-14b8a6)](#security--privacy)
[![Zero Telemetry](https://img.shields.io/badge/privacy-100%25%20local%20%7C%20zero%20telemetry-22c55e)](#security--privacy)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)

---

## Why TuxHarbor?

Switching from Windows to Linux shouldn't feel like a leap into the unknown. Most people hesitate because they worry about forgetting essential tools, hitting unsupported Windows-only software, or breaking active development projects.

**TuxHarbor** runs locally on your PC as a sleek, standalone **native desktop application** (zero HTTP servers, zero open TCP ports, zero browser UI, zero telemetry). It analyzes your tools, maps each application to its native Linux version or curated open-source alternative, audits optional project folders for Linux compatibility and unpushed Git work, reminds you to back up your personal files, and generates:

1. **`*-report.html`** — A standalone, static offline HTML migration readiness report (zero JavaScript, strict CSP).
2. **`*-install.sh`** — A human-readable, shell-safe Bash installer that auto-detects your Linux distro (`apt` / `dnf` / `pacman` / `zypper` + `Flatpak`) and installs your selected applications, alternatives, developer runtimes, and VS Code extensions.
3. **`*-plan.json`** — A portable manifest you can also load directly inside **TuxHarbor's Linux Mode** to inspect installed status, run a Dry Run preview, and apply packages natively on Linux.

> **Important Backup Notice:** TuxHarbor migrates **tools, development environments, and Linux alternatives ONLY** — it never copies, backs up, or uploads your personal files or project source code. Always back up your projects, `.env` files, SSH keys, and personal documents to an external drive or cloud storage before switching operating systems.

---

## Key Features

- **Native Cross-Platform Desktop GUI** — Modern dark-mode desktop interface built with CustomTkinter (runs natively on Windows & Linux with zero HTTP server, zero listening ports, and a built-in **How It Works** guide).
- **100% Offline Scanning & Smart 5-Bucket Classification** — Separates Desktop Apps (grouped by category), Hardware & Drivers, PC Games & Launchers, Windows OS Built-ins (language-independent across any Windows UI language), and remaining Niche Apps.
- **Universal Hardware & Architecture Support** — Automatically probes CPU architecture (`x86_64` vs. `ARM64` / Qualcomm Snapdragon), GPUs (NVIDIA, AMD, Intel, Qualcomm Adreno), Wi-Fi/Bluetooth (Intel, MediaTek, Qualcomm Atheros, Broadcom, Realtek), major laptop OEMs (Lenovo, Dell, HP, ASUS, MSI, Acer, Gigabyte, Microsoft Surface, Apple Boot Camp), printers, drawing tablets, and SSD utilities — plus generic driver heuristics for any other vendor.
- **Read-Only Windows Application & Steam Scanner** — Inspects Windows Registry (`HKLM`/`HKCU`), `winget`, Scoop, Chocolatey, and local Steam manifests cleanly.
- **Developer Environment Audit** — Detects Git, Node.js, Python, Docker, Go, Rust, .NET, Java, FFmpeg, VS Code extensions, global npm packages, and Git global identity.
- **Read-Only Project Compatibility & Git Backup Audit** — Spots Windows-specific dependencies (WPF/WinForms, `.bat`/`.ps1` scripts, hardcoded `C:\` paths), warns about `.env` files (without ever reading their contents), and flags uncommitted or unpushed Git work.
- **Curated Community Catalog (`catalog.json`)** — Classifies 115+ popular apps into Native on Linux, Great Alternatives (with interactive pickers in the GUI), Compatibility Layer, and Needs Attention (honest compatibility notes for anti-cheat titles and proprietary suites).
- **Mandatory Pre-Export Backup Checklist** — Dedicated Step 3 warning card, auto-detected project backup risk list, and 4-item safety checklist before generating your migration kit.
- **Ask-Before-Generate Flexible Delivery** — Choose how to deliver your migration kit before creating files:
  - **Save Locally ("Save As")** — Custom sanitized filename prefix with live preview, auto-detected USB drives & OneDrive/Google Drive/Desktop quick-picks, native folder browser, and optional `.zip` archive preserving Unix `0755` script permissions.
  - **Send Securely via Email** — Direct local-only **TLS 1.2+ verified SMTP** with all 3 files attached (passwords masked, cleared immediately, never stored or logged), OR passwordless **Gmail / Outlook / Mail Client quick drafts**.
  - **Both** — Save locally and send via email in one step.
  - **Live Script Preview** — Inspect the exact generated `.sh` Bash script in a modal before saving or sending.
- **Built-In Linux Mode** — Switch to the **Linux Mode (Apply Plan)** tab on Linux (or preview via Dry Run on Windows) to load `*-plan.json`, inspect installed vs. pending packages, and install directly with a live output log.

---

## Quick Start

### Option 1: Download Prebuilt Binary (Recommended)
1. Download **`TuxHarbor-windows-x64.exe`** (or **`TuxHarbor-linux-x64`**) and **`SHA256SUMS.txt`** from **GitHub Releases**.
2. Double-click **`TuxHarbor-windows-x64.exe`** — the native desktop application launches directly (no console window, no browser server).
3. Follow the 4 guided steps: **Scan System → Pick Alternatives → Backup Reminder → Save / Email**.
4. Once on Linux, run:
   ```bash
   chmod +x tuxharbor-migration-install.sh
   ./tuxharbor-migration-install.sh --dry-run   # Optional: preview commands first
   ./tuxharbor-migration-install.sh             # Install selected apps & alternatives
   ```

### Option 2: Run from Source (Python 3.10+)
```bash
git clone https://github.com/tuxharbor/tuxharbor.git
cd tuxharbor
pip install -e .
python main.py          # Launch native desktop GUI
python main.py --demo   # Launch GUI with Demo Mode hint (great on any OS)
```

### Headless CLI Usage
```bash
# Scan & export a migration bundle without opening the GUI
python main.py --cli-scan --out ./my-kit --name my-pc --projects C:\Projects

# Preview or apply a saved plan directly on Linux
python main.py --linux-apply ./my-kit/my-pc-plan.json --dry-run
python main.py --linux-apply ./my-kit/my-pc-plan.json
```

### Build Standalone `.exe` Locally (Windows)
```powershell
.\build_exe.ps1
# Output: .\dist\TuxHarbor.exe
```

---

## Security & Privacy

TuxHarbor is engineered for security-conscious users and developers:

- **Zero Network Exposure by Default:** Pure native desktop app — zero HTTP servers, zero listening TCP ports, zero telemetry, zero remote APIs.
- **Read-Only Scanning:** Project scanning uses `git -c core.fsmonitor=false --no-optional-locks`, skips symlinks, and never opens or reads `.env` file contents.
- **Zero-Storage Encrypted Email:** Direct SMTP strictly validates inputs against header injection, enforces verified TLS 1.2+ (`CERT_REQUIRED` + hostname verification), masks password entry, and scrubs credentials immediately from memory.
- **Injection-Proof Scripts & Static Reports:** Every package name, Flatpak ID, npm package, and VS Code extension is validated against strict `\A...\Z` allowlists and shell-quoted (`shlex.quote`) with `--` argument delimiters. Generated HTML reports are 100% static (zero JavaScript) with an inline Content Security Policy.

---

## Documentation, Legal & Privacy

- **[USER_GUIDE.md](USER_GUIDE.md)** — Complete usage guide: offline vs. online requirements, exact scan scope, 5-stage matching engine, and universal hardware guide (Intel, AMD, NVIDIA, Snapdragon/ARM64).
- **[SECURITY.md](SECURITY.md)** — Threat model, security controls, and vulnerability reporting.
- **[PRIVACY.md](PRIVACY.md)** — Local-only data handling and zero-telemetry privacy policy.
- **[DISCLAIMER.md](DISCLAIMER.md)** — No-warranty ("AS IS") disclaimer, trademark nominative fair use, and EULA/ToS notice.
- **[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)** — Licenses and attributions for bundled open-source components.

---

## Contributing

The heart of TuxHarbor is [`tuxharbor/data/catalog.json`](tuxharbor/data/catalog.json) — a curated, factual database of Windows applications and their Linux equivalents. Pull requests adding new entries or updated Flatpak/distro packages are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Released under the [MIT License](LICENSE).
