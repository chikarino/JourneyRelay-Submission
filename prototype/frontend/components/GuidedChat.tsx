"use client";

import { useEffect, useRef, useState } from "react";
import { CatalogNeed, Draft, Need } from "../lib/api";
import { Lang, t } from "../lib/i18n";
import { AssistanceChat, isDescriptionChoice, needKey } from "../lib/useAssistanceChat";
import { listenOnce, SpeechLang, speechSupported } from "../lib/speech";
import { btn, Close, Mic } from "../lib/ui";
import { TravelPortals } from "./TravelPortals";

const STARTERS = ["waiting", "mobility", "communication", "seating", "unsure"];
const VOICE_LANGS: { label: string; code: SpeechLang }[] = [
  { label: "粵語", code: "zh-HK" }, { label: "普通話", code: "zh-CN" }, { label: "English", code: "en-US" },
];

export function GuidedChat({ chat, lang, catalog, activeNeeds, lastTrip, onClose, onResult }: {
  chat: AssistanceChat; lang: Lang;
  catalog: CatalogNeed[]; activeNeeds: Need[]; lastTrip: Need[]; onClose: () => void; onResult: (draft: Draft) => void;
}) {
  const [listening, setListening] = useState(false);
  const [voiceLang, setVoiceLang] = useState<SpeechLang>(lang === "en" ? "en-US" : "zh-HK");
  const [speechError, setSpeechError] = useState(false);
  const stop = useRef<(() => void) | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const selectedKeys = new Set(chat.selected.map(needKey));
  const activeKeys = new Set(activeNeeds.map(needKey));
  const label = (n: Need) => lang === "en" ? n.label_en : n.label_zh;
  const recommendations = (chat.reply?.recommendations ?? []).filter((n) => !activeKeys.has(needKey(n)));
  const canSpeak = speechSupported();

  useEffect(() => () => { try { stop.current?.(); } catch { /* already stopped */ } }, []);
  // Pre-select the last trip's needs at the start of each conversation (REDESIGN.md §5.4).
  useEffect(() => { if (!chat.seeded && lastTrip.length) chat.seed(lastTrip); }, [chat, lastTrip]);
  const lastTripKeys = new Set(lastTrip.map(needKey));
  const unselected = recommendations.filter((n) => !selectedKeys.has(needKey(n)));
  const chips = chat.messages.length ? chat.reply?.quick_replies ?? [] : STARTERS.map((key) => t(lang, `chat.start_${key}`));
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [chat.messages, chat.pending]);
  useEffect(() => {
    if (chat.completed) {
      const title = document.getElementById("sheet-title");
      title?.focus({ preventScroll: true });
      title?.scrollIntoView({ block: "start" });
    }
  }, [chat.completed]);

  function toggleMic() {
    if (listening) { stop.current?.(); return; }
    const base = chat.input.trim();
    let final = "";
    let ended = false;
    setSpeechError(false); setListening(true);
    try {
      stop.current = listenOnce(voiceLang, (chunk, isFinal) => {
        if (ended) return;
        if (isFinal) final = [final, chunk].filter(Boolean).join(" ");
        chat.setInput([base, final, isFinal ? "" : chunk].filter(Boolean).join(" ").slice(0, 1000));
      }, (err) => {
        if (ended) return;
        ended = true; stop.current = null; setListening(false);
        if (err && err !== "aborted") setSpeechError(true);
      });
    } catch { setListening(false); setSpeechError(true); }
  }

  // Changing the voice language mid-dictation stops it; the next tap uses the new language.
  function changeVoiceLang(code: SpeechLang) {
    setVoiceLang(code);
    try { stop.current?.(); } catch { /* already stopped */ }
  }

  return <>
    <div className="flex items-center justify-between gap-2">
      <h2 id="sheet-title" tabIndex={-1} className="py-2 text-xl font-semibold">{t(lang, chat.completed ? "chat.finished_title" : "chat.title")}</h2>
      <button aria-label={t(lang, "compose.close")} onClick={onClose}
        className="grid size-11 place-items-center rounded-full text-ink-2 hover:bg-paper"><Close /></button>
    </div>
    {chat.completed ? <div aria-live="polite" aria-busy={chat.busy}>
      <TravelPortals portals={chat.portals ?? []} lang={lang} />
      {chat.selected.length > 0 && <>
        <p className="mt-4 text-sm">{t(lang, "chat.selected", { n: chat.selected.length })}</p>
        <button className={`${btn.primary} mt-3 w-full`} disabled={chat.busy}
          onClick={() => void chat.review(onResult)}>{t(lang, "chat.review", { n: chat.selected.length })}</button>
        <p className="mt-2 text-xs text-ink-2">{t(lang, "chat.confirm_hint")}</p>
      </>}
      {chat.error && <p role="alert" className="mt-3 text-sm text-error">{t(lang, "chat.error")}</p>}
      <button className={`${btn.secondary} mt-3 w-full`} disabled={chat.busy} onClick={onClose}>{t(lang, "chat.done")}</button>
      <button className={`${btn.text} mt-3 text-sm`} disabled={chat.busy}
        onClick={() => { chat.continueChat(); requestAnimationFrame(() => input.current?.focus()); }}>{t(lang, "chat.keep_chatting")}</button>
    </div> : <>

    <div role="log" aria-label={t(lang, "chat.conversation")} aria-live="polite" aria-relevant="additions"
      aria-busy={chat.busy} className="mt-3 max-h-[38dvh] space-y-2 overflow-y-auto overscroll-contain border-y border-line bg-paper-light p-3">
      <div className="mr-8 border-l-2 border-cx-jade bg-white px-3 py-2 text-sm">{t(lang, "chat.greeting")}</div>
      {chat.messages.map((message, i) => <div key={i}
        className={`whitespace-pre-wrap px-3 py-2 text-sm leading-relaxed ${message.role === "user" ? "ml-8 bg-cx-green text-white" : "mr-8 border-l-2 border-cx-jade bg-white"}`}>
        <span className="sr-only">{t(lang, message.role === "user" ? "chat.you" : "chat.assistant")}：</span>
        {message.content}
      </div>)}
      {chat.pending && <div className="ml-8 bg-cx-green px-3 py-2 text-sm text-white">{chat.pending}</div>}
      {chat.busy && <p role="status" className="text-sm text-ink-2">{t(lang, "chat.working")}</p>}
      <div ref={end} />
    </div>
    {chips.length > 0 && <div className="-mx-5 mt-2 flex gap-2 overflow-x-auto px-5 pb-1">
      {chips.map((answer) =>
        <button key={answer} disabled={chat.busy || listening || chat.historyFull}
          className={`${btn.quiet} min-h-11 shrink-0 whitespace-nowrap px-3 text-sm`} onClick={() => {
            void chat.send(lang, answer);
            if (isDescriptionChoice(answer)) requestAnimationFrame(() => input.current?.focus());
          }}>{answer}</button>)}
    </div>}

    {recommendations.length > 0 && <section className="mt-3 border border-cx-jade" aria-label={t(lang, "chat.found", { n: recommendations.length })}>
      <div className="flex items-center justify-between gap-2 border-b border-line bg-cx-jade-95 px-3 py-1.5">
        <h3 className="text-sm font-semibold">{t(lang, "chat.found", { n: recommendations.length })}</h3>
        {unselected.length > 1 && <button className={`${btn.text} text-sm`} disabled={chat.busy || listening}
          onClick={() => chat.chooseAll(unselected)}>{t(lang, "chat.add_all")}</button>}
      </div>
      <ul className="divide-y divide-line">
        {recommendations.map((n) => {
          const on = selectedKeys.has(needKey(n));
          return <li key={needKey(n)} className="flex items-center gap-3 px-3 py-2">
            <div className="min-w-0 flex-1 text-sm">
              <p className="font-semibold">{label(n)}</p>
              {n.reason && <p className="text-ink-2">{n.reason}</p>}
            </div>
            <button aria-pressed={on} disabled={chat.busy || listening}
              aria-label={t(lang, on ? "preview.remove_of" : "chat.add_of", { label: label(n) })}
              className={`${on ? btn.secondary : btn.primary} min-h-11 shrink-0 px-3 text-sm`}
              onClick={() => on ? chat.remove(n) : chat.choose(n)}>{t(lang, on ? "chat.added" : "preview.add")}</button>
          </li>;
        })}
      </ul>
    </section>}

    {chat.referrals.length > 0 && <div className="mt-3 border border-line bg-reminder-bg p-3 text-sm">
      <p className="font-semibold">{t(lang, "preview.referral_title")}</p>
      {chat.referrals.map((r) => <p key={r.code} className="mt-2">{lang === "en" ? r.advice_en : r.advice_zh}</p>)}
      <button className={`${btn.text} mt-2`} disabled={chat.busy || selectedKeys.has("CS_CALLBACK:full") || activeKeys.has("CS_CALLBACK:full")}
        onClick={() => { const callback = catalog.find((n) => n.code === "CS_CALLBACK"); if (callback) chat.choose(callback); }}>
        {t(lang, activeKeys.has("CS_CALLBACK:full") ? "chat.already_active" : selectedKeys.has("CS_CALLBACK:full") ? "preview.callback_added" : "preview.callback_add")}
      </button>
    </div>}

    {chat.selected.length > 0 && <div className="mt-3 border border-line px-3 py-2">
      <h3 className="text-sm font-semibold">{t(lang, "chat.selected", { n: chat.selected.length })}</h3>
      <ul>
        {chat.selected.map((n) => <li key={needKey(n)} className="flex items-center justify-between gap-2 text-sm">
          <span>{label(n)}{lastTripKeys.has(needKey(n)) && <span className="ml-2 text-xs font-semibold text-ink-2">{t(lang, "preview.from_last_trip")}</span>}</span>
          <button className="min-h-11 px-2 text-cx-jade underline" disabled={chat.busy}
            onClick={() => chat.remove(n)} aria-label={t(lang, "preview.remove_of", { label: label(n) })}>{t(lang, "preview.remove")}</button>
        </li>)}
      </ul>
      {chat.reply?.recheck_selected.filter((r) => selectedKeys.has(r.id)).map((r) =>
        <p key={r.id} className="mt-1 bg-reminder-bg p-2 text-sm">{t(lang, "chat.recheck")} {r.reason}</p>)}
    </div>}

    {chat.error && <p role="alert" className="mt-3 bg-error-bg p-3 text-sm text-error">{t(lang, "chat.error")}</p>}
    {chat.historyFull && <p role="status" className="mt-3 bg-reminder-bg p-3 text-sm">{t(lang, "chat.limit")}</p>}

    <form className="mt-3" onSubmit={(e) => { e.preventDefault(); void chat.send(lang); }}>
      <label htmlFor="chat-answer" className="sr-only">{t(lang, "chat.answer")}</label>
      <div className="flex gap-2">
        <input ref={input} id="chat-answer" type="text" value={chat.input} maxLength={1000} autoComplete="off"
          disabled={chat.busy || chat.historyFull} placeholder={t(lang, "chat.placeholder")}
          onChange={(e) => chat.setInput(e.target.value)}
          className="min-h-12 min-w-0 flex-1 border border-line-strong bg-white px-3 text-base focus:outline-none focus:ring-2 focus:ring-cx-jade" />
        {canSpeak && <button type="button" disabled={chat.busy || chat.historyFull} onClick={toggleMic}
          aria-label={t(lang, listening ? "compose.mic_stop" : "compose.mic")} aria-pressed={listening}
          className={`grid size-12 shrink-0 place-items-center border ${listening ? "border-error text-error" : "border-line-strong text-ink-2"}`}><Mic /></button>}
        <button type="submit" className={`${btn.primary} shrink-0 px-3`} disabled={chat.busy || listening || !chat.input.trim() || chat.historyFull}>
          {t(lang, "chat.send")}</button>
      </div>
      {listening && <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        <span role="status" className="text-error">{t(lang, "compose.mic_listening")}</span>
        <label htmlFor="chat-voice-lang" className="ml-auto">{t(lang, "chat.voice_language")}</label>
        <select id="chat-voice-lang" value={voiceLang} className="min-h-9 border border-line px-2"
          onChange={(e) => changeVoiceLang(e.target.value as SpeechLang)}>{VOICE_LANGS.map((v) => <option key={v.code} value={v.code}>{v.label}</option>)}</select>
      </div>}
      {speechError && <p role="alert" className="mt-2 text-sm text-error">{t(lang, "chat.speech_error")}</p>}
    </form>

    <button className={`${btn.primary} mt-3 w-full`} disabled={chat.busy || listening || (!chat.messages.length && !chat.selected.length) || Boolean(chat.input.trim())}
      onClick={() => void chat.finish()}>{t(lang, chat.busy ? "chat.working" : "chat.finish")}</button>
    {Boolean(chat.input.trim()) && <p className="mt-2 text-xs text-ink-2">{t(lang, "chat.send_before_finish")}</p>}
    {chat.selected.length > 0 && <button className={`${btn.text} mt-3 text-sm`} disabled={chat.busy || listening}
      onClick={() => void chat.review(onResult)}>{t(lang, "chat.review", { n: chat.selected.length })}</button>}
    <p className="mt-2 text-xs text-ink-2">{t(lang, "chat.confirm_hint")}</p>
    {(chat.messages.length > 0 || chat.selected.length > 0) && <button className={`${btn.text} mt-2 text-sm`} disabled={chat.busy || listening}
      onClick={() => { chat.reset(); }}>{t(lang, "chat.restart")}</button>}
    </>}
  </>;
}
