"use client";

import { useEffect, useRef, useState } from "react";
import { api, ChatMessage, ChatReply, Draft, Need, Referral, TravelPortal } from "./api";
import { Lang } from "./i18n";

export const needKey = (n: Pick<Need, "code" | "scope">) => `${n.code}:${n.scope}`;

const DESCRIPTION_CHOICES = new Set([
  "其他問題", "有其他問題", "其他情況", "其他需要", "有其他需要", "其他說明",
  "唔係以上任何一種", "以上都不是", "以上都唔係", "以上皆非",
  "somethingelse", "noneoftheabove", "other", "anotherissue",
]);
export const isDescriptionChoice = (text: string) =>
  DESCRIPTION_CHOICES.has(text.toLowerCase().replace(/[\s。.!！？?，,、]/g, ""));

// This is the form's "other" path, like the initial greeting, not an AI failure fallback.
const DESCRIPTION_PROMPT: Record<Lang, string> = {
  zh: "請直接描述您遇到的情況，或希望得到甚麼協助；不需要從剛才的選項中選擇。",
  en: "Please describe the situation or the help you need in your own words. You do not have to choose one of the previous options.",
};

export function useAssistanceChat(pnr: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [reply, setReply] = useState<ChatReply | null>(null);
  const [selected, setSelected] = useState<Need[]>([]);
  const [dismissed, setDismissed] = useState<string[]>([]);
  const [referrals, setReferrals] = useState<Referral[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [portals, setPortals] = useState<TravelPortal[] | null>(null);
  const [completed, setCompleted] = useState(false);
  // Pre-select the previous trip once for each conversation.
  const [seeded, setSeeded] = useState(false);
  const controller = useRef<AbortController | null>(null);

  function cancel() {
    controller.current?.abort();
    controller.current = null;
    setBusy(false); setPending("");
  }

  function reset(keepPortals = false) {
    cancel();
    setMessages([]); setReply(null); setSelected([]); setDismissed([]);
    setReferrals([]); setInput(""); setPending(""); setBusy(false); setError(false);
    setCompleted(false); setSeeded(false);
    if (!keepPortals) setPortals(null);
  }

  function seed(needs: Need[]) {
    setSeeded(true);
    setSelected((old) => [...old, ...needs.filter((n) => !old.some((o) => o.code === n.code))]);
  }

  useEffect(() => {
    reset();
    return () => { controller.current?.abort(); };
    // Session state belongs to the booking and lives only in browser memory.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pnr]);

  const historyFull = messages.length >= 38
    || messages.reduce((total, m) => total + m.content.length, 0) + input.length > 15000;

  async function send(lang: Lang, value = input) {
    const text = value.trim();
    if (controller.current || !text || text.length > 1000 || historyFull) return;
    const history: ChatMessage[] = [...messages, { role: "user", content: text }];
    if (history.reduce((total, m) => total + m.content.length, 0) > 16000) return;
    if (isDescriptionChoice(text)) {
      const prompt = DESCRIPTION_PROMPT[lang];
      if (history.reduce((total, m) => total + m.content.length, 0) + prompt.length > 16000) return;
      setMessages([...history, { role: "assistant", content: prompt }]);
      setReply(null); setInput(""); setError(false); setCompleted(false); setPortals(null);
      return;
    }
    const ac = new AbortController();
    controller.current = ac;
    setCompleted(false); setPortals(null);
    setBusy(true); setError(false); setPending(text); setInput(text);
    try {
      const next = await api.chat(pnr, { messages: history, selected, dismissed, lang }, ac.signal);
      if (ac.signal.aborted) return;
      setMessages([...history, { role: "assistant", content: [next.message, next.question].filter(Boolean).join("\n\n") }]);
      setReply(next);
      // Each validated reply contains the full current set, including retractions.
      setReferrals(next.referrals);
      setInput("");
    } catch {
      if (!ac.signal.aborted) setError(true);
    } finally {
      if (controller.current === ac) {
        controller.current = null; setBusy(false); setPending("");
      }
    }
  }

  function choose(need: Need) {
    setSelected((old) => [...old.filter((n) => n.code !== need.code), need]);
    setDismissed((old) => old.filter((key) => key !== needKey(need)));
  }

  function chooseAll(needs: Need[]) {
    needs.forEach(choose);
  }

  function remove(need: Need) {
    setSelected((old) => old.filter((n) => needKey(n) !== needKey(need)));
    setDismissed((old) => [...new Set([...old, needKey(need)])]);
  }

  function restoreDraft(draft: Draft) {
    // A reviewed draft is the passenger's current selection, including removals.
    // Returning to chat must not seed last-trip needs into it again.
    setSeeded(true);
    setSelected(draft.needs);
    setReferrals(draft.referrals);
    setError(false);
    setCompleted(false); setPortals(null);
  }

  function continueChat() {
    setCompleted(false); setPortals(null); setError(false);
  }

  async function finish() {
    if (controller.current || (!messages.length && !selected.length)) return;
    const ac = new AbortController();
    controller.current = ac;
    setBusy(true); setError(false);
    try {
      const result = await api.completeChat(pnr, messages, selected, ac.signal);
      if (!ac.signal.aborted) { setPortals(result.portals); setCompleted(true); }
    } catch {
      if (!ac.signal.aborted) setError(true);
    } finally {
      if (controller.current === ac) { controller.current = null; setBusy(false); }
    }
  }

  async function review(onResult: (draft: Draft) => void) {
    if (controller.current || !selected.length) return;
    const ac = new AbortController();
    controller.current = ac;
    setBusy(true); setError(false);
    try {
      const draft = await api.chatDraft(pnr, selected, referrals.map((r) => r.code), ac.signal);
      if (!ac.signal.aborted) onResult(draft);
    } catch {
      if (!ac.signal.aborted) setError(true);
    } finally {
      if (controller.current === ac) { controller.current = null; setBusy(false); }
    }
  }

  return { messages, reply, selected, referrals, input, setInput, pending, busy, error,
    historyFull, send, choose, chooseAll, seeded, seed, remove, restoreDraft, review, reset, cancel, dismissed,
    portals, completed, finish, continueChat };
}

export type AssistanceChat = ReturnType<typeof useAssistanceChat>;
