# Legal Disclaimer, Trademark Notice & Terms of Use

> **Important Notice:** This document is provided to establish clear open-source terms, risk disclosures, and intellectual property boundaries for **TuxHarbor**. Nothing in this repository constitutes formal legal advice or creates an attorney-client relationship.

---

## 1. Open-Source License & "AS IS" No-Warranty Disclaimer

TuxHarbor is free, open-source software distributed under the [MIT License](LICENSE).

**THE SOFTWARE, ALL GENERATED REPORTS (`*-report.html`), MIGRATION PLANS (`*-plan.json`), BASH INSTALLATION SCRIPTS (`*-install.sh`), DOCUMENTATION, AND APPLICATION CATALOG DATA (`catalog.json`) ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, ACCURACY, COMPLETENESS, COMPATIBILITY, SYSTEM SAFETY, AND NON-INFRINGEMENT.**

While TuxHarbor aims to provide accurate, neutral, and helpful Linux compatibility information, software ecosystems evolve continuously. TuxHarbor contributors make no guarantee that:

- Every installed Windows application will be detected or accurately matched;
- Suggested Linux equivalents or web applications will offer feature parity with Windows software or suit your specific professional or personal workflow;
- Referenced package identifiers, Flatpak IDs, or external URLs will remain available, current, or error-free across all Linux distributions.

---

## 2. Limitation of Liability & System Modification Risks

**IN NO EVENT SHALL THE AUTHORS, MAINTAINERS, OR COPYRIGHT HOLDERS OF TUXHARBOR BE LIABLE FOR ANY CLAIM, DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, WITHOUT LIMITATION, DATA LOSS, CORRUPTED PARTITIONS, OPERATING SYSTEM FAILURE, LOST PROFITS, BUSINESS INTERRUPTION, ACCOUNT SUSPENSION, OR HARDWARE/DRIVER ISSUES), HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, ARISING OUT OF OR IN CONNECTION WITH THE USE OF OR INABILITY TO USE TUXHARBOR OR ANY FILE IT GENERATES.**

By using TuxHarbor, you acknowledge and accept the following operational responsibilities:

1. **Operating System Migration & Partitioning:** Installing Linux, dual-booting, resizing disks, or formatting a Windows installation carries inherent risk of permanent data loss. TuxHarbor does **not** install operating systems, partition drives, or back up your computer.
2. **Sole Responsibility for Data Backups:** TuxHarbor helps plan and reinstall **software tools, development runtimes, and alternatives ONLY**. It **never** copies, backs up, or migrates your personal files, documents, media, project source code, local Git commits, `.env` secret files, SSH/GPG keys, browser profiles, or software licenses. **You are solely responsible for creating and verifying independent backups** (e.g., external USB/SSD drive, encrypted cloud storage, and remote Git repositories) before making any system or operating system changes.
3. **Privileged Script Execution (`sudo` / Package Managers):** The generated Linux setup script (`*-install.sh`) and TuxHarbor's Linux Mode invoke system package managers (`apt`, `dnf`, `pacman`, `zypper`), `flatpak`, `code`, `npm`, and `git`, including commands requiring administrative privileges (`sudo`). **You are solely responsible for reading and auditing any generated script before executing it.** Running `./<prefix>-install.sh --dry-run` first is strongly recommended.

---

## 3. Trademark & Non-Affiliation Notice (Nominative Fair Use)

TuxHarbor is an **independent, community open-source project**. TuxHarbor is **not affiliated with, endorsed by, sponsored by, authorized by, or officially connected to** any third-party company, software vendor, foundation, or brand referenced within the software, catalog, generated reports, or documentation.

All third-party product names, software titles, company names, logos, service marks, and registered or unregistered trademarks—including, without limitation, those owned by Microsoft Corporation, Adobe Inc., Google LLC, Apple Inc., NVIDIA Corporation, Intel Corporation, Advanced Micro Devices, Inc. (AMD), Qualcomm Incorporated (Snapdragon / Adreno), MediaTek Inc., Realtek Semiconductor Corp., Broadcom Inc., Lenovo Group Limited, Dell Inc. (Alienware), HP Inc., Acer Inc., Micro-Star International (MSI), GIGABYTE Technology, ASUSTeK Computer Inc. (ASUS), Samsung Electronics, Western Digital, Micron (Crucial), Wacom Co., Ltd., Canon Inc., Seiko Epson Corporation, Brother Industries, Valve Corporation, Riot Games, Inc., Epic Games, Inc., Take-Two Interactive Software, Inc. / Rockstar Games, Roblox Corporation, Autodesk, Inc., Dassault Systèmes (SolidWorks), Docker Inc., JetBrains s.r.o., Meta Platforms, Inc. (WhatsApp / Quest), Discord Inc., Spotify AB, TeamViewer, Gen Digital / Piriform (CCleaner), BitTorrent, Inc. (uTorrent), Logitech, Razer, Corsair, Elgato, SteelSeries, Focusrite, Dolby Laboratories, THX, Deno Land Inc., Ollama, Snapmaker, DisplayLink / Synaptics, GitHub, Inc., Oracle Corporation, Blackmagic Design, Zoom, Slack / Salesforce, Flathub, and any Linux distribution—are the **exclusive property of their respective owners**.

