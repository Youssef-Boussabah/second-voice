# 05: Guardrails that adapt per relationship

This is the part that's new, so it has to be **visible, deterministic, and measurable**.

## 1. Enforcement (Lane A, `guard/enforce.py`): pure function, no LLM
```
apply_guard(candidates, person, active_boundaries) -> (allowed, blocked)
```
1. **Safety-net tagging.** For each candidate, `tag_topics_safety_net(text, topics)` adds topics the LLM missed using keyword/regex lists:
   - `medication`: drug-name list (riluzole, edaravone, baclofen, gabapentin, morphine, …), "meds", "pills", "prescription", "dose"
   - `health`: "tired", "pain", "doctor", "hospital", "diagnos", "symptom", "ALS", "breathing", "feeding tube", "wheelchair"
   - `finances`: `\$\d`, "rent", "bills", "money", "afford", "loan"
   - `location_schedule`: "home alone", "away until", "address", "key under"
   - `death_dying`, `distress`, `family_conflict`, `romance`: small keyword sets
2. **Applicable rules** for this person: all `active` boundaries where
   `scope.type == "global"` **or** (`scope.type == "relationship"` and `scope.value == person.relationship`) **or** (`scope.type == "person"` and `scope.value == person.id`).
   Unknown speaker → treat as relationship `stranger`.
3. A candidate is **blocked** if `set(candidate.topics) ∩ set(rule.topics)` is non-empty for any applicable rule with `action == "block"`. Record `blocked_by = rule.id`.
4. Return the first 4 allowed (preserve LLM rank) and all blocked.
5. The generator prompt **also** receives the applicable rules ("Do not suggest replies about: health, medication"), but that's only for efficiency. Correctness comes from step 3.

## 2. Seed policy (Lane D seeds; status `active`, origin `seed`)
| Scope | Topics blocked |
|---|---|
| relationship = `stranger` | all sensitive topics |
| relationship = `service` | health, finances, family_conflict, romance, location_schedule, death_dying |

**`acquaintance` deliberately has NO seed rule.** The demo shows it being learned live.

## 3. Learning (Lane D, `learning/boundaries.py`)
Triggered by a `suggestion_rejected` event with `reason == "too_personal"`.

```
propose_and_validate(evt):
  sens = evt.topics ∩ SENSITIVE_TOPICS
  if not sens: return None                      # e.g. rejected small talk as "too personal": no rule
  if an active rule already covers (relationship, sens): return None

  # 1. propose at the broadest reasonable scope
  candidate = Boundary(scope={relationship: evt.relationship}, topics=sens, status="proposed",
                       origin="learned", evidence={trigger_event_id, rejected_text, person_id})

  # 2. REPLAY: would this rule have blocked anything the user actually said?
  history = events where user_id = evt.user_id
                     and type in {suggestion_selected, suggestion_edited, reply_typed}
                     and relationship = evt.relationship
  conflicts = [h for h in history if set(h.topics) ∩ sens]
  candidate.validation = {replayed: len(history), conflicts: len(conflicts), ...}

  if conflicts == 0:
      activate(candidate)                        # status active → change stream → toast
  else:
      # 3. narrow to just this person and re-replay
      narrow = same rule with scope={person: evt.person_id}
      conflicts_p = [h in conflicts if h.person_id == evt.person_id]
      if conflicts_p == 0: activate(narrow, narrowed_from="relationship")
      else: save candidate as "proposed" → WS boundary.proposed
            → UI: "You've told Mike about health before (Oct 28: '…'). Keep it private from now on?"
            → confirm / dismiss endpoints
  return candidate
```
Topics on history events come from the chosen candidate's `topics` (after the safety net). For `reply_typed`, the worker tags topics with the same safety-net function plus a quick LLM tag.

**Why the replay matters (say this on stage):** "It won't learn a rule that would have silenced something you actually chose to say. Every rule is tested against your own history before it turns on."

## 4. UI requirements (Lane C)
- **Long-press** (or ⋯ button) on a card opens reasons: **Too personal** · Not how I talk · Wrong facts.
- Toast on `boundary.activated`: **"Learned: keep *health, medication* private with *acquaintances*. Checked against 23 past replies, no conflicts."**
- Under the cards: "🔒 2 suggestions hidden by your boundaries" (tap to see which rule hid them; read-only).
- Confirm dialog on `boundary.proposed` (two big buttons).
- P1: Boundaries panel listing rules with a Retire button.

## 5. Demo proof points
1. Mike (acquaintance) → a health suggestion appears → reject "too personal" → toast.
2. Mike again → health suggestions are gone, and "🔒 1 hidden" shows.
3. Dana (clinician) → medication suggestions still appear. **The scope is per relationship, not a blanket ban.**
