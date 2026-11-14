"use client";
// JourneyRelay bilingual UI strings. zh = Traditional Chinese written style
// (書面語), en = plain English. Keys must exist in both languages (CI-checked
// by tests/test_bilingual on the backend; here by the typed DICT shape).

import { useEffect, useState } from "react";

export type Lang = "zh" | "en";
export const LANG_STORAGE_KEY = "jr-lang";

type Entry = { zh: string; en: string };

export const DICT: Record<string, Entry> = {
  // Passenger shell
  "shell.title": { zh: "管理訂位", en: "Manage booking" },
  "shell.demo_note": { zh: "概念設計 · 虛構旅客 · 班表來自 OAG", en: "Concept design · fictional passenger · schedule from OAG" },
  "passenger.delay": { zh: "{flight} 預計延誤 {minutes} 分鐘。", en: "{flight} is expected to be {minutes} minutes late." },
  "passenger.connection": { zh: "轉機時間由 {scheduled} 分鐘縮短至 {expected} 分鐘。", en: "Your connection shortens from {scheduled} to {expected} minutes." },
  "passenger.offer_q": { zh: "需要職員帶你直接去下一班機的閘口嗎？", en: "Would you like a staff member to take you straight to your connecting gate?" },
  "passenger.offer_btn": { zh: "加入「{label}」", en: "Add \"{label}\"" },
  "passenger.delay_source_demo": { zh: "示範情境：延誤由示範頁設定", en: "Demo scenario: delay set from the demo page" },
  "shell.loading": { zh: "載入中…", en: "Loading…" },
  "passenger.booking_ref": { zh: "訂位參考編號", en: "Booking reference" },
  "passenger.manage": { zh: "管理行程", en: "Manage trip" },
  "passenger.assist": { zh: "旅途協助", en: "Journey assistance" },
  "passenger.arranged_of": { zh: "已安排或已通知 {done} / {total}", en: "Arranged or notified {done} / {total}" },
  "passenger.none_yet": { zh: "未有安排", en: "No arrangements yet" },
  "passenger.closed_item": { zh: "示範未開放", en: "Not in this demo" },
  "passenger.intro": { zh: "透過簡短對話，一步步找出適合你的旅途協助。", en: "Find useful journey assistance through a short conversation." },
  "passenger.start": { zh: "開始", en: "Start" },
  "passenger.progress_label": { zh: "安排進度", en: "Arrangement progress" },
  "passenger.followup_n": { zh: "{n} 項安排跟進中", en: "{n} arrangements being followed up" },
  "passenger.reconfirm_title": { zh: "出發前確認：", en: "Before departure:" },
  "passenger.reconfirm_q": { zh: "以下安排仍然適用嗎？", en: "Do these arrangements still apply?" },
  "passenger.reconfirm_yes": { zh: "仍然適用", en: "Still applies" },
  "passenger.reconfirm_update": { zh: "有更新", en: "I have an update" },
  "passenger.stages": { zh: "沿途安排", en: "Arrangements along the way" },
  "passenger.my_needs": { zh: "我的需要", en: "My needs" },
  "passenger.no_longer": { zh: "不再需要", en: "No longer needed" },
  "passenger.confirm_cancel": { zh: "確定取消", en: "Confirm cancellation" },
  "passenger.keep": { zh: "保留", en: "Keep" },
  "passenger.cancelled": { zh: "已取消", en: "Cancelled" },
  "passenger.added_midjourney": { zh: "行程中新增", en: "Added mid-journey" },
  "passenger.update_or_add": { zh: "補充或更新需要", en: "Add or update a need" },
  "passenger.history": { zh: "安排紀錄", en: "Arrangement history" },
  "passenger.items": { zh: "{n} 項", en: "{n} entries" },
  "passenger.no_needs_this_stage": { zh: "此段毋須特別安排", en: "Nothing special needed for this leg" },
  "passenger.flagged_note": { zh: "相關團隊正在跟進，如有需要會聯絡你。", en: "The team is following up and will contact you if needed." },
  "passenger.amend_prefix": { zh: "調整：", en: "Adjustment: " },
  "passenger.read_aloud": { zh: "朗讀安排", en: "Read arrangements aloud" },
  "passenger.shared_toast": { zh: "已分享", en: "Shared" },
  "passenger.shared_new": { zh: "客服會先核對並寫入訂位紀錄，沿途各個崗位隨後收到。", en: "Customer Care checks and files your needs first; every team along the way then receives them." },
  "passenger.status_wait_care": { zh: "待客服寫入訂位紀錄", en: "waiting for Customer Care to file it" },
  "passenger.status_on_day": { zh: "出發當日由當值職員接手", en: "picked up by the team on duty on the day" },
  "passenger.reuse_note": { zh: "你上次行程確認過 {n} 項需要，下一步可以直接沿用。", en: "You confirmed {n} needs on your last trip; you can reuse them in the next step." },
  "preview.from_last_trip": { zh: "上次行程", en: "Last trip" },
  "passenger.shared_update": { zh: "只通知受影響的崗位，其他安排不變。", en: "Only the affected teams were notified; other arrangements unchanged." },
  "passenger.reconfirmed_toast": { zh: "已確認", en: "Confirmed" },
  "passenger.reconfirmed_body": { zh: "出發前安排仍然適用，沿途崗位會照常準備。", en: "Your arrangements still apply; teams will prepare as planned." },
  // Compose sheet
  "chat.title": { zh: "一起找出合適的協助", en: "Find the help you need" },
  "chat.already_active": { zh: "已申請客服聯絡，可於「我的需要」管理", en: "Callback already requested; manage it in My needs" },
  "chat.greeting": { zh: "旅途中，甚麼事情令你感到困難？選一個方向開始，或用你習慣的語言告訴我。", en: "What could be difficult during your journey? Pick a starting point, or tell me in your own words." },
  "chat.start_waiting": { zh: "等候、人多或排隊", en: "Waiting, crowds or queues" },
  "chat.start_mobility": { zh: "步行或轉機", en: "Walking or transfers" },
  "chat.start_communication": { zh: "接收資訊或溝通", en: "Updates or communication" },
  "chat.start_seating": { zh: "座位安排", en: "Seating" },
  "chat.start_unsure": { zh: "未確定，請幫我想想", en: "I am not sure yet" },
  "chat.conversation": { zh: "旅途協助對話", en: "Journey assistance conversation" },
  "chat.you": { zh: "你", en: "You" },
  "chat.assistant": { zh: "旅途助手", en: "Journey assistant" },
  "chat.working": { zh: "正在尋找合適的協助…", en: "Finding relevant assistance…" },
  "chat.found": { zh: "建議（{n} 項）", en: "Suggestions ({n})" },
  "chat.added": { zh: "已加入", en: "Added" },
  "chat.add_of": { zh: "加入「{label}」", en: "Add \"{label}\"" },
  "chat.add_all": { zh: "全部加入", en: "Add all" },
  "chat.selected": { zh: "已選 {n} 項 · 尚未分享", en: "{n} selected · not shared yet" },
  "chat.recheck": { zh: "請再確認這項選擇：", en: "Please check this selection:" },
  "chat.answer": { zh: "你的回覆", en: "Your reply" },
  "chat.placeholder": { zh: "輸入簡短回覆…", en: "Type a short reply…" },
  "chat.send": { zh: "傳送", en: "Send" },
  "chat.voice_language": { zh: "語音輸入語言", en: "Voice input language" },
  "chat.speech_error": { zh: "暫時無法使用語音輸入，請輸入回覆或選擇按鈕。", en: "Voice input is unavailable. Type a reply or choose a button." },
  "chat.review": { zh: "檢視已選需要（{n}）", en: "Review my needs ({n})" },
  "chat.finish": { zh: "結束對話，查看實用連結", en: "Finish chat and see useful links" },
  "chat.finished_title": { zh: "為旅程準備的實用入口", en: "Useful links for your journey" },
  "chat.done": { zh: "返回行程", en: "Return to my journey" },
  "chat.keep_chatting": { zh: "繼續對話", en: "Keep chatting" },
  "chat.send_before_finish": { zh: "請先傳送回覆，或清空輸入框，再結束對話。", en: "Send your reply or clear the input before finishing." },
  "portals.title": { zh: "適合你的服務及資訊", en: "Services and information for you" },
  "portals.intro": { zh: "根據你的需要及行程整理的官方入口。", en: "Official portals selected for your needs and itinerary." },
  "portals.new_tab": { zh: "（在新分頁開啟）", en: "(opens in a new tab)" },
  "portals.empty": { zh: "目前未有適合這段行程的官方入口。你仍可檢視已選需要或繼續對話。", en: "No suitable official portals for this itinerary yet. You can still review your needs or keep chatting." },
  "portals.external": { zh: "連結僅供參考；開放時間、位置及預約要求請以服務提供者為準。", en: "Check the provider for locations, opening hours and booking requirements." },
  "chat.confirm_hint": { zh: "下一步仍可修改，按「確認分享」後職員才會收到。", en: "You can still edit in the next step. Staff receive your needs only after you confirm sharing." },
  "chat.restart": { zh: "重新開始對話", en: "Start a new conversation" },
  "chat.error": { zh: "暫時無法完成，已保留你的回覆及選擇。請重試。", en: "We could not complete that step. Your reply and selections are kept. Please retry." },
  "chat.limit": { zh: "這次對話已達上限。請檢視已選需要，或重新開始對話。", en: "This conversation has reached its limit. Review your selections or start a new conversation." },
  "compose.close": { zh: "關閉", en: "Close" },
  "compose.mic": { zh: "說話輸入", en: "Speak instead" },
  "compose.mic_listening": { zh: "聆聽中…", en: "Listening…" },
  "compose.mic_stop": { zh: "停止聆聽", en: "Stop listening" },
  // Preview sheet
  "preview.title": { zh: "請確認以下需要", en: "Please confirm these needs" },
  "preview.empty": { zh: "未有已選需要。你可以返回對話補充，或者請客服聯絡你。", en: "No needs are selected. Go back to chat to describe your needs, or ask Customer Care to contact you." },
  "preview.referral_title": { zh: "以下事項未能在這裡直接安排", en: "These cannot be arranged here directly" },
  "preview.callback_add": { zh: "請客服聯絡我", en: "Ask Customer Care to contact me" },
  "preview.callback_added": { zh: "已加入「請客服聯絡我」。確認後，客服會收到並聯絡你。", en: "Added. After you confirm, Customer Care is asked to contact you." },
  "preview.callback_topics": { zh: "客服會看到事項類別（{topics}），其他崗位不會看到。", en: "Customer Care will see the topic ({topics}); other teams will not." },
  "preview.referral_phone": { zh: "如需即時協助，可直接致電國泰客服，電話以國泰網站為準。", en: "For urgent help, call Cathay Customer Care directly; the number is on the Cathay website." },
  "preview.suggest_title": { zh: "根據你的描述，AI 建議以下協助", en: "Based on your description, the AI suggests these kinds of help" },
  "preview.suggest_hint": { zh: "這只是建議。請揀選你實際需要的；確認前不會分享任何項目。", en: "Suggestions only — pick what you actually need. Nothing is shared until you confirm." },
  "preview.suggest_apply": { zh: "套用所選需要", en: "Apply selected needs" },
  "preview.suggest_decline": { zh: "返回對話自行揀選", en: "Back to chat to choose" },
  "preview.transfer_only": { zh: "僅轉機段", en: "Transfer leg only" },
  "preview.remove": { zh: "移除", en: "Remove" },
  "preview.remove_of": { zh: "移除「{label}」", en: "Remove \"{label}\"" },
  "preview.add": { zh: "加入", en: "Add" },
  "preview.staff_only": { zh: "職員只會看到以上需要，每個崗位只看到自己要做的事；不會看到你的原文及任何診斷。", en: "Staff see only the needs above, each team only its own part; never your own words or any diagnosis." },
  "preview.update_note": { zh: "原有安排保持不變，只會通知受影響的崗位。", en: "Existing arrangements stay; only affected teams are notified." },
  "preview.remarks_title": { zh: "訂位紀錄的建議備註（示意）", en: "Suggested booking-record remark (illustrative)" },
  "preview.remarks_note": { zh: "客服核對後寫入訂位紀錄，沿現有系統通知各站及機組。只列功能需要，不含診斷及你的原文。格式僅供示意。", en: "Customer Care checks this before adding it to the booking record, which carries it to every station and the crew. Functional needs only: no diagnosis, none of your own words. Illustrative format." },
  "preview.situation": { zh: "AI 對你行程的理解", en: "The AI's understanding of your trip" },
  "preview.confirm": { zh: "確認並分享", en: "Confirm and share" },
  "preview.back": { zh: "返回對話", en: "Back to chat" },
  "preview.cancel_share": { zh: "取消，不分享", en: "Cancel — do not share" },
  // Staff page
  "staff.title": { zh: "前線協助任務", en: "Frontline assistance tasks" },
  "staff.demo_note": { zh: "概念設計 · 示範資料", en: "Concept design · demo data" },
  "staff.role": { zh: "崗位", en: "Role" },
  "staff.place": { zh: "地點", en: "Place" },
  "staff.open_n": { zh: "{n} 待辦", en: "{n} open" },
  "staff.done": { zh: "完成", en: "Clear" },
  "staff.updated_at": { zh: "更新於 {t}", en: "Updated {t}" },
  "staff.empty": { zh: "目前沒有協助任務。", en: "No assistance tasks right now." },
  "staff.receive": { zh: "已收到", en: "Received" },
  "staff.done_btn": { zh: "已安排", en: "Arranged" },
  "staff.amend": { zh: "調整", en: "Adjust" },
  "staff.flag": { zh: "需要跟進", en: "Follow up" },
  "staff.save": { zh: "儲存", en: "Save" },
  "staff.submit": { zh: "提交", en: "Submit" },
  "staff.cancel": { zh: "取消", en: "Cancel" },
  "staff.amend_placeholder": { zh: "調整內容（旅客會看到）", en: "Adjustment (visible to the passenger)" },
  "staff.flag_placeholder": { zh: "跟進原因（只供內部）", en: "Follow-up reason (internal only)" },
  "staff.amend_note": { zh: "（旅客看得到）", en: " (visible to the passenger)" },
  "staff.flag_note": { zh: "（只供內部）", en: " (internal only)" },
  "staff.cancelled_note": { zh: "旅客已取消這項需要，毋須處理。", en: "The passenger cancelled this need; no action required." },
  "staff.ssr": { zh: "建議 SSR {code}", en: "Suggested SSR {code}" },
  "staff.remarks_title": { zh: "建議訂位備註（整個訂位）", en: "Suggested booking remarks (whole booking)" },
  "staff.remarks_note": { zh: "核對後寫入訂位紀錄，代碼由客服確認。只列功能需要。格式僅供示意。", en: "Check before adding to the booking record; Customer Care confirms the code. Functional needs only. Illustrative format." },
  "staff.topics": { zh: "旅客提及：{topics}", en: "Passenger mentioned: {topics}" },
  "staff.remark_channel": { zh: "這個崗位經訂位紀錄的備註接收安排，不用任務卡，毋須在此回報。以下是對方會收到的內容。", en: "This team receives arrangements through the booking remark, not task cards; nothing to acknowledge here. Below is what they will receive." },
  "staff.arranged_at": { zh: "已安排 {t}", en: "Arranged {t}" },
  "staff.received_at": { zh: "已收到 {t}", en: "Received {t}" },
  "staff.arrival_time": { zh: "航班抵達", en: "Flight arrival" },
  "staff.dep_time": { zh: "航班起飛", en: "Flight departure" },
  "staff.delay": { zh: "延誤 {minutes} 分鐘", en: "{minutes} min late" },
  "staff.due_soon": { zh: "時間臨近，未接手", en: "Due soon, unclaimed" },
  "staff.receive_all": { zh: "全部已收到", en: "Receive all" },
  "staff.done_all": { zh: "全部已安排", en: "Arrange all" },
  "staff.is_update": { zh: "行程中新增", en: "Added mid-journey" },
  // Demo header
  "demo.title": { zh: "JourneyRelay · 雙螢幕示範", en: "JourneyRelay · two-screen demo" },
  "demo.ai_ready": { zh: "本機 AI 就緒 · {model}", en: "On-device AI ready · {model}" },
  "demo.api_ready": { zh: "雲端 AI 就緒 · {model}", en: "Cloud AI ready · {model}" },
  "demo.ai_down": { zh: "AI 引擎未就緒 · 請檢查後端", en: "AI engine not ready · check the backend" },
  "demo.ai_checking": { zh: "正在檢查 AI 引擎…", en: "Checking AI engine…" },
  "demo.engine": { zh: "AI 引擎", en: "AI engine" },
  "demo.engine_local": { zh: "本機 {model}", en: "On-device {model}" },
  "demo.engine_api": { zh: "雲端 {model}", en: "Cloud {model}" },
  "demo.reset": { zh: "重設", en: "Reset" },
  "demo.reset_fresh": { zh: "由頭開始", en: "From the start" },
  "demo.reset_midjourney": { zh: "行程途中", en: "Mid-journey" },
  "demo.reset_family": { zh: "家庭轉機", en: "Family transfer" },
  "demo.reset_ok_fresh": { zh: "已重設：陳太未有任何需要", en: "Reset: Chan has no needs yet" },
  "demo.reset_ok_mid": { zh: "已重設：行程途中", en: "Reset: mid-journey" },
  "demo.reset_ok_family": { zh: "已重設：陳太與兩名兒童", en: "Reset: Mrs Chan and two children" },
  "demo.scenario": { zh: "示範情境", en: "Scenario" },
  "demo.delay_on": { zh: "CX100 延誤 50 分鐘", en: "CX100 50 min late" },
  "demo.delay_off": { zh: "取消延誤", en: "Clear delay" },
  "demo.reset_fail": { zh: "重設失敗：{msg}", en: "Reset failed: {msg}" },
  "demo.frontline": { zh: "前線（任務卡）", en: "Frontline (task cards)" },
  "demo.preview_only": { zh: "經備註接收（只供預覽）", en: "Via booking remark (preview)" },
  "demo.ops": { zh: "營運看板", en: "Ops board" },
  "demo.hub": { zh: "示範首頁", en: "Demo home" },
  "demo.phone_caption": { zh: "旅客手機 · 管理訂位（概念）", en: "Passenger phone · manage booking (concept)" },
  "demo.tablet_caption": { zh: "前線平板 · {view}", en: "Frontline tablet · {view}" },
  // Hub
  "hub.title": { zh: "JourneyRelay 一路有應", en: "JourneyRelay" },
  // Ops
  "ops.title": { zh: "營運看板", en: "Ops board" },
};

