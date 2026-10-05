"use client";

import { ArrowDown, ArrowUp, X } from "lucide-react";
import type { Property } from "@/types/property";

type Driver = NonNullable<NonNullable<Property["sale_probability_explanations"]>["drivers"]>[number];
type Features = NonNullable<Property["sale_probability_features"]>;

function percent(value: number | null | undefined): string {
  return value == null ? "Unavailable" : `${Math.round(value * 100)}%`;
}

function times(count: number): string {
  return count === 1 ? "once" : `${count} times`;
}

function verdict(probability: number | null | undefined): string {
  if (probability == null) return "No estimate is available for this sale.";
  if (probability < 0.15) return "Unlikely to be sold on the next sale date. It will most likely be postponed or cancelled again.";
  if (probability < 0.35) return "Possible, but it is more likely to be postponed or cancelled than sold on the next date.";
  if (probability < 0.6) return "A real chance it is sold on the next sale date.";
  return "Likely to be sold on the next sale date.";
}

function strength(impact: number): string {
  const points = Math.abs(impact) * 100;
  if (points >= 10) return "a lot";
  if (points >= 4) return "somewhat";
  return "slightly";
}

/** One plain-language sentence explaining a reason, in the direction it pushes. */
function explain(driver: Driver, features: Features, county: string): string {
  const up = driver.impact > 0;
  const more = up ? "more" : "less";
  switch (driver.key) {
    case "county":
      return up
        ? `Sheriff sales in ${county} County go ahead more often than in most NJ counties.`
        : `Sheriff sales in ${county} County are postponed or cancelled more often than in most NJ counties.`;
    case "bankruptcy": {
      const count = features.bankruptcy_count ?? 0;
      return count > 0
        ? `The owner has filed for bankruptcy ${times(count)}. A bankruptcy filing legally pauses a sheriff sale.`
        : "No bankruptcy has been filed, so nothing is legally pausing the sale.";
    }
    case "reschedules": {
      const count = features.prior_scheduled_count ?? 0;
      if (count === 0) {
        return up
          ? "This is the first sale date on record."
          : "This is the first sale date on record, and first dates are often postponed.";
      }
      return up
        ? `It has been on the sale calendar ${times(count)} before and is still moving forward. Cases that keep coming back tend to sell eventually.`
        : `It has been on the sale calendar ${times(count)} before, a sign the case keeps getting delayed.`;
    }
    case "adjournments": {
      const total = features.adjournment_count ?? 0;
      if (total === 0) {
        return up ? "The sale has never been postponed." : "The sale has never been postponed yet; first dates often are.";
      }
      const parts = [
        features.plaintiff_adjournment_count ? `${features.plaintiff_adjournment_count} by the lender` : null,
        features.defendant_adjournment_count ? `${features.defendant_adjournment_count} by the owner` : null,
        features.court_adjournment_count ? `${features.court_adjournment_count} by the court` : null,
      ].filter(Boolean);
      const other = total - (features.plaintiff_adjournment_count ?? 0) - (features.defendant_adjournment_count ?? 0) - (features.court_adjournment_count ?? 0);
      if (other > 0) parts.push(`${other} other`);
      const breakdown = parts.length ? ` (${parts.join(", ")})` : "";
      return up
        ? `The sale has been postponed ${times(total)}${breakdown}. In similar cases that often comes just before the sale finally goes ahead.`
        : `The sale has been postponed ${times(total)}${breakdown}. Repeated postponements usually mean more delays.`;
    }
    case "days_in_process":
      return `It has been in the sheriff-sale process for ${driver.value}. Cases at this stage go ahead ${more} often than usual.`;
    case "days_since_previous_event":
      return `Its status last changed ${driver.value} ago. Sales at this point go ahead ${more} often than usual.`;
    case "sale_month":
      return `It is scheduled for ${driver.value}. Sales in that month go ahead ${more} often than usual.`;
    case "minimum_bid":
      return driver.value === "Not published"
        ? `No minimum bid has been published. Sales like this go ahead ${more} often than usual.`
        : `Its minimum bid is ${driver.value}. Sales around this price go ahead ${more} often than usual.`;
    default:
      return `${driver.label}: ${driver.value}.`;
  }
}

