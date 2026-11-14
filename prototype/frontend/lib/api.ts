// JourneyRelay API client + types (mirrors backend/main.py, REDESIGN.md §6).
// All passengers are fictional demo data.

export const ROLES = ["cs", "checkin", "gate", "cabin", "arrival"] as const;
export type Role = (typeof ROLES)[number];

export const ROLE_LABELS_ZH: Record<Role, string> = {
  cs: "客服", checkin: "辦理登機手續", gate: "閘口", cabin: "機艙組員", arrival: "抵達／轉機站",
};
// Mirrors backend/db.py ROLE_LABELS_EN.
export const ROLE_LABELS_EN: Record<Role, string> = {
  cs: "Customer Care", checkin: "Check-in", gate: "Gate", cabin: "Cabin Crew", arrival: "Arrival / Transit",
};

// "notified": a remark-channel task whose booking remark Customer Care has filed (REDESIGN.md §5.3).
export type TaskStatus = "pending" | "received" | "done" | "amended" | "flagged" | "cancelled" | "notified";
// app: a task card the team acknowledges. remark: outstations and crew, reached by the booking remark.
export type Channel = "app" | "remark";

// Same status, different audience (REDESIGN.md §4.1).
export const PASSENGER_STATUS: Record<TaskStatus, string> = {
  pending: "處理中", received: "已收到", done: "已安排", amended: "已安排（有調整）",
  flagged: "跟進中", cancelled: "已取消", notified: "已經訂位紀錄通知",
};
export const STAFF_STATUS: Record<TaskStatus, string> = {
  pending: "待處理", received: "已收到", done: "已安排", amended: "已調整",
  flagged: "需要跟進", cancelled: "旅客已取消", notified: "已通知（備註）",
};

export interface Need {
  code: string; scope: "full" | "transfer"; label_zh: string; label_en: string; detail_zh: string; detail_en: string;
  from_last_trip?: boolean; // draft only: also confirmed on the traveller's last trip
}
export interface CatalogNeed extends Need { ssr_hint: string }
export interface MyNeed extends Need { need_id: number; version: number; status: "active" | "cancelled" }

export interface StageItem {
  task_id: number; role: Role; role_label: string; need_label: string; instruction_zh: string;
  instruction_en: string; need_label_en: string; role_label_en: string;
  status: TaskStatus; channel: Channel; at: string | null; note: string | null; is_update: boolean;
}
export interface Stage {
  key: "booking" | "dep" | "f1" | "transfer" | "f2" | "arr";
  kind: "booking" | "dep" | "flight" | "transfer" | "arr";
  title: string; title_en: string; place: string; time: string | null; sub: string; sub_en: string; items: StageItem[];
}
export interface AnalysisInfo {
  source: "local" | "api" | "profile" | "offer" | "chat"; // chat: explicit selections from guided discovery
  status: "ok" | "empty" | "error";
  model: string | null;
  latency_ms: number | null;
  situation: string | null;
}
export interface SuggestedNeed {
  code: string; scope: "full" | "transfer"; label_zh: string; label_en: string;
  detail_zh: string; detail_en: string; reason: string;
}
// Asked for but not arrangeable here; wording comes from backend/catalog.py REFERRALS (REDESIGN.md §5.2).
export interface Referral { code: string; label_zh: string; label_en: string; advice_zh: string; advice_en: string }
export interface Draft {
  request_id: number; version: number; is_update: boolean; needs: Need[];
  suggestions?: SuggestedNeed[];
  referrals: Referral[];
  staff_will_see: string[]; staff_wont_see: string[]; recognised?: boolean;
  booking_remarks: string[]; // suggested booking-record remark lines, whole booking (REDESIGN.md §5.1)
  analysis: AnalysisInfo;
}

