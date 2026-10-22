# Governance

The bridge reads everything I've written with AI for months: notes, decisions and full session transcripts. That makes it the most sensitive thing I run. The governance is built on one idea: **every rule is a guard in code, and every guard has a test that turns red when the guard is switched off.**

## The rules, in plain English

| Rule | What it means |
|---|---|
| **Read-only pipe** | The pipe never changes a source. It may write exactly two generated files into the vault (`CURRENT.md` and the inbox review), and a single write function refuses every other path. |
| **Human approval gates** | I run every git command except one scoped exception (below). Inbox notes are filed only after my yes. Every design question is a written ruling ([rulings.md](rulings.md)). |
| **Privacy quarantine** | A protected folder holds third parties' personal data. Its files are never read. Any AI session that names it, anywhere, is quarantined whole, forever, retroactively. Anything shown to a reader is dropped if it, or a section within 3 of it, mentions the folder. |
| **Secret-stripper** | Whole files and whole turns are stripped before they are cut into records, then each record again. `[REDACTED:<kind>]` marks each hit. |
| **The audit blocks the push** | After every run, every stored record is re-scanned. The digest is audited again as files on disk, twice: staged, then in the repo. Any non-zero count means ALERT, and nothing is published. |
| **A single scoped auto-push** | Only the digest repo may be pushed by automation: only `push origin main`, only digest files by name, never force, never with credentials in the URL, nothing when an audit fails. Every other repo: the AI commits, I push. |
| **Loud when quiet** | A run that checked nothing looks exactly like a clean run. Missing folders, empty connectors and an exclusion that never fired are ALERTs, not OKs. |
| **Notes are facts, not orders** | Every briefing and digest file opens with a framing line, so a model never treats an old note as an instruction. |

## Every guard, what it protects, how it's tested

Reproduce this table yourself: `python tools/guard_check.py`. It switches each guard off in a throwaway copy of the code, runs all 61 tests, and counts the reds. It fails if any guard turns nothing red.

| Area | Guard | Protects against | Test(s) | Red when off |
|---|---|---|---|---|
| Index | Secret-stripper | Pasted keys stored in the index | `SecretStripper.*`, `Index.test_secrets_never_stored` | 11 |
| Index | Strip the whole file before cutting it | A key split across two records escaping every pattern | `test_secret_split_across_records_is_still_stripped` | 1 |
| Index | Hard exclusions | The protected folder, `.env*`, `.ssh`, `secrets*` being read | `test_protected_folder_is_never_read`, `Exclusions.*` | 5 |
| Index | Exclusions ignore case and trailing dots | `Protected-People.` slipping past on Windows | `test_case_slashes_and_trailing_dots` | 1 |
| Index | Session quarantine: every line checked | A session that read protected files (in a tool call or tool output) being indexed | `test_session_naming_protected_folder_is_quarantined_whole` | 5 |
| Index | Session quarantine: retroactive | Turns stored by an earlier run surviving a later mention | `test_quarantine_is_retroactive` | 2 |
| Index | Session quarantine: permanent | A rewritten session file coming back in | `test_quarantine_is_permanent` | 1 |
| Index | Re-judge every session on a rule change | Sessions indexed under an older, looser rule staying in | `test_rule_change_rescans_every_session` | 1 |
| Index | Transcripts kept after the source deletes them | Losing history when the AI tool deletes old sessions | `test_transcripts_survive_deletion_of_their_source` | 1 |
| Index | Removed notes pruned | Deleted notes lingering in search | `test_removed_markdown_is_pruned` | 1 |
| Index | Recency boost | Stale records outranking fresh ones | `test_newer_wins_over_a_slightly_better_old_match` | 1 |
| Audit | Secret-shaped records | Anything the stripper missed, found after the fact | `test_audit_catches_a_planted_secret` | 1 |
| Audit | Records from excluded paths | An exclusion bug that let a file in | `test_audit_catches_excluded_paths` | 1 |
| Audit | Records from quarantined sessions | A quarantine bug that let a session in | `test_audit_catches_records_from_a_quarantined_session` | 1 |
| Health | Empty connector is an ALERT | A silent "OK" when nothing was read | `test_a_quiet_run_is_an_alert` | 1 |
| Health | Missing source folder is an ALERT | A moved folder silently dropping out | `test_a_missing_source_folder_is_an_alert` | 1 |
| Health | Exclusion never fired is an ALERT | A broken exclusion going unnoticed | `test_an_exclusion_that_never_fires_is_an_alert` | 1 |
| Briefing | No transcript text | Raw conversation reaching every new session | `Briefing.test_no_transcript_text` | 1 |
| Briefing | Neighbouring sections hidden | A nearby section quoting the same people | `test_protected_folder_and_its_neighbours_are_hidden` | 1 |
| Briefing | Index opened read-only | The briefing changing the index | `test_index_is_opened_read_only` | 1 |
| Briefing | An error prints nothing | A crash dumping a traceback into a session | `test_an_error_prints_nothing_and_exits_0` | 1 |
| Briefing | Deadline | A locked index stalling a session start | `test_a_slow_index_prints_nothing_within_the_deadline` | 1 |
| Briefing | 40-line cap | A briefing flooding the context window | `test_line_cap` | 1 |
| Briefing | Framing line | Old notes read as instructions | `test_framing_line_and_footer` | 1 |
| Digest | Source gate | Transcript text reaching the cloud copy | `test_source_gate_blanks_transcript_text` | 7 |
| Digest | Page filter | Protected or excluded-path lines in a published file | `test_page_drops_protected_and_excluded_lines` | 1 |
| Digest | Nothing published after a failed index audit | Publishing from a bad index | `test_a_failed_index_audit_publishes_nothing` | 1 |
| Digest | Audit the staged files | A poisoned build reaching the output | `test_a_poisoned_build_never_reaches_the_output` | 1 |
| Digest | Audit the output copy again | A stray file in the repo being published | `test_a_stray_file_in_the_output_blocks_publishing` | 1 |
| Digest | Audit checks: secrets, protected folder, unexpected files, framing, 200 KB, START-HERE < 150 lines, transcript leak | Each failure mode on disk | `AuditOnDisk.*` | 1–2 each (7 guards) |
| Git | No force / add-all flags | A force-push rewriting history | `test_force_and_add_all_are_refused` | 1 |
| Git | Only `push origin main` | Pushing anywhere else | `test_the_only_push_is_push_origin_main` | 1 |
| Git | Exactly one fetch and one push URL | A second, hidden push target | `test_a_second_url_is_refused` | 1 |
| Git | No credentials in the URL | A token stored in config | `test_credentials_in_the_url_are_refused` | 1 |
| Git | Origin must be the configured remote | Pushing the digest to the wrong repo | `test_any_other_remote_is_refused` | 1 |
| Git | Branch must be main | Publishing from a side branch | `test_a_branch_other_than_main_is_refused` | 1 |
| Git | Nothing but digest files committed | Another file riding along in the commit | `test_nothing_but_digest_files_may_be_committed` | 1 |
| Inbox | Header project must be a real project | A hostile `project: ../../x` header becoming a path | `test_a_hostile_header_project_is_refused` | 1 |
| Inbox | No path from odd text | Path traversal via the project name | same test | 1 |
| Inbox | Header values secret-stripped | A key pasted into a note header | `test_header_values_are_secret_stripped` | 1 |
| Inbox | Protected notes withheld | A note about protected people shown in a review | `test_notes_naming_the_protected_folder_are_withheld` | 1 |
| Inbox | Filed detection | Filed notes nagging forever | `test_a_note_is_filed_once_its_text_is_in_the_target` | 1 |
| Inbox | Short notes never count as filed | A note of "ok" vanishing unfiled | `test_a_short_note_never_counts_as_filed` | 1 |
| Inbox | Vault write guard | Any bug becoming an edit of a note I wrote | `test_only_the_two_generated_files_may_be_written` | 1 |