export function t(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  const entry = DICT[key];
  if (!entry) return key;
  let text = entry[lang];
  if (vars) {
    for (const [name, value] of Object.entries(vars)) text = text.replaceAll(`{${name}}`, String(value));
  }
  return text;
}

export function useLang(): [Lang, (lang: Lang) => void] {
  const [lang, setLang] = useState<Lang>("zh");
  useEffect(() => {
    const read = () => {
      const stored = window.localStorage.getItem(LANG_STORAGE_KEY);
      if (stored === "en" || stored === "zh") setLang(stored);
    };
    read();
    // One language for the whole app: a switch in any page or /demo frame reaches the others.
    window.addEventListener("storage", read);
    return () => window.removeEventListener("storage", read);
  }, []);
  const update = (next: Lang) => {
    setLang(next);
    window.localStorage.setItem(LANG_STORAGE_KEY, next);
  };
  return [lang, update];
}

export function LangToggle({ lang, onChange }: { lang: Lang; onChange: (l: Lang) => void }) {
  // Inside the /demo frames the demo header's toggle drives every screen, so frames show none.
  const [embedded, setEmbedded] = useState(false);
  useEffect(() => setEmbedded(window.self !== window.top), []);
  if (embedded) return null;
  return (
    <div className="flex shrink-0 text-xs font-semibold" role="group" aria-label="Language / 語言">
      <button aria-pressed={lang === "zh"} onClick={() => onChange("zh")}
        className={`-ml-px min-h-9 whitespace-nowrap border px-2.5 first:ml-0 ${lang === "zh" ? "relative z-10 border-cx-green bg-cx-green text-white" : "border-line-strong bg-white text-ink hover:bg-paper-light"}`}>
        中文
      </button>
      <button aria-pressed={lang === "en"} onClick={() => onChange("en")}
        className={`-ml-px min-h-9 whitespace-nowrap border px-2.5 first:ml-0 ${lang === "en" ? "relative z-10 border-cx-green bg-cx-green text-white" : "border-line-strong bg-white text-ink hover:bg-paper-light"}`}>
        EN
      </button>
    </div>
  );
}
