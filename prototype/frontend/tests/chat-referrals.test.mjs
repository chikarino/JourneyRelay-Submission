import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const compiled = ts.transpileModule(readFileSync(new URL("../lib/useAssistanceChat.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

// A synchronous hook-state harness exercises actual send/review transitions.
// Lifecycle effects are intentionally out of scope; each render gets fresh closures.
function harness(api) {
  const slots = [];
  let cursor = 0;
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], (value) => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index];
    },
    useEffect() {},
  };
  const context = { exports: {}, AbortController, require: (name) => {
    if (name === "react") return react;
    if (name === "./api") return { api };
    throw new Error(`Unexpected dependency: ${name}`);
  } };
  vm.runInNewContext(compiled, context);
  return () => { cursor = 0; return context.exports.useAssistanceChat("CXDEMO1"); };
}

const answer = (referrals) => ({ message: "Consider these options.", question: "", quick_replies: [],
  recommendations: [], referrals: referrals.map((code) => ({ code })), recheck_selected: [] });

test("withdrawn referrals are removed from the hook state and subsequent draft payload", async () => {
  const replies = [answer(["MEDICAL", "SERVICE_ANIMAL"]), answer(["SERVICE_ANIMAL"]), answer([])];
  const drafts = [];
  const render = harness({ chat: async () => replies.shift(), chatDraft: async (_pnr, _needs, codes) => {
    drafts.push(Array.from(codes)); return {};
  } });
  let chat = render();
  chat.choose({ code: "CS_CALLBACK", scope: "full" });
  chat = render();
  await chat.send("en", "Oxygen equipment and a service dog.");
  chat = render();
  await chat.send("en", "No equipment now, but the dog is still coming.");
  chat = render();
  assert.deepEqual(Array.from(chat.referrals, (r) => r.code), ["SERVICE_ANIMAL"]);
  await chat.review(() => {});
  assert.deepEqual(drafts[0], ["SERVICE_ANIMAL"]);
  chat = render();
  await chat.send("en", "The dog is no longer coming either.");
  chat = render();
  assert.equal(chat.referrals.length, 0);
  // Removing referral advice must not silently remove an explicitly chosen callback.
  assert.equal(chat.selected[0].code, "CS_CALLBACK");
  await chat.review(() => {});
  assert.deepEqual(drafts[1], []);
});

test("failed turns keep referral advice and unrelated turns retain current topics", async () => {
  let fail = false;
  const render = harness({ chat: async () => {
    if (fail) throw new Error("offline");
    return answer(["MEDICAL"]);
  } });
  let chat = render();
  await chat.send("en", "I need oxygen equipment.");
  chat = render();
  await chat.send("en", "I also need written updates.");
  chat = render();
  assert.equal(chat.referrals[0].code, "MEDICAL");
  fail = true;
  await chat.send("en", "No equipment after all.");
  chat = render();
  assert.equal(chat.referrals[0].code, "MEDICAL");
  assert.equal(chat.error, true);
});

test("a chat-only passenger can finish, retain links after confirmation, and start fresh", async () => {
  const calls = [];
  const render = harness({ chat: async () => answer([]), completeChat: async (_pnr, messages, selected) => {
    calls.push({ messages, selected });
    return { portals: [{ id: "hkg-sensory" }] };
  } });
  let chat = render();
  await chat.send("en", "Quiet spaces, no assistance request.");
  chat = render();
  await chat.finish();
  chat = render();
  assert.equal(chat.completed, true);
  assert.equal(chat.portals[0].id, "hkg-sensory");
  assert.equal(calls[0].messages.length, 2);
  assert.equal(calls[0].selected.length, 0);
  chat.reset(true);
  chat = render();
  assert.equal(chat.messages.length, 0);
  assert.equal(chat.portals.length, 1);
  chat.reset();
  chat = render();
  assert.equal(chat.portals, null);
});

test("completion failure preserves selections and retry succeeds without drafting", async () => {
  let fail = true;
  const render = harness({ completeChat: async () => {
    if (fail) throw new Error("offline");
    return { portals: [] };
  } });
  let chat = render();
  chat.choose({ code: "QUIET_WAIT", scope: "full" });
  chat = render();
  await chat.finish();
  chat = render();
  assert.equal(chat.error, true);
  assert.equal(chat.completed, false);
  assert.equal(chat.selected.length, 1);
  fail = false;
  await chat.finish();
  chat = render();
  assert.equal(chat.error, false);
  assert.equal(chat.completed, true);
  assert.equal(chat.portals.length, 0);
  chat.continueChat();
  chat = render();
  assert.equal(chat.portals, null);
  assert.equal(chat.completed, false);
  assert.equal(chat.selected.length, 1);
});

