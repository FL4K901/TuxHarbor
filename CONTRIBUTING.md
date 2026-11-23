# Contributing to TuxHarbor

Thank you for helping make switching from Windows to Linux clearer and safer for everyone!

## Adding a Windows App or Linux Alternative

All application mappings live in a single clean JSON file: [`tuxharbor/data/catalog.json`](tuxharbor/data/catalog.json).

### Entry Schema (English Only)
```json
{
  "id": "my-app-id",
  "name": "Windows App Display Name",
  "category": "utilities",
  "status": "alternative",
  "match_patterns": ["lowercase registry substring", "winget.id"],
  "exclude_patterns": ["optional false-positive substring"],
  "summary": "Clear, neutral, factually verifiable explanation in English.",
  "alternatives": [
    {
      "id": "linux-alt-id",
      "name": "Recommended Linux App",
      "tagline": "Short, neutral description of this Linux option",
      "recommended": true,
      "type": "app",
      "packages": {
        "flatpak": "org.example.AppId",
        "apt": "example-pkg",
        "dnf": "example-pkg",
        "pacman": "example-pkg"
      }
    }
  ]
}
```

### Rules for Package Safety & Legal Neutrality
- Prefer official **Flathub** IDs (`flatpak`) and official distro packages (`apt`, `dnf`, `pacman`, `zypper`).
- Never suggest unverified third-party PPAs or `curl | bash` installers — use `"official_url": "https://..."` for vendor download pages instead.
- Keep all descriptions neutral, factual, and strictly in English — avoid disparaging vendors, avoid implying vendor endorsement for community-maintained Flatpaks, and never suggest bypassing DRM, licensing, or anti-cheat protections.
- Always run the automated test suite before opening a PR:
  ```bash
  python -m unittest discover -s tests -v
  ```
