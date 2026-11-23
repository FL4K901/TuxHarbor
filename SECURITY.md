# Security Policy

## Security Architecture

TuxHarbor is engineered around a **100% local, zero-server, least-privilege threat model**:

1. **Zero Network Exposure (No Embedded Web Server):**
   - TuxHarbor runs exclusively as a native cross-platform desktop application (`CustomTkinter`) or headless CLI.
   - It opens **zero listening TCP/UDP ports**, runs **no HTTP server**, and makes **zero background network requests** or telemetry calls.
   - The only outbound network connection TuxHarbor can ever initiate is an explicit, user-triggered SMTP delivery session over verified TLS.

2. **Verified TLS SMTP & Ephemeral Credential Handling:**
   - Direct SMTP delivery (`tuxharbor/delivery.py`) enforces `ssl.create_default_context()` with `check_hostname = True`, `verify_mode = ssl.CERT_REQUIRED`, and `minimum_version = ssl.TLSVersion.TLSv1_2` for both `SMTP_SSL` and `STARTTLS` (explicitly verifying the server advertises `STARTTLS` before upgrading).
   - Strict input validation blocks **SMTP header injection** by rejecting CR (`\r`), LF (`\n`), NUL (`\x00`), and ASCII control characters before normalization across host, sender, recipient, filename prefix, and password fields, and enforces RFC-compliant email, hostname/IP, and port (`1..65535`) validation.
   - Passwords are masked in the GUI, never bound to persistent state, cleared immediately from the input widget and memory in a `finally` block, never logged or persisted to disk, and scrubbed (both raw and base64-encoded forms) from any error message.

3. **Defense-in-Depth Shell & Command Injection Prevention:**
   - Every native package token, Flatpak reverse-DNS ID, global npm package name, VS Code extension ID, and Git identity field is validated against strict `\A...\Z`-anchored allowlist regular expressions (`tuxharbor/models.py`) rejecting newlines, `..`, paths, URLs, and leading dashes (`-`).
   - Validation is enforced both when creating `*-plan.json` and again inside `generate_linux_script()` and `apply_plan_on_linux()` to defend against tampered plan files.
   - Generated Bash scripts use Unix LF endings, `shlex.quote()` on all dynamic arguments, Bash arrays (`CODE_CMD=()`) to prevent word-splitting, and `--` option delimiters (`apt-get`, `dnf`, `pacman`, `zypper`, `npm`, `git config`).
   - All Python `subprocess.run()` and `subprocess.Popen()` calls use explicit `shell=False`, list arguments, resolved executable paths (`shutil.which()`), and bounded timeouts.

4. **Static Offline HTML Reports & XSS Protection:**
   - Generated HTML migration reports (`tuxharbor/generators/html_report.py`) are 100% static with **zero JavaScript** and include a strict Content-Security-Policy header (`default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none';`).
   - Every interpolated string across applications, hardware/drivers, PC games, Windows OS built-ins, projects, and unmatched apps is HTML-escaped (`html.escape(..., quote=True)`), search query parameters use `urllib.parse.quote_plus()`, numeric Steam AppIDs are validated against `\A[0-9]{1,10}\Z`, external links enforce `is_safe_https_url()` with `rel="noopener noreferrer"`, and ProtonDB / AreWeAntiCheatYet lookup URLs enforce expected-hostname validation.

5. **Safe File Handling, Symlink/Junction Protection & ZIP Slip Prevention:**
   - Custom filename prefixes are strictly sanitized against path traversal (`..`, `/`, `\`), shell metacharacters, and Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`).
   - Read-only Windows Steam library scanning (`tuxharbor/scanners/windows_apps.py`) rejects UNC/SMB network paths (requiring local drive paths on Windows), skips symbolic links and NTFS directory junctions, enforces strict file-size and count caps (`<= 2 MB` `.vdf`, `<= 512 KB` `.acf`, `<= 32` libraries, `<= 500` manifests), and uses bounded linear-time regular expressions (zero ReDoS).
   - Registry `UninstallString` values are read strictly in memory for game heuristics and are never executed, serialized, or emitted into reports or scripts.
   - Hardware and GPU driver guidance is strictly informational — generated Bash scripts never auto-modify kernel driver packages and never emit `curl | sh` / `curl | bash` installers.
   - Bundle exports refuse to write into or through symbolic links, assert destination directory containment, and emit bare basenames inside ZIP archives (with POSIX `0755` permissions on `.sh` scripts).
   - Plan JSON files loaded in Linux Mode enforce a 5 MB size cap and strict schema type validation.

6. **Read-Only Project Auditing & Privacy:**
   - Project scanning (`tuxharbor/scanners/projects.py`) never modifies files, skips symbolic links, and checks only `.env` filename presence — **`.env` file contents are never opened or read**.
   - Git metadata queries invoke the resolved `git` binary with `-c core.fsmonitor=false --no-optional-locks` to prevent untrusted repository configuration execution and avoid creating Git lock files.

7. **CI/CD & Supply-Chain Hardening:**
   - GitHub Actions release workflows (`.github/workflows/release.yml`) enforce least-privilege permissions (`contents: read` globally, `contents: write` scoped strictly to the tag-triggered `release` job), pin all Actions to full 40-character commit SHAs with `persist-credentials: false`, pin Python build dependencies, avoid shell expression injection, and publish `SHA256SUMS.txt` checksums alongside release binaries.

## Reporting a Vulnerability

If you discover a security vulnerability in TuxHarbor, please report it responsibly and privately via **GitHub Security Advisories** rather than opening a public issue. Include reproduction steps, affected version/commit, and potential impact so the maintainers can investigate and ship a coordinated fix.
