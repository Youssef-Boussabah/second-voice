# 06: Evaluation: cold vs warm (Lane D)

Goal: one honest scoreboard that proves memory and learned boundaries help. **Freeze the test set before anyone tunes prompts.**

## Dataset: `seed/conversations/*.json`
8 scripted conversations, 3 recurring people. Five are `train` (c01–c05), three are `test` (c06–c08). Each person appears in both splits.

```json
{
  "id": "c03", "split": "train", "person_id": "per_mike", "date": "2026-11-02",
  "turns": [
    {"speaker":"partner","text":"Hey Maya! Haven't seen you in a while, how've you been?"},
    {"speaker":"user","intended":"Hanging in there! How's the new dog?","topics":["small_talk","hobbies"]},
    {"speaker":"partner","text":"He chewed my boots. Anything new with you?"},
    {"speaker":"user","intended":"Ha! Same old. Watching a lot of Leafs games.","topics":["small_talk","hobbies"]}
  ]
}
```
Plus `seed/privacy_truth.json`: the *hidden* ground truth of what Maya considers too personal per relationship. The simulated user uses it to reject; the system never reads it.
```json
{"acquaintance":["health","medication","finances","distress","death_dying"],
 "family":["finances"], "clinician":[], "service":["health","finances"]}
```
Write the scripts so the test conversations reuse things learned in train (Sam's hockey, Dana's blister-pack thread, Maya's "bud").

## Simulated user (for train and test runs)
For each partner turn: call the pipeline (in-process `on_partner_utterance` with forced `person_id`, or `POST /api/utterances/text`), take the **final** `SuggestionSet`, then:
1. For every shown candidate whose topics hit `privacy_truth[relationship]` → **leak += 1**, and (train only) post a `reject(too_personal)` event.
2. **Hit test:** a candidate *matches* the intended reply if `cosine(embed(candidate), embed(intended)) ≥ 0.80` **or** an LLM judge says "same meaning, Maya would send this as-is". Record which method.
3. If hit → `select` (1 tap). Else → `reply_typed` with `intended`.
4. Learning events flow through the real worker (run it during train). Wait for the worker to drain before moving on.

## Metrics
| Metric | Definition |
|---|---|
| **hit@4** | % of user turns where an intended-equivalent reply was among the 4 shown |
| **taps / message** | 1 if hit; else `ceil(len(intended_chars) × 0.5)` (assumes a predictive keyboard halves keystrokes; state this assumption on the slide) |
| **privacy leaks / conversation** | shown candidates that violate `privacy_truth` |
| **latency p50 / p95** | utterance → final suggestions |
| **rules learned** | count of active `learned` boundaries, and whether any was a false positive (blocked a test-set intended reply) |

## Protocol
1. `cold`: reset DB → seed people + seed boundaries only (no memories) → run **test** c06–c08 → record.
2. `warm`: reset DB → seed → run **train** c01–c05 with learning on → session_end after each (episodes written) → run **test** c06–c08 → record.
3. Same model, same prompts, same temperature (0.3), same seed order. Run each config **twice** and report the mean, so it's not one lucky draw.
4. Save to `eval_runs`; `GET /api/eval/scoreboard` returns both configs plus the delta.

## Scoreboard (what the UI shows)
```
                 Cold      Warm
hit@4            38%  →    71%
taps / message   9.4  →    2.1
leaks / conv     1.7  →    0.0
p50 latency      2.4s      2.6s
```
(These numbers are illustrative. Show whatever you actually measure. If warm loses on something, say so. Honesty wins judges.)

## Time-boxing
The eval must produce a first real scoreboard by **3:30 PM**, even if crude. Improve after that.