**50 of 50 guards turn at least one test red** (last run on this repo). In the real deployment, 83 guard switch-offs across five batches each turned at least one test red.

## Adversarial reviews (real deployment)

After four of the five batches were built and tested, a fresh-context AI reviewer got **the code only**, with no builder notes and no conclusions to confirm, and was told to break it. It was a separate agent I launched, not a human or third-party audit. Every HIGH finding was fixed before the batch shipped. The rest were fixed or logged with a written reason.

| Batch | HIGH | MED | LOW | Fixed | Logged with a reason |
|---|---|---|---|---|---|
| Connectors, index, auto-briefing | 6 | 4 | 2 | 11 | 1 |
| Session-start briefing hook | 1 | 4 | 5 | 5 (1 partial) | 5 |
| Digest, auto-push, inbox | 2 | 5 | 6 | 12 | 1 |
| Coverage extension | 0 | 3 | 4 | 5 | 2 |
| **Total** | **9** | **16** | **17** | **33 of 42** | **9** |

Examples of what the reviewers caught:
- **HIGH:** the protected-folder check missed most mentions. Fixed: every line of a session is scanned, tool calls and tool output included.
- **HIGH:** a secret split across two records escaped every pattern. Fixed: strip before chunking.
- **HIGH:** a run that checked nothing reported OK. Fixed: health ALERTs.
- **HIGH:** an untrusted inbox header like `//host/share` became a path, so the PC would open a network connection every hour. Fixed: the project must name a real project, and path characters are refused.
- **MED:** on Windows, a git timeout never fires while a credential helper holds the pipes, so the hourly run could hang silently. Fixed: output goes to temp files, and a timeout kills the whole process tree.

## Known limits (stated, not hidden)

- The audit uses the stripper's own patterns, so a secret shape no pattern knows passes both. The answer is to extend the patterns, which re-strips everything stored.
- Memory notes written during a protected session aren't filtered by the session rule. They are curated one-fact notes, so the risk is low, but it isn't zero.
- If the digest audit fails on the repo copy, the changed files are already in the working folder. They are never committed, and the next run overwrites them.