test("closing completion cancels late results and allows another attempt", async () => {
  let resolve;
  const render = harness({ completeChat: () => new Promise((done) => { resolve = done; }) });
  let chat = render();
  chat.choose({ code: "QUIET_WAIT", scope: "full" });
  chat = render();
  const pending = chat.finish();
  chat = render();
  chat.cancel();
  resolve({ portals: [{ id: "stale" }] });
  await pending;
  chat = render();
  assert.equal(chat.portals, null);
  assert.equal(chat.completed, false);
  assert.equal(chat.busy, false);
});

test("other-issue choices ask for a description locally without repeating an AI turn", async () => {
  for (const choice of ["其他問題", "有其他問題", "其他情況", "Something else"]) {
    let calls = 0;
    const render = harness({ chat: async () => { calls++; throw new Error("Must not call AI for a form choice"); } });
    let chat = render();
    chat.choose({ code: "QUIET_WAIT", scope: "full" });
    chat = render();
    await chat.send("zh", choice);
    chat = render();
    assert.equal(calls, 0);
    assert.equal(chat.messages.length, 2);
    assert.equal(chat.messages[0].content, choice);
    assert.match(chat.messages[1].content, /描述/);
    assert.equal(chat.selected[0].code, "QUIET_WAIT");
    assert.equal(chat.reply, null);
    assert.equal(chat.error, false);
    assert.equal(chat.input, "");
  }
});

test("the actual description after an other-issue choice reaches AI with alternating full history", async () => {
  const payloads = [];
  const render = harness({ chat: async (_pnr, body) => {
    payloads.push(body);
    return answer(["MEDICAL"]);
  } });
  let chat = render();
  await chat.send("en", "I need oxygen equipment.");
  chat = render();
  await chat.send("en", "Something else");
  chat = render();
  assert.equal(chat.referrals[0].code, "MEDICAL");
  assert.equal(chat.reply, null);
  await chat.send("en", "My other issue is needing written updates.");
  assert.equal(payloads.length, 2);
  assert.deepEqual(Array.from(payloads[1].messages, (m) => m.role), ["user", "assistant", "user", "assistant", "user"]);
  assert.equal(payloads[1].messages[4].content, "My other issue is needing written updates.");
});

test("returning from a resumed draft preserves its selection without last-trip seeding", async () => {
  const drafts = [];
  const render = harness({ chatDraft: async (_pnr, needs, codes) => {
    drafts.push({ needs: Array.from(needs, (n) => n.code), referrals: Array.from(codes) });
    return {};
  } });
  let chat = render();
  assert.equal(chat.seeded, false);
  chat.restoreDraft({ needs: [{ code: "SEAT_ADJACENT", scope: "full" }], referrals: [{ code: "OTHER" }] });
  chat = render();
  assert.equal(chat.seeded, true);
  assert.deepEqual(Array.from(chat.selected, (n) => n.code), ["SEAT_ADJACENT"]);
  await chat.review(() => {});
  assert.deepEqual(drafts, [{ needs: ["SEAT_ADJACENT"], referrals: ["OTHER"] }]);

  // Removing every need must also survive returning from the preview.
  chat.restoreDraft({ needs: [], referrals: [] });
  chat = render();
  assert.equal(chat.seeded, true);
  assert.equal(chat.selected.length, 0);
  assert.equal(chat.referrals.length, 0);

  // Starting a new conversation still allows reuse of last-trip needs.
  chat.reset();
  chat = render();
  assert.equal(chat.seeded, false);
  chat.seed([{ code: "QUIET_WAIT", scope: "full" }]);
  chat = render();
  assert.equal(chat.seeded, true);
  assert.equal(chat.selected[0].code, "QUIET_WAIT");
});

test("removed last-trip needs can be offered again, explicitly reselected and drafted", async () => {
  const quiet = { code: "QUIET_WAIT", scope: "full" };
  const seat = { code: "SEAT_ADJACENT", scope: "full" };
  const payloads = [];
  const drafts = [];
  const render = harness({
    chat: async (_pnr, body) => {
      payloads.push(body);
      return { ...answer([]), recommendations: [seat] };
    },
    chatDraft: async (_pnr, needs) => { drafts.push(Array.from(needs, (n) => n.code)); return {}; },
  });
  let chat = render();
  chat.seed([quiet, seat]);
  chat = render();
  chat.remove(quiet);
  chat.remove(seat);
  chat = render();
  await chat.send("zh", "與照顧者坐在一起");
  chat = render();
  assert.deepEqual(Array.from(payloads[0].dismissed), ["QUIET_WAIT:full", "SEAT_ADJACENT:full"]);
  assert.equal(chat.selected.length, 0); // A new recommendation must not select itself.
  assert.equal(chat.reply.recommendations[0].code, "SEAT_ADJACENT");
  chat.choose(chat.reply.recommendations[0]);
  chat = render();
  assert.deepEqual(Array.from(chat.dismissed), ["QUIET_WAIT:full"]);
  await chat.review(() => {});
  assert.deepEqual(drafts, [["SEAT_ADJACENT"]]);
});
