"""JourneyRelay — neutral functional-needs catalogue (single source of truth).

Every need the product can carry lives here: its neutral labels, the SSR code a
Customer Care agent would most likely file it under, and how it is routed to
staff roles along the journey. The analysis prompt, the API and the seed data
all read from this module, so a label or instruction is changed in one place only.

Routing uses journey *stage kinds* rather than concrete stages:
  dep       departure station (check-in, departure gate)
  flight    every flight in the itinerary (one task per flight's cabin crew)
  transfer  the connecting station (absent on direct flights)
  arr       the final arrival station
`journey.py` expands kinds into the concrete stages of a booking.

Each need also carries the wording for a suggested booking-record remark
(`booking_remarks`, REDESIGN.md §5.1): the existing channel that takes a need to
outstations and crew.

Privacy: labels, instructions and remarks are functional only — no diagnosis, no
medical wording (research doc 06-無障礙 §3.6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class Route:
    """One staff task a need creates: at which stage kind, for which role."""
    stage: str           # dep | flight | transfer | arr (booking: Customer Care, before travel)
    role: str            # cs | checkin | gate | cabin | arrival
    instruction_zh: str  # what this role must do, readable in ten seconds
    instruction_en: str = ""


@dataclass(frozen=True)
class Need:
    """One neutral functional need (mirrors the `needs` table row)."""
    code: str            # stable machine code, e.g. QUIET_WAIT
    label_zh: str        # 功能性需要（中性字句）
    label_en: str
    detail_zh: str       # one-line functional description
    detail_en: str = ""  # English mirror of detail_zh
    scope: str = "full"  # full | transfer  (segment scoping for mid-journey updates)
    ssr_hint: str = ""   # SSR code / remark a Customer Care agent would file it under
    ssr_code: str = ""   # IATA SSR code for the suggested remark; "" = OSI line (no code fits)
    ssr_joins: str = ""  # join this code's line instead when the booking already has one
    remark: str = ""     # remark wording: short upper-case English, functional only
    routes: tuple[Route, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        return f"{self.code}:{self.scope}"


QUIET_WAIT = Need(
    code="QUIET_WAIT", label_zh="安靜候機", label_en="Quiet waiting area",
    detail_zh="需要較安靜或人較少的位置等候；實際位置視乎各站設施。",
    detail_en="A quieter or less crowded place to wait; what is available depends on the station.", ssr_hint="DPNA（備註）",
    ssr_code="DPNA", remark="QUIET WAITING AREA",
    routes=(
        # Not every station has a quiet area, so the instruction names the alternative.
        Route("dep", "checkin", "如站內有安靜區則指引；否則安排人較少的位置等候",
              "Guide to the quiet area if the station has one; otherwise a less crowded place to wait"),
        Route("transfer", "arrival", "轉機時如有安靜區則指引；否則安排人較少的位置等候",
              "During transfer, guide to the quiet area if there is one; otherwise a less crowded place"),
    ),
)

PREBOARD = Need(
    code="PREBOARD", label_zh="預先登機", label_en="Pre-boarding",
    detail_zh="安排較早登機，減少在閘口排隊等候。",
    detail_en="Board earlier to reduce waiting at the gate.", ssr_hint="DPNA（備註）",
    ssr_code="DPNA", remark="PREBOARD",
    routes=(
        Route("dep", "gate", "安排預先登機（照顧者同行）",
              "Arrange pre-boarding (with caregiver)"),
        Route("transfer", "gate", "轉機航班安排預先登機（照顧者同行）",
              "Arrange pre-boarding for the connecting flight (with caregiver)"),
    ),
)

SEAT_ADJACENT = Need(
    code="SEAT_ADJACENT", label_zh="座位與家長相連", label_en="Seat next to caregiver",
    detail_zh="全程需要與照顧者相連的座位。",
    detail_en="Seats together with the caregiver for the whole journey.", ssr_hint="座位備註",
    remark="SEAT NEXT TO CAREGIVER",
    routes=(
        Route("dep", "checkin", "核對全程航班親子相連座位",
              "Verify caregiver-adjacent seats for all flights"),
        Route("flight", "cabin", "登機時輕聲引導入座",
              "Guide quietly to seats during boarding"),
    ),
)

SEAT_QUIET = Need(
    code="SEAT_QUIET", label_zh="較安靜的座位位置", label_en="Quieter seat location",
    detail_zh="希望座位遠離廚房及洗手間等人多聲雜的位置；按劃位情況安排，不包括鄰座留空。",
    detail_en="A seat away from the galley and lavatories where possible; does not include an empty neighbouring seat.",
    ssr_hint="座位備註", remark="SEAT AWAY FROM GALLEY AND LAVATORY IF AVAILABLE",
    routes=(
        Route("dep", "checkin", "核對全程座位是否遠離廚房及洗手間；可行時調位",
              "Check seats on all flights are away from galley and lavatories; move if possible"),
    ),
)

TEXT_INFO = Need(
    code="TEXT_INFO", label_zh="以文字代替廣播", label_en="Written updates instead of announcements",
    detail_zh="閘口、登機及接駁等重要資訊，需以文字通知。",
    detail_en="Gate, boarding and connection updates in writing.", ssr_hint="DPNA／DEAF（備註）",
    ssr_code="DEAF", ssr_joins="DPNA", remark="WRITTEN UPDATES NOT PA",
    routes=(
        Route("dep", "gate", "閘口或時間變更，以文字通知",
              "Send gate or time changes as a written message"),
        Route("flight", "cabin", "以文字補充重要廣播",
              "Follow up key announcements in writing"),
        Route("transfer", "arrival", "以文字通知轉機接駁資訊",
              "Send connection details in writing"),
        Route("arr", "arrival", "抵達時以文字通知行李及接駁資訊",
              "Send baggage and connection info in writing on arrival"),
    ),
)

ASK_BEFORE_TOUCH_TRANSFER = Need(
    code="ASK_BEFORE_TOUCH", scope="transfer",
    label_zh="接觸前先說明（僅轉機段）", label_en="Explain before touching (transfer only)",
    detail_zh="轉機協助時先說明要做甚麼，得到同意才作身體接觸。",
    detail_en="During transfer assistance, explain what you are about to do and ask before physical contact.",
    ssr_hint="DPNA（轉機段備註）", ssr_code="DPNA", remark="EXPLAIN AND ASK BEFORE TOUCHING AT TRANSFER ONLY",
    routes=(
        Route("transfer", "arrival", "轉機協助前先說明要做甚麼，得到同意才接觸旅客",
              "Explain the transfer assistance first and ask before touching the passenger"),
    ),
)

ASK_BEFORE_TOUCH = Need(
    code="ASK_BEFORE_TOUCH", label_zh="接觸前先說明", label_en="Explain before touching",
    detail_zh="協助時先說明要做甚麼，得到同意才作身體接觸。",
    detail_en="Staff say what they are about to do and ask before any physical contact.",
    ssr_hint="DPNA（備註）", ssr_code="DPNA", remark="EXPLAIN AND ASK BEFORE TOUCHING",
    routes=(
        Route("dep", "gate", "引導前先說明，得到同意才接觸旅客",
              "Explain first; ask before touching the passenger"),
        Route("flight", "cabin", "協助前先說明，得到同意才接觸旅客",
              "Explain before assisting; ask before touching the passenger"),
        Route("transfer", "arrival", "轉機引導前先說明，得到同意才接觸旅客",
              "Explain before guiding at transfer; ask before touching the passenger"),
    ),
)

SIMPLE_STEPS = Need(
    code="SIMPLE_STEPS", label_zh="逐步簡單說明", label_en="Simple step-by-step instructions",
    detail_zh="需要職員用簡單字句、每次說明一個步驟，並給予較多時間。",
    detail_en="Staff explain one step at a time in simple words and allow extra time.",
    ssr_hint="DPNA（備註）", ssr_code="DPNA", remark="EXPLAIN ONE STEP AT A TIME",
    routes=(
        Route("dep", "checkin", "用簡單字句逐步說明手續，給予較多時間",
              "Explain each step in simple words; allow extra time"),
        Route("dep", "gate", "逐步說明登機安排，確認旅客明白",
              "Explain boarding one step at a time; check understanding"),
        Route("flight", "cabin", "逐步說明安全指示及機上服務",
              "Explain safety instructions and service one step at a time"),
        Route("transfer", "arrival", "逐步說明轉機路線，確認旅客明白",
              "Explain the transfer route step by step; check understanding"),
    ),
)

SAFETY_BRIEFING = Need(
    code="SAFETY_BRIEFING", label_zh="個別安全講解", label_en="Individual safety briefing",
    detail_zh="起飛前由機艙組員個別講解安全須知，例如以口述或文字方式。",
    detail_en="Cabin crew explain the safety information individually before take-off, spoken or in writing.",
    ssr_hint="BLND／DEAF（備註）", remark="INDIVIDUAL SAFETY BRIEFING",
    routes=(
        Route("flight", "cabin", "起飛前向旅客個別講解安全須知",
              "Give the passenger an individual safety briefing before take-off"),
    ),
)

GUIDE = Need(
    code="GUIDE", label_zh="專人引路", label_en="Guided assistance",
    detail_zh="需要專人引路，例如由櫃檯到閘口、轉機及抵達。",
    detail_en="A staff member to guide between counters, gates and halls.", ssr_hint="BLND／MAAS",
    ssr_code="MAAS", remark="STAFF GUIDE TO GATE AND CONNECTION",
    routes=(
        Route("dep", "checkin", "安排專人由櫃檯引路至閘口",
              "Arrange staff guidance from counter to gate"),
        Route("transfer", "arrival", "安排專人引路轉機",
              "Arrange staff guidance for the connection"),
        Route("arr", "arrival", "安排專人引路至抵達大堂",
              "Arrange staff guidance to the arrivals hall"),
    ),
)

GUIDE_TRANSFER = Need(
    code="GUIDE", label_zh="專人引路（僅轉機段）", label_en="Guided assistance (transfer only)",
    detail_zh="只在轉機時需要專人引路到下一班機的閘口。",
    detail_en="A staff member to guide to the connecting gate, at the transfer only.", scope="transfer",
    ssr_hint="MAAS（轉機段）", ssr_code="MAAS", remark="STAFF GUIDE AT TRANSFER ONLY",
    routes=(
        Route("transfer", "arrival", "安排專人引路至轉機閘口（僅轉機段）",
              "Arrange staff guidance to the connecting gate (transfer only)"),
    ),
)

SEATED_WAIT = Need(
    code="SEATED_WAIT", label_zh="座位等候（毋須久站）", label_en="Seated waiting (no long standing)",
    detail_zh="可以步行，但不能長時間站立或排隊；等候時需要座位。",
    detail_en="Can walk, but cannot stand or queue for long; needs a seat while waiting.",
    ssr_hint="MAAS（備註）", ssr_code="MAAS", remark="SEAT WHILE WAITING NO LONG STANDING",
    routes=(
        Route("dep", "checkin", "安排座位等候，毋須站立排隊",
              "Offer a seat while waiting; no standing in the queue"),
        Route("dep", "gate", "閘口安排座位，輪到時再請旅客登機",
              "Seat at the gate; call the passenger when it is their turn"),
        Route("transfer", "arrival", "轉機及保安檢查時安排座位等候",
              "Offer a seat while waiting at transfer and security"),
    ),
)

ARRIVAL_HANDOVER = Need(
    code="ARRIVAL_HANDOVER", label_zh="抵達時交給接機人", label_en="Handover to the person meeting me",
    detail_zh="抵達後由職員陪同到抵達大堂，交給接機的親友。",
    detail_en="Staff accompany the passenger to the arrivals hall and hand over to the person meeting them.",
    ssr_hint="MAAS（備註）", ssr_code="MAAS", remark="ESCORT TO MEETER AT ARRIVAL",
    routes=(
        Route("arr", "arrival", "陪同旅客至抵達大堂，交給接機人",
              "Accompany the passenger to arrivals and hand over to the person meeting them"),
    ),
)

WHEELCHAIR_FULL = Need(
    code="WHEELCHAIR", label_zh="輪椅協助（全程）", label_en="Wheelchair assistance (full journey)",
    detail_zh="出發、轉機及抵達都需要輪椅接駁。",
    detail_en="Wheelchair assistance at departure, transfer and arrival.", ssr_hint="WCHR",
    ssr_code="WCHR", remark="ASSISTANCE AT ALL STATIONS",
    routes=(
        Route("dep", "checkin", "安排出發輪椅（櫃檯至登機）",
              "Arrange departure wheelchair (counter to gate)"),
        Route("transfer", "arrival", "安排轉機輪椅接駁",
              "Arrange transfer wheelchair"),
        Route("arr", "arrival", "安排抵達輪椅接駁",
              "Arrange arrival wheelchair"),
    ),
)

WHEELCHAIR_TRANSFER = Need(
    code="WHEELCHAIR", label_zh="輪椅協助（僅轉機段）", label_en="Wheelchair assistance (transfer only)",
    detail_zh="只在轉機時需要輪椅接駁。",
    detail_en="Wheelchair for the connection only.", scope="transfer", ssr_hint="WCHR（轉機段）",
    ssr_code="WCHR", remark="TRANSFER STATION ONLY",
    routes=(
        Route("transfer", "arrival", "安排轉機輪椅接駁（僅轉機段）",
              "Arrange transfer wheelchair (connection only)"),
    ),
)

# The fallback: anything the list cannot carry goes to a person (REDESIGN.md §5.2).
CS_CALLBACK = Need(
    code="CS_CALLBACK", label_zh="請客服聯絡我", label_en="Ask Customer Care to contact me",
    detail_zh="有清單以外的需要，請客服聯絡你了解及安排。",
    detail_en="For needs outside this list: Customer Care contacts you to arrange them.",
    ssr_hint="OSI", remark="CONTACT PAX RE ASSISTANCE NEEDS",
    routes=(
        Route("booking", "cs", "聯絡旅客，了解清單以外的需要並安排",
              "Contact the passenger about needs outside the list and arrange them"),
    ),
)

# Display order for chips, lists and the catalogue picker.
CATALOG: tuple[Need, ...] = (
    QUIET_WAIT, PREBOARD, SEAT_ADJACENT, SEAT_QUIET, TEXT_INFO,
    ASK_BEFORE_TOUCH, ASK_BEFORE_TOUCH_TRANSFER, SIMPLE_STEPS,
    SAFETY_BRIEFING, GUIDE, GUIDE_TRANSFER, SEATED_WAIT, ARRIVAL_HANDOVER,
    WHEELCHAIR_FULL, WHEELCHAIR_TRANSFER, CS_CALLBACK,
)
BY_KEY: dict[str, Need] = {n.key: n for n in CATALOG}

# Customer Care checks each booking and files the remark: a full review on the
# first confirmed request, a remark update after later changes (REDESIGN.md §5.3).
CS_REVIEW_INSTRUCTION = "核對可行安排，把備註寫入訂位紀錄"
CS_REVIEW_INSTRUCTION_EN = "Review the arrangements and file the booking remark"
CS_UPDATE_INSTRUCTION = "需要有更新：核對後更新訂位備註"
CS_UPDATE_INSTRUCTION_EN = "Needs changed: check and update the booking remark"
CS_FILING_INSTRUCTIONS = (CS_REVIEW_INSTRUCTION, CS_UPDATE_INSTRUCTION)


@dataclass(frozen=True)
class Referral:
    """Something a passenger may ask for that this service cannot arrange
    directly (REDESIGN.md §5.2). The engine outputs the code only; the wording
    the passenger reads comes from here."""
    code: str
    label_zh: str
    label_en: str
    advice_zh: str  # why it cannot be arranged here and what happens instead
    advice_en: str


REFERRALS: tuple[Referral, ...] = (
    Referral("MEDICAL", "醫療許可、氧氣或醫療器材", "Medical clearance, oxygen or medical equipment",
             "這類安排需要醫護人員預先評估，不能在這裡直接安排。請盡早聯絡客服。",
             "These need a medical assessment in advance and cannot be arranged here. Please contact Customer Care early."),
    Referral("SERVICE_ANIMAL", "服務犬同行", "Travelling with a service dog",
             "需要預先核實文件及目的地的入境規定，由客服處理。",
             "Documents and the destination's entry rules must be checked in advance by Customer Care."),
    Referral("OWN_MOBILITY_AID", "自備輪椅或助行器材", "Your own wheelchair or mobility aid",
             "需要預先提供尺寸、重量及電池資料，由客服確認可否運載。",
             "Customer Care needs its size, weight and battery details in advance to confirm carriage."),
    Referral("UNACCOMPANIED_MINOR", "兒童獨自乘機", "A child travelling alone",
             "兒童獨自乘機另有獨立的申請程序，由客服處理。",
             "Children travelling alone go through a separate application handled by Customer Care."),
    Referral("EXTRA_SEAT", "鄰座留空或額外座位", "An empty neighbouring seat or an extra seat",
             "鄰座留空一般需要另購座位，前線不能保證。客服可以說明做法。",
             "Keeping the next seat empty usually means buying an extra seat; frontline staff cannot promise it. Customer Care can explain the options."),
    Referral("OTHER", "清單以外的其他需要", "Another need outside this list",
             "這項需要未能在這裡直接安排，可以請客服聯絡你。",
             "This cannot be arranged here directly; you can ask Customer Care to contact you."),
)


def get_need(code: str, scope: str = "full") -> Need | None:
    return BY_KEY.get(f"{code}:{scope}")


def order_index(code: str, scope: str = "full") -> int:
    key = f"{code}:{scope}"
    return next((i for i, n in enumerate(CATALOG) if n.key == key), len(CATALOG))


def booking_remarks(needs: Iterable[Need]) -> list[str]:
    """Suggested booking-record remark lines for a whole booking (REDESIGN.md §5.1).

    One SSR line per code, plus one OSI line for needs no code fits. Built from
    catalogue wording only, so no passenger text or diagnosis can reach it. The
    layout follows the agent entry format Cathay publishes and is illustrative:
    Customer Care confirms the code before anything is filed.
    """
    chosen = sorted(set(needs), key=CATALOG.index)
    full = {n.code for n in chosen if n.scope == "full"}
    chosen = [n for n in chosen if n.scope == "full" or n.code not in full]
    present = {n.ssr_code for n in chosen}
    by_code: dict[str, list[str]] = {}
    for n in chosen:
        code = n.ssr_joins if n.ssr_joins and n.ssr_joins in present else n.ssr_code
        by_code.setdefault(code, []).append(n.remark)
    lines = [f"SR {code} CX NN1-{'/'.join(parts)}" for code, parts in by_code.items() if code]
    if "" in by_code:
        lines.append(f"OS CX {'/'.join(by_code[''])}")
    return lines
