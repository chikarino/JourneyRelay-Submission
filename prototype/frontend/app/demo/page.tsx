"use client";
// Two-screen demo for the projector (REDESIGN.md §4.3): the passenger phone on
// the left, a staff tablet on the right. Both are the real app in iframes and
// poll the API, so an action on one shows up on the other within seconds.
// The header also switches the AI engine live; switching reloads both iframes
// so the passenger compose badge reflects the new engine immediately.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, Role, Scenario } from "../../lib/api";
import { Lang, LangToggle, t, useLang } from "../../lib/i18n";
import { usePolling } from "../../lib/usePolling";

// Task-card views first; outstations and crew get the booking remark, so their
// views are read-only previews (REDESIGN.md §5.3).
const STAFF_VIEWS: { label: string; label_en: string; role: Role; place: string; preview?: boolean }[] = [
  { label: "客服", label_en: "Customer Care", role: "cs", place: "CS" },
  { label: "轉機站 · HKG", label_en: "Transit · HKG", role: "arrival", place: "HKG" },
  { label: "閘口 · HKG", label_en: "Gate · HKG", role: "gate", place: "HKG" },
  { label: "辦理登機 · SYD", label_en: "Check-in · SYD", role: "checkin", place: "SYD", preview: true },
  { label: "機艙 · CX100", label_en: "Cabin · CX100", role: "cabin", place: "CX100", preview: true },
  { label: "機艙 · CX251", label_en: "Cabin · CX251", role: "cabin", place: "CX251", preview: true },
];
const PHONE = { w: 390, h: 844, pad: 12, radius: 46 };
const TABLET = { w: 1180, h: 820, pad: 16, radius: 30 };
const GAP = 36;
const CAPTION = 28;
const RESET_MESSAGES = {
  fresh: "demo.reset_ok_fresh",
  midjourney: "demo.reset_ok_mid",
  "family-transfer": "demo.reset_ok_family",
} as const;

