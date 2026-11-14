"use client";
// Ops view — duty-manager board (REDESIGN.md §4.4): who needs what, where, and
// what needs following up. Kept deliberately small; it closes the pitch.
// Bilingual via lib/i18n DICT; strings with no DICT key live in local records.

import { useCallback } from "react";
import { api, OpsCounts, ROLES, ROLE_LABELS_EN, ROLE_LABELS_ZH, STAFF_STATUS, TaskStatus } from "../../lib/api";
import { longDate } from "../../lib/format";
import { Lang, LangToggle, t, useLang } from "../../lib/i18n";
import { usePolling } from "../../lib/usePolling";
import { StatusLabel } from "../../lib/ui";

const SHOWN: (keyof OpsCounts)[] = ["flagged", "pending", "received", "done", "amended", "notified"];
const th = "border-b border-line bg-paper-light px-3 py-2 text-left text-xs font-semibold text-ink-2";
const td = "border-b border-line px-3 py-3 align-top";

// English status wording (same values as the staff page's local record).
const STAFF_STATUS_EN: Record<TaskStatus, string> = {
  pending: "Pending", received: "Received", done: "Arranged", amended: "Adjusted",
  flagged: "Follow up", cancelled: "Cancelled by passenger", notified: "Notified via booking record",
};
// Local bilingual records for ops copy with no DICT key.
const METRICS = {
  followups: { zh: "需要跟進", en: "Follow-ups" },
  due_soon: { zh: "時間臨近，未接手", en: "Due soon, unclaimed" },
  open: { zh: "待處理／已收到", en: "Open" },
  completion: { zh: "已安排比例", en: "Completion" },
  avg_handle: { zh: "平均處理時間", en: "Avg handling (min)" },
};
const TABLE_HEADERS = { passenger: { zh: "旅客", en: "Passenger" }, trip: { zh: "行程", en: "Trip" } };
const NOTES = { zh: "虛構旅客示範資料 · 每 4 秒更新", en: "fictional passengers · refreshes every 4s" };
const MIN = { zh: "分鐘", en: "min" };
const DEMAND_TITLE = { zh: "各站及航班的協助需求", en: "Assistance demand by station and flight" };
const DEMAND_NOTE = {
  zh: "按旅客已確認的需要計算，不是預測；旅客越早說明，這裡越早有數。",
  en: "Counted from needs passengers have confirmed, not a forecast; the earlier they say it, the earlier it shows here.",
};
const DEMAND_HEADERS = {
  time: { zh: "時間", en: "Time" }, where: { zh: "站點／航班", en: "Station / flight" },
  bookings: { zh: "訂位", en: "Bookings" }, needs: { zh: "需要", en: "Needs" }, open: { zh: "未完成", en: "Open" },
};
const STAFFING_TITLE = { zh: "人手與待辦（示意）", en: "Staffing and open tasks (indicative)" };
const STAFFING_HEADERS = { on_duty: { zh: "當值", en: "On duty" }, open: { zh: "待辦", en: "Open" }, load: { zh: "負荷", en: "Load" } };
const GOAL = {
  zh: "目標：旅客重複解釋次數 → 0。上線後以抽樣問卷量度，不在此頁計算。",
  en: "Goal: passengers repeating themselves → 0. Measured by sampled survey after launch, not on this page.",
};

