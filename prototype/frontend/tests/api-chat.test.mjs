import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const compiled = ts.transpileModule(readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

function client(fetch) {
  const context = { exports: {}, fetch };
  vm.runInNewContext(compiled, context);
  return context.exports.api;
}

test("chat and draft send only catalogue references for selected cards", async () => {
  const calls = [];
  const api = client(async (path, init) => {
    calls.push({ path, body: JSON.parse(init.body), signal: init.signal });
    return { ok: true, json: async () => ({}) };
  });
  const need = { code: "QUIET_WAIT", scope: "full", label_en: "Quiet waiting area", reason: "Suggested only" };
  const messages = [{ role: "user", content: "A quieter place would help" }];
  const signal = new AbortController().signal;
  await api.chat("CX/DEMO", { messages, selected: [need], dismissed: [], lang: "en" }, signal);
  await api.chatDraft("CX/DEMO", [need], ["OTHER"], signal);
  assert.equal(calls[0].path, "/api/passenger/CX%2FDEMO/chat");
  assert.deepEqual(calls[0].body.selected, [{ code: "QUIET_WAIT", scope: "full" }]);
  assert.deepEqual(calls[0].body.messages, messages);
  assert.deepEqual(calls[1].body, { needs: [{ code: "QUIET_WAIT", scope: "full" }], referrals: ["OTHER"] });
  assert.equal(calls[1].signal, signal);
});

test("a failed chat rejects so the UI can retain the reply and selections", async () => {
  const api = client(async () => ({ ok: false, status: 503, json: async () => ({ detail: { code: "unreachable" } }) }));
  await assert.rejects(api.chat("CXDEMO1", { messages: [], selected: [], dismissed: [], lang: "en" }),
    (error) => error.status === 503);
});

test("completion sends the full conversation and only selected catalogue references", async () => {
  const calls = [];
  const api = client(async (path, init) => {
    calls.push({ path, body: JSON.parse(init.body), signal: init.signal });
    return { ok: true, json: async () => ({ portals: [] }) };
  });
  const messages = [{ role: "user", content: "Quiet spaces please" }, { role: "assistant", content: "Noted" }];
  const signal = new AbortController().signal;
  await api.completeChat("CX/DEMO", messages, [{ code: "QUIET_WAIT", scope: "full", reason: "Private" }], signal);
  assert.equal(calls[0].path, "/api/passenger/CX%2FDEMO/chat/complete");
  assert.deepEqual(calls[0].body, { messages, selected: [{ code: "QUIET_WAIT", scope: "full" }] });
  assert.equal(calls[0].signal, signal);
});