export function SaleProbabilityReasonModal({ property, onClose }: { property: Property; onClose: () => void }) {
  const explanation = property.sale_probability_explanations ?? {};
  const features = property.sale_probability_features ?? {};
  const drivers = explanation.drivers ?? [];
  const quality = explanation.model_quality;

  return (
    <div className="fixed inset-0 z-[2100] flex items-center justify-center bg-slate-950/55 p-4" onMouseDown={onClose}>
      <article role="dialog" aria-modal="true" aria-labelledby="sale-probability-reason-title" className="flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
          <div>
            <h2 id="sale-probability-reason-title" className="text-lg font-bold text-slate-950">Why this probability?</h2>
            <p className="mt-1 text-sm text-slate-600">{property.street_address}, {property.city}, {property.state}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close probability explanation" className="rounded-full p-2 text-slate-500 hover:bg-slate-100"><X className="h-5 w-5" /></button>
        </header>
        <div className="min-h-0 space-y-5 overflow-y-auto p-5">
          <div className="rounded-xl border border-teal-200 bg-teal-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-teal-700">Chance it is sold at the next sale date</p>
            <p className="mt-1 text-3xl font-bold text-slate-950">{percent(property.sale_probability)}</p>
            <p className="mt-2 text-sm font-medium leading-5 text-slate-800">{verdict(property.sale_probability)}</p>
          </div>

          <section>
            <h3 className="font-semibold text-slate-900">What pushed the number up or down</h3>
            <p className="mb-3 mt-1 text-xs text-slate-500">Compared with an ordinary NJ sheriff sale, these facts about this case matter most.</p>
            {drivers.length ? (
              <ul className="space-y-2.5">
                {drivers.map((driver) => {
                  const up = driver.impact > 0;
                  return (
                    <li key={driver.key} className={`flex gap-3 rounded-lg border p-3 ${up ? "border-teal-200 bg-teal-50/50" : "border-red-200 bg-red-50/50"}`}>
                      <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${up ? "bg-teal-600" : "bg-red-600"} text-white`}>
                        {up ? <ArrowUp className="h-3.5 w-3.5" /> : <ArrowDown className="h-3.5 w-3.5" />}
                      </span>
                      <div className="text-sm leading-5">
                        <p className={`font-semibold ${up ? "text-teal-800" : "text-red-800"}`}>{up ? "Raises" : "Lowers"} the chance {strength(driver.impact)}</p>
                        <p className="text-slate-700">{explain(driver, features, property.county)}</p>
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="text-sm text-slate-600">Nothing about this case stands out; it looks like an ordinary NJ sheriff sale.</p>
            )}
          </section>

          <section className="rounded-xl border border-slate-200 p-4 text-sm leading-6 text-slate-700">
            <h3 className="mb-1 font-semibold text-slate-900">How we get this number</h3>
            <p>We looked at thousands of past New Jersey sheriff sales and whether each one was actually sold or was postponed, cancelled or stopped. A computer model learned which patterns usually end in a sale: the county, how often the sale was postponed and by whom, bankruptcy filings, how long the case has been going, the month, and the minimum bid. It then checks this case against those patterns.</p>
            {quality?.holdout_roc_auc != null && (
              <>
                <h3 className="mb-1 mt-3 font-semibold text-slate-900">How reliable is it?</h3>
                <p>
                  We tested it on {quality.holdout_rows?.toLocaleString()} recent sales it had never seen. When comparing a sale that went ahead with one that did not, it picked the right one about {Math.round(quality.holdout_roc_auc * 10)} times out of 10.
                  Its numbers also run a little high, so use them to compare properties rather than as an exact promise.
                </p>
              </>
            )}
          </section>
          <p className="text-xs leading-5 text-slate-500">This is an estimate, not a guarantee that a sale will happen. Model {explanation.model_version ?? "unavailable"}.</p>
        </div>
      </article>
    </div>
  );
}
