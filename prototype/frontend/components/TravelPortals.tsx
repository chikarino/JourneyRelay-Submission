import { TravelPortal } from "../lib/api";
import { Lang, t } from "../lib/i18n";

export function TravelPortals({ portals, lang }: { portals: TravelPortal[]; lang: Lang }) {
  return <section aria-labelledby="travel-portals-title" className="mt-5 border-y border-line bg-white">
    <div className="py-3">
      <h3 id="travel-portals-title" className="font-semibold">{t(lang, "portals.title")}</h3>
      <p className="mt-1 text-xs text-ink-2">{t(lang, "portals.intro")}</p>
    </div>
    {portals.length ? <ul className="divide-y divide-line border-t border-line">
      {portals.map((portal) => <li key={portal.id}>
        <a href={portal.url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer"
          className="flex min-h-16 items-center justify-between gap-3 py-3 text-cx-green focus-visible:outline focus-visible:outline-2 focus-visible:outline-cx-jade">
          <span className="min-w-0">
            <span className="block text-sm font-semibold underline underline-offset-4">{lang === "en" ? portal.title_en : portal.title_zh}</span>
            <span className="mt-1 block text-xs text-ink-2">{portal.station} · {portal.provider}</span>
          </span>
          <span aria-hidden="true" className="shrink-0 text-lg">↗</span>
          <span className="sr-only">{t(lang, "portals.new_tab")}</span>
        </a>
      </li>)}
    </ul> : <p className="pb-3 text-sm text-ink-2">{t(lang, "portals.empty")}</p>}
    <p className="border-t border-line py-3 text-xs text-ink-2">{t(lang, "portals.external")}</p>
  </section>;
}
