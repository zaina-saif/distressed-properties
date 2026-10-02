"use client";

import { X } from "lucide-react";
import type { Property } from "@/types/property";

function number(value: number | undefined): string {
  return value == null ? "Unavailable" : value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function percent(value: number | null | undefined): string {
  return value == null ? "Unavailable" : `${Math.round(value * 100)}%`;
}

export function SaleProbabilityReasonModal({ property, onClose }: { property: Property; onClose: () => void }) {
  const features = property.sale_probability_features ?? {};
  const explanation = property.sale_probability_explanations ?? {};

  return (
    <div className="fixed inset-0 z-[2100] flex items-center justify-center bg-slate-950/55 p-4" onMouseDown={onClose}>
      <article role="dialog" aria-modal="true" aria-labelledby="sale-probability-reason-title" className="w-full max-w-xl rounded-2xl bg-white shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
          <div>
            <h2 id="sale-probability-reason-title" className="text-lg font-bold text-slate-950">Why this probability?</h2>
            <p className="mt-1 text-sm text-slate-600">{property.street_address}, {property.city}, {property.state}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close probability explanation" className="rounded-full p-2 text-slate-500 hover:bg-slate-100"><X className="h-5 w-5" /></button>
        </header>
        <div className="space-y-5 p-5">
          <div className="rounded-xl border border-teal-200 bg-teal-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-teal-700">Calculated probability</p>
            <p className="mt-1 text-3xl font-bold text-slate-950">{percent(property.sale_probability)}</p>
            <p className="mt-2 text-sm leading-5 text-slate-700">This is the model&apos;s estimated chance that the current scheduled event reaches a sold or purchased terminal outcome, based on the recorded status history available for this sale.</p>
          </div>
          <section>
            <h3 className="mb-2 font-semibold text-slate-900">Evidence used</h3>
            <dl className="divide-y divide-slate-100 rounded-lg border border-slate-200 px-4">
              <div className="flex justify-between gap-4 py-2 text-sm"><dt className="text-slate-500">Prior status events</dt><dd className="font-semibold text-slate-900">{number(features.prior_event_count)}</dd></div>
              <div className="flex justify-between gap-4 py-2 text-sm"><dt className="text-slate-500">Prior scheduled events</dt><dd className="font-semibold text-slate-900">{number(features.prior_scheduled_count)}</dd></div>
              <div className="flex justify-between gap-4 py-2 text-sm"><dt className="text-slate-500">Adjournments</dt><dd className="font-semibold text-slate-900">{number(features.adjournment_count)} ({number(features.plaintiff_adjournment_count)} plaintiff, {number(features.defendant_adjournment_count)} defendant)</dd></div>
              <div className="flex justify-between gap-4 py-2 text-sm"><dt className="text-slate-500">Bankruptcy events</dt><dd className="font-semibold text-slate-900">{number(features.bankruptcy_count)}</dd></div>
              <div className="flex justify-between gap-4 py-2 text-sm"><dt className="text-slate-500">Days in process</dt><dd className="font-semibold text-slate-900">{number(features.days_in_process)}</dd></div>
              <div className="flex justify-between gap-4 py-2 text-sm"><dt className="text-slate-500">Days until scheduled sale</dt><dd className="font-semibold text-slate-900">{number(features.days_until_sale)}</dd></div>
              <div className="flex justify-between gap-4 py-2 text-sm"><dt className="text-slate-500">Minimum bid used</dt><dd className="font-semibold text-slate-900">{features.minimum_bid == null ? "Unavailable" : `$${features.minimum_bid.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}</dd></div>
            </dl>
          </section>
          <p className="text-xs leading-5 text-slate-500">{explanation.methodology ?? "Calibrated gradient-boosting model trained on historical status events."} Model version: {explanation.model_version ?? "Unavailable"}. This is an estimate, not a guarantee that an auction will occur.</p>
        </div>
      </article>
    </div>
  );
}