export interface ChatMessage { role: "user" | "assistant"; content: string }
export interface TravelPortal {
  id: string; station: string; title_zh: string; title_en: string; provider: string; url: string;
}
export interface ChatReply {
  message: string; question: string; quick_replies: string[];
  recommendations: SuggestedNeed[]; referrals: Referral[];
  recheck_selected: { id: string; reason: string }[];
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
export interface EngineProbes {
  local: { reachable: boolean; model: string | null; model_installed: boolean };
  api: { configured: boolean; reachable: boolean; model: string | null };
}
export interface AiStatus extends EngineProbes { ok: boolean; engine: "local" | "api" }
export interface EngineState extends EngineProbes { engine: "local" | "api" }
export interface Booking {
  origin: string; via: string | null; destination: string; flight_1: string; flight_2: string | null;
  f1_dep: string | null; f1_arr: string | null; f2_dep: string | null; f2_arr: string | null;
  travel_date: string; reconfirmed_at: string | null;
}
export interface PassengerView {
  pnr: string;
  passenger: { display_name: string; party_note: string | null };
  booking: Booking;
  has_active: boolean;
  summary: { total: number; done: number; received: number; followup: number; notified: number };
  stages: Stage[];
  needs: MyNeed[];
  draft: Draft | null;
  // Delays (live from OAG, or a demo scenario) and what they prompt (REDESIGN.md §5.5).
  journey_status: {
    flights: { flight: string; minutes: number; source: "oag" | "demo" }[];
    connection: { station: string; scheduled: number; expected: number; tight: boolean } | null;
    offer: Need | null;
  };
  reusable: Need[]; // needs passport: confirmed on this traveller's last trip (REDESIGN.md §5.4)
  ledger: { text: string; text_en: string | null; who: string; who_en: string | null; at: string }[];
}

export interface StaffItem {
  task_id: number; label_zh: string; label_en: string; ssr_hint: string; scope: string;
  topics: { label_zh: string; label_en: string }[]; // Customer Care callback card only (REDESIGN.md §5.2)
  instruction_zh: string; instruction_en: string;
  status: TaskStatus; channel: Channel; note: string | null; is_update: boolean;
  due_soon: boolean; // unclaimed and close to its stage time
  created_at: string; received_at: string | null; done_at: string | null;
}
export interface StaffGroup {
  pnr: string; passenger: string; stage: string; stage_title: string; stage_sub: string;
  stage_title_en: string; stage_sub_en: string; time: string | null;
  travel_date: string; items: StaffItem[]; delay_minutes: number;
  booking_remarks: string[]; // Customer Care only; empty for other roles
}
export interface StaffView {
  role: Role; label_zh: string; label_en: string; place: string | null;
  places: { place: string; open: number; total: number }[];
  groups: StaffGroup[]; updated_at: string; privacy_note: string;
}

export type OpsCounts = Record<"pending" | "received" | "done" | "amended" | "flagged" | "notified", number>;
export interface OpsBoard {
  date: string;
  rows: { pnr: string; passenger: string; route: string; flights: string; by_role: Record<Role, OpsCounts> }[];
  metrics: { avg_handle_minutes: number | null; completion_pct: number | null; followups: number; open: number; due_soon: number };
  demand: {
    place: string; kind: Stage["kind"]; title: string; title_en: string; time: string | null;
    bookings: number; open_tasks: number; needs: { label_zh: string; label_en: string; count: number }[];
  }[];
  staffing: { role: Role; label_zh: string; headcount: number; open_tasks: number }[];
}

export type Scenario = "midjourney" | "fresh" | "family-transfer";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, cache: "no-store", ...init });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* keep */ }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  http<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });

export const api = {
  aiStatus: () => http<AiStatus>("/api/ai/status"),
  setEngine: (engine: "local" | "api") => post<EngineState>("/api/ai/engine", { engine }),
  passenger: (pnr: string) => http<PassengerView>(`/api/passenger/${encodeURIComponent(pnr)}`),
  catalog: () => http<{ needs: CatalogNeed[] }>("/api/needs/catalog"),
  chat: (pnr: string, body: { messages: ChatMessage[]; selected: Pick<Need, "code" | "scope">[];
    dismissed: string[]; lang: "zh" | "en" }, signal?: AbortSignal) =>
    http<ChatReply>(`/api/passenger/${encodeURIComponent(pnr)}/chat`, {
      method: "POST", body: JSON.stringify({ ...body,
        selected: body.selected.map(({ code, scope }) => ({ code, scope })),
      }), signal,
    }),
  completeChat: (pnr: string, messages: ChatMessage[], selected: Pick<Need, "code" | "scope">[], signal?: AbortSignal) =>
    http<{ portals: TravelPortal[] }>(`/api/passenger/${encodeURIComponent(pnr)}/chat/complete`, {
      method: "POST", body: JSON.stringify({ messages,
        selected: selected.map(({ code, scope }) => ({ code, scope })),
      }), signal,
    }),
  chatDraft: (pnr: string, needs: Pick<Need, "code" | "scope">[], referrals: string[], signal?: AbortSignal) =>
    http<Draft>(`/api/passenger/${encodeURIComponent(pnr)}/chat/draft`, {
      method: "POST", body: JSON.stringify({ needs: needs.map(({ code, scope }) => ({ code, scope })), referrals }), signal,
    }),
  acceptOffer: (pnr: string) => post<Draft>(`/api/passenger/${encodeURIComponent(pnr)}/requests/offer`),
  editDraft: (id: number, needs: Pick<Need, "code" | "scope">[]) =>
    http<Draft>(`/api/requests/${id}/needs`, { method: "PUT", body: JSON.stringify({ needs }) }),
  discardDraft: (id: number) => http<{ ok: boolean }>(`/api/requests/${id}`, { method: "DELETE" }),
  confirmRequest: (id: number) => post<PassengerView>(`/api/requests/${id}/confirm`),
  cancelNeed: (needId: number) => post<PassengerView>(`/api/needs/${needId}/cancel`),
  reconfirm: (pnr: string) => post<PassengerView>(`/api/passenger/${encodeURIComponent(pnr)}/reconfirm`),

  staffTasks: (role: Role, place?: string | null) =>
    http<StaffView>(`/api/staff/tasks?role=${role}${place ? `&place=${encodeURIComponent(place)}` : ""}`),
  receiveTask: (id: number) => post(`/api/tasks/${id}/receive`),
  doneTask: (id: number) => post(`/api/tasks/${id}/done`),
  amendTask: (id: number, note: string) => post(`/api/tasks/${id}/amend`, { note }),
  flagTask: (id: number, note: string) => post(`/api/tasks/${id}/flag`, { note }),

  opsBoard: () => http<OpsBoard>("/api/ops/board"),
  demoDelay: (flight: string, minutes: number) => post<{ delays: Record<string, number> }>("/api/demo/delay", { flight, minutes }),
  resetDemo: (scenario: Scenario) => post<{ ok: boolean }>("/api/demo/reset", { scenario }),
};
