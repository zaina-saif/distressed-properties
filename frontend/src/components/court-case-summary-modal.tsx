"use client";

import { CalendarDays, Clock, FileText, Gavel, MapPin, Scale, X } from "lucide-react";
import { useEffect, useState } from "react";

import { getCourtCase, type CourtCaseEvent, type CourtCaseSummary } from "@/services/properties";
import type { Property } from "@/types/property";

const money = (value: number | null) => value == null ? null : value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const day = (value: string | null) => value ? new Date(`${value}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : null;

const EVENT_LABEL: Record<CourtCaseEvent["status"], string> = {
  scheduled: "On the calendar",
  not_held: "Not held",
  passed: "Date passed; result not published",
  dropped: "Taken off the calendar",
};

function Fact({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className="grid grid-cols-[10rem_1fr] gap-3 px-3 py-2 text-sm">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium text-slate-900">{value}</dd>
    </div>
  );
}

function NextAuction({ summary }: { summary: CourtCaseSummary }) {
  const next = summary.next_auction;
  return (
    <section className="mb-4 rounded-xl border border-teal-200 bg-teal-50/70 p-3" aria-label="Next auction">
      <div className="grid gap-3 sm:grid-cols-[auto_auto_1fr]">
        <div className="flex items-start gap-2">
          <CalendarDays className="mt-0.5 h-4 w-4 shrink-0 text-teal-700" />
          <div><p className="text-[11px] font-semibold uppercase tracking-wide text-teal-800">Next auction</p><p className="font-bold text-slate-950">{day(next?.date ?? null) ?? "None scheduled"}</p></div>
        </div>
        <div className="flex items-start gap-2">
          <Clock className="mt-0.5 h-4 w-4 shrink-0 text-teal-700" />
          <div><p className="text-[11px] font-semibold uppercase tracking-wide text-teal-800">Time</p><p className="font-bold text-slate-950">{next?.time ?? "—"}</p></div>
        </div>
        <div className="flex items-start gap-2">
          <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-teal-700" />
          <div><p className="text-[11px] font-semibold uppercase tracking-wide text-teal-800">Location</p><p className="font-semibold text-slate-950">{next?.location ?? `${summary.court}, Foreclosure Auction Part`}</p></div>
        </div>
      </div>
      <p className="mt-2 border-t border-teal-200 pt-2 text-[11px] text-slate-600">
        Referee auctions are often adjourned or cancelled; check the court calendar on WebCivil before attending.
      </p>
    </section>
  );
}

/** A NY referee foreclosure case in one view, in place of a sheriff sale page. */
export function CourtCaseSummaryModal({ property, onClose }: { property: Property; onClose: () => void }) {
  const [summary, setSummary] = useState<CourtCaseSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [allAppearances, setAllAppearances] = useState(false);

  useEffect(() => {
    let active = true;
    getCourtCase(property.sheriff_sale_id)
      .then((result) => { if (active) setSummary(result); })
      .catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [property.sheriff_sale_id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const appearances = summary ? (allAppearances ? summary.appearances : summary.appearances.slice(0, 8)) : [];

  return (
    <div className="fixed inset-0 z-[2200] flex items-center justify-center bg-slate-950/50 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Court case summary" onClick={(event) => event.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 px-5 py-4">
          <div>
            <h2 className="flex items-center gap-2 font-bold text-slate-950"><Scale className="h-4 w-4 text-teal-600" />Court case summary</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Index No. {property.court_case_number ?? property.sheriff_number} · {summary?.court ?? `${property.county} County Supreme Court`}
              {summary?.years_in_foreclosure != null && ` · ${summary.years_in_foreclosure} years in foreclosure`}
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100" aria-label="Close"><X className="h-5 w-5" /></button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {error ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{error}</div>
          ) : !summary ? (
            <div className="space-y-2">{[1, 2, 3, 4, 5, 6].map((item) => <div key={item} className="h-8 animate-pulse rounded bg-slate-100" />)}</div>
          ) : (
            <>
              <NextAuction summary={summary} />

              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">How the foreclosure has moved</h3>
              <ol className="mb-5 space-y-0 border-l-2 border-teal-200 pl-4">
                {summary.stages.map((stage, index) => (
                  <li key={`${stage.stage}-${stage.date}-${index}`} className="relative pb-3">
                    <span className="absolute -left-[1.4rem] top-1 h-2.5 w-2.5 rounded-full border-2 border-white bg-teal-600" aria-hidden />
                    <p className="text-sm font-semibold text-slate-900">{stage.stage} <span className="font-normal tabular-nums text-slate-500">· {day(stage.date)}</span></p>
                    <p className="text-xs leading-5 text-slate-600">{stage.detail}</p>
                  </li>
                ))}
                {summary.stages.length === 0 && <li className="text-sm text-slate-500">No court dates read from the case files yet.</li>}
              </ol>

              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Case details</h3>
              <dl className="mb-5 divide-y divide-slate-100 rounded-xl border border-slate-200">
                <Fact label="Property" value={summary.address} />
                <Fact label="Block / lot" value={summary.block_lot} />
                <Fact label="Plaintiff" value={summary.plaintiff} />
                <Fact label="Plaintiff's attorney" value={summary.plaintiff_attorney} />
                <Fact label="Referee" value={summary.referee} />
                <Fact label="Filed" value={[day(summary.filing_date), summary.initiating_document].filter(Boolean).join(" · ") || null} />
                <Fact label="Original lender" value={summary.original_lender} />
                <Fact label="Unpaid principal" value={summary.unpaid_principal != null ? `${money(summary.unpaid_principal)} (in the complaint)` : null} />
                <Fact label="Judgment entered" value={day(summary.judgment_date)} />
                <Fact label="Approx. judgment" value={money(summary.approximate_judgment)} />
                <Fact label="Approx. lien amount" value={money(summary.approximate_lien_amount)} />
              </dl>

              {summary.auction_calendar.length > 0 && <>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Auction calendar</h3>
                <div className="mb-5 divide-y divide-slate-100 rounded-xl border border-slate-200 text-sm">
                  {summary.auction_calendar.map((event) => (
                    <div key={event.date} className="px-3 py-2">
                      <div className="flex justify-between gap-3">
                        <span className="font-medium tabular-nums text-slate-900">{day(event.date)}{event.time ? ` · ${event.time}` : ""}</span>
                        <span className={event.status === "scheduled" ? "text-teal-700" : "text-amber-700"}>{event.outcome ?? EVENT_LABEL[event.status]}</span>
                      </div>
                      {event.remarks && <p className="text-xs text-slate-500">{event.remarks}</p>}
                    </div>
                  ))}
                </div>
              </>}

              {summary.appearances.length > 0 && <>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Court appearances ({summary.appearances.length})</h3>
                <div className="overflow-x-auto rounded-xl border border-slate-200">
                  <table className="w-full min-w-[32rem] text-left text-xs">
                    <thead className="bg-slate-50 text-[10px] uppercase tracking-wide text-slate-500">
                      <tr><th className="px-3 py-2">Date</th><th className="px-3 py-2">Purpose</th><th className="px-3 py-2">Outcome</th><th className="px-3 py-2">Part / justice</th></tr>
                    </thead>
                    <tbody>
                      {appearances.map((row, index) => (
                        <tr key={`${row.date}-${row.purpose}-${index}`} className="border-t border-slate-100 align-top">
                          <td className="whitespace-nowrap px-3 py-1.5 tabular-nums">{day(row.date)}</td>
                          <td className="px-3 py-1.5">{row.purpose ?? "—"}</td>
                          <td className="px-3 py-1.5 font-medium">{row.outcome ?? "—"}</td>
                          <td className="px-3 py-1.5 text-slate-500">{[row.part, row.justice].filter(Boolean).join(" · ") || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {summary.appearances.length > 8 && (
                  <button type="button" onClick={() => setAllAppearances((value) => !value)} className="mt-2 text-xs font-semibold text-teal-700 hover:underline">
                    {allAppearances ? "Show fewer" : `Show all ${summary.appearances.length}`}
                  </button>
                )}
              </>}
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 bg-slate-50 px-5 py-3 text-xs text-slate-500">
          <span className="inline-flex items-center gap-1"><FileText className="h-3 w-3" />{summary ? `From: ${summary.sources.join(", ")} · updated ${new Date(summary.updated_at).toLocaleDateString()}` : "From the court filings"}</span>
          <span className="inline-flex items-center gap-1"><Gavel className="h-3 w-3" />Look up filings on NYSCEF by index number</span>
        </div>
      </div>
    </div>
  );
}
