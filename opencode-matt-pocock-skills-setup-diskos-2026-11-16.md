---
type: how-to
tags: [opencode, skills, matt-pocock, diskos, github-issues, triage, glossary, adr, fork]
created: 2026-11-16
last_verified: 2026-11-16
status: current
---

# Matt Pocock skill setup in the diskOS fork (2026-11-16)

Repo `/home/moo/diskos/diskos`, branch `main`, commit `027c24b`. The release tag `v1.2.1-fork.5` stays at `ade7ee1`; the setup commit is after it. Related: [[diskos-shuffle-index-loop-fix-2026-11-16]], [[diskos-standards-review-25-commits-adrs-and-ui-naming-2026-11-12]].

## Request

`@setup-matt-pocock-skills` to scaffold the issue tracker, triage labels and domain docs for this repo.

## What exploration found

- Three GitHub remotes: `origin` is `txtsamu/diskos` (the fork), `upstream` is `b0hemia/diskOS`, `disco` is a separate project.
- `gh repo view` inside the clone resolves to **`b0hemia/diskOS`**, not the fork. This is the fork trap: an unpinned `gh issue create` would file upstream.
- GitHub Issues was **disabled** on `txtsamu/diskos` (`hasIssuesEnabled: false`) even though the account has admin.
- `gh` is 2.87.3, below 2.94, so native sub-issues and `--blocked-by` are unavailable.
- `CLAUDE.md` exists at the root; no root `AGENTS.md`. The repo also has `agents/AGENTS.md` as an internal rules file.
- `GLOSSARY.md` and `docs/adr/` (0001 working-mode switches, 0002 USB Debug) exist. No `GLOSSARY-MAP.md`, `CONTEXT.md`, `docs/agents/` or `.scratch/`.
- No monorepo signals (`package.json`, `pnpm-workspace.yaml`, `packages/*` all absent), so single-context.
- The `triage` skill is installed.

## Decisions

- Issue tracker: GitHub `txtsamu/diskos`, the fork. Every command passes `-R txtsamu/diskos`.
- Triage labels: the five defaults, unchanged.
- Domain docs: single-context, `GLOSSARY.md` plus `docs/adr/`.

## What was written

- `gh api -X PATCH repos/txtsamu/diskos -F has_issues=true` enabled Issues. Verified with `gh repo view txtsamu/diskos --json hasIssuesEnabled` -> `true`.
- `CLAUDE.md`: added the `## Agent skills` block with the issue tracker, triage labels and domain docs pointers.
- `docs/agents/issue-tracker.md`: GitHub tracker pinned to the fork, the `-R` rule, and the older-`gh` `api` fallbacks for sub-issues and blocking.
- `docs/agents/triage-labels.md`: five roles mapped to the same strings.
- `docs/agents/domain.md`: single-context layout, glossary vocabulary and ADR conflict rules.
- Labels created in `txtsamu/diskos`: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`. `wontfix` already existed and was not recreated.
- Commit `027c24b` ("Agent skills: pin GitHub issues to the fork, add triage labels and domain docs"), pushed to `origin/main` and `origin/dev`.

## Verification

```text
gh repo view txtsamu/diskos --json nameWithOwner,hasIssuesEnabled
{"hasIssuesEnabled":true,"nameWithOwner":"txtsamu/diskos"}

gh label list -R txtsamu/diskos --json name
accessibility bug documentation duplicate enhancement "good first issue"
"help wanted" invalid needs-info needs-triage question ready-for-agent
ready-for-human wontfix
```

`git status` was clean after the commit. The release tag `v1.2.1-fork.5` still points at `ade7ee1`, so the release assets are unchanged.

## Gotchas

- **Never rely on `gh repo view` inside this clone.** It resolves to `b0hemia/diskOS` because of the `upstream` remote. Use `-R txtsamu/diskos` for every issue, label and writing API call.
- GitHub Issues was off. Labels and issues cannot exist until it is on. The one-call fix needs admin, which the account has.
- `gh` 2.87.3 lacks `--parent` and `--blocked-by`. `docs/agents/issue-tracker.md` uses `gh api` and the `Blocked by:` body fallback.
- The repo's internal `agents/AGENTS.md` is separate from the new `docs/agents/` consumed by the Matt Pocock skills. Do not merge them.

## Not verified

- No issue was created, edited or closed through the new conventions.
- No Matt Pocock skill has been run since the setup to confirm it reads `docs/agents/*.md`.
- The `wayfinder` labels (`wayfinder:map`, `wayfinder:*`) were not created; they are only needed when `/wayfinder` is used.
