# Usage Guide

The README covers *what it is and what it cleans*. This covers **how to use it well**.

- [First run](#first-run)
- [The interface](#the-interface)
- [Every config key](#every-config-key)
- [Command line](#command-line)
- [Adding a scanner](#adding-a-scanner)
- [Troubleshooting](#troubleshooting)
- [Design trade-offs](#design-trade-offs)

---

## First run

![Overview](01-overview.png)

1. Download `DevCleaner.exe` and double-click it. **It scans on its own**, taking about 20–30 s
2. Don't delete anything yet. **Expand each category and check the criteria make sense** — this is the
   only part that deserves your time
3. Read-only lists (🔒 icon) never appear in the deletable set. They exist so you can see the *size*
4. Check what you want, then hit "移入回收站". **Everything goes to the Recycle Bin, restorable**

⚠️ For the first run, confirm the results look right before making it a habit.

### If you want to be more cautious

Change every `risk: safe` to `risk: caution` in `settings.yaml`. Then nothing is pre-checked and you
confirm every single item. Restart to apply.

---

## The interface

### Top bar

| Element | Meaning |
|---|---|
| 安全可清 | Byte total of all `safe` items. **Pre-checked** |
| 需确认 | Byte total of all `caution` items. **Not pre-checked** |
| 合计 | Sum of both |
| 主题 | 6 palettes, switch live; the choice is written to `settings.yaml` |

### Toolbar

| Button | Effect |
|---|---|
| 重新扫描 | Re-run the scan. Hit it after cleaning to find more |
| 全部展开 / 全部折叠 | See all 10 categories at once, or open everything up |

During a scan the progress bar is a **marquee** (indeterminate), not a percentage — the categories
take wildly different amounts of time, so a percentage would sit frozen on one number and mislead you.
The label to its right shows which category is being scanned.

### Category cards

Header row, left to right: icon, category name, `N items · M safe`, reclaimable size, `▸/▾`.

**Click the header to expand/collapse.** Everything is collapsed by default — all 10 categories fit on
one screen, so you don't have to scroll down through the list.

Once expanded:

- `全选本组` / `清空本组` affect only that group
- Each row has a checkbox on the left, size and risk badge (🟢 safe / 🟡 needs confirmation) on the right
- Four lines of text per row: name, path, the deciding signal, and why it's safe to delete

### Read-only lists (🔒)

`全局 npm 包` and `Git 仓库` **never offer a delete button**. They're there so you know how big the
thing is, and can decide whether to handle it yourself.

### Footer

`已选 N items · size + entry count`. The `+ 462 entries` part means 462 of the selected items are
counted by entry rather than by bytes (registry and empty-file items are 0 bytes).

### The confirmation dialog

![Confirm](03-confirm.png)

The dialog will:

- List the first 40 items with **name + size + full path**
- Call out every "needs confirmation" item by name
- If registry items are included, **print the backup directory and the restore command**
- Warn about the item count for bulk deletions

That's the last gate. Read it before clicking.

---

## Every config key

`settings.yaml` sits next to the exe; a bundled copy is used if none is found there. **Restart to
apply — no rebuild.**

```yaml
theme: "Ink"
```

Written automatically when you pick a theme in the UI.

```yaml
scan_roots:
  - "%USERPROFILE%"
```

**Roots that need recursive walking.** Only affects three scanners: `.venv`, Git repos, and
build artifacts / empty files.

Adding drives makes it noticeably slower — 4 roots here take about 25 s, and the empty-file scan alone
is 11 s of that (it must walk everything).

```yaml
exclude_dirs:
  - "C:/Windows"
exclude_globs:
  - "**/node_modules/**"
```

Allow-list. A hit is skipped entirely, not even counted.

System directories are excluded by default (`C:/Windows`, `C:/Program Files`, `C:/Program Files (x86)`).
**Don't exclude other dev directories** — that would skew the results.

```yaml
installer_roots: []
```

Where to look for installers. **Empty = auto-detect Downloads + Desktop** via the Windows known
folders API, which correctly resolves redirection (lots of people move Documents to another drive;
hardcoding `%USERPROFILE%\Downloads` misses it in that case).

```yaml
min_installer_age_days: 14
temp_min_age_days: 7
stale_clone_days: 60
```

Three age thresholds, each with a different scope:

| Key | Governs |
|---|---|
| `min_installer_age_days` | Only **unconfirmed** installers. Confirmed-installed ones count as safe regardless of age |
| `temp_min_age_days` | Stale temp files. Directories with a running exe in them get flagged as caution |
| `stale_clone_days` | Local clones with no remote |

Lowering `min_installer_age_days` lets freshly downloaded installers show up — but if the install
hasn't run yet, deleting it wastes the download.

```yaml
installed_aliases:
  OfficeAce: ["OfficeClaw"]
```

Fallbacks when the product name doesn't match. Typical case: the installer is
`OfficeAce-1.1.4-setup.exe` but the program installs to `%LOCALAPPDATA%\OfficeClaw`.

The pipeline: strip version/platform/role suffixes → look for the product name among process names and
install directories → then check this table and the uninstall registry. All three must agree before
it's called "installed".

```yaml
custom_cache:
  - name: "pip download cache"
    path: "%LOCALAPPDATA%/pip/Cache"
    risk: safe
    note: "Wheel cache; re-downloads if needed."
```

**Dropping any directory in here is a complete rule — zero code.** This is the extension point you'll
use most.

- `name` — display name
- `path` — supports `%VAR%`; both `/` and `\` work
- `risk` — `safe` (pre-checked) or `caution` (not pre-checked, needs confirmation)
- `note` — shown on the "why this is safe" line

```yaml
extra_junk: []
```

Extra traditional-junk directories. Same shape as the first three fields of `custom_cache`.

```yaml
agent_configs:
  - path: "%USERPROFILE%/.config/opencode/opencode.jsonc"
agent_cache_root: "%USERPROFILE%/.cache/opencode/packages"
```

Configuration for the AI-agent cache scanner. The `plugin` array is read out of the files in
`agent_configs`, and only cached packages **absent from that list** are reported as unused.

`.jsonc` works too (line comments are stripped).

```yaml
scan_options:
  max_recursion_depth: 10
  min_size_bytes: 2097152
```

- `max_recursion_depth` — recursion cap. Lower is faster, at the cost of missing deep paths
- `min_size_bytes` — items below this aren't shown. **Registry and empty-file items are counted by
  entry and aren't affected by it**

---

## Command line

`app.py` has no UI. Useful for scripting.

```bash
python app.py --version          # DevCleaner 0.1.0
python app.py --help

python app.py                     # scan and print
python app.py --json              # JSON output
python app.py -c "registry"       # one category only
python app.py -c "junk" --min-age 3   # override the age threshold for this run
```

`-c` is a case-insensitive substring match. With no match it lists every available category and exits
with code 2.

`--json` shape:

```json
{
  "version": "0.1.0",
  "log": ["已安装软件的安装包: 6 items · 0.0s", "..."],
  "items": [
    {"name": "...", "category": "...", "path": "...",
     "size": 707788800, "unit": "bytes", "risk": "safe"}
  ],
  "notes": [{"name": "...", "kind": "global npm package", "path": "...", "size": 537133056}]
}
```

When `unit` is `count`, `size` is an **entry count**, not bytes.

The GUI also accepts `--version` / `--help`.

---

## Adding a scanner

```python
class MyScanner(Scanner):
    category, icon = "My category", "\U0001f9f0"

    def scan(self) -> List[Item]:
        return [mk(self.category, Path("C:/some/cache"), "display name", "safe",
                   meta="last modified 2026-09-28", note="why it's safe")]
```

Append it to `SCANNERS`; the UI grows a collapsible group automatically with **no UI code**.

Two requirements:

1. **Be honest about `risk`.** If you're unsure, use `caution`
2. **Set `unit="count"` for zero-byte categories** (registry, entry counts) so the UI shows counts
   instead of pretending with bytes

**But the more important rule: changing a criterion requires a test.** See [CONTRIBUTING](CONTRIBUTING.md).

---

## Troubleshooting

### The scan is very slow

The bulk of it is "empty files / empty dirs / broken links" — it has to walk everything. 11 s of the
25 s here.

To go faster:

```yaml
scan_roots:            # drop roots you don't care about
  - "D:/projects"      # instead of all of %USERPROFILE%
scan_options:
  max_recursion_depth: 6
```

Or set `empty_scan_dirs: false` to check empty files but not empty directories.

### An installer wasn't recognised

Its "deciding signal" line will read `N days ago · installation not confirmed` and it lands under
needs-confirmation. Usually no "installed" evidence was found.

Check in order:

1. Was the product name derived correctly? `FooSetup-1.2.3-x64.exe` → `Foo`
2. Is the program actually installed? Does it show in Installed apps?
3. Did it install somewhere non-standard? Add an `installed_aliases` entry

### "In use by another process"

Expected. Usage is checked before deleting, so open executables, DLLs and held handles are skipped.
Close the program or reboot, then scan again.

### "Insufficient permission"

Administrator rights needed. System-level uninstall entries and the `Run` branch under `HKLM` are
in this category.

If you'd rather not elevate, just **don't tick those items** — they already sit under needs-confirmation.

### Where are the registry backups, and how do I restore them?

Location: `%LOCALAPPDATA%\DevCleaner\registry_backups\<timestamp>_<type>\`

```powershell
# list all backups
Get-ChildItem "$env:LOCALAPPDATA\DevCleaner\registry_backups"

# restore one
reg import "$env:LOCALAPPDATA\DevCleaner\registry_backups\20260928_164512_MRU\MRU.reg"
```

Double-clicking the `.reg` also works (regedit will ask you to confirm).

### I changed the theme and nothing happened

The name must match exactly and is case-sensitive. An unknown name falls back to `Ink`.

Valid values: `Studio Dark` `Studio Light` `Paper` `Ink` `Rosé Pine` `Tokyo Night`

### Chinese text renders as boxes

The system is missing `Microsoft YaHei UI`. It should fall back automatically, but some stripped
Windows builds don't. Install a CJK font.

### The packaged exe starts slowly

PyInstaller onefile re-extracts to `%TEMP%` on every launch, at roughly 1.5 MB/s. If that bothers you,
build with `--onedir` instead (copy the whole `dist\DevCleaner\` folder) — you trade "single file" for
startup speed.

### It can't find my `Downloads` folder

On this machine `C:\Users\Administrator\Downloads` doesn't exist because Documents is redirected to
D:. The tool tries, in order: the known-folders API → `Downloads` under the resolved Documents
directory → `%USERPROFILE%\Downloads`. You can also give an absolute path in `installer_roots`.

---

## Design trade-offs

These were settled after hitting the problems. Read the [decision log in the CHANGELOG](CHANGELOG.md)
before changing any of them.

| Decision | Why |
|---|---|
| "Dead program" means only "the exe in the uninstall command is missing" | It also required `InstallLocation` to be missing, which **produced a pile of false positives** — WeChat and the VS Installer still had their `Uninstall.exe`; only `InstallLocation` was stale. Deleting a live program's uninstall entry means you can never uninstall it again |
| Git repos are read-only by default | Nothing reliably distinguishes a throwaway clone from an active project |
| Fresh Temp files aren't scanned | All 770 MB here is under 7 days old, and 121 MB of that is a running program's PyInstaller unpack directory. An age filter reclaims nothing |
| Prefetch is left alone | Deleting it makes the next boot slower. Net negative |
| `HKCR\CLSID` is never walked | A mistake there can make Windows unable to install programs |
| Registry deletes back up first; a failed export aborts the delete | Deleting anyway would void the "recoverable" guarantee |
| Selected rows use QPalette, not `setObjectName`+`unpolish` | The latter re-resolves the whole stylesheet; auto-selecting 27 rows is 27 full re-resolutions back to back, and the window flashes |
| Config writes are line-by-line, not `yaml.dump` | A full dump destroys the user's comments |
| `build.bat` is pure ASCII | cmd reads `.bat` in the OEM codepage, and CJK plus `&` gets mis-parsed |
