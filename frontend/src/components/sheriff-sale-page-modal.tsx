"use client";

import { CalendarDays, Clock, ExternalLink, Gavel, MapPin, X } from "lucide-react";
import { useEffect, useState } from "react";

import { getSalePage, type SalePage } from "@/services/properties";
import type { Property } from "@/types/property";

function basisLabel(basis: "notice" | "county_typical" | null, county: string): string {
  if (basis === "notice") return "From this sale's notice";
  if (basis === "county_typical") return `Typical for ${county} County sales`;
  return "Not published on the listing";
}

function SaleLogistics({ page }: { page: SalePage }) {
  const { date, time, location, basis } = page.sale_logistics;
  return (
    <section className="mb-4 rounded-xl border border-teal-200 bg-teal-50/70 p-3" aria-label="Sale time and location">
      <div className="grid gap-3 sm:grid-cols-[auto_auto_1fr]">
        <div className="flex items-start gap-2">
          <CalendarDays className="mt-0.5 h-4 w-4 shrink-0 text-teal-700" />
          <div><p className="text-[11px] font-semibold uppercase tracking-wide text-teal-800">Sale date</p><p className="font-bold text-slate-950">{date ?? "—"}</p></div>
        </div>
        <div className="flex items-start gap-2">
          <Clock className="mt-0.5 h-4 w-4 shrink-0 text-teal-700" />
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-teal-800">Time</p>
            <p className="font-bold text-slate-950">{time ?? "—"}</p>
            <p className="text-[10px] text-slate-500">{basisLabel(basis.time, page.county)}</p>
          </div>
        </div>
        <div className="flex items-start gap-2">
          <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-teal-700" />
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-teal-800">Location</p>
            <p className="font-semibold text-slate-950">{location ?? "—"}</p>
            <p className="text-[10px] text-slate-500">{basisLabel(basis.location, page.county)}</p>
          </div>
        </div>
      </div>
      <p className="mt-2 border-t border-teal-200 pt-2 text-[11px] text-slate-600">
        Prevailing local time. Sales are often adjourned; confirm with the {page.county} County Sheriff&apos;s Office before attending.
      </p>
    </section>
  );
}

/** The sale's actual CivilView detail page, fetched live and shown in place. */
export function SheriffSalePageModal({ property, onClose }: { property: Property; onClose: () => void }) {
  const [page, setPage] = useState<SalePage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getSalePage(property.sheriff_sale_id)
      .then((result) => { if (active) setPage(result); })
      .catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [property.sheriff_sale_id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[2200] flex items-center justify-center bg-slate-950/50 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Sheriff sale page" onClick={(event) => event.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 px-5 py-4">
          <div>
            <h2 className="flex items-center gap-2 font-bold text-slate-950"><Gavel className="h-4 w-4 text-teal-600" />{page?.title ?? "Sheriff sale page"}</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Court case {property.court_case_number ?? "—"} · Sheriff # {property.sheriff_number}
              {page && ` · ${page.listing === "open" ? "Open listing" : "Sold/cancelled history"}`}
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100" aria-label="Close"><X className="h-5 w-5" /></button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {error ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{error}</div>
          ) : !page ? (
            <div className="space-y-2">{[1, 2, 3, 4, 5, 6].map((item) => <div key={item} className="h-8 animate-pulse rounded bg-slate-100" />)}<p className="pt-2 text-xs text-slate-500">Loading the live page from CivilView…</p></div>
          ) : (
            <>
              <SaleLogistics page={page} />
              <dl className="divide-y divide-slate-100 rounded-xl border border-slate-200">
                {page.fields.map((field) => (
                  <div key={field.label} className="grid grid-cols-[10rem_1fr] gap-3 px-3 py-2 text-sm">
                    <dt className="text-slate-500">{field.label}</dt>
                    <dd className="whitespace-pre-line font-medium text-slate-900">{field.value || "—"}</dd>
                  </div>
                ))}
              </dl>
              {page.status_history.length > 0 && (
                <div className="mt-4">
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Status history</h3>
                  <div className="divide-y divide-slate-100 rounded-xl border border-slate-200 text-sm">
                    {page.status_history.map((event, index) => (
                      <div key={`${event.status}-${event.date}-${index}`} className="flex justify-between gap-3 px-3 py-1.5">
                        <span className="text-slate-800">{event.status}</span><span className="tabular-nums text-slate-500">{event.date}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {page.notes.map((note) => <p key={note} className="mt-3 text-xs text-slate-500">{note}</p>)}
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 bg-slate-50 px-5 py-3 text-xs text-slate-500">
          <span>{page ? `Live from CivilView · ${new Date(page.fetched_at).toLocaleString()}` : "Source: CivilView SalesWeb"}</span>
          {(page?.county_search_url) && (
            <a href={page.county_search_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-semibold text-teal-700 hover:underline">
              {page.county} County listings on CivilView <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