All references to third-party names and marks in TuxHarbor are made strictly under **nominative fair use** for the sole factual purposes of:

- Identifying software already installed on the user's local system; and
- Providing neutral, informational cross-platform compatibility notes and Linux alternatives.

No ownership over any third-party mark is claimed, and no endorsement, partnership, or sponsorship by any trademark holder is implied.

### Corrections & Trademark Inquiries

TuxHarbor strives to maintain strictly factual, neutral, and respectful descriptions for all referenced software. If you represent a software vendor or rights holder and believe a catalog entry, trademark reference, or compatibility note is inaccurate, outdated, or improperly attributed, please open an issue on the project's GitHub repository and maintainers will review and update it promptly.

---

## 4. Third-Party Packages, Repositories & External Links

TuxHarbor's catalog (`catalog.json`) and generated outputs reference independent third-party package repositories and external websites, including Linux distribution repositories (`apt`, `dnf`, `pacman`, `zypper`), **Flathub** (`flatpak`), the **Visual Studio Marketplace**, the **npm registry**, **ProtonDB**, **AreWeAntiCheatYet**, **AlternativeTo**, and official vendor download websites.

- **Independent Control:** TuxHarbor does not host, build, sign, audit, control, or redistribute any third-party software packages installed via generated scripts or linked from reports.
- **Independent Community Compatibility Databases:** **ProtonDB** (`protondb.com`) and **AreWeAntiCheatYet** (`areweanticheatyet.com`) are independent, community-maintained compatibility databases—they are **not** official game publisher, platform, or vendor guarantees, and game or anti-cheat compatibility on Linux may change at any time following publisher updates.
- **Hardware & Kernel Driver Guidance:** Hardware and driver entries in TuxHarbor reports are informational only; generated Linux setup scripts (`*-install.sh`) never automatically modify kernel or GPU driver packages. Consult your Linux distribution's driver manager or official vendor documentation before installing proprietary drivers.
- **Community vs. Vendor Packaging:** Some packages hosted on Flathub or distribution repositories are community-maintained repackagings rather than directly vendor-verified builds. Users should verify publisher verification badges, provenance, and licensing terms directly on Flathub or the vendor's official website before installation.
- **Third-Party Licensing:** Every third-party application you choose to install is governed exclusively by its own software license, EULA, and Terms of Service (including any commercial vs. non-commercial eligibility requirements).

---

## 5. EULA, Terms of Service, DRM & Anti-Cheat Compliance

TuxHarbor respects intellectual property rights, software licenses, and platform integrity:

- **Zero Circumvention:** TuxHarbor **never** provides, facilitates, links to, or encourages the use of tools, patches, or methods designed to bypass Digital Rights Management (DRM), software licensing/activation mechanisms, subscription paywalls, or kernel/user-mode anti-cheat protections.
- **Anti-Cheat & Incompatible Software:** Where third-party games or applications (such as titles protected by Windows kernel-level anti-cheat systems or Windows-only proprietary suites) do not support Linux, TuxHarbor transparently discloses that incompatibility and highlights only compliant paths (such as native Linux alternatives, official browser/cloud services, or retaining a properly licensed Windows installation).
- **Community Compatibility Layers & Unofficial Wrappers:** Where TuxHarbor notes the existence of independent, community-developed compatibility layers or third-party desktop wrappers (e.g., Wine, Proton, Lutris, Bottles, Sober, or unofficial web-app wrappers), TuxHarbor does **not** warrant that such tools are authorized by or compliant with any vendor's EULA or Terms of Service. **Users are solely responsible for reviewing and complying with all applicable EULAs, Terms of Service, and local laws** before using any third-party runtime or wrapper.

---

## 6. Governing Responsibility

You are responsible for ensuring that your use of TuxHarbor and any software installed using its outputs complies with all applicable laws, organizational IT policies, and third-party agreements in your jurisdiction.
