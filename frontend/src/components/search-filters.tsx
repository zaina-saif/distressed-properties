"use client";

import { SlidersHorizontal, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { SearchFilterValues } from "@/services/properties";

export const HOME_TYPES: [string, string][] = [
  ["SINGLE_FAMILY", "Single family"], ["CONDO", "Condo"], ["TOWNHOUSE", "Townhouse"], ["MULTI_FAMILY", "Multi-family"],
  ["MANUFACTURED", "Manufactured"], ["APARTMENT", "Apartment"], ["LOT", "Lot / land"],
];
const BEDS = [1, 2, 3, 4, 5];
const BATHS = [1, 2, 3, 4];
const PROBABILITIES = [0.25, 0.5, 0.75];

const money = (value: number) => value >= 1_000_000 ? `$${+(value / 1_000_000).toFixed(2)}M`
  : value >= 1_000 ? `$${+(value / 1_000).toFixed(1)}K` : `$${value}`;
const range = (low: number | string | undefined, high: number | string | undefined, format: (v: never) => string) =>
  low !== undefined && high !== undefined ? `${format(low as never)}–${format(high as never)}`
    : low !== undefined ? `${format(low as never)}+` : `up to ${format(high as never)}`;
const day = (value: string) => new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

/** One removable chip per active filter: the label and the keys it clears. */
export function filterChips(filters: SearchFilterValues): { label: string; keys: (keyof SearchFilterValues)[] }[] {
  const chips: { label: string; keys: (keyof SearchFilterValues)[] }[] = [];
  const has = (value: unknown) => value !== undefined && value !== "";
  if (has(filters.minPrice) || has(filters.maxPrice)) chips.push({ label: `Min. bid ${range(filters.minPrice, filters.maxPrice, money)}`, keys: ["minPrice", "maxPrice"] });
  if (has(filters.minValue) || has(filters.maxValue)) chips.push({ label: `Value ${range(filters.minValue, filters.maxValue, money)}`, keys: ["minValue", "maxValue"] });
  if (has(filters.minEquity)) chips.push({ label: `Equity ${money(filters.minEquity!)}+`, keys: ["minEquity"] });
  if (has(filters.minBeds)) chips.push({ label: `${filters.minBeds}+ beds`, keys: ["minBeds"] });
  if (has(filters.minBaths)) chips.push({ label: `${filters.minBaths}+ baths`, keys: ["minBaths"] });
  if (filters.homeTypes?.length) chips.push({ label: filters.homeTypes.map((type) => HOME_TYPES.find(([key]) => key === type)?.[1] ?? type).join(", "), keys: ["homeTypes"] });
  if (has(filters.minSqft) || has(filters.maxSqft)) chips.push({ label: `${range(filters.minSqft, filters.maxSqft, (v: number) => v.toLocaleString())} sq ft`, keys: ["minSqft", "maxSqft"] });
  if (has(filters.minYear) || has(filters.maxYear)) chips.push({ label: `Built ${range(filters.minYear, filters.maxYear, String)}`, keys: ["minYear", "maxYear"] });
  if (has(filters.saleFrom) || has(filters.saleTo)) chips.push({ label: `Sale ${range(filters.saleFrom, filters.saleTo, day)}`, keys: ["saleFrom", "saleTo"] });
  if (has(filters.minProbability)) chips.push({ label: `${Math.round(filters.minProbability! * 100)}%+ to auction`, keys: ["minProbability"] });
  return chips;
}

/** The filters without the given keys. */
export function withoutFilters(filters: SearchFilterValues, keys: (keyof SearchFilterValues)[]): SearchFilterValues {
  const next = { ...filters };
  keys.forEach((key) => delete next[key]);
  return next;
}

function NumberField({ label, value, onChange, prefix, placeholder }: { label: string; value?: number; onChange: (value?: number) => void; prefix?: string; placeholder: string }) {
  return <label className="flex min-w-0 flex-1 items-center rounded-md border border-slate-300 bg-white px-2 focus-within:border-teal-500">
    {prefix && <span className="text-xs text-slate-400">{prefix}</span>}
    <span className="sr-only">{label}</span>
    <input type="number" inputMode="numeric" min={0} value={value ?? ""} placeholder={placeholder}
      onChange={(event) => onChange(event.target.value === "" ? undefined : Number(event.target.value))}
      className="w-full min-w-0 bg-transparent px-1 py-1.5 text-base outline-none sm:text-xs" />
  </label>;
}

function Choice<T extends number>({ options, value, onChange, format, label }: { options: T[]; value?: T; onChange: (value?: T) => void; format: (value: T) => string; label: string }) {
  const base = "flex-1 rounded-md px-2 py-1.5 text-xs font-semibold";
  return <div className="flex gap-1 rounded-lg bg-slate-100 p-1" role="group" aria-label={label}>
    <button type="button" onClick={() => onChange(undefined)} className={`${base} ${value === undefined ? "bg-white text-teal-700 shadow-sm" : "text-slate-500"}`} aria-pressed={value === undefined}>Any</button>
    {options.map((option) => <button key={option} type="button" onClick={() => onChange(option)} className={`${base} ${value === option ? "bg-white text-teal-700 shadow-sm" : "text-slate-500"}`} aria-pressed={value === option}>{format(option)}</button>)}
  </div>;
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return <fieldset className="space-y-1.5">
    <legend className="flex w-full items-baseline justify-between text-xs font-bold text-slate-800">{title}{hint && <span className="font-normal text-slate-400">{hint}</span>}</legend>
    {children}
  </fieldset>;
}

/** The Filters button and panel. `analytics` hides the filters that only describe upcoming sales. */
export function SearchFiltersButton({ value, onApply, analytics = false }: { value: SearchFilterValues; onApply: (filters: SearchFilterValues) => void; analytics?: boolean }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<SearchFilterValues>(value);
  const panel = useRef<HTMLDivElement>(null);
  const active = filterChips(analytics ? withoutFilters(value, ["minEquity", "minProbability"]) : value).length;

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !panel.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);

  const set = (patch: Partial<SearchFilterValues>) => setDraft((current) => ({ ...current, ...patch }));
  const toggleType = (type: string) => set({ homeTypes: draft.homeTypes?.includes(type) ? draft.homeTypes.filter((item) => item !== type) : [...(draft.homeTypes ?? []), type] });
  const apply = () => { onApply(Object.fromEntries(Object.entries(draft).filter(([, v]) => v !== undefined && v !== "" && !(Array.isArray(v) && !v.length)))); setOpen(false); };

  return <div ref={panel} className="relative">
    <button type="button" onClick={() => { setDraft(value); setOpen(!open); }} aria-expanded={open} aria-haspopup="dialog"
      className={`flex items-center gap-1 rounded-md border px-2 py-2 text-xs font-semibold sm:py-1 ${active ? "border-teal-500 bg-teal-50 text-teal-800" : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}>
      <SlidersHorizontal className="h-3.5 w-3.5" />Filters{active > 0 && <span className="rounded-full bg-teal-600 px-1.5 text-[10px] text-white">{active}</span>}
    </button>
    {open && <div role="dialog" aria-label="Search filters"
      className="fixed inset-x-0 bottom-0 z-[60] flex max-h-[85dvh] flex-col overflow-hidden rounded-t-2xl border border-slate-200 bg-white shadow-2xl sm:absolute sm:inset-x-auto sm:bottom-auto sm:right-0 sm:top-full sm:mt-2 sm:w-[24rem] sm:max-h-[75vh] sm:rounded-xl">
      <div className="flex shrink-0 items-center justify-between border-b border-slate-100 px-4 py-3">
        <h2 className="text-sm font-bold text-slate-950">Filters</h2>
        <button type="button" onClick={() => setOpen(false)} className="rounded p-1 text-slate-400 hover:bg-slate-100" aria-label="Close filters"><X className="h-4 w-4" /></button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
        <Section title="Minimum bid" hint="upset price or judgment">
          <div className="flex gap-2"><NumberField label="Minimum bid from" prefix="$" placeholder="No min" value={draft.minPrice} onChange={(v) => set({ minPrice: v })} /><NumberField label="Minimum bid to" prefix="$" placeholder="No max" value={draft.maxPrice} onChange={(v) => set({ maxPrice: v })} /></div>
        </Section>
        <Section title="Estimated value" hint="Zestimate">
          <div className="flex gap-2"><NumberField label="Estimated value from" prefix="$" placeholder="No min" value={draft.minValue} onChange={(v) => set({ minValue: v })} /><NumberField label="Estimated value to" prefix="$" placeholder="No max" value={draft.maxValue} onChange={(v) => set({ maxValue: v })} /></div>
        </Section>
        {!analytics && <Section title="Gross equity" hint="value minus minimum bid">
          <NumberField label="Minimum gross equity" prefix="$" placeholder="Any equity" value={draft.minEquity} onChange={(v) => set({ minEquity: v })} />
        </Section>}
        <Section title="Bedrooms"><Choice label="Bedrooms" options={BEDS} value={draft.minBeds as number | undefined} onChange={(v) => set({ minBeds: v })} format={(v) => `${v}+`} /></Section>
        <Section title="Bathrooms"><Choice label="Bathrooms" options={BATHS} value={draft.minBaths as number | undefined} onChange={(v) => set({ minBaths: v })} format={(v) => `${v}+`} /></Section>
        <Section title="Home type">
          <div className="flex flex-wrap gap-1.5">{HOME_TYPES.map(([key, label]) => {
            const on = draft.homeTypes?.includes(key);
            return <button key={key} type="button" onClick={() => toggleType(key)} aria-pressed={on}
              className={`rounded-full border px-2.5 py-1 text-xs font-medium ${on ? "border-teal-500 bg-teal-50 text-teal-800" : "border-slate-300 text-slate-600 hover:bg-slate-50"}`}>{label}</button>;
          })}</div>
        </Section>
        <Section title="Square feet">
          <div className="flex gap-2"><NumberField label="Square feet from" placeholder="No min" value={draft.minSqft} onChange={(v) => set({ minSqft: v })} /><NumberField label="Square feet to" placeholder="No max" value={draft.maxSqft} onChange={(v) => set({ maxSqft: v })} /></div>
        </Section>
        <Section title="Year built">
          <div className="flex gap-2"><NumberField label="Built from" placeholder="From" value={draft.minYear} onChange={(v) => set({ minYear: v })} /><NumberField label="Built to" placeholder="To" value={draft.maxYear} onChange={(v) => set({ maxYear: v })} /></div>
        </Section>
        <Section title={analytics ? "Sale or result date" : "Sale date"}>
          <div className="flex gap-2">
            {(["saleFrom", "saleTo"] as const).map((key) => <label key={key} className="flex min-w-0 flex-1 items-center rounded-md border border-slate-300 px-2 focus-within:border-teal-500">
              <span className="sr-only">{key === "saleFrom" ? "Sale date from" : "Sale date to"}</span>
              <input type="date" value={draft[key] ?? ""} onChange={(event) => set({ [key]: event.target.value || undefined })} className="w-full min-w-0 bg-transparent py-1.5 text-base outline-none sm:text-xs" />
            </label>)}
          </div>
        </Section>
        {!analytics && <Section title="Probability to auction"><Choice label="Probability to auction" options={PROBABILITIES} value={draft.minProbability as number | undefined} onChange={(v) => set({ minProbability: v })} format={(v) => `${v * 100}%+`} /></Section>}
        <p className="text-[11px] leading-4 text-slate-400">Bedrooms, bathrooms, home type, size and year built come from the property&apos;s Zillow record; properties without one are left out when these filters are on.</p>
      </div>
      <div className="flex shrink-0 gap-2 border-t border-slate-200 bg-white p-3">
        <button type="button" onClick={() => setDraft({})} className="rounded-md px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100">Clear all</button>
        <button type="button" onClick={apply} className="ml-auto rounded-md bg-teal-600 px-4 py-2 text-xs font-semibold text-white hover:bg-teal-700">Apply filters</button>
      </div>
    </div>}
  </div>;
}
