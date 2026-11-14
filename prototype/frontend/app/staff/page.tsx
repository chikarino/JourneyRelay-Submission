"use client";
// Staff view — a tablet tool for one role at one place (REDESIGN.md §4.2).
// The instruction is the headline; raw passenger text and diagnosis never appear.
// Deep link: /staff?role=arrival&place=HKG. Bilingual via lib/i18n DICT.

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { api, Role, ROLE_LABELS_EN, ROLE_LABELS_ZH, ROLES, STAFF_STATUS, StaffItem, TaskStatus } from "../../lib/api";
import { stamp } from "../../lib/format";
import { Lang, LangToggle, t, useLang } from "../../lib/i18n";
import { usePolling } from "../../lib/usePolling";
import { btn, StatusLabel } from "../../lib/ui";

// English status wording (no DICT key; mirrors the PASSENGER_STATUS_EN
// precedent on the passenger page).
const STAFF_STATUS_EN: Record<TaskStatus, string> = {
  pending: "Pending", received: "Received", done: "Arranged", amended: "Adjusted",
  flagged: "Follow up", cancelled: "Cancelled by passenger", notified: "Notified via booking record",
};
// Prefix for the flag note line ("跟進原因：…") — the only staff string with no
// DICT key; kept as a local record like STAFF_STATUS_EN.
const FLAG_PREFIX: Record<Lang, string> = { zh: "跟進原因：", en: "Follow-up reason: " };

export default function StaffPage() {
  return (
    <Suspense fallback={<div className="min-h-dvh bg-paper" />}>
      <StaffBoard />
    </Suspense>
  );
}

