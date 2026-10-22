# One guard, end to end: whole-session quarantine

I don't write the code. My job is to make sure that what the agents build does what I ruled. This page shows how I check that for one guard: the rule, the questions behind it, the code, the tests, and the proof that the tests matter.

## The rule (ruling 8)

> If any line of an AI session names the protected folder, none of that session's turns are ever indexed. That holds for anything stored earlier, forever, and whatever the session file does later.

The protected folder holds third parties' personal data. A session that opened it may quote those people in a later turn without naming the folder again, so the only safe unit is the whole session.

## The questions behind it

Each question came from a ruling or a review finding, and each became a test. These are the questions I ask of any privacy guard:

| Question | Answer in this repo | Test |
|---|---|---|
| What if the folder only appears in a **tool's output**, not in anything typed? | Every line is checked before anything is parsed, tool output included. | `test_session_naming_protected_folder_is_quarantined_whole` |
| What about the turns **before** the mention? | They're dropped too. In the test fixture, the first turn never names the folder and is still kept out. | same test |
| What if an **earlier run already stored** some turns? | They're deleted when the mention appears. | `test_quarantine_is_retroactive` |
| What if the file is later **rewritten without** the mention? | The session ID is on a permanent list, so it never comes back. | `test_quarantine_is_permanent` |
| What if we **tighten the rule** later? | Changing the rule's version re-judges every session from the start. | `test_rule_change_rescans_every_session` |
| What if all of the above **fails silently**? | The audit after each run counts records from quarantined sessions. Anything above 0 is an ALERT. | `test_audit_catches_records_from_a_quarantined_session` |

## The code

The check runs on raw bytes, line by line, before any line is understood (`brainbridge/connectors.py`):

```python
for line in data[:end].splitlines(keepends=True):
    start, pos = pos, pos + len(line)
    if line_names_protected(line):
        return [], offset + end, True, None
```

When it fires, the session goes on the permanent list and anything stored from it is deleted:

```python
if protected:
    ctx.store.quarantine(sid)
    ctx.store.delete_records(path)  # including turns an earlier run stored
```

And every later run checks the list first, whatever the file now says:

```python
if ctx.store.is_quarantined(sid):
    ctx.store.delete_records(path)  # out forever, whatever the file does now
    return "quarantined"
```

## Proof the tests matter

A test that passes whether or not the guard works proves nothing. `tools/guard_check.py` switches each part off in a throwaway copy and runs every test:

| Part switched off | Tests that go red |
|---|---|
| The line check | 5 |
| The retroactive delete | 2 |
| The permanent list | 1 |
| The re-judge on a rule change | 1 |
| The audit count | 1 |

## What this caught

When I first ran the switch-off check on this repo, **switching off the permanent list turned nothing red.** The test rewrote the session file without the mention and expected nothing to come back. But the code didn't handle a rewritten, shorter file at all: it read from the old position, found nothing, and passed by accident.

The fix was in the code, not the test. A rewritten session is now read again from the top, as the real deployment does, and a new test covers that case. With that in place, switching off the permanent list turns the test red, as it should. The script now fails outright if any guard turns nothing red, so a guard can't quietly become decoration again.

## Known limit

Memory notes written during a protected session aren't covered by this rule. They are short, curated notes, so the risk is low, but it isn't zero. It's listed in [governance.md](governance.md).
