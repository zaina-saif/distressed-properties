"use client";

import { X } from "lucide-react";
import type { Property } from "@/types/property";

function date(value: string | null | undefined): string {
  if (!value) return "Unavailable";
  return new Intl.DateTimeFormat("en-US", { month: "numeric", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(value));
}

export function PropertyStatusHistoryModal({ property, onClose }: { property: Property; onClose: () => void }) {
  const history = property.status_history ?? [];
  return <div className="fixed inset-0 z-[2100] flex items-center justify-center bg-slate-950/55 p-4" onMouseDown={onClose}>
    <article role="dialog" aria-modal="true" className="w-full max-w-xl overflow-hidden rounded-2xl bg-white shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
      <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4"><div><h2 className="text-lg font-bold text-slate-950">Status History</h2><p className="mt-1 text-sm text-slate-500">{property.normalized_address}</p></div><button type="button" onClick={onClose} aria-label="Close status history" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><X className="h-5 w-5" /></button></header>
      <div className="max-h-[60vh] overflow-y-auto p-5">{history.length ? <table className="w-full border-collapse text-sm"><thead><tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500"><th className="px-3 py-2">Status</th><th className="px-3 py-2 text-right">Date</th></tr></thead><tbody>{history.map((entry, index) => <tr key={`${entry.observed_at}-${entry.status}-${index}`} className="border-b border-slate-100 last:border-0"><td className="px-3 py-2.5 font-medium capitalize text-slate-800">{(entry.raw_status || entry.status).replaceAll("_", " ")}</td><td className="px-3 py-2.5 text-right text-slate-600">{date(entry.event_date || entry.sale_date || entry.observed_at)}</td></tr>)}</tbody></table> : <p className="text-sm text-slate-500">No sheriff status history recorded.</p>}</div>
    </article>
  </div>;
}