function StaffBoard() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [lang, setLang] = useLang();
  const role = (ROLES as readonly string[]).includes(params.get("role") ?? "")
    ? (params.get("role") as Role) : "gate";
  const place = params.get("place");
  const roleLabel = (r: Role) => (lang === "en" ? ROLE_LABELS_EN[r] : ROLE_LABELS_ZH[r]);

  const fetcher = useCallback(() => api.staffTasks(role, place), [role, place]);
  const { data: view, error, setError, refresh } = usePolling(fetcher);
  const [composing, setComposing] = useState<{ taskId: number; kind: "amend" | "flag" } | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const seen = useRef<Set<number> | null>(null);
  const [fresh, setFresh] = useState<Set<number>>(new Set());

  useEffect(() => { refresh(); }, [role, place, refresh]);

  // Highlight tasks that appeared since the last poll (e.g. a mid-journey update).
  useEffect(() => {
    if (!view) return;
    const ids = new Set(view.groups.flatMap((g) => g.items.map((i) => i.task_id)));
    if (seen.current) {
      const added = [...ids].filter((id) => !seen.current!.has(id));
      if (added.length) setFresh(new Set(added));
    }
    seen.current = ids;
  }, [view]);

  function go(nextRole: Role, nextPlace?: string | null) {
    const q = new URLSearchParams({ role: nextRole });
    if (nextPlace) q.set("place", nextPlace);
    seen.current = null;
    setComposing(null);
    router.replace(`${pathname}?${q.toString()}`);
  }

  async function act(item: StaffItem, kind: "receive" | "done" | "amend" | "flag") {
    setBusy(true);
    setError(null);
    try {
      if (kind === "receive") await api.receiveTask(item.task_id);
      else if (kind === "done") await api.doneTask(item.task_id);
      else if (kind === "amend") await api.amendTask(item.task_id, note.trim());
      else await api.flagTask(item.task_id, note.trim());
      setComposing(null);
      setNote("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function actAll(items: StaffItem[], kind: "receive" | "done") {
    setBusy(true);
    setError(null);
    try {
      for (const item of items) await (kind === "receive" ? api.receiveTask(item.task_id) : api.doneTask(item.task_id));
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-dvh bg-paper">
      <header className="flex flex-wrap items-end gap-x-6 gap-y-3 bg-cx-green px-5 py-3 text-white">
        <div className="mr-auto self-center">
          <p className="text-lg font-semibold">{t(lang, "staff.title")}</p>
          <p className="text-xs text-white/70">{t(lang, "staff.demo_note")}</p>
        </div>
        <label className="text-xs text-white/70">
          {t(lang, "staff.role")}
          <select value={role} onChange={(e) => go(e.target.value as Role)}
            className="mt-1 block min-h-11 border border-white/40 bg-cx-green-dark px-3 text-base text-white">
            {ROLES.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
          </select>
        </label>
        <div>
          <p id="place-label" className="text-xs text-white/70">{t(lang, "staff.place")}</p>
          <div role="group" aria-labelledby="place-label" className="mt-1 flex">
            {view?.places.map((p) => {
              const on = view.place === p.place;
              return (
                <button key={p.place} aria-pressed={on} onClick={() => go(role, p.place)}
                  className={`-ml-px min-h-11 border border-white/50 px-4 font-semibold first:ml-0 ${on ? "bg-white text-cx-green" : "text-white hover:bg-white/10"}`}>
                  {p.place}
                  <span className={`ml-2 text-xs font-normal ${on ? "text-ink-2" : "text-white/70"}`}>
                    {p.open ? t(lang, "staff.open_n", { n: p.open }) : t(lang, "staff.done")}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
        <p className="self-center text-xs tabular-nums text-white/70" aria-live="polite">
          {view ? t(lang, "staff.updated_at", { t: view.updated_at.slice(11) }) : t(lang, "shell.loading")}
        </p>
        <div className="self-center">
          <LangToggle lang={lang} onChange={setLang} />
        </div>
      </header>
      {error && <p className="mx-5 mt-3 bg-error-bg px-3 py-2 text-sm text-error">{error}</p>}

      <main className="space-y-4 px-5 py-4">
        {view && view.groups.length === 0 && (
          <p className="py-16 text-center text-ink-2">
            {roleLabel(role)}{view.place ? ` · ${view.place}` : ""} {t(lang, "staff.empty")}
          </p>
        )}
        {view?.groups.map((g) => (
          <section key={`${g.pnr}-${g.stage}`} aria-label={`${g.passenger}，${lang === "en" ? g.stage_title_en : g.stage_title}`} className="border border-line bg-white">
            <header className="flex items-start justify-between gap-4 border-b border-line bg-paper-light px-4 py-3">
              <div>
                <h2 className="text-lg font-semibold">
                  {g.passenger}<span className="ml-3 text-sm font-normal tracking-wider text-ink-2">{g.pnr}</span>
                </h2>
                <p className="text-sm text-ink-2">
                  {lang === "en" ? g.stage_title_en : g.stage_title} · {lang === "en" ? g.stage_sub_en : g.stage_sub}
                </p>
              </div>
              {g.time && (
                <div className="text-right">
                  <p className="text-2xl font-semibold tabular-nums text-cx-green">{g.time.replace(" (+1)", "")}</p>
                  {g.delay_minutes > 0 && (
                    <p className="text-sm font-semibold text-error">{t(lang, "staff.delay", { minutes: g.delay_minutes })}</p>
                  )}
                  <p className="text-xs text-ink-2">
                    {g.stage === "transfer" || g.stage === "arr" ? t(lang, "staff.arrival_time") : t(lang, "staff.dep_time")}
                  </p>
                </div>
              )}
            </header>
            {g.booking_remarks.length > 0 && (
              <div className="border-b border-line px-4 py-3">
                <p className="text-sm font-semibold">{t(lang, "staff.remarks_title")}</p>
                <ul className="mt-1 space-y-1 font-mono text-sm break-words">
                  {g.booking_remarks.map((line) => <li key={line}>{line}</li>)}
                </ul>
                <p className="mt-2 text-xs text-ink-2">{t(lang, "staff.remarks_note")}</p>
              </div>
            )}
            {g.items.some((it) => it.channel === "remark") && (
              <p className="border-b border-line bg-reminder-bg px-4 py-2 text-sm">{t(lang, "staff.remark_channel")}</p>
            )}
            {/* One tap per passenger per station when nothing needs adjusting. */}
            {g.items.filter((it) => it.channel === "app" && ["pending", "received"].includes(it.status)).length > 1 && (
              <div className="flex justify-end gap-2 border-b border-line px-4 py-2">
                {g.items.some((it) => it.status === "pending") && (
                  <button className={`${btn.secondary} min-h-11 px-4 text-sm`} disabled={busy}
                    onClick={() => actAll(g.items.filter((it) => it.status === "pending"), "receive")}>{t(lang, "staff.receive_all")}</button>
                )}
                <button className={`${btn.primary} min-h-11 px-4 text-sm`} disabled={busy}
                  onClick={() => actAll(g.items.filter((it) => ["pending", "received"].includes(it.status)), "done")}>{t(lang, "staff.done_all")}</button>
              </div>
            )}
            <ul className="divide-y divide-line">
              {g.items.map((it) => {
                const isNew = it.is_update && it.status !== "cancelled";
                return (
                  <li key={it.task_id}
                    className={`grid grid-cols-[104px_1fr] gap-x-4 gap-y-3 px-4 py-4 lg:grid-cols-[104px_1fr_auto] ${isNew ? "bg-new" : ""} ${fresh.has(it.task_id) ? "animate-flash motion-reduce:animate-none" : ""}`}>
                    <div className="pt-1">
                      <StatusLabel status={it.status}>
                        {lang === "en" ? STAFF_STATUS_EN[it.status] : STAFF_STATUS[it.status]}
                      </StatusLabel>
                      {isNew && <p className="mt-1 text-xs font-semibold text-cx-gold">{t(lang, "staff.is_update")}</p>}
                      {it.due_soon && <p className="mt-1 text-xs font-semibold text-error">{t(lang, "staff.due_soon")}</p>}
                    </div>
                    <div className="min-w-0">
                      <p className={`text-lg font-semibold leading-snug ${it.status === "cancelled" ? "text-ink-3 line-through" : ""}`}>
                        {lang === "en" ? it.instruction_en || it.instruction_zh : it.instruction_zh}
                      </p>
                      <p className="mt-1 text-sm text-ink-2">
                        {lang === "en" ? it.label_en : it.label_zh}
                        {it.ssr_hint && <> · {t(lang, "staff.ssr", { code: it.ssr_hint })}</>}
                        {it.status === "notified" ? null : it.done_at ? <> · {t(lang, "staff.arranged_at", { t: stamp(it.done_at, g.travel_date) })}</>
                          : it.received_at ? <> · {t(lang, "staff.received_at", { t: stamp(it.received_at, g.travel_date) })}</> : null}
                      </p>
                      {it.topics.length > 0 && (
                        <p className="mt-1 text-sm">
                          {t(lang, "staff.topics", {
                            topics: it.topics.map((x) => (lang === "en" ? x.label_en : x.label_zh)).join(lang === "en" ? ", " : "、"),
                          })}
                        </p>
                      )}
                      {it.note && it.status === "amended" && (
                        <p className="mt-1 text-sm text-cx-gold">{t(lang, "passenger.amend_prefix")}{it.note}{t(lang, "staff.amend_note")}</p>
                      )}
                      {it.note && it.status === "flagged" && (
                        <p className="mt-1 text-sm text-error">{FLAG_PREFIX[lang]}{it.note}{t(lang, "staff.flag_note")}</p>
                      )}
                      {it.status === "cancelled" && <p className="mt-1 text-sm text-ink-2">{t(lang, "staff.cancelled_note")}</p>}

                      {composing?.taskId === it.task_id && (
                        <div className="mt-3 flex gap-2">
                          <label className="sr-only" htmlFor={`note-${it.task_id}`}>
                            {t(lang, composing.kind === "amend" ? "staff.amend_placeholder" : "staff.flag_placeholder")}
                          </label>
                          <input id={`note-${it.task_id}`} autoFocus value={note} onChange={(e) => setNote(e.target.value)}
                            placeholder={t(lang, composing.kind === "amend" ? "staff.amend_placeholder" : "staff.flag_placeholder")}
                            className="min-h-12 flex-1 border border-line-strong px-3 text-base focus:border-cx-jade focus:outline-none focus:ring-2 focus:ring-cx-jade-90" />
                          <button className={btn.primary} disabled={busy || !note.trim()} onClick={() => act(it, composing.kind)}>
                            {t(lang, composing.kind === "amend" ? "staff.save" : "staff.submit")}
                          </button>
                          <button className={btn.quiet} onClick={() => setComposing(null)}>{t(lang, "staff.cancel")}</button>
                        </div>
                      )}
                    </div>
                    {it.status !== "cancelled" && it.channel === "app" && (
                      <div className="col-start-2 flex flex-wrap items-start gap-2 lg:col-start-3 lg:justify-end">
                        {it.status === "pending" && (
                          <button className={btn.secondary} disabled={busy} onClick={() => act(it, "receive")}>{t(lang, "staff.receive")}</button>
                        )}
                        {it.status !== "done" && it.status !== "amended" && (
                          <button className={btn.primary} disabled={busy} onClick={() => act(it, "done")}>{t(lang, "staff.done_btn")}</button>
                        )}
                        <button className={btn.quiet} disabled={busy}
                          onClick={() => { setNote(""); setComposing({ taskId: it.task_id, kind: "amend" }); }}>{t(lang, "staff.amend")}</button>
                        <button className={btn.danger} disabled={busy}
                          onClick={() => { setNote(""); setComposing({ taskId: it.task_id, kind: "flag" }); }}>{t(lang, "staff.flag")}</button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </main>
    </div>
  );
}
