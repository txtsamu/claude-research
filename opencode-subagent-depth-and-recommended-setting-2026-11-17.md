---
type: investigation
tags: [opencode, subagents, subagent-depth, config, experimental, github-issues, agent-orchestration]
created: 2026-11-17
last_verified: 2026-11-17
status: current
---

# OpenCode subagent_depth: what the default means and what the internet recommends (2026-11-17)

Request, in three steps: "how many subagent my current opencode can spawn", then "check on internet what is the recommended setting for it", then "update docs to claude-research". Working directory was `/home/moo/diskos/diskos` (`main`, `15797a0`), but the subject is the global OpenCode install, not that repo. No diskOS code was touched.

## The setting only limits depth, not count

The global config at `~/.config/opencode/opencode.json` line 22 has:

```json
"experimental": { "subagent_depth": 2 }
```

OpenCode v2.3.0 reads it in the subagent tool as `subagent_depth ?? 1`, then walks the caller's parent chain and refuses the spawn when the number of ancestors is greater than or equal to the limit. With the default of 1, only the primary session can start a subagent. With 2, the primary and its direct children can start one, so the deepest chain is main -> subagent -> subagent. A depth-2 subagent cannot delegate further.

There is no count cap anywhere. The published schema exposes only `subagent_depth` under `experimental` for this area, and the spawn path has no semaphore, queue, or per-parent child limit. Parallel fan-out is bounded only by provider rate limits, context budget, and local resources. PR [#63227](https://github.com/anomalyco/opencode/pull/63227) proposes `experimental.subagent_concurrency` and `experimental.subagent_over_limit` (`fail` or `wait`), but it is still open and unmerged as of 2026-11-17. A second PR, [#55983](https://github.com/anomalyco/opencode/pull/55983), adds the same key, so maintainers have not picked one.

## What the internet says

**Official docs** (config page, "Subagent depth") document the semantics and the default, but recommend no value:

> `subagent_depth` sets how deeply subagents can start their own subagents. Defaults to `1`, so a subagent cannot start another subagent.

The `"subagent_depth": 2` in the experimental example block is illustrative, not advice.

**Maintainers** answered the "please allow nesting" requests in [#59826](https://github.com/anomalyco/opencode/issues/59826) and [#50539](https://github.com/anomalyco/opencode/issues/50539). The bot's answer in #59826 is the clearest statement found:

> "The default of `1` is intentional." ... "`2` allows main -> subagent -> subagent; use higher values for deeper chains."

It also called `2` "the supported way to allow nesting". A maintainer closed #50539 with the same guidance: raise the setting above 1 if you want nested subagents.

**Third-party guides** converge on 2:

- `shahboura.github.io/agents-opencode/customization.html`: "This requires `subagent_depth` of at least 2 in your `opencode.json`; the default of 1 lets only top-level agents spawn subagents."
- A write-up of the v1.18.2 change (10100.com) says existing users need no config change and users who want nesting explicitly set `subagent_depth: 2`.
- In #59826 the reporter used `3` to fix a main -> coder -> explore chain, but the bot's explanation implies `2` was enough. That was headroom, not a requirement.

## Known rough edges above depth 1

The low default is defensive. Recursive delegation multiplies token spend, and several open issues document bugs that only appear when nesting is enabled:

- [#53356](https://github.com/anomalyco/opencode/issues/53356): the `subagent` tool stays advertised at the maximum depth, so a child tries to delegate and gets "Subagent depth limit reached".
- [#58489](https://github.com/anomalyco/opencode/issues/58489): the Desktop running-subagents indicator does not show nested subagents when `subagent_depth > 1`.
- [#49342](https://github.com/anomalyco/opencode/issues/49342): questions from depth-2 subagents were dropped by the same non-root bail-out as permission requests.
- [#60961](https://github.com/anomalyco/opencode/issues/60961): the built-in `general` agent's own `subagent` deny makes `experimental.subagent_depth` ineffective for it.
- [#60410](https://github.com/anomalyco/opencode/issues/60410): a project-level `experimental` block hides every global experimental option, because those fields are not merged per key.
- [#2906](https://github.com/anomalyco/opencode/issues/2906): an older report about runaway subagent spawning, the failure mode a depth cap is meant to contain.

## Practical recommendation

| Value | Effect | When |
| --- | --- | --- |
| 1 (default) | Only the primary session delegates | Most users. Keep this unless nesting is actually used. |
| 2 | main -> subagent -> subagent | Orchestrator or specialist patterns that delegate one level down. This is the value maintainers point to, and what this machine runs. |
| 3+ | Deeper chains | Rare, deliberate multi-tier hierarchies only. Cost and failure surface grow quickly. |

For this machine, `2` is defensible but not required. It should be dropped to 1 if no workflow depends on a child launching another child. `experimental` settings can change or be removed without notice, so treat this as current behavior, not a contract.

## Verification

```bash
opencode --version
grep -n 'subagent_depth' ~/.config/opencode/opencode.json
curl -s https://opencode.ai/config.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['properties']['experimental']['properties']['subagent_depth'])"
curl -sL https://opencode.ai/docs/config/ | sed 's/<[^>]*>/ /g' | tr -s ' \n' ' ' | grep -o 'subagent_depth sets[^.]*\. Defaults to [0-9][^.]*\.'
```

Observed output:

```
opencode v2.3.0
22:    "subagent_depth": 2
{'type': 'integer', 'minimum': 0, 'maximum': 9007199254740991}
subagent_depth sets how deeply subagents can start their own subagents. Defaults to 1 , so a subagent cannot start another subagent.
```

The binary agrees with the docs. A string scan of `/home/moo/.opencode/bin/opencode` shows the guard and its error text: `if(R>=z) return ... "Subagent depth limit reached (${z}). Increase \"experimental.subagent_depth\" to allow nested subagents."`.

## Gotchas

- The `websearch` tool failed three times with "Unable to search the web" through the configured camofox provider. Results above came from direct `webfetch` calls to DuckDuckGo HTML and GitHub, so the discovery path was search-engine HTML rather than the built-in provider.
- GitHub search for `subagent_depth` returns 38 results, many closed. Always check a PR's merge state before treating a proposed key as available.
- Do not quote the whole `~/.config/opencode/opencode.json` in notes or tickets. It contains a plugin access key.
- The built-in `general` and `explore` agents are the only subagents on this machine today; there is no `~/.config/opencode/agents/` directory.

## Not verified

- I did not empirically spawn a depth-2 chain and watch it fail at depth 3. The depth semantics come from the bundled code, the docs, and maintainer statements, which agree with each other.
- The concurrency PR state is as of 2026-11-17. It may merge later and add `subagent_concurrency`, which would change the "unlimited count" answer.
- The known-issue list above is a sample from search results, not an exhaustive audit of the tracker.

## Related

- [[diskos-lastfm-removal-terminal-cursor-and-subagent-worktrees]]
- [[diskos-session-and-play-admission-modules-parallel-agents]]
- [[diskos-six-module-deepening-parallel-agents-merge-charging-fixes]]