export default function DemoPage() {
  const stageRef = useRef<HTMLDivElement>(null);
  const [lang, setLang] = useLang();
  const [size, setSize] = useState({ w: 1440, h: 800 });
  const [staff, setStaff] = useState(STAFF_VIEWS[1]);
  const [reloadKey, setReloadKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [delayed, setDelayed] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [engine, setEngine] = useState<"local" | "api" | null>(null);
  const aiFetcher = useCallback(() => api.aiStatus(), []);
  const { data: aiStatus } = usePolling(aiFetcher, 5000);

  // Keep the active-engine chip in step with the backend between switches.
  useEffect(() => {
    if (aiStatus) setEngine(aiStatus.engine);
  }, [aiStatus]);

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!message) return;
    const id = setTimeout(() => setMessage(null), 4000);
    return () => clearTimeout(id);
  }, [message]);

  const availH = size.h - 32 - CAPTION;
  const phoneScale = Math.min(1, availH / (PHONE.h + PHONE.pad * 2));
  const phoneW = (PHONE.w + PHONE.pad * 2) * phoneScale;
  const tabletScale = Math.min(
    1,
    availH / (TABLET.h + TABLET.pad * 2),
    (size.w - 32 - phoneW - GAP) / (TABLET.w + TABLET.pad * 2),
  );

  async function reset(scenario: Scenario) {
    setBusy(true);
    try {
      await api.resetDemo(scenario);
      setDelayed(false);
      setReloadKey((k) => k + 1);
      setMessage(t(lang, RESET_MESSAGES[scenario]));
    } catch (e) {
      setMessage(t(lang, "demo.reset_fail", { msg: e instanceof Error ? e.message : String(e) }));
    } finally {
      setBusy(false);
    }
  }

  async function switchEngine(next: "local" | "api") {
    setBusy(true);
    try {
      const s = await api.setEngine(next);
      setEngine(s.engine);
      setReloadKey((k) => k + 1);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const viewLabel = (v: (typeof STAFF_VIEWS)[number]) => (lang === "en" ? v.label_en : v.label);

  const chip = (on: boolean) =>
    `-ml-px min-h-9 border px-3 text-sm font-semibold first:ml-0 disabled:cursor-not-allowed disabled:opacity-50 ${on ? "relative z-10 border-cx-green bg-cx-green text-white" : "border-line-strong bg-white text-ink hover:bg-paper-light"}`;

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-[#dfe1e2]">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-line bg-white px-5 py-2.5">
        <h1 className="mr-auto font-semibold">{t(lang, "demo.title")}</h1>
        <p
          className={`text-xs ${aiStatus?.ok ? "text-cx-jade-dark" : "text-reminder"}`}
          role="status"
        >
          {aiStatus
            ? aiStatus.ok
              ? aiStatus.engine === "api"
                ? t(lang, "demo.api_ready", { model: aiStatus.api.model ?? "" })
                : t(lang, "demo.ai_ready", { model: aiStatus.local.model ?? "" })
              : t(lang, "demo.ai_down")
            : t(lang, "demo.ai_checking")}
        </p>
        <div className="flex items-center gap-2">
          <span className="text-xs text-ink-2">{t(lang, "demo.engine")}</span>
          <div className="flex">
            <button className={chip(engine === "local")} disabled={busy || !aiStatus?.local.reachable || !aiStatus?.local.model_installed}
              onClick={() => switchEngine("local")}>
              {t(lang, "demo.engine_local", { model: aiStatus?.local.model ?? "" })}
            </button>
            <button className={chip(engine === "api")} disabled={busy || !aiStatus?.api.configured}
              onClick={() => switchEngine("api")}>
              {t(lang, "demo.engine_api", { model: aiStatus?.api.model ?? "" })}
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-ink-2">{t(lang, "demo.reset")}</span>
          <div className="flex">
            <button className={chip(false)} disabled={busy} onClick={() => reset("fresh")}>{t(lang, "demo.reset_fresh")}</button>
            <button className={chip(false)} disabled={busy} onClick={() => reset("midjourney")}>{t(lang, "demo.reset_midjourney")}</button>
            <button className={chip(false)} disabled={busy} onClick={() => reset("family-transfer")}>{t(lang, "demo.reset_family")}</button>
          </div>
          <span role="status" className="min-w-24 text-xs text-cx-jade-dark">{message}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-ink-2">{t(lang, "demo.scenario")}</span>
          <button className={chip(delayed)} aria-pressed={delayed} disabled={busy}
            onClick={async () => { await api.demoDelay("CX100", delayed ? 0 : 50); setDelayed(!delayed); }}>
            {t(lang, delayed ? "demo.delay_off" : "demo.delay_on")}
          </button>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-ink-2">{t(lang, "demo.frontline")}</span>
          <div className="flex flex-wrap">
            {STAFF_VIEWS.filter((v) => !v.preview).map((v) => (
              <button key={v.label} className={chip(v === staff)} aria-pressed={v === staff} onClick={() => setStaff(v)}>
                {viewLabel(v)}
              </button>
            ))}
          </div>
          <span className="text-xs text-ink-2">{t(lang, "demo.preview_only")}</span>
          <div className="flex flex-wrap">
            {STAFF_VIEWS.filter((v) => v.preview).map((v) => (
              <button key={v.label} className={chip(v === staff)} aria-pressed={v === staff} onClick={() => setStaff(v)}>
                {viewLabel(v)}
              </button>
            ))}
          </div>
        </div>
        <nav className="flex gap-4 text-sm">
          <a className="text-cx-jade underline underline-offset-4" href="/ops" target="_blank" rel="noreferrer">{t(lang, "demo.ops")}</a>
          <a className="text-cx-jade underline underline-offset-4" href="/">{t(lang, "demo.hub")}</a>
        </nav>
        <LangToggle lang={lang} onChange={setLang} />
      </header>
      <div ref={stageRef} className="flex min-h-0 flex-1 items-center justify-center gap-9 p-4">
        <Device key={`p${reloadKey}`} caption={t(lang, "demo.phone_caption")} device={PHONE} scale={phoneScale}
          src="/passenger/CXDEMO1" />
        <Device key={`s${reloadKey}-${staff.role}-${staff.place}`}
          caption={t(lang, "demo.tablet_caption", { view: viewLabel(staff) })} device={TABLET}
          scale={tabletScale} src={`/staff?role=${staff.role}&place=${staff.place}`} />
      </div>
    </div>
  );
}

function Device({ caption, device, scale, src }: {
  caption: string; device: { w: number; h: number; pad: number; radius: number }; scale: number; src: string;
}) {
  const { w, h, pad, radius } = device;
  return (
    <figure className="m-0 flex flex-col items-center gap-2">
      <div className="bg-[#1b1c1c] shadow-[0_20px_50px_rgba(0,0,0,0.25)]"
        style={{ width: (w + pad * 2) * scale, height: (h + pad * 2) * scale, borderRadius: radius * scale, padding: pad * scale }}>
        <div style={{ width: w * scale, height: h * scale }}>
          {/* Scale the clipped screen, not the iframe: with the clip outside the
              transform, Firefox leaves the lower part of the frame unpainted once
              the page inside scrolls. Here the clip and the iframe share one space. */}
          <div className="origin-top-left overflow-hidden"
            style={{ width: w, height: h, borderRadius: radius - pad, transform: `scale(${scale})` }}>
            <iframe title={caption} src={src} className="block border-0 bg-white" style={{ width: w, height: h }} />
          </div>
        </div>
      </div>
      <figcaption className="text-xs font-semibold text-ink-2">{caption}</figcaption>
    </figure>
  );
}
