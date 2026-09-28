# Before opening an issue

Two minutes here can save a round trip.

## Reporting a bug

Use the [bug report template](bug_report.en.yml), not a blank issue.

For a cleaner, **the criterion matters more than the symptom.** So the template asks for:

- **The full path** involved — this is what makes it reproducible; don't redact it
- **Which kind** — missed / false positive / deletion failed / UI / crash
- **The relevant config** — only the `settings.yaml` keys that matter
- **A criteria check** — confirm this is a detection problem, not your own `exclude_*` misconfiguration

**For UI stutter or flicker, attach a screen recording.** "It flickers" can't be diagnosed from
words.

## Requesting a category

Use the [feature request template](feature_request.en.yml).

The most important field is **criteria**. Please give conditions that can be verified automatically
rather than "it looks like junk".

| Request | Response |
|---|---|
| Delete `node_modules` | We'll ask for a criterion. It may hold something you're mid-build on, and reinstalling is a chore anyway. |
| Delete a repo when **all** of these hold: no remote + 60 days idle + `git status --porcelain` empty | This is the criterion the project itself uses. |

**This isn't timidity — it's the biggest risk in the project.** Deleting an active project as "junk"
costs far more than leaving a few hundred MB. Two existing decisions in the
[decision log](../../CHANGELOG.en.md) came from exactly this: an earlier `InstallLocation` check
produced a pile of false positives (WeChat and the VS Installer still had their `Uninstall.exe`),
and Git repos were switched from "deletable in one click" to read-only because nothing reliably
separates a throwaway clone from real work.

## Known limitations (not bugs)

Listed in the README under [Known limitations](../../README.en.md#known-limitations), all deliberate:

- Registry cleaning barely frees space (15 KB total here) — the value is clearing dead references
- Empty files/dirs free no space either — the value is tidiness
- Git repos have no bulk delete — the criteria can't guarantee safety
- UI text is hardcoded Chinese
- The empty-file scan walks everything, roughly half the total scan time

## Contributing code

See [CONTRIBUTING.en.md](../../CONTRIBUTING.en.md). The one rule that matters most: **changing a
cleanup criterion requires a test in the same change.**

## Questions

Prefer a Discussion, or just ask an AI assistant. This project is a small tool written with AI
assistance; I can't promise prompt replies.