export default function OpsPage() {
  const [lang, setLang] = useLang();
  const fetcher = useCallback(() => api.opsBoard(), []);
  const { data: board, error } = usePolling(fetcher, 4000);

  if (!board) return <main className="mx-auto max-w-6xl px-5 py-8 text-ink-2">{error ?? t(lang, "shell.loading")}</main>;
  const m = board.metrics;
  const stats: [string, string, boolean?][] = [
    [METRICS.followups[lang], String(m.followups), m.followups > 0],
    [METRICS.due_soon[lang], String(m.due_soon), m.due_soon > 0],
    [METRICS.open[lang], String(m.open)],
    [METRICS.completion[lang], m.completion_pct == null ? "—" : `${m.completion_pct}%`],
    [METRICS.avg_handle[lang], m.avg_handle_minutes == null ? "—" : `${Math.round(m.avg_handle_minutes)} ${MIN[lang]}`],
  ];

  return (
    <main className="mx-auto max-w-6xl px-5 py-8">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t(lang, "ops.title")}</h1>
        <div className="flex items-center gap-4">
          <p className="text-sm text-ink-2">{longDate(board.date)} · {NOTES[lang]}</p>
          <LangToggle lang={lang} onChange={setLang} />
        </div>
      </div>
      {error && <p className="mt-3 bg-error-bg px-3 py-2 text-sm text-error">{error}</p>}

      <dl className="mt-6 grid grid-cols-2 divide-line border border-line bg-white sm:grid-cols-5 sm:divide-x">
        {stats.map(([label, value, alert]) => (
          <div key={label} className="px-4 py-3">
            <dt className="text-sm text-ink-2">{label}</dt>
            <dd className={`text-2xl font-semibold tabular-nums ${alert ? "text-error" : "text-cx-green"}`}>{value}</dd>
          </div>
        ))}
      </dl>

      {/* The role matrix is wider than a phone; it scrolls inside its frame, not the page. */}
      <div className="mt-6 overflow-x-auto">
      <table className="w-full min-w-[720px] border border-line bg-white text-sm">
        <thead>
          <tr>
            <th scope="col" className={th}>{TABLE_HEADERS.passenger[lang]}</th>
            <th scope="col" className={th}>{TABLE_HEADERS.trip[lang]}</th>
            {ROLES.map((r) => <th key={r} scope="col" className={th}>{lang === "en" ? ROLE_LABELS_EN[r] : ROLE_LABELS_ZH[r]}</th>)}
          </tr>
        </thead>
        <tbody>
          {board.rows.map((row) => (
            <tr key={row.pnr}>
              <td className={td}>
                <p className="font-semibold">{row.passenger}</p>
                <p className="text-xs tracking-wider text-ink-2">{row.pnr}</p>
              </td>
              <td className={`${td} text-ink-2`}>{row.route}<br />{row.flights}</td>
              {ROLES.map((r) => (
                <td key={r} className={td}>
                  <div className="flex flex-col gap-1">
                    {SHOWN.filter((s) => row.by_role[r][s] > 0).map((s) => (
                      <StatusLabel key={s} status={s}>
                        {lang === "en" ? STAFF_STATUS_EN[s] : STAFF_STATUS[s]} {row.by_role[r][s]}
                      </StatusLabel>
                    ))}
                  </div>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      </div>

      <h2 className="mt-8 text-sm font-semibold text-ink-2">{DEMAND_TITLE[lang]}</h2>
      <table className="mt-2 w-full border border-line bg-white text-sm">
        <thead>
          <tr>
            <th scope="col" className={th}>{DEMAND_HEADERS.time[lang]}</th>
            <th scope="col" className={th}>{DEMAND_HEADERS.where[lang]}</th>
            <th scope="col" className={th}>{DEMAND_HEADERS.bookings[lang]}</th>
            <th scope="col" className={`${th} w-1/2`}>{DEMAND_HEADERS.needs[lang]}</th>
            <th scope="col" className={th}>{DEMAND_HEADERS.open[lang]}</th>
          </tr>
        </thead>
        <tbody>
          {board.demand.map((d) => (
            <tr key={`${d.place}-${d.kind}`}>
              <td className={`${td} tabular-nums`}>{d.time}</td>
              <td className={td}>
                <span className="font-semibold">{lang === "en" ? d.title_en : d.title}</span>
                {d.kind !== "flight" && <span className="ml-2 text-xs tracking-wider text-ink-2">{d.place}</span>}
              </td>
              <td className={`${td} tabular-nums`}>{d.bookings}</td>
              <td className={`${td} text-ink-2`}>
                {d.needs.map((n) => `${lang === "en" ? n.label_en : n.label_zh} ${n.count}`).join(" · ")}
              </td>
              <td className={`${td} tabular-nums ${d.open_tasks > 0 ? "font-semibold" : "text-ink-2"}`}>{d.open_tasks}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-ink-2">{DEMAND_NOTE[lang]}</p>

      <h2 className="mt-8 text-sm font-semibold text-ink-2">{STAFFING_TITLE[lang]}</h2>
      <table className="mt-2 w-full border border-line bg-white text-sm">
        <thead>
          <tr>
            <th scope="col" className={th}>{t(lang, "staff.role")}</th>
            <th scope="col" className={th}>{STAFFING_HEADERS.on_duty[lang]}</th>
            <th scope="col" className={th}>{STAFFING_HEADERS.open[lang]}</th>
            <th scope="col" className={`${th} w-1/2`}>{STAFFING_HEADERS.load[lang]}</th>
          </tr>
        </thead>
        <tbody>
          {board.staffing.map((s) => {
            const over = s.open_tasks > s.headcount;
            return (
              <tr key={s.role}>
                <td className={td}>{lang === "en" ? ROLE_LABELS_EN[s.role] : s.label_zh}</td>
                <td className={`${td} tabular-nums`}>{s.headcount}</td>
                <td className={`${td} tabular-nums ${over ? "font-semibold text-error" : ""}`}>{s.open_tasks}</td>
                <td className={td}>
                  <div className="mt-1.5 h-1.5 bg-line">
                    <div className={`h-full ${over ? "bg-error" : "bg-cx-jade"}`}
                      style={{ width: `${Math.min(100, (100 * s.open_tasks) / Math.max(s.headcount, 1))}%` }} />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <p className="mt-6 text-sm text-ink-2">{GOAL[lang]}</p>
    </main>
  );
}
