# Privacy Policy

**Effective Date:** November 2026  
**Applies To:** TuxHarbor Desktop Application, CLI, and Standalone Releases

> **TL;DR:** TuxHarbor runs **100% locally** on your device with **zero telemetry, zero analytics, zero remote backend servers, and zero open network ports**. TuxHarbor and its authors never collect, transmit, store, sell, or share your personal data.

---

## 1. Core Privacy-by-Design Architecture

TuxHarbor is engineered as an offline-first, native desktop utility:

- **No Remote Servers:** TuxHarbor does not operate any cloud backend, API server, telemetry collector, or analytics endpoint.
- **No Tracking or Telemetry:** The application contains no crash reporters, usage trackers, advertising SDKs, cookies, or automatic phone-home checks.
- **Zero Embedded Web Server:** TuxHarbor runs as a native desktop GUI application and opens **no listening TCP/UDP network ports** on your machine.
- **Open-Source Verifiability:** All source code is publicly inspectable in this repository so you can independently verify every file read and network call.

---

## 2. Information Processed Locally on Your Device

All scanning and report generation occur strictly inside volatile memory on your local machine. Depending on the options you choose, TuxHarbor performs **read-only** local inspection of:

1. **Installed Applications, Hardware Profile, Drivers & PC Games Inventory (Windows):**
   - Reads standard Windows Uninstall Registry keys (`HKLM` and `HKCU`), read-only hardware identification keys (CPU architecture/brand `CentralProcessor\0`, Display Adapters class GUID, and BIOS system manufacturer/product), optional `winget list` output, Scoop/Chocolatey package folder names, and local Steam library manifests (`libraryfolders.vdf` and `appmanifest_*.acf` game titles and numeric AppIDs only — strictly read-only, local-drive-only, symlink/junction-skipped, and size-bounded).
   - Used exclusively in memory to classify applications, hardware/drivers, PC games, and Windows built-ins against the local `tuxharbor/data/catalog.json` database.
2. **Developer Environment Metadata (Optional):**
   - Detects installed local CLI runtimes (`git`, `gh`, `node`, `python`, `docker`, `go`, `rustc`, `dotnet`, `java`, `deno`, `ollama`, `ffmpeg`, `code`), VS Code extension IDs (from `.vscode/extensions/extensions.json`), and global `npm` package folder names.
   - Reads your local global Git configuration (`git config --global user.name` and `user.email`) **only** to offer an opt-in checkbox to include those values in your exported migration plan. Git identity is excluded by default unless you explicitly enable it.
3. **Project Folder Compatibility Audit (Strictly Opt-In):**
   - Scans only the folders you explicitly select.
   - Inspects project manifest filenames (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `.csproj`, etc.), Windows-only target flags in `.csproj`/`.vbproj` files, Windows drive-path patterns in `package.json`, and local `git` status/remote metadata (`git remote`, `git status --porcelain`, unpushed commit count).
   - **Strict Secret Protection (`.env` Guarantee):** TuxHarbor checks only whether filenames such as `.env` or `.env.local` *exist* so it can remind you to back them up safely. **TuxHarbor NEVER opens, reads, parses, logs, or copies the contents of `.env` files, SSH private keys, API tokens, passwords, or your application source code.**
4. **Save Location Shortcuts:**
   - Queries mounted removable USB drive labels and standard user directories (Desktop, Documents, Downloads, and local cloud-sync folder paths such as OneDrive or Google Drive) solely to offer convenient "Save As" destination buttons.

---

## 3. Locally Generated Export Files

TuxHarbor writes files to disk **only** when you explicitly choose to generate and save a migration bundle (`*-report.html`, `*-install.sh`, `*-plan.json`, and optional `*-bundle.zip`) in a destination folder you specify.

Please note that your locally saved `*-report.html` and `*-plan.json` files may include:

- Your detected list of installed software and developer tools;
- Directory paths of project folders you chose to scan; and
- Your Git `user.name` and `user.email` (only if you explicitly opted in).

These files remain entirely under your control. Store them securely and review them before sharing them with anyone else.

---

## 4. Optional Email Delivery & Transient Credential Handling

TuxHarbor never accesses the network during scanning or local file export. Outbound network connections occur **only** if you explicitly initiate one of the optional email delivery methods in Step 4:

### A. Direct TLS SMTP Delivery (Optional, User-Initiated)
- Connects **directly from your computer** to the SMTP server you select or configure (e.g., Gmail, Outlook, Yahoo, iCloud, or a custom SMTP server). No TuxHarbor intermediary server is involved.
- **Mandatory Verified TLS:** Connections strictly require encrypted TLS (`STARTTLS` or `SMTP_SSL`) with certificate verification via Python's `ssl.create_default_context()`. Unencrypted plaintext SMTP is prohibited.
- **Zero Credential Persistence:** Your SMTP username and password / App Password exist **strictly in transient volatile memory** for the duration of the single SMTP transmission. TuxHarbor immediately clears the password from memory and the GUI input field after the send attempt and **never** writes credentials to disk, configuration files, logs, or generated reports.

### B. Passwordless Quick Draft (Gmail Web / Outlook Web / `mailto:`)
- Opens a pre-populated compose link in your default web browser or local mail client containing a summary of your migration kit.
- TuxHarbor never receives or handles your email password in this mode.

Once you transmit an email through your email provider or open a webmail compose URL, your email contents and metadata are governed by that email provider's own privacy policy.

---

## 5. Third-Party Services & External Links

- Generated HTML reports and the app catalog contain links to independent external websites (such as official vendor download sites, Flathub, AlternativeTo, and independent community compatibility databases like ProtonDB and AreWeAntiCheatYet). Visiting those links is optional and subject to each site's privacy policy.
- When you later choose to execute the generated Linux setup script (`*-install.sh`) or TuxHarbor Linux Mode on a Linux machine, your Linux system connects directly to your chosen Linux distribution's package mirrors, Flathub, the Visual Studio Marketplace, or the npm registry to download packages. Those connections are initiated directly by your OS package managers and governed by those services' respective privacy policies.

---

## 6. GDPR (EU/EEA/UK) & CCPA/CPRA (California) Compliance Notice

Because TuxHarbor operates exclusively as client-side open-source software with zero remote data collection:

- **No Collection, Sale, or Sharing of Personal Information:** Under the EU/UK General Data Protection Regulation (GDPR) and the California Consumer Privacy Act / California Privacy Rights Act (CCPA/CPRA), the TuxHarbor project and its contributors do **not** collect, receive, store, process on remote servers, "sell," or "share" any Personal Data or Personal Information.
- **User as Sole Custodian:** You remain the sole controller and custodian of all information read locally and all migration files exported to your chosen storage locations.
- **Exercise of Rights (Access, Portability, Deletion):** Because all data resides solely on your own device, you may inspect, move, or permanently delete all TuxHarbor-generated files at any time using your operating system's standard file tools—no deletion request to TuxHarbor is required because we hold no data about you.
- **Children's Privacy:** TuxHarbor does not collect personal information from any users, including children under 13 (COPPA) or 16 (GDPR).

---

## 7. Policy Updates & Contact

Any updates to this Privacy Policy will be published directly in this repository alongside the corresponding software release. If you have privacy questions or discover a privacy-related issue in TuxHarbor, please report it via the repository's GitHub Security Advisories or Issues tracker (see [SECURITY.md](SECURITY.md)).

> *Note: This Privacy Policy reflects open-source privacy best practices and accurate technical documentation of TuxHarbor's behavior; it is not formal attorney-client legal advice.*
