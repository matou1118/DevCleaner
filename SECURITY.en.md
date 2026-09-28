# Security Policy (English)

## Supported versions

| Version | Reports accepted |
|---|---|
| 0.1.x | ✅ |

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's [private vulnerability reporting](https://github.com/OWNER/DevCleaner/security/advisories/new) (Security → Report a vulnerability).

I'll confirm receipt within 48 hours and give a remediation timeline after assessing it.

## Attack surface

It operates on your machine **with your current user's permissions**. It does not elevate by default;
deleting keys under `HKLM` reports "insufficient permission".

It does **not**:

- Touch the network. No telemetry, no auto-update, no crash reporting
- Read file *contents*. Scanning only looks at **paths, filenames, sizes, modification times**
- Execute anything it deletes
- Modify PATH, registry defaults, or the firewall

## Known trust boundaries

Highest risk first:

### 1. A wrong criterion causes a wrong deletion

**This is the project's biggest risk.** One scanner mistaking an active project for junk costs you
source code.

Current defences:

- File deletion uses `SHFileOperationW` + `FOF_ALLOWUNDO` → **Recycle Bin, restorable**
- "Caution" items are never pre-checked
- The confirmation dialog lists the first 40 items plus a total count
- Git repos are read-only; three conditions must all hold before one becomes deletable
- Before deleting, it re-checks that the file is still there and still in use

**Residual risk**: if you check a "caution" item and confirm, its source goes to the Recycle Bin.

### 2. Registry modification

- A `.reg` backup is **always** exported first, and **if the export fails it refuses to delete**
- Backups land in `%LOCALAPPDATA%\DevCleaner\registry_backups\`
- Only 10 MRU keys under `HKCU` plus three `Uninstall`/`Run` branches are touched. It deliberately
  does **not** walk `HKCR\CLSID` — a mistake there can make Windows unable to install programs

### 3. Broken-link deletion

Uses `os.rmdir`/`os.unlink` on the link itself and **does not recurse** — the target of a broken link
no longer exists, and recursing could hit an unrelated thing with the same name.

### 4. TOCTOU

There's a gap between scanning and cleaning. State that changes in between (a program installed or
removed, a file now in use) can lead to the wrong deletion. The defence is re-checking existence and
in-use status immediately before deleting.

## Safer usage

- **First run: don't hit "移入回收站" yet.** Expand each category and check the criteria make sense
- Keep a copy of your `settings.yaml`
- Before emptying the Recycle Bin, review what was recently deleted
- Don't rush to delete the registry backup directory
- If your important projects are backed up in Git, the risk is low to begin with

## Disclosure

Report privately as described above. Once fixed, I'll note it in [CHANGELOG](CHANGELOG.md) —
**including what was a false positive**. Lessons from criteria bugs are worth more than the fix itself.
