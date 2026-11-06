## Overall (invalid runs, where the provider failed on every attempt, are excluded)

| agent | runs | pass rate (95% CI) | median wall s | mean tool calls | mean tokens in | mean tokens out | errors | invalid | runs needing a retry |
|---|---|---|---|---|---|---|---|---|---|
| evonic | 47 | 47/47 = 100% (92-100%) | 24.8 | 7.9 | 42697 | 1504 | 0 | 1 | 13 |
| hermes | 48 | 48/48 = 100% (93-100%) | 36.4 | 5.2 | 26702 | 759 | 0 | 0 | 7 |

## By category (pass rate, median wall s)

| category | evonic | hermes |
|---|---|---|
| authoring | 12/12 (17s) | 12/12 (33s) |
| coding | 12/12 (38s) | 12/12 (39s) |
| recovery | 11/11 (26s) | 12/12 (40s) |
| tool_use | 12/12 (19s) | 12/12 (35s) |

## By task (passes / reps)

| task | evonic | hermes |
|---|---|---|
| A1_create_files | 3/3 | 3/3 |
| A2_count_grep | 3/3 | 3/3 |
| A3_csv_to_json | 3/3 | 3/3 |
| A4_organize_by_ext | 3/3 | 3/3 |
| B1_implement_slugify | 3/3 | 3/3 |
| B2_fix_bug | 3/3 | 3/3 |
| B3_write_cli | 3/3 | 3/3 |
| B4_refactor_dedupe | 3/3 | 3/3 |
| C1_broken_script | 3/3 | 3/3 |
| C2_bad_config | 3/3 | 3/3 |
| C3_readonly_file | 3/3 | 3/3 |
| C4_find_the_config | 2/2 | 3/3 |
| E1_postmortem | 3/3 | 3/3 |
| E2_changelog | 3/3 | 3/3 |
| E3_extract_entities | 3/3 | 3/3 |
| E4_constrained_summary | 3/3 | 3/3 |

Tasks won: evonic=0, hermes=0, tied=16. Sign test over differing tasks: p=1.000 (n=0).

## Failures (first detail per task/agent)

