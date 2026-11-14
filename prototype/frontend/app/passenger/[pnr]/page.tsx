"use client";
// Passenger view — the 旅途協助 module inside Manage Booking (REDESIGN.md §4.1).
// Flow: guided discovery chat → select → preview → confirm → journey progress.
// Bilingual with voice replies and arrangement read-aloud.

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import {
  api, CatalogNeed, Draft, MyNeed, Need, PASSENGER_STATUS, Stage, StageItem, TaskStatus,
} from "../../../lib/api";
import { Lang, LangToggle, t, useLang } from "../../../lib/i18n";
import { dayLabel, layover, place, stamp } from "../../../lib/format";
import { speak, ttsSupported } from "../../../lib/speech";
import { GuidedChat } from "../../../components/GuidedChat";
import { TravelPortals } from "../../../components/TravelPortals";
import { useAssistanceChat } from "../../../lib/useAssistanceChat";
import { usePolling } from "../../../lib/usePolling";
import { ArrowRight, btn, ChevronLeft, ChevronRight, Close, Speaker, StatusLabel } from "../../../lib/ui";

// The fallback need: Customer Care contacts the passenger (backend/catalog.py CS_CALLBACK).
const CALLBACK = { code: "CS_CALLBACK", scope: "full" } as const;
const PROGRESSED: TaskStatus[] = ["received", "done", "amended", "flagged", "notified"];

type Sheet = { step: "compose" } | { step: "preview"; draft: Draft } | null;
type Toast = { title: string; body: string } | null;

const sectionLabel = "px-4 pb-2 pt-6 text-sm font-semibold text-ink-2";
const panel = "border-y border-line bg-white";

