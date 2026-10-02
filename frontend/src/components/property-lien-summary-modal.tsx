"use client";

import { ExternalLink, X } from "lucide-react";
import { useEffect, useState } from "react";

import { getLienSummary } from "@/services/properties";
import type { LienSummaryResponse, Property } from "@/types/property";

function money(value: number | null | undefined): string {
  if (value == null) return "Unavailable";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

function date(value: string | null | undefined): string {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

function statusLabel(value: string): string {
  return value.replaceAll("_", " ").toLowerCase();
}

export function PropertyLienSummaryModal({ property, onClose }: { property: Property; onClose: () => void }) {
  const [result, setResult] = useState<LienSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getLienSummary(property.property_id)
      .then((value) => { if (active) setResult(value); })
      .catch(() => { if (active) setResult(null); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [property.property_id]);

  return (
    <div className="fixed inset-0 z-[2100] flex items-center justify-center bg-slate-950/55 p-4" onMouseDown={onClose}>
      <section role="dialog" aria-modal="true" aria-labelledby="lien-summary-title" className="max-h-[92vh] w-full max-w-5xl overflow-hidden rounded-2xl bg-white p-5 shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-center justify-between gap-4 border-b border-slate-200 pb-3">
          <div><h2 id="lien-summary-title" className="text-lg font-bold text-slate-950">Preliminary Lien &amp; Title Summary</h2><p className="mt-1 text-xs text-slate-500">{property.normalized_address}</p></div>
          <button type="button" onClick={onClose} aria-label="Close lien summary" className="rounded-full p-2 text-slate-500 hover:bg-slate-100"><X className="h-5 w-5" /></button>
        </header>
        {loading ? <p className="py-8 text-sm text-slate-500">Loading lien summary…</p> : !result ? <p className="py-8 text-sm text-slate-500">The lien summary could not be loaded. Try again later.</p> : (
          <div className="max-h-[82vh] space-y-5 overflow-y-auto pt-4 pr-1">
            <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Overall</p><p className="mt-1 text-xl font-bold text-slate-950">{statusLabel(result.summary.risk_level)} preliminary lien risk</p><p className="mt-1 text-xs text-slate-500">Confidence: {result.summary.confidence}% · Data freshness: {statusLabel(result.summary.data_freshness)}</p></div>
                <div className="rounded-lg bg-white px-4 py-3 text-center shadow-sm"><p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Risk score</p><p className="text-2xl font-bold text-teal-700">{result.risk.risk_score}/100</p></div>
              </div>
              <p className="mt-4 text-sm leading-6 text-slate-700">{result.summary.summary_text}</p>
            </section>

            <section>
              <h3 className="mb-2 font-bold text-slate-900">Key findings</h3>
              {result.summary.key_findings.length === 0 ? <p className="text-sm text-slate-500">No evidence-backed findings were generated.</p> : <ul className="space-y-2">{result.summary.key_findings.map((finding) => <li key={finding.finding_id} className="rounded-lg border border-slate-200 p-3 text-sm"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold text-slate-900">{finding.label}</span><span className="rounded bg-slate-100 px-2 py-1 text-[11px] font-semibold uppercase text-slate-600">{finding.severity}</span></div><p className="mt-1 text-xs leading-5 text-slate-600">{finding.message}</p>{finding.evidence_ids.length > 0 && <a href={`#evidence-${finding.evidence_ids[0]}`} className="mt-1 inline-block text-xs font-semibold text-teal-700 underline">View supporting evidence</a>}</li>)}</ul>}
            </section>

            <section>
              <h3 className="mb-2 font-bold text-slate-900">Supporting evidence</h3>
              {result.liens.length === 0 ? <p className="text-sm text-slate-500">No normalized lien records were returned. This does not confirm clean title.</p> : <div className="overflow-x-auto rounded-lg border border-slate-200"><table className="w-full min-w-[48rem] text-left text-xs"><thead className="bg-slate-50 text-[10px] uppercase tracking-wide text-slate-500"><tr><th className="px-3 py-2">Type</th><th className="px-3 py-2">Creditor / debtor</th><th className="px-3 py-2">Amount</th><th className="px-3 py-2">Recorded</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Confidence</th><th className="px-3 py-2">Source</th></tr></thead><tbody>{result.liens.map((lien) => <tr id={`evidence-${lien.id}`} key={lien.id} className="border-t border-slate-100 align-top"><td className="px-3 py-2 font-semibold">{statusLabel(lien.lien_type)}</td><td className="px-3 py-2">{lien.creditor_name || "Unknown creditor"}<br /><span className="text-slate-500">{lien.debtor_name || "Unknown debtor"}</span></td><td className="px-3 py-2">{money(lien.current_amount ?? lien.original_amount)}</td><td className="px-3 py-2">{date(lien.recording_date)}</td><td className="px-3 py-2">{statusLabel(lien.status)}</td><td className="px-3 py-2">{lien.match_confidence}%</td><td className="px-3 py-2">{lien.source_url ? <a href={lien.source_url} target="_blank" rel="noopener noreferrer" className="text-teal-700 underline">{statusLabel(lien.source_name)} <ExternalLink className="inline h-3 w-3" /></a> : statusLabel(lien.source_name)}</td></tr>)}</tbody></table></div>}
            </section>

            <section><h3 className="mb-2 font-bold text-slate-900">Data coverage</h3><div className="grid gap-2 sm:grid-cols-2">{result.summary.coverage.map((item) => <div key={`${item.source_type}-${item.source_name}`} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2 text-xs"><span>{item.source_name}</span><span className="font-semibold text-slate-600">{statusLabel(item.status)}{item.checked_at ? ` · ${date(item.checked_at)}` : ""}</span></div>)}</div></section>

            <section><h3 className="mb-2 font-bold text-slate-900">Manual verification required</h3>{result.summary.manual_review.length === 0 ? <p className="text-sm text-slate-500">No additional manual-review items were generated.</p> : <ul className="space-y-2">{result.summary.manual_review.map((item, index) => <li key={`${String(item.source)}-${index}`} className="rounded-lg bg-amber-50 p-3 text-xs leading-5 text-amber-900"><strong>{String(item.source)}:</strong> {String(item.reason)}{item.property_address ? ` Search ${String(item.property_address)}` : ""}{item.block || item.lot ? `; block/lot ${String(item.block || "")}/${String(item.lot || "")}` : ""}.</li>)}</ul>}</section>

            <p className="rounded-lg bg-amber-50 p-3 text-xs leading-5 text-amber-900">{result.summary.disclaimer}</p>
            {result.professional_title_search && <section className="rounded-xl border border-teal-200 bg-teal-50 p-4"><h3 className="font-bold text-slate-900">Need a Comprehensive Title Search?</h3><p className="mt-2 text-xs leading-5 text-slate-700">SheriffSale’s automated lien analysis is preliminary screening of available public records. A professional search may identify additional liens, judgments, municipal charges, association obligations, ownership issues, easements, or other encumbrances.</p><a href={result.professional_title_search.provider_url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-teal-700 px-3 py-2 text-sm font-semibold text-white hover:bg-teal-800">Order Comprehensive Title Search <ExternalLink className="h-3.5 w-3.5" /></a><p className="mt-2 text-[11px] text-slate-600">Independent third-party provider: {result.professional_title_search.provider_name}</p></section>}
          </div>
        )}
      </section>
    </div>
  );
}
