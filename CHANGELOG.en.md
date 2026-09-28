# Changelog

All notable changes to DevCleaner are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

**Note: while pre-1.0, a bump in the minor position signals a breaking change.**

## [Unreleased]

### Planned

- Scan only the categories you pick (currently it walks everything)
- Export scan results to a report file
- UI text i18n (currently hardcoded Chinese)

---

## [0.1.0] — 2026-09-28

First public release. Measured on Windows 11, 24 volumes.

### Added · detection

| Category | How it decides | Measured here |
|---|---|---|
| Installers of already-installed software | Strips version/platform/role suffixes off the filename, then confirms "installed" via **three signals: running process, install directory, uninstall registry** | 6 items / 1.51 GB |
| Traditional junk files | Thumbnail cache, jump lists, browser caches, shader caches, crash dumps, Windows Update cache | 5 items / 51.6 MB |
| Stale temp files | Untouched for N days; marked caution if a running exe lives in that directory | 0 items |
| GitHub leftovers | gh CLI / GitHub Desktop / Copilot caches; local clones with no remote | 0 items |
| AI agent / skill caches | Packages absent from `opencode.jsonc`'s `plugin` array; the stale copy when both `X` and `X@latest` exist | 1 item / 79.6 MB |
| Updater leftovers | `*@*-updater\pending\*`, `*\updates\executors\*`, … | 1 item / 87.2 MB |
| Build artifacts / dev junk | `build/` next to a `*.spec`; `__pycache__`, `.pytest_cache`, `.ruff_cache`, … | 6 items / 248 MB |
| Python envs & caches | `.venv` (only with `pyvenv.cfg`), pip cache, plus anything added in config | 5 items / 182 MB |
| Registry | Uninstall/startup entries whose uninstall command points at a missing exe; safely-resettable MRU keys | 1 item / 466 entries |
| Empty files / empty dirs / broken links | 0-byte items, automatically skipping `.gitkeep` / `*.lock` / `desktop.ini` / `Thumbs.db` | 1 item / 4369 entries |

**Total: 2.22 GB reclaimable.**

### Added · interface

- Native PySide6 window — no browser, no WebView, no console
- 6 palettes (Studio Dark/Light, Ink, Paper, Rosé Pine, Tokyo Night), switched live and written back to config
- Categories collapsed by default; all 10 fit on one screen. "Expand all / collapse all"
- Registry and empty-file items display an **entry count**, not bytes
- Scans automatically on launch; indeterminate progress bar + throttled stage label
- Startup scan time cut from 42.5 s to 5.9 s (cache `resolve()` in `excluded()`)

### Safety

- File deletion via `SHFileOperationW` + `FOF_ALLOWUNDO` — **Recycle Bin, restorable**
- Registry writes a `.reg` backup first; **if the export fails it refuses to delete**
- `.reg` files are generated in-process, not via `reg.exe export` (the latter fails with "invalid syntax" on paths containing spaces)
- Broken links removed with `os.rmdir`/`os.unlink` on the link itself
- Files/directories in use are detected and skipped
- Caution items are never pre-checked
- Git repos with a remote never enter the deletable list
- "Dead program" means only "the exe in the uninstall command is missing"

### Known limitations

- Deleting keys under `HKLM` needs administrator rights; an unelevated run reports "insufficient permission" (expected)
- Registry scanning is limited to 10 MRU keys under `HKCU` plus three `Uninstall`/`Run` branches. It deliberately never walks `HKCR\CLSID` — a mistake there can make Windows unable to install programs
- The empty-file/dir scan walks everything, about half the total scan time
- Git repos in the read-only list have no bulk delete
- UI text is hardcoded Chinese

### Decision log

These were settled after hitting the problems. Read this before changing any of them.

**"Dead program" means only "the exe in the uninstall command is missing."**
An earlier version also required `InstallLocation` to be missing, and that **produced a pile of false positives** — WeChat and the Visual Studio Installer both still had their `Uninstall.exe`; only `InstallLocation` pointed at an old path. Deleting a live program's uninstall entry means you can never uninstall it again.

**Git repos are read-only by default.**
Nothing reliably distinguishes a throwaway clone from an active project. A repo only becomes deletable when all three hold: no remote, untouched for 60+ days, and no uncommitted changes.

**Fresh files in Windows Temp aren't scanned.**
Temp here is 770 MB, but *all* of it is under 7 days old, and 121 MB of that is a PyInstaller unpack directory for a program that is currently running. An age filter reclaims ~nothing here and risks deleting live temp files.

**Prefetch is left alone.**
Deleting it makes the next boot slower. Net negative.

**Selected rows use QPalette, not `setObjectName` + `unpolish`/`polish`.**
The latter re-resolves the entire stylesheet; auto-selecting 27 rows is 27 full re-resolutions back to back, the main thread locks up, and it reads as a full-window flash.

**"Text on accent" is computed per WCAG, not hand-copied.**
It reproduces the design's choice for 4 of 6 themes. The deviation is **Ink**: the mockup used white text (3.3:1), but 13px bold needs 4.5:1 for AA, so the background colour is used (5.3:1).

**Config writes are line-by-line, not a full `yaml.dump`.**
A full dump destroys the user's comments.

**`build.bat` is pure ASCII.**
cmd reads `.bat` in the OEM codepage, and CJK plus `&` gets mis-parsed into a command that doesn't exist.

**Console output is forced to UTF-8.**
GitHub Actions runners use cp1252 and Chinese machines use GBK; neither can encode the Chinese category names. This only surfaced in CI — see the second commit.

### Tests

36 self-checks via `python test_app.py`. Notably:

- Headless UI construction, all 6 themes switched in turn
- Full registry round trip: create key → back up → delete → `reg import` → verify data matches
- Multi-level subkeys must be fully removed
- "Valid uninstall command + stale InstallLocation" must **not** be reported
- Bulk empty-file deletion really deletes, and `.gitkeep` survives
- Repos with a remote never enter the deletable list
- Palette matches the design file character for character; 7 contrast pairs per theme meet WCAG AA
- Selected-row colouring never uses `unpolish`/`polish`
- Categories collapsed by default; expand button works via real click
- Config edits preserve comments
- Internal protocol strings (`REG:` / `BULK:`) never reach the UI
- Version matches CHANGELOG and READMEs; 20 required OSS files present; no placeholders left
- All local image references resolve
- Survives a non-UTF-8 console
- Leaves no temp directories behind

[Unreleased]: https://github.com/matou1118/DevCleaner/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/matou1118/DevCleaner/releases/tag/v0.1.0
