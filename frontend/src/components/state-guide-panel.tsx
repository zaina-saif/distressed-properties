"use client";

import { BookOpen, ChevronDown, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useSyncExternalStore } from "react";

import { buyerSteps, stateGuide } from "@/lib/state-guides";

const STORAGE_KEY = "state-guide-open";
const CHANGED = "state-guide-open-changed";

// The open/closed choice is remembered per browser (closed until first opened); when
// storage is unavailable (private browsing) it lasts for this page visit.
let openInMemory = false;
function readOpen(): boolean {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return saved === null ? openInMemory : saved === "1";
  } catch { return openInMemory; }
}
function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", onChange);
  return () => { window.removeEventListener(CHANGED, onChange); window.removeEventListener("storage", onChange); };
}

/** "Buying at a sale in <State>": what someone interested in a property there has to do. */
export function StateGuidePanel({ state }: { state: string }) {
  const guide = stateGuide(state);
  const open = useSyncExternalStore(subscribe, readOpen, () => false);
  if (!guide) return null;
  const toggle = () => {
    openInMemory = !open;
    try { window.localStorage.setItem(STORAGE_KEY, openInMemory ? "1" : "0"); } catch { /* kept in memory */ }
    window.dispatchEvent(new Event(CHANGED));
  };
  return <section className="rounded-lg border border-slate-200 bg-slate-50" aria-label={`How sales work in ${guide.name}`}>
    <button type="button" onClick={toggle} aria-expanded={open} className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs">
      <BookOpen className="h-3.5 w-3.5 shrink-0 text-teal-700" aria-hidden="true" />
      <span className="font-semibold text-slate-900">Buying at a sale in {guide.name}</span>
      <span className="hidden truncate text-slate-500 sm:inline">· {guide.who} · what to do if you&apos;re interested in a property here</span>
      <ChevronDown className={`ml-auto h-4 w-4 shrink-0 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
    </button>
    {open && <div className="border-t border-slate-200 px-3 pb-3 pt-2">
      <ol className="grid gap-x-6 gap-y-2 text-xs leading-5 text-slate-600 md:grid-cols-2">
        {buyerSteps(guide).map((step, index) => <li key={`${step.title}-${index}`} className="flex gap-2">
          <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-teal-600 text-[10px] font-bold text-white">{index + 1}</span>
          <span><span className="font-semibold text-slate-900">{step.title}.</span> {step.text}</span>
        </li>)}
      </ol>
      <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
        <span>General information, not legal advice. Terms vary by county and change; confirm them with the selling office.</span>
        <Link href={`/how-sheriff-sales-work#state-${guide.code}`} className="inline-flex items-center gap-1 font-semibold text-teal-700 hover:underline">Full guide<ExternalLink className="h-3 w-3" /></Link>
      </p>
    </div>}
  </section>;
}
