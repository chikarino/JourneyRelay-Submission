"use client";
// Demo hub — entry point for the team; the passenger, staff and demo pages
// carry their own chrome and do not link back here. Bilingual: the title comes
// from the DICT (hub.*); the rest of this small team page uses local records.

import Link from "next/link";
import { Lang, LangToggle, t, useLang } from "../lib/i18n";
import { ChevronRight } from "../lib/ui";

const LINKS: { href: string; title: Record<Lang, string>; desc: Record<Lang, string> }[] = [
  {
    href: "/demo",
    title: { zh: "雙螢幕示範", en: "Two-screen demo" },
    desc: {
      zh: "左邊旅客手機、右邊前線平板，即時同步。Pitch 用這頁。",
      en: "Passenger phone on the left, frontline tablet on the right, in live sync. Use this page for the pitch.",
    },
  },
  {
    href: "/passenger/CXDEMO1",
    title: { zh: "旅客 · 管理訂位", en: "Passenger · Manage booking" },
    desc: {
      zh: "旅途協助：說一次、預覽確認、按旅程階段看安排進度。",
      en: "Journey assistance: say it once, preview and confirm, then watch arrangements progress by journey stage.",
    },
  },
  {
    href: "/staff?role=arrival&place=HKG",
    title: { zh: "前線平板", en: "Frontline tablet" },
    desc: { zh: "按崗位及地點列出任務。", en: "Tasks listed by role and place." },
  },
  {
    href: "/ops",
    title: { zh: "營運看板", en: "Ops board" },
    desc: {
      zh: "各旅客、各崗位的進度，及需要跟進的事項。",
      en: "Progress per passenger and per role, plus items needing follow-up.",
    },
  },
];

const KICKER = "Cathay Hackathon 2026 · Challenge #3 Accessibility · Cathay/Gradient";

export default function Home() {
  const [lang, setLang] = useLang();

  return (
    <main className="mx-auto max-w-3xl px-5 py-12">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-ink-2">{KICKER}</p>
        <LangToggle lang={lang} onChange={setLang} />
      </div>
      <h1 className="mt-1 text-3xl font-semibold">{t(lang, "hub.title")}</h1>

      <ul className="mt-8 divide-y divide-line border-y border-line bg-white">
        {LINKS.map((l) => (
          <li key={l.href}>
            <Link href={l.href} className="flex items-center justify-between gap-4 px-4 py-4 hover:bg-paper-light">
              <span>
                <span className="block font-semibold text-cx-jade-dark">{l.title[lang]}</span>
                <span className="block text-sm text-ink-2">{l.desc[lang]}</span>
              </span>
              <ChevronRight className="size-5 shrink-0 text-ink-3" />
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