export default function PassengerPage() {
  const { pnr } = useParams<{ pnr: string }>();
  const [lang, setLang] = useLang();
  const fetcher = useCallback(() => api.passenger(pnr), [pnr]);
  const { data: view, setData: setView, error, setError } = usePolling(fetcher);

  const [sheet, setSheet] = useState<Sheet>(null);
  const chat = useAssistanceChat(pnr);
  const [busy, setBusy] = useState(false);
  const [catalog, setCatalog] = useState<CatalogNeed[]>([]);
  const [toast, setToast] = useState<Toast>(null);
  const [confirmingNeed, setConfirmingNeed] = useState<number | null>(null);
  const previous = useRef<Map<number, TaskStatus> | null>(null);
  const resumed = useRef(false);
  const sheetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const dialog = sheetRef.current;
    if (!dialog) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    dialog.querySelector<HTMLElement>("#sheet-title")?.focus({ preventScroll: true });
    function trapFocus(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const controls = Array.from(dialog!.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), summary, a[href], [tabindex="0"]',
      )).filter((node) => node.offsetParent !== null);
      const first = controls[0], last = controls[controls.length - 1];
      if (!first) { event.preventDefault(); return; }
      const current = document.activeElement;
      if (event.shiftKey && (current === first || !controls.includes(current as HTMLElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (current === last || !controls.includes(current as HTMLElement))) {
        event.preventDefault(); first.focus();
      }
    }
    dialog.addEventListener("keydown", trapFocus);
    return () => {
      dialog.removeEventListener("keydown", trapFocus);
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, [sheet?.step]);

  useEffect(() => {
    api.catalog().then((c) => setCatalog(c.needs)).catch(() => setCatalog([]));
  }, []);

  // Notify when staff move an arrangement forward (detected between polls).
  useEffect(() => {
    if (!view) return;
    const now = new Map<number, TaskStatus>();
    const moved: { stage: Stage; item: StageItem }[] = [];
    for (const stage of view.stages) {
      for (const item of stage.items) {
        now.set(item.task_id, item.status);
        const before = previous.current?.get(item.task_id);
        if (before && before !== item.status && PROGRESSED.includes(item.status)) moved.push({ stage, item });
      }
    }
    if (moved.length) {
      const { stage, item } = moved[moved.length - 1];
      const more = moved.length > 1
        ? (lang === "en" ? ` (+${moved.length - 1} more updates)` : `（另有 ${moved.length - 1} 項更新）`)
        : "";
      const status = lang === "en" ? PASSENGER_STATUS_EN[item.status] : PASSENGER_STATUS[item.status];
      const need = lang === "en" ? item.need_label_en : item.need_label;
      const title = `${lang === "en" ? stage.title_en : stage.title} · ${lang === "en" ? item.role_label_en : item.role_label}`;
      setToast({
        title,
        body: lang === "en" ? `${status}: "${need}"${more}` : `${status}「${need}」${more}`,
      });
    }
    previous.current = now;
  }, [view, lang]);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(id);
  }, [toast]);

  // Resume an unconfirmed draft once (e.g. after a reload).
  useEffect(() => {
    if (!view || resumed.current) return;
    resumed.current = true;
    if (view.draft) setSheet({ step: "preview", draft: view.draft });
  }, [view]);

  async function run<T>(fn: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function editNeeds(draft: Draft, needs: Pick<Need, "code" | "scope">[]) {
    const next = await run(() => api.editDraft(draft.request_id, needs));
    if (next) setSheet({ step: "preview", draft: next });
  }

  async function acceptOffer() {
    const draft = await run(() => api.acceptOffer(pnr));
    if (draft) setSheet({ step: "preview", draft });
  }

  async function confirm(draft: Draft) {
    const next = await run(() => api.confirmRequest(draft.request_id));
    if (!next) return;
    const assist = document.getElementById("assist");
    setView(next);
    // Firefox can leave the fixed-sheet layer in the lower half of a scrolled
    // iframe. Close it at the top, then reveal the updated section next frame.
    window.scrollTo(0, 0);
    setSheet(null);
    chat.reset(true);
    setToast({
      title: t(lang, "passenger.shared_toast"),
      body: draft.is_update ? t(lang, "passenger.shared_update") : t(lang, "passenger.shared_new"),
    });
    requestAnimationFrame(() => assist?.scrollIntoView({ behavior: "smooth" }));
  }

  async function discard(draft: Draft) {
    const discarded = await run(() => api.discardDraft(draft.request_id));
    if (discarded) { chat.reset(); setSheet(null); }
  }

  async function cancelNeed(n: MyNeed) {
    const next = await run(() => api.cancelNeed(n.need_id));
    if (next) setView(next);
    setConfirmingNeed(null);
  }

  async function reconfirm() {
    const next = await run(() => api.reconfirm(pnr));
    if (next) {
      setView(next);
      setToast({ title: t(lang, "passenger.reconfirmed_toast"), body: t(lang, "passenger.reconfirmed_body") });
    }
  }

  if (!view) {
    return (
      <Shell lang={lang} onLang={setLang}>
        <p className="px-4 py-6 text-ink-2">{error ?? t(lang, "shell.loading")}</p>
      </Shell>
    );
  }

  const b = view.booking;
  const o = place(b.origin);
  const v = place(b.via);
  const d = place(b.destination);
  const name = `${view.passenger.display_name}${view.passenger.party_note ? ` ${view.passenger.party_note}` : ""}`;
  const s = view.summary;
  const settled = s.done + s.notified;
  const js = view.journey_status;

  return (
    <Shell lang={lang} onLang={setLang}>
      <section aria-label={lang === "en" ? "Itinerary" : "行程"} className="border-b border-line bg-white px-4 pb-3 pt-5">
        <div className="flex items-baseline justify-between text-sm text-ink-2">
          <span>{t(lang, "passenger.booking_ref")} <span className="font-semibold tracking-wider text-ink">{view.pnr}</span></span>
          <span>{dayLabel(b.travel_date)}</span>
        </div>
        <p className="mt-1 text-xl font-semibold">{name}</p>
        <Leg lang={lang} flight={b.flight_1} from={o.code} dep={b.f1_dep} to={v.code || d.code} arr={b.f1_arr} />
        {b.via && b.flight_2 && (
          <>
            <div className="flex items-center gap-3 text-xs text-ink-2">
              <span className="flex-1 border-t border-dashed border-line-strong" />
              {lang === "en"
                ? `${v.city} transfer · layover ${layover(b.f1_arr, b.f2_dep)}`
                : `${v.city}轉機 · 停留 ${layover(b.f1_arr, b.f2_dep)}`}
              <span className="flex-1 border-t border-dashed border-line-strong" />
            </div>
            <Leg lang={lang} flight={b.flight_2} from={v.code} dep={b.f2_dep} to={d.code} arr={b.f2_arr} />
          </>
        )}
      </section>
      {js.flights.some((f) => f.minutes > 0) && (
        <div role="status" className="border-b border-line bg-reminder-bg px-4 py-3 text-sm">
          <p>
            {js.flights.filter((f) => f.minutes > 0).map((f) => t(lang, "passenger.delay", { flight: f.flight, minutes: f.minutes })).join(" ")}
            {js.connection && js.connection.expected < js.connection.scheduled && (
              <> {t(lang, "passenger.connection", { scheduled: js.connection.scheduled, expected: js.connection.expected })}</>
            )}
          </p>
          {js.offer && (
            <>
              <p className="mt-1 font-semibold">{t(lang, "passenger.offer_q")}</p>
              <button className={`${btn.primary} mt-2 min-h-11 px-4 text-sm`} disabled={busy} onClick={acceptOffer}>
                {t(lang, "passenger.offer_btn", { label: lang === "en" ? js.offer.label_en : js.offer.label_zh })}
              </button>
            </>
          )}
          {/* A demo-scenario delay is always labelled as such (REDESIGN.md §5.5). */}
          {js.flights.some((f) => f.source === "demo") && (
            <p className="mt-2 text-xs text-ink-2">{t(lang, "passenger.delay_source_demo")}</p>
          )}
        </div>
      )}

      <h2 className={sectionLabel}>{t(lang, "passenger.manage")}</h2>
      <ul className={`divide-y divide-line ${panel}`}>
        <li>
          <a href="#assist" className="flex min-h-14 items-center justify-between px-4 font-semibold text-ink">
            {t(lang, "passenger.assist")}
            <span className="flex items-center gap-1 text-sm font-normal text-ink-2">
              {view.has_active
                ? t(lang, "passenger.arranged_of", { done: settled, total: s.total })
                : t(lang, "passenger.none_yet")}
              <ChevronRight className="size-5 text-ink-3" />
            </span>
          </a>
        </li>
      </ul>

      <section id="assist" aria-labelledby="assist-h" className="scroll-mt-16">
        <div className="flex items-baseline justify-between px-4 pb-2 pt-7">
          <h2 id="assist-h" className="text-lg font-semibold">{t(lang, "passenger.assist")}</h2>
        </div>
        {error && !sheet && <p className="mx-4 mb-3 bg-error-bg px-3 py-2 text-sm text-error">{error}</p>}

        {!view.has_active ? (
          <div className={`${panel} px-4 py-5`}>
            <p className="text-[15px] leading-relaxed">{t(lang, "passenger.intro")}</p>
            <button className={`${btn.primary} mt-5 w-full`} onClick={() => setSheet({ step: "compose" })}>
              {t(lang, "passenger.start")}
            </button>
            {view.reusable.length > 0 && (
              <p className="mt-2 text-sm text-ink-2">{t(lang, "passenger.reuse_note", { n: view.reusable.length })}</p>
            )}
          </div>
        ) : (
          <>
            <div className="h-1 bg-line" role="progressbar" aria-label={t(lang, "passenger.progress_label")}
              aria-valuemin={0} aria-valuemax={s.total} aria-valuenow={settled}>
              <div className="h-full bg-cx-jade transition-[width] duration-500"
                style={{ width: `${s.total ? (100 * settled) / s.total : 0}%` }} />
            </div>
            {s.followup > 0 && (
              <p className="bg-white px-4 py-2 text-sm text-error">{t(lang, "passenger.followup_n", { n: s.followup })}</p>
            )}

            {!b.reconfirmed_at && (
              <div className="border-y border-line bg-reminder-bg px-4 py-3">
                <p className="text-sm">
                  <span className="font-semibold">{t(lang, "passenger.reconfirm_title")}</span>
                  {t(lang, "passenger.reconfirm_q")}
                </p>
                <div className="mt-2 flex gap-2">
                  <button className={`${btn.primary} min-h-11 px-4 text-sm`} disabled={busy} onClick={reconfirm}>
                    {t(lang, "passenger.reconfirm_yes")}
                  </button>
                  <button className={`${btn.secondary} min-h-11 px-4 text-sm`} onClick={() => setSheet({ step: "compose" })}>
                    {t(lang, "passenger.reconfirm_update")}
                  </button>
                </div>
              </div>
            )}

            <div className="flex items-baseline justify-between px-4 pb-2 pt-6">
              <h3 className="text-sm font-semibold text-ink-2">{t(lang, "passenger.stages")}</h3>
              {ttsSupported() && (
                <button className={btn.text + " text-sm"}
                  onClick={() => speak(arrangementSpeech(view.stages, lang), lang)}>
                  <Speaker className="mr-1 inline size-4 align-text-bottom" />{t(lang, "passenger.read_aloud")}
                </button>
              )}
            </div>
            <ol className="border-t border-line">
              {view.stages.map((stage) => (
                <StageRows key={stage.key} lang={lang} stage={stage} travelDate={b.travel_date} />
              ))}
            </ol>

            <h3 className={sectionLabel}>{t(lang, "passenger.my_needs")}</h3>
            <ul className={`divide-y divide-line ${panel}`}>
              {view.needs.map((n) => {
                const label = lang === "en" ? n.label_en : n.label_zh;
                return (
                  <li key={n.need_id} className="flex items-center justify-between gap-3 px-4 py-3">
                    <div className="min-w-0">
                      <p className={n.status === "cancelled" ? "text-ink-3 line-through" : "font-medium"}>
                        {label}
                        {n.version > 1 && n.status === "active" && (
                          <span className="ml-2 text-xs font-semibold text-cx-gold">{t(lang, "passenger.added_midjourney")}</span>
                        )}
                      </p>
                      <p className="text-sm text-ink-2">{lang === "en" ? n.detail_en : n.detail_zh}</p>
                    </div>
                    {n.status === "cancelled" ? (
                      <span className="shrink-0 text-sm text-ink-3">{t(lang, "passenger.cancelled")}</span>
                    ) : confirmingNeed === n.need_id ? (
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <button className={`${btn.danger} min-h-10 px-3 text-sm`} disabled={busy} onClick={() => cancelNeed(n)}>
                          {t(lang, "passenger.confirm_cancel")}
                        </button>
                        <button className={btn.text + " text-sm"} onClick={() => setConfirmingNeed(null)}>
                          {t(lang, "passenger.keep")}
                        </button>
                      </div>
                    ) : (
                      <button className={`${btn.text} shrink-0 whitespace-nowrap text-sm`}
                        aria-label={lang === "en" ? `No longer needed: ${label}` : `不再需要「${label}」`}
                        onClick={() => setConfirmingNeed(n.need_id)}>
                        {t(lang, "passenger.no_longer")}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
            <div className="px-4 pt-5">
              <button className={`${btn.primary} w-full`} onClick={() => setSheet({ step: "compose" })}>
                {t(lang, "passenger.update_or_add")}
              </button>
            </div>

            <details className={`${panel} group mt-6`}>
              <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between px-4 font-medium [&::-webkit-details-marker]:hidden">
                {t(lang, "passenger.history")}
                <span className="flex items-center gap-1 text-sm font-normal text-ink-2">
                  {t(lang, "passenger.items", { n: view.ledger.length })}
                  <ChevronRight className="size-5 transition-transform group-open:rotate-90" />
                </span>
              </summary>
              <ul className="divide-y divide-line border-t border-line">
                {view.ledger.map((e, i) => (
                  <li key={i} className="px-4 py-2.5 text-sm">
                    {lang === "en" ? (e.text_en ?? e.text) : e.text}
                    <time className="block text-xs tabular-nums text-ink-3">{stamp(e.at, b.travel_date)}</time>
                  </li>
                ))}
              </ul>
            </details>
          </>
        )}
      </section>

      {!sheet && chat.portals !== null && <div className="px-4"><TravelPortals portals={chat.portals} lang={lang} /></div>}

      {sheet && (
        <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/40">
          <div ref={sheetRef} role="dialog" aria-modal="true" aria-labelledby="sheet-title"
            onKeyDown={(event) => {
              if (event.key === "Escape" && sheet.step === "compose") {
                chat.cancel(); setSheet(null); setError(null);
              }
            }}
            className="max-h-[92dvh] w-full max-w-[440px] animate-rise overflow-y-auto rounded-t-xl bg-white px-5 pb-6 pt-2 motion-reduce:animate-none">
            <div aria-hidden="true" className="mx-auto mb-2 h-1 w-10 rounded-full bg-line-strong" />
            {sheet.step === "compose" ? (
              <GuidedChat
                chat={chat} lang={lang}
                catalog={catalog} lastTrip={view.has_active ? [] : view.reusable}
                activeNeeds={view.needs.filter((n) => n.status === "active")}
                onClose={() => { chat.cancel(); setSheet(null); setError(null); }}
                onResult={(draft) => setSheet({ step: "preview", draft })}
              />
            ) : (
              <Preview
                lang={lang} draft={sheet.draft} busy={busy} error={error}
                onEdit={(needs) => editNeeds(sheet.draft, needs)}
                onConfirm={() => confirm(sheet.draft)}
                onBack={() => { chat.restoreDraft(sheet.draft); setSheet({ step: "compose" }); }}
                onDiscard={() => discard(sheet.draft)}
              />
            )}
          </div>
        </div>
      )}

      {toast && (
        <div role="status"
          className="fixed bottom-5 left-1/2 z-50 w-[calc(100%-32px)] max-w-[408px] -translate-x-1/2 animate-rise rounded-sm bg-ink px-4 py-3 text-[15px] text-white motion-reduce:animate-none">
          <p className="font-semibold">{toast.title}</p>
          <p>{toast.body}</p>
        </div>
      )}
    </Shell>
  );
}

function Shell({ lang, onLang, children }: { lang: Lang; onLang: (l: Lang) => void; children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh justify-center bg-line">
      <div className="relative min-h-dvh w-full max-w-[440px] bg-paper pb-10">
        <header className="relative sticky top-0 z-20 grid h-14 grid-cols-[48px_1fr_48px] items-center border-b border-line bg-white">
          <span aria-hidden="true" className="grid size-12 place-items-center"><ChevronLeft className="size-6" /></span>
          <h1 className="text-center text-[17px] font-semibold">{t(lang, "shell.title")}</h1>
          {/* Right header slot: language toggle (absolute so the title stays centred). */}
          <div className="absolute right-2 top-1/2 -translate-y-1/2">
            <LangToggle lang={lang} onChange={onLang} />
          </div>
        </header>
        <p className="bg-paper-warm px-4 py-1.5 text-xs text-ink-2">{t(lang, "shell.demo_note")}</p>
        <main>{children}</main>
      </div>
    </div>
  );
}

function Leg({ lang, flight, from, dep, to, arr }: {
  lang: Lang; flight: string; from: string; dep: string | null; to: string; arr: string | null;
}) {
  const nextDay = arr?.includes("(+1)");
  const arrTime = arr?.replace(" (+1)", "") ?? "";
  const label = lang === "en"
    ? `${flight}: depart ${from} ${dep}, arrive ${to} ${arrTime}${nextDay ? " (+1)" : ""}`
    : `${flight}：${from} ${dep} 起飛，${to} ${arrTime}${nextDay ? "（翌日）" : ""} 抵達`;
  return (
    <div className="grid grid-cols-[auto_1fr_auto] items-center gap-4 py-3" aria-label={label}>
      <div>
        <p className="text-2xl font-semibold tabular-nums">{dep}</p>
        <p className="text-sm text-ink-2">{from}</p>
      </div>
      <div aria-hidden="true" className="text-center text-xs text-ink-2">
        {flight}
        <div className="mt-1 flex items-center text-line-strong">
          <span className="flex-1 border-t border-line-strong" />
          <ArrowRight className="-ml-1 size-4" />
        </div>
      </div>
      <div className="text-right">
        <p className="text-2xl font-semibold tabular-nums">{arrTime}{nextDay && <sup className="ml-0.5 text-xs">+1</sup>}</p>
        <p className="text-sm text-ink-2">{to}</p>
      </div>
    </div>
  );
}

// One summary row per stage; the per-team instructions open on demand (REDESIGN.md §4.1).
const STAGE_PRIORITY: TaskStatus[] = ["flagged", "pending", "received", "amended", "done", "notified", "cancelled"];

function itemStatusText(lang: Lang, i: StageItem): string {
  // Pending means different things by channel and time (REDESIGN.md §5.3).
  if (i.status === "pending" && i.channel === "remark") return t(lang, "passenger.status_wait_care");
  if (i.status === "pending" && i.role !== "cs") return t(lang, "passenger.status_on_day");
  return lang === "en" ? PASSENGER_STATUS_EN[i.status] : PASSENGER_STATUS[i.status];
}

function StageRows({ lang, stage, travelDate }: { lang: Lang; stage: Stage; travelDate: string }) {
  const showPlace = stage.kind !== "flight" && stage.kind !== "booking";
  const live = stage.items.filter((i) => i.status !== "cancelled");
  // The stage shows its least advanced item, so anything still open is visible.
  const lead = [...(live.length ? live : stage.items)]
    .sort((x, y) => STAGE_PRIORITY.indexOf(x.status) - STAGE_PRIORITY.indexOf(y.status))[0];
  const needs = [...new Set(live.map((i) => (lang === "en" ? i.need_label_en : i.need_label)))];
  const heading = (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-sm font-semibold">
        {lang === "en" ? stage.title_en : stage.title}
        {showPlace && <span className="ml-2 font-normal text-ink-2">{stage.place}</span>}
      </span>
      <span className="text-xs tabular-nums text-ink-2">{lang === "en" ? stage.sub_en : stage.sub}</span>
    </div>
  );
  if (!lead) {
    return (
      <li className="border-b border-line bg-white px-4 py-3">
        {heading}
        <p className="mt-1 text-sm text-ink-3">{t(lang, "passenger.no_needs_this_stage")}</p>
      </li>
    );
  }
  const highlight = stage.items.some((i) => i.status === "flagged" || i.status === "amended"
    || (i.is_update && i.status !== "cancelled"));
  return (
    <li className="border-b border-line bg-white">
      <details className="group" open={highlight}>
        <summary className={`flex cursor-pointer list-none items-start gap-2 px-4 py-3 [&::-webkit-details-marker]:hidden ${highlight ? "bg-new" : ""}`}>
          <div className="min-w-0 flex-1">
            {heading}
            <div className="mt-1 flex items-start justify-between gap-3">
              <p className="min-w-0 text-sm text-ink-2">{needs.join(lang === "en" ? ", " : "、") || "—"}</p>
              <StatusLabel status={lead.status}>{itemStatusText(lang, lead)}</StatusLabel>
            </div>
          </div>
          <ChevronRight className="mt-0.5 size-4 shrink-0 text-ink-3 transition-transform group-open:rotate-90" />
        </summary>
        <ul className="divide-y divide-line border-t border-line bg-paper-light">
          {stage.items.map((i) => {
            const isNew = i.is_update && i.status !== "cancelled";
            return (
              <li key={i.task_id} className="flex gap-3 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className={`text-sm leading-snug ${i.status === "cancelled" ? "text-ink-3 line-through" : ""}`}>
                    {lang === "en" ? i.instruction_en || i.instruction_zh : i.instruction_zh}
                  </p>
                  <p className="mt-0.5 text-xs text-ink-2">
                    {lang === "en" ? i.role_label_en : i.role_label} · {lang === "en" ? i.need_label_en : i.need_label}
                    {isNew && <span className="font-semibold text-cx-gold"> · {t(lang, "passenger.added_midjourney")}</span>}
                  </p>
                  {i.note && <p className="mt-1 text-sm text-cx-gold">{t(lang, "passenger.amend_prefix")}{i.note}</p>}
                  {i.status === "flagged" && <p className="mt-1 text-sm text-error">{t(lang, "passenger.flagged_note")}</p>}
                </div>
                <div className="shrink-0 text-right">
                  <StatusLabel status={i.status}>{itemStatusText(lang, i)}</StatusLabel>
                  {i.at && i.status !== "cancelled" && (
                    <p className="text-xs tabular-nums text-ink-3">{stamp(i.at, travelDate)}</p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </details>
    </li>
  );
}

function SheetHead({ title, closeLabel, onClose }: { title: string; closeLabel: string; onClose: () => void }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <h2 id="sheet-title" tabIndex={-1} className="py-2 text-xl font-semibold">{title}</h2>
      <button aria-label={closeLabel} onClick={onClose}
        className="grid size-11 place-items-center rounded-full text-ink-2 hover:bg-paper">
        <Close />
      </button>
    </div>
  );
}

function Preview({ lang, draft, busy, error, onEdit, onConfirm, onBack, onDiscard }: {
  lang: Lang; draft: Draft; busy: boolean; error: string | null;
  onEdit: (needs: Pick<Need, "code" | "scope">[]) => void; onConfirm: () => void; onBack: () => void; onDiscard: () => void;
}) {
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const current = draft.needs.map((n) => ({ code: n.code, scope: n.scope }));
  const inDraft = new Set(draft.needs.map((n) => `${n.code}:${n.scope}`));
  const hasCallback = inDraft.has(`${CALLBACK.code}:${CALLBACK.scope}`);
  const label = (n: Need) => (lang === "en" ? n.label_en : n.label_zh);
  const detail = (n: Need) => (lang === "en" ? n.detail_en : n.detail_zh);

  // AI suggestions show only while the draft is still empty; the passenger
  // picks or returns to chat — nothing is shared before the confirm gate.
  useEffect(() => {
    setPicked(new Set());
  }, [draft.request_id]);
  const suggestions = draft.needs.length === 0 ? draft.suggestions ?? [] : [];

  // Which engine produced the draft (model or rule fallback) is shown on the
  // /demo header only; the passenger sees the same preview either way.
  return (
    <>
      <SheetHead title={t(lang, "preview.title")} closeLabel={t(lang, "preview.cancel_share")} onClose={onDiscard} />
      {draft.analysis.situation && (
        <p className="mt-3 border-l-2 border-cx-jade bg-paper-light px-3 py-2 text-sm">
          <span className="font-semibold">{t(lang, "preview.situation")}{lang === "en" ? ": " : "："}</span>
          {draft.analysis.situation}
        </p>
      )}
      {draft.needs.length === 0 && suggestions.length === 0 && draft.referrals.length === 0 && (
        <div className="mt-3 bg-reminder-bg px-3 py-2 text-sm">
          <p>{t(lang, "preview.empty")}</p>
          <button className={`${btn.secondary} mt-2 min-h-11 px-4 text-sm`} disabled={busy} onClick={() => onEdit([CALLBACK])}>
            {t(lang, "preview.callback_add")}
          </button>
        </div>
      )}
      {draft.referrals.length > 0 && (
        <div className="mt-3 border border-line bg-white text-sm">
          <p className="border-b border-line bg-reminder-bg px-3 py-2 font-semibold">{t(lang, "preview.referral_title")}</p>
          <ul className="divide-y divide-line">
            {draft.referrals.map((r) => (
              <li key={r.code} className="px-3 py-2">
                <p className="font-medium">{lang === "en" ? r.label_en : r.label_zh}</p>
                <p className="text-ink-2">{lang === "en" ? r.advice_en : r.advice_zh}</p>
              </li>
            ))}
          </ul>
          <div className="border-t border-line px-3 py-3">
            {hasCallback
              ? (
                <>
                  <p className="font-medium text-cx-jade">{t(lang, "preview.callback_added")}</p>
                  <p className="mt-1 text-xs text-ink-2">
                    {t(lang, "preview.callback_topics", {
                      topics: draft.referrals.map((r) => (lang === "en" ? r.label_en : r.label_zh)).join(lang === "en" ? ", " : "、"),
                    })}
                  </p>
                </>
              )
              : (
                <button className={`${btn.primary} min-h-11 w-full px-4 text-sm`} disabled={busy}
                  onClick={() => onEdit([...current, CALLBACK])}>
                  {t(lang, "preview.callback_add")}
                </button>
              )}
            <p className="mt-2 text-xs text-ink-2">{t(lang, "preview.referral_phone")}</p>
          </div>
        </div>
      )}
      {suggestions.length > 0 && (
        <div className="mt-3 border border-line bg-white">
          <p className="border-b border-line bg-paper-light px-3 py-2 text-sm font-semibold">
            {t(lang, "preview.suggest_title")}
          </p>
          <p className="border-b border-line px-3 py-2 text-xs text-ink-2">{t(lang, "preview.suggest_hint")}</p>
          <ul className="divide-y divide-line">
            {suggestions.map((s) => {
              const key = `${s.code}:${s.scope}`;
              const on = picked.has(key);
              return (
                <li key={key}>
                  <button aria-pressed={on} disabled={busy}
                    className={`flex w-full items-start gap-3 px-3 py-3 text-left ${on ? "bg-cx-green text-white" : "bg-white hover:bg-paper-light"}`}
                    onClick={() => {
                      const next = new Set(picked);
                      if (on) next.delete(key); else next.add(key);
                      setPicked(next);
                    }}>
                    <span aria-hidden="true"
                      className={`mt-0.5 grid size-5 shrink-0 place-items-center border text-sm font-bold ${on ? "border-white bg-white text-cx-green" : "border-line-strong text-transparent"}`}>✓</span>
                    <span className="min-w-0">
                      <span className="block font-medium">
                        {lang === "en" ? s.label_en : s.label_zh}
                        {s.scope === "transfer" && (
                          <span className="ml-2 text-xs font-semibold">{t(lang, "preview.transfer_only")}</span>
                        )}
                      </span>
                      <span className={`mt-0.5 block text-sm ${on ? "text-white/85" : "text-ink-2"}`}>{s.reason}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="flex gap-2 px-3 py-3">
            <button className={`${btn.primary} min-h-11 flex-1 px-4 text-sm`} disabled={busy || picked.size === 0}
              onClick={() => onEdit([...picked].map((key) => {
                const [code, scope] = key.split(":") as [string, Need["scope"]];
                return { code, scope };
              }))}>
              {t(lang, "preview.suggest_apply")}{picked.size > 0 ? `（${picked.size}）` : ""}
            </button>
            <button className={`${btn.quiet} min-h-11 px-4 text-sm`} disabled={busy} onClick={onBack}>
              {t(lang, "preview.suggest_decline")}
            </button>
          </div>
        </div>
      )}
      <ul className="divide-y divide-line border-b border-line">
        {draft.needs.map((n) => (
          <li key={`${n.code}:${n.scope}`} className="flex items-center justify-between gap-3 py-3">
            <div className="min-w-0">
              <p className="font-medium">
                {label(n)}
                {n.scope === "transfer" && (
                  <span className="ml-2 text-xs font-semibold text-cx-jade">{t(lang, "preview.transfer_only")}</span>
                )}
                {n.from_last_trip && (
                  <span className="ml-2 text-xs font-semibold text-ink-2">{t(lang, "preview.from_last_trip")}</span>
                )}
              </p>
              <p className="text-sm text-ink-2">{detail(n)}</p>
            </div>
            <button className={`${btn.text} shrink-0 text-sm`} disabled={busy}
              aria-label={t(lang, "preview.remove_of", { label: label(n) })}
              onClick={() => onEdit(current.filter((c) => !(c.code === n.code && c.scope === n.scope)))}>
              {t(lang, "preview.remove")}
            </button>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-sm text-ink-2">{t(lang, "preview.staff_only")}</p>
      {draft.booking_remarks.length > 0 && (
        <details className="mt-3 border border-line bg-white px-3 text-sm">
          <summary className="min-h-11 cursor-pointer py-2.5 font-semibold">{t(lang, "preview.remarks_title")}</summary>
          <ul className="space-y-1 font-mono text-xs break-words">
            {draft.booking_remarks.map((line) => <li key={line}>{line}</li>)}
          </ul>
          <p className="mb-3 mt-2 text-xs text-ink-2">{t(lang, "preview.remarks_note")}</p>
        </details>
      )}
      {draft.is_update && <p className="mt-3 text-sm text-ink-2">{t(lang, "preview.update_note")}</p>}
      {error && <p className="mt-3 bg-error-bg px-3 py-2 text-sm text-error">{error}</p>}

      <div className="mt-5 grid gap-2">
        <button className={btn.primary} disabled={busy || draft.needs.length === 0} onClick={onConfirm}>
          {t(lang, "preview.confirm")}
        </button>
        <button className={btn.secondary} onClick={onBack}>{t(lang, "preview.back")}</button>
      </div>
    </>
  );
}

// English status wording for PASSENGER_STATUS (task brief, exact values).
const PASSENGER_STATUS_EN: Record<TaskStatus, string> = {
  pending: "in progress", received: "received", done: "arranged", amended: "arranged with adjustment",
  flagged: "being followed up", cancelled: "cancelled", notified: "notified via the booking record",
};

/** Read-aloud script: one "{stage title}: {need label} {status}" sentence per
 * non-cancelled item, joined with ". " (en) / "；" (zh). */
function arrangementSpeech(stages: Stage[], lang: Lang): string {
  const colon = lang === "en" ? ": " : "：";
  const sep = lang === "en" ? ". " : "；";
  const parts: string[] = [];
  for (const stage of stages) {
    const title = lang === "en" ? stage.title_en : stage.title;
    for (const item of stage.items) {
      if (item.status === "cancelled") continue;
      const need = lang === "en" ? item.need_label_en : item.need_label;
      const status = lang === "en" ? PASSENGER_STATUS_EN[item.status] : PASSENGER_STATUS[item.status];
      parts.push(`${title}${colon}${need} ${status}`);
    }
  }
  return parts.join(sep);
}
