"use client";

import { X } from "lucide-react";
import { useEffect, useState } from "react";

import { getPublicComplaints } from "@/services/properties";
import type { Property, PublicComplaint } from "@/types/property";

function label(key: string): string {
  return key.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function value(item: unknown): string {
  if (item == null || item === "") return "—";
  if (typeof item === "object") return JSON.stringify(item);
  return String(item);
}

export function PropertyComplaintsModal({ property, onClose }: { property: Property; onClose: () => void }) {
  const [complaints, setComplaints] = useState<PublicComplaint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getPublicComplaints(property.property_id)
      .then((items) => { if (active) setComplaints(items); })
      .catch(() => { if (active) setComplaints([]); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [property.property_id]);

  return (
    <div className="fixed inset-0 z-[2100] flex items-center justify-center bg-slate-950/55 p-4" onMouseDown={onClose}>
      <section role="dialog" aria-modal="true" aria-labelledby="complaints-title" className="max-h-[85vh] w-full max-w-5xl overflow-hidden rounded-2xl bg-white p-5 shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-center justify-between gap-4 border-b border-slate-200 pb-3">
          <div><h2 id="complaints-title" className="text-lg font-bold text-slate-950">Complaints</h2><p className="mt-1 text-xs text-slate-500">{property.normalized_address}</p></div>
          <button type="button" onClick={onClose} aria-label="Close complaints" className="rounded-full p-2 text-slate-500 hover:bg-slate-100"><X className="h-5 w-5" /></button>
        </header>
        {loading ? <p className="py-6 text-sm text-slate-500">Loading complaints…</p> : complaints.length === 0 ? (
          <p className="py-6 text-sm text-slate-500">No public complaint records have been retrieved for this property.</p>
        ) : (
          <div className="max-h-[68vh] overflow-auto pt-4">
            <div className="space-y-3">
              {complaints.map((complaint, index) => (
                <article key={String(complaint.unique_key ?? complaint.violationid ?? index)} className="rounded-lg border border-slate-200 p-3 text-xs text-slate-700">
                  {Object.entries(complaint).filter(([, item]) => item != null && item !== "").map(([key, item]) => (
                    <p key={key} className="mb-1 last:mb-0"><span className="font-semibold text-slate-900">{label(key)}:</span> {value(item)}</p>
                  ))}
                </article>
              ))}
            </div>
            <p className="mt-4 text-[11px] leading-5 text-slate-500">Public complaint records are preliminary screening information and do not establish a lien, debt, or legal conclusion.</p>
          </div>
        )}
      </section>
    </div>
  );
}
