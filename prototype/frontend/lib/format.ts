// Small display helpers shared by the passenger, staff and ops views.

/** "2026-11-14" -> "2026年11月14日" */
export function longDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${y}年${m}月${d}日`;
}

/** "2026-11-14 12:31" -> "12:31" on the travel day, otherwise "10/20 14:35". */
export function stamp(ts: string | null | undefined, travelDate?: string): string {
  if (!ts) return "";
  const [date, time] = ts.split(" ");
  if (travelDate && date === travelDate) return time;
  const [, m, d] = date.split("-").map(Number);
  return `${m}/${d} ${time}`;
}

/** Layover between an arrival "21:30" and the next departure "23:00" -> "1 小時 30 分". */
export function layover(arr: string | null, dep: string | null): string {
  if (!arr || !dep) return "";
  const mins = (t: string) => {
    const [h, m] = t.slice(0, 5).split(":").map(Number);
    return h * 60 + m;
  };
  let diff = mins(dep) - mins(arr);
  if (diff < 0) diff += 24 * 60;
  const h = Math.floor(diff / 60);
  const m = diff % 60;
  return h ? `${h} 小時${m ? ` ${m} 分` : ""}` : `${m} 分鐘`;
}

/** "悉尼 SYD" -> { city: "悉尼", code: "SYD" } */
export function place(text: string | null): { city: string; code: string } {
  if (!text) return { city: "", code: "" };
  const i = text.lastIndexOf(" ");
  return i < 0 ? { city: text, code: text } : { city: text.slice(0, i), code: text.slice(i + 1) };
}

/** "2026-11-14" -> "11月14日 星期六" */
export function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const weekday = "日一二三四五六"[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  return `${m}月${d}日 星期${weekday}`;
}
