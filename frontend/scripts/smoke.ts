// Lane C smoke test: drives the mock backend through the demo flow (Dana → Mike too-personal → Mike → Dana).
import { mockApi as api, mockConnect } from "../src/mock/mockBackend";
import type { SuggestionSet, WSMessage } from "../src/contracts";
import { newId } from "../src/contracts";

const msgs: WSMessage[] = [];
const fail = (m: string) => { console.error("FAIL:", m); process.exit(1); };
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function finalFor(sessionId: string, text: string, person: string): Promise<SuggestionSet> {
  const before = msgs.length;
  await api.postText({ session_id: sessionId, text, person_id: person });
  await wait(1400);
  const fin = msgs.slice(before).filter((m) => m.type === "suggestions.ready").map((m) => m.data as SuggestionSet).find((s) => s.stage === "final");
  if (!fin) fail(`no final suggestions for "${text}"`);
  if (fin!.candidates.length !== 4) fail(`expected 4 cards, got ${fin!.candidates.length}`);
  return fin!;
}
const has = (s: SuggestionSet, re: RegExp) => s.candidates.some((c) => re.test(c.text));

const s = await api.createSession({ person_id: "per_dana" });
mockConnect(s._id, { onMessage: (m) => msgs.push(m), onStatus: () => undefined, onReconnect: () => undefined });

const dana = await finalFor(s._id, "Hi Maya! Here for your refill?", "per_dana");
if (!has(dana, /blister/)) fail("Dana should get blister-pack reply");
const sel = await api.select(dana._id, { candidate_id: dana.candidates[1].id, event_id: newId("evt") });
if (sel.text_to_speak !== dana.candidates[1].text) fail("select text mismatch");
if (await api.tts(sel.text_to_speak) !== null) fail("mock tts should fall back to browser");

const mike = await finalFor(s._id, "Hey Maya! How've you been?", "per_mike");
const meds = mike.candidates.find((c) => /meds/.test(c.text)) ?? fail("Mike should see meds card pre-rule");
await api.reject(mike._id, { candidate_id: meds.id, reason: "too_personal", event_id: newId("evt") });
await wait(900);
const act = msgs.find((m) => m.type === "boundary.activated") ?? fail("no boundary.activated");
if (act.type === "boundary.activated" && act.data.scope.value !== "acquaintance") fail("rule should scope to acquaintance");

const mike2 = await finalFor(s._id, "Anything new?", "per_mike");
if (mike2.candidates.some((c) => c.topics.includes("health") || c.topics.includes("medication"))) fail("health leaked to Mike");
if (mike2.blocked.length === 0) fail("expected hidden-by-boundary candidates");

const dana2 = await finalFor(s._id, "Any side effects with the new generic?", "per_dana");
if (!dana2.candidates.some((c) => c.topics.includes("medication"))) fail("Dana should still get medication replies");

console.log(`PASS: ${msgs.length} WS msgs; Mike hidden=${mike2.blocked.length}; Dana meds kept`);
process.exit(0);
