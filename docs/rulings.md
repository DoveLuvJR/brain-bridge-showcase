# Rulings log

Every decision below was mine to make. The AI agents proposed options with trade-offs; I chose, and the choice was written down before code was built on it. Dates are when the ruling was made. Project and client names are replaced with generic labels.

| # | Date | Ruling | Why |
|---|---|---|---|
| 1 | Before the build | **Stop the bleeding first:** raise the AI tool's session retention from 30 days to 10 years. | The tool was silently deleting session history after 30 days. My main project had 6 sessions left. Nothing else matters if the source keeps vanishing. |
| 2 | 2026-10-21 | **Run the pipe locally on the OS scheduler with plain Python,** not a hosted AI session. | Cheapest option, always on while the PC is on, and no AI cost per run. |
| 3 | 2026-10-21 | **AI-written summaries are deferred** to a later phase. Phase 1 has none. | Get search and briefings working with zero API cost first. Summaries are polish, not the core. |
| 4 | 2026-10-21 | **Cloud sessions read a separate, small, private digest repo,** not a folder inside another repo and not the whole notes vault. | The smallest exposure. Opening the whole vault was the biggest exposure, and it was stale anyway. |
| 5 | 2026-10-21 | **Phase order:** connectors, search and auto-briefing first; the cloud bridge and write-back second; summaries and alerts third. Folders are listed in a config file, not hard-coded. I run every git command. | Ship the part that helps local work first, and keep the human in charge of what leaves the machine. |
| 6 | 2026-10-21 | **Hard exclusions live in code, not in settings.** | Editing a config file must never be able to switch off a privacy rule. |
| 7 | 2026-10-21 | **First protected-folder rule:** drop any session turn that names the protected folder, plus the next 3 turns. I accepted the residual risk. | It kept more useful history. The reviewer had offered whole-session quarantine; I chose the looser rule and logged the risk. |
| 8 | 2026-10-21 (same day) | **Reversed #7: chose whole-session quarantine over the 3-turn window.** One mention anywhere in a session (typed, in a reply, in a tool call or tool output, or as the working folder) keeps the WHOLE session out of the index, permanently and retroactively. | A turn ten minutes later can quote the same people without naming the folder. A window is a guess about how far a conversation drifts; a session boundary is a fact. When the data is other people's, the rule has to fail closed, and privacy wins over recall. Result: 48 sessions quarantined. The recruiting project's searchable session turns dropped from 96 to 5, and its handoff and decision notes were untouched. |
| 9 | 2026-10-21 | **Briefings are framed as background facts, never instructions.** Every briefing opens with a framing line. | A review found a handoff note containing destructive server commands that landed verbatim at the start of every session. A model could read it as an order. |
| 10 | 2026-10-21 | **One scoped auto-push exception.** The hourly task may commit and push the digest repo's `main` by itself. Every other repo keeps "the AI commits, I push." It never force-pushes, commits only digest files by name, pushes nothing when its audit fails, and uses the existing credential manager with no token in any file. | Cloud sessions need fresh context every hour, and I can't push by hand hourly. The exception is written into the digest's own README so it can't quietly grow. The push path was ruled Tier 1 (full ceremony): a push can't be quietly taken back. |
| 11 | 2026-10-21 | **Write-back through an inbox, never direct edits.** Sessions drop dated notes in their repo's `brain-inbox/`. The pipe indexes them and lists them in one weekly review file, and it never edits a note I wrote. Filing happens only after my yes. | Cloud sessions are untrusted writers. A review step keeps the vault mine. |
| 12 | 2026-10-21 | **A second reader** (a phone assistant that can't see the PC) reads the same digest through a `START-HERE` page kept under 150 lines. | One source of truth with two readers, not two systems. |
| 13 | 2026-10-22 | **The protected-folder check matches the folder's name, not the client's name.** | The client's name isn't third parties' personal data. The people's data stays out by the folder rules. |
| 14 | 2026-10-22 | **Every project gets the inbox convention,** and any project the bridge was missing gets added. | One project's notes lived outside the usual projects folder. Fixing it took a small code change (folder-to-project mapping lines), so the batch moved up from Tier 3 to Tier 2. Tiers can go up, never quietly down. |
| 15 | 2026-10-22 | **Dropped an alias** that pulled an unrelated repo's stale warnings into a project's briefing, and gave that repo its own briefing file instead. | Fix the cause, not the symptom. |

## How a ruling is made

1. The AI lays out 2–4 options with what each costs and risks, and marks a recommendation.
2. I pick one. The ruling, the date and the reason go into the design doc before code depends on it.
3. If a later finding shows the ruling was wrong (#7 → #8), it is reversed in writing, not quietly patched.
