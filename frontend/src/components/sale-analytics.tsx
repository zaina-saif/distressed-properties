"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { getSaleAnalytics, type PricedSale, type SaleAnalytics, type SaleOutcome } from "@/services/analytics";

// Categorical slots 1-4 (validated together); cancelled sales are the muted context, not a series hue.
const OUTCOME_STYLE: Record<SaleOutcome, { label: string; color: string }> = {
  third_party: { label: "Sold to a third-party bidder", color: "#2a78d6" },
  plaintiff: { label: "Bought back by the lender", color: "#eb6834" },
  sold_other: { label: "Sold, buyer not published", color: "#1baf7a" },
  unsold: { label: "No bids", color: "#eda100" },
  cancelled: { label: "Cancelled", color: "#c9c8c1" },
};
const OUTCOME_ORDER: SaleOutcome[] = ["third_party", "plaintiff", "sold_other", "unsold", "cancelled"];
const SERIES = "#2a78d6";
const INK = { primary: "#0f172a", secondary: "#475569", muted: "#94a3b8", grid: "#e7e6e0", axis: "#c3c2b7" };
const PERIODS = [{ label: "6 months", months: 6 }, { label: "12 months", months: 12 }, { label: "24 months", months: 24 }, { label: "All time", months: undefined }];
const VALUE_BINS = [
  { label: "Under 50%", short: "<50%", max: 0.5 }, { label: "50–60%", short: "50–60", max: 0.6 }, { label: "60–70%", short: "60–70", max: 0.7 },
  { label: "70–80%", short: "70–80", max: 0.8 }, { label: "80–90%", short: "80–90", max: 0.9 }, { label: "90–100%", short: "90–100", max: 1 },
  { label: "100%+", short: "100%+", max: Infinity },
];
const RATIO_BINS = [
  { label: "Under 80%", short: "<80%", max: 0.8 }, { label: "80–100%", short: "80–100", max: 1 }, { label: "100–110%", short: "100–110", max: 1.1 },
  { label: "110–125%", short: "110–125", max: 1.25 }, { label: "125–150%", short: "125–150", max: 1.5 }, { label: "150–200%", short: "150–200", max: 2 },
  { label: "200%+", short: "200%+", max: Infinity },
];

const money = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;
const compact = (n: number) => n >= 1e6 ? `$${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M` : n >= 1e3 ? `$${Math.round(n / 1e3)}K` : `$${Math.round(n)}`;
const pct = (n: number | null | undefined) => n == null ? "—" : `${Math.round(n * 100)}%`;
const premium = (ratio: number | null | undefined) => ratio == null ? "—" : `${ratio >= 1 ? "+" : "−"}${Math.abs(Math.round((ratio - 1) * 100))}%`;
const monthLabel = (key: string, withYear = false) => new Date(`${key}-01T12:00:00`).toLocaleDateString("en-US", withYear ? { month: "short", year: "numeric" } : { month: "short" });
const formatDate = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0];
  const raw = max / count;
  const step = [1, 2, 2.5, 5, 10].map((m) => m * 10 ** Math.floor(Math.log10(raw))).find((s) => s >= raw) ?? raw;
  return Array.from({ length: Math.ceil(max / step) + 1 }, (_, i) => i * step);
}

/** Bar path with a 4px rounded data-end and a square baseline. */
function columnPath(x: number, y: number, w: number, h: number, r = 4): string {
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

type Tip = { x: number; y: number; body: ReactNode } | null;

function Tooltip({ tip }: { tip: Tip }) {
  if (!tip) return null;
  return <div role="status" className="pointer-events-none absolute z-10 min-w-40 -translate-x-1/2 -translate-y-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg" style={{ left: tip.x, top: tip.y - 10 }}>{tip.body}</div>;
}

function TipRow({ color, value, label, line = false }: { color?: string; value: string; label: string; line?: boolean }) {
  return <div className="flex items-center gap-2 py-0.5">{color && <span aria-hidden="true" className={line ? "h-0.5 w-3 rounded" : "h-2.5 w-2.5 rounded-sm"} style={{ background: color }} />}<strong className="font-semibold text-slate-900">{value}</strong><span className="text-slate-500">{label}</span></div>;
}

function Card({ title, subtitle, children, className = "" }: { title: string; subtitle?: string; children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-slate-200 bg-white p-4 sm:p-5 ${className}`}><h3 className="text-sm font-semibold text-slate-900">{title}</h3>{subtitle && <p className="mt-0.5 text-xs leading-5 text-slate-500">{subtitle}</p>}<div className="mt-4">{children}</div></section>;
}

function StatTile({ label, value, detail, hero = false }: { label: string; value: string; detail: string; hero?: boolean }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs font-medium text-slate-500">{label}</p><p className={`mt-1 font-semibold text-slate-950 ${hero ? "text-5xl" : "text-2xl"}`}>{value}</p><p className="mt-1 text-xs leading-5 text-slate-500">{detail}</p></div>;
}

function OutcomesChart({ months }: { months: SaleAnalytics["months"] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip>(null);
  const [hover, setHover] = useState<number | null>(null);
  const height = 240, left = 40, bottom = 26, top = 8;
  const totals = months.map((m) => OUTCOME_ORDER.reduce((sum, key) => sum + m[key], 0));
  const ticks = niceTicks(Math.max(1, ...totals));
  const yMax = ticks[ticks.length - 1];
  const plotW = Math.max(0, width - left - 8), plotH = height - top - bottom;
  const band = months.length ? plotW / months.length : 0;
  const barW = Math.max(2, Math.min(24, band * 0.6));
  const y = (v: number) => top + plotH - (v / yMax) * plotH;
  const labelEvery = Math.max(1, Math.ceil(40 / Math.max(band, 1)));
  return <div ref={ref} className="relative">
    <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">{OUTCOME_ORDER.map((key) => <li key={key} className="flex items-center gap-1.5"><span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm" style={{ background: OUTCOME_STYLE[key].color }} />{OUTCOME_STYLE[key].label}</li>)}</ul>
    {width > 0 && <svg width={width} height={height} role="img" aria-label="Sale outcomes by month" onPointerLeave={() => { setTip(null); setHover(null); }}>
      {ticks.map((t) => <g key={t}><line x1={left} x2={width - 8} y1={y(t)} y2={y(t)} stroke={t === 0 ? INK.axis : INK.grid} /><text x={left - 6} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill={INK.muted} style={{ fontVariantNumeric: "tabular-nums" }}>{t.toLocaleString("en-US")}</text></g>)}
      {months.map((m, i) => {
        const x = left + i * band + (band - barW) / 2;
        let base = 0;
        const present = OUTCOME_ORDER.filter((key) => m[key] > 0);
        return <g key={m.month} opacity={hover === null || hover === i ? 1 : 0.55}>
          {present.map((key, index) => {
            const y0 = y(base), y1 = y(base + m[key]);
            base += m[key];
            const h = Math.max(0, y0 - y1 - (index > 0 ? 2 : 0));
            return index === present.length - 1
              ? <path key={key} d={columnPath(x, y1, barW, h)} fill={OUTCOME_STYLE[key].color} />
              : <rect key={key} x={x} y={y1} width={barW} height={h} fill={OUTCOME_STYLE[key].color} />;
          })}
          {i % labelEvery === 0 && <text x={x + barW / 2} y={height - 8} textAnchor="middle" fontSize={11} fill={INK.muted}>{monthLabel(m.month, i === 0 || m.month.endsWith("-01"))}</text>}
          <rect x={left + i * band} y={top} width={band} height={plotH} fill="transparent" tabIndex={0}
            onPointerMove={() => { setHover(i); setTip({ x: x + barW / 2, y: y(totals[i]), body: <><p className="mb-1 font-semibold text-slate-900">{monthLabel(m.month, true)} · {totals[i].toLocaleString("en-US")} sales</p>{OUTCOME_ORDER.map((key) => <TipRow key={key} color={OUTCOME_STYLE[key].color} value={m[key].toLocaleString("en-US")} label={OUTCOME_STYLE[key].label} />)}</> }); }}
            onFocus={() => { setHover(i); setTip({ x: x + barW / 2, y: y(totals[i]), body: <p className="font-semibold">{monthLabel(m.month, true)}: {totals[i]} sales</p> }); }} onBlur={() => { setTip(null); setHover(null); }} />
        </g>;
      })}
    </svg>}
    <Tooltip tip={tip} />
    <details className="mt-3 text-xs text-slate-600"><summary className="cursor-pointer font-medium text-teal-700">Show as table</summary>
      <div className="mt-2 max-h-64 overflow-auto"><table className="w-full text-left" style={{ fontVariantNumeric: "tabular-nums" }}><thead><tr className="text-slate-500"><th className="py-1 pr-3 font-medium">Month</th>{OUTCOME_ORDER.map((key) => <th key={key} className="py-1 pr-3 text-right font-medium">{OUTCOME_STYLE[key].label}</th>)}</tr></thead>
        <tbody>{[...months].reverse().map((m) => <tr key={m.month} className="border-t border-slate-100"><td className="py-1 pr-3">{monthLabel(m.month, true)}</td>{OUTCOME_ORDER.map((key) => <td key={key} className="py-1 pr-3 text-right">{m[key].toLocaleString("en-US")}</td>)}</tr>)}</tbody></table></div>
    </details>
  </div>;
}

function CountyWinRates({ counties, showState }: { counties: SaleAnalytics["counties"]; showState: boolean }) {
  const rows = counties.filter((c) => c.third_party + c.plaintiff >= 5).slice(0, 14);
  if (!rows.length) return <p className="text-sm text-slate-500">Not enough sales with a published buyer yet.</p>;
  return <ul className="space-y-2.5">{rows.map((c) => {
    const buyers = c.third_party + c.plaintiff;
    return <li key={`${c.state}-${c.county}`} className="grid grid-cols-[7.5rem_1fr] items-center gap-3 text-xs" title={`${c.county}: third-party bidders won ${c.third_party} of ${buyers} sales with a published buyer${c.median_bid_to_ask != null ? `; median winning bid ${premium(c.median_bid_to_ask)} vs. ask` : ""}`}>
      <span className="truncate text-slate-700">{c.county}{showState ? `, ${c.state}` : ""}</span>
      <span className="flex items-center gap-2"><span className="h-3 rounded-r" style={{ width: `calc(${(c.third_party_rate ?? 0) * 100}% * 0.72)`, minWidth: 2, background: SERIES }} /><span className="whitespace-nowrap text-slate-600" style={{ fontVariantNumeric: "tabular-nums" }}><strong className="font-semibold text-slate-900">{pct(c.third_party_rate)}</strong> · {c.third_party} of {buyers}</span></span>
    </li>;
  })}</ul>;
}

function AskVsBid({ points: all }: { points: PricedSale[] }) {
  const points = useMemo(() => all.filter((p): p is PricedSale & { ask: number; bid_to_ask: number } => p.ask != null && p.ask > 0 && p.bid_to_ask != null), [all]);
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip>(null);
  const [active, setActive] = useState<number | null>(null);
  const height = 300, left = 52, bottom = 36, top = 10, right = 12;
  const values = points.flatMap((p) => [p.ask, p.winning_bid]).filter((v) => v > 0);
  const lo = Math.min(...values) * 0.85, hi = Math.max(...values) * 1.15;
  const plotW = Math.max(0, width - left - right), plotH = height - top - bottom;
  const scale = (v: number, size: number) => ((Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * size;
  const x = (v: number) => left + scale(v, plotW);
  const y = (v: number) => top + plotH - scale(v, plotH);
  const ticks = [5e3, 1e4, 25e3, 5e4, 1e5, 25e4, 5e5, 1e6, 25e5, 5e6].filter((t) => t >= lo && t <= hi);
  // Keep x labels at least 40px apart so they never collide on narrow screens.
  const xTicks: number[] = [];
  for (const t of ticks) if (!xTicks.length || x(t) - x(xTicks[xTicks.length - 1]) >= 40) xTicks.push(t);
  const labelAt = 10 ** (Math.log10(lo) + (Math.log10(hi) - Math.log10(lo)) * 0.9);
  const nearest = (px: number, py: number) => {
    let best = -1, dist = 24 * 24;
    points.forEach((p, i) => { const d = (x(p.ask) - px) ** 2 + (y(p.winning_bid) - py) ** 2; if (d < dist) { dist = d; best = i; } });
    return best;
  };
  const show = (i: number) => {
    const p = points[i];
    setActive(i);
    setTip({ x: x(p.ask), y: y(p.winning_bid), body: <><p className="mb-1 font-semibold text-slate-900">{p.address ?? "Address unavailable"}{p.city ? `, ${p.city}` : ""}</p><p className="mb-1 text-slate-500">{p.county} County · sold {formatDate(p.sold_on)}</p><TipRow value={money(p.winning_bid)} label="winning bid" /><TipRow value={money(p.ask)} label="ask" /><TipRow value={premium(p.bid_to_ask)} label="vs. ask" /></> });
  };
  if (!points.length) return <p className="text-sm text-slate-500">No third-party sales with both an ask and a winning bid in this selection.</p>;
  return <div ref={ref} className="relative">
    {width > 0 && <svg width={width} height={height} role="img" aria-label="Asking price against winning bid for third-party sales"
      onPointerMove={(e) => { const box = e.currentTarget.getBoundingClientRect(); const i = nearest(e.clientX - box.left, e.clientY - box.top); if (i >= 0) show(i); else { setTip(null); setActive(null); } }}
      onPointerLeave={() => { setTip(null); setActive(null); }}>
      {ticks.map((t) => <g key={t}><line x1={x(t)} x2={x(t)} y1={top} y2={top + plotH} stroke={INK.grid} /><line x1={left} x2={left + plotW} y1={y(t)} y2={y(t)} stroke={INK.grid} />
        {xTicks.includes(t) && <text x={x(t)} y={height - bottom + 16} textAnchor="middle" fontSize={11} fill={INK.muted}>{compact(t)}</text>}<text x={left - 6} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill={INK.muted}>{compact(t)}</text></g>)}
      <line x1={x(lo)} y1={y(lo)} x2={x(hi)} y2={y(hi)} stroke={INK.secondary} strokeWidth={1} />
      <text x={x(labelAt) + 4} y={y(labelAt) + 16} textAnchor="start" fontSize={11} fill={INK.secondary} transform={`rotate(${-Math.atan2(plotH, plotW) * 180 / Math.PI} ${x(labelAt) + 4} ${y(labelAt) + 16})`}>bid = ask</text>
      {points.map((p, i) => <circle key={p.sale_id} cx={x(p.ask)} cy={y(p.winning_bid)} r={i === active ? 6 : 4} fill={SERIES} fillOpacity={0.85} stroke="#fff" strokeWidth={2} />)}
      <text x={left + plotW / 2} y={height - 4} textAnchor="middle" fontSize={11} fill={INK.secondary}>Ask (minimum bid)</text>
      <text transform={`translate(12 ${top + plotH / 2}) rotate(-90)`} textAnchor="middle" fontSize={11} fill={INK.secondary}>Winning bid</text>
    </svg>}
    <Tooltip tip={tip} />
  </div>;
}

function Columns({ data, label }: { data: Array<{ label: string; short?: string; value: number }>; label: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip>(null);
  const height = 220, left = 8, bottom = 26, top = 20;
  const max = Math.max(1, ...data.map((d) => d.value));
  const plotW = Math.max(0, width - left * 2), plotH = height - top - bottom;
  const band = data.length ? plotW / data.length : 0;
  const barW = Math.min(24, band * 0.6);
  const total = data.reduce((sum, d) => sum + d.value, 0);
  return <div ref={ref} className="relative">
    {width > 0 && <svg width={width} height={height} role="img" aria-label={label} onPointerLeave={() => setTip(null)}>
      <line x1={left} x2={width - left} y1={top + plotH} y2={top + plotH} stroke={INK.axis} />
      {data.map((d, i) => {
        const h = (d.value / max) * plotH, x = left + i * band + (band - barW) / 2, yTop = top + plotH - h;
        return <g key={d.label}>
          {h > 0 && <path d={columnPath(x, yTop, barW, h)} fill={SERIES} />}
          <text x={x + barW / 2} y={yTop - 6} textAnchor="middle" fontSize={11} fill={INK.secondary} style={{ fontVariantNumeric: "tabular-nums" }}>{d.value.toLocaleString("en-US")}</text>
          <text x={x + barW / 2} y={height - 8} textAnchor="middle" fontSize={10.5} fill={INK.muted}>{band < 64 && d.short ? d.short : d.label}</text>
          <rect x={left + i * band} y={top} width={band} height={plotH} fill="transparent" onPointerMove={() => setTip({ x: x + barW / 2, y: yTop, body: <><TipRow value={d.value.toLocaleString("en-US")} label={`sales · ${d.label}`} /><TipRow value={pct(total ? d.value / total : null)} label="of the total" /></> })} />
        </g>;
      })}
    </svg>}
    <Tooltip tip={tip} />
  </div>;
}

function RecentSales({ points }: { points: PricedSale[] }) {
  const [all, setAll] = useState(false);
  const rows = all ? points : points.slice(0, 15);
  return <div className="overflow-x-auto"><table className="w-full min-w-[820px] text-left text-xs" style={{ fontVariantNumeric: "tabular-nums" }}>
    <thead><tr className="border-b border-slate-200 text-slate-500"><th className="py-2 pr-3 font-medium">Sold</th><th className="py-2 pr-3 font-medium">Property</th><th className="py-2 pr-3 font-medium">County</th><th className="py-2 pr-3 text-right font-medium">Ask</th><th className="py-2 pr-3 text-right font-medium">Winning bid</th><th className="py-2 pr-3 text-right font-medium">vs. ask</th><th className="py-2 pr-3 text-right font-medium">Est. value</th><th className="py-2 text-right font-medium">% of value</th></tr></thead>
    <tbody>{rows.map((p) => <tr key={p.sale_id} className="border-b border-slate-100 text-slate-700"><td className="py-2 pr-3 whitespace-nowrap">{formatDate(p.sold_on)}</td><td className="py-2 pr-3">{p.address ?? "—"}{p.city ? `, ${p.city}` : ""}</td><td className="py-2 pr-3">{p.county}</td><td className="py-2 pr-3 text-right">{p.ask == null ? "—" : money(p.ask)}</td><td className="py-2 pr-3 text-right font-semibold text-slate-900">{money(p.winning_bid)}</td><td className="py-2 pr-3 text-right">{premium(p.bid_to_ask)}</td><td className="py-2 pr-3 text-right">{p.estimated_value == null ? "—" : money(p.estimated_value)}</td><td className="py-2 text-right">{pct(p.bid_to_value)}</td></tr>)}</tbody>
  </table>{points.length > 15 && <button type="button" onClick={() => setAll(!all)} className="mt-3 text-xs font-semibold text-teal-700 hover:underline">{all ? "Show fewer" : `Show all ${points.length.toLocaleString("en-US")} sales`}</button>}</div>;
}

function binned(points: PricedSale[], ratio: (p: PricedSale) => number | null, bins: typeof RATIO_BINS) {
  const counts = bins.map((bin) => ({ label: bin.label, short: bin.short, value: 0 }));
  for (const p of points) {
    const r = ratio(p);
    if (r != null) counts[bins.findIndex((bin) => r < bin.max)].value += 1;
  }
  return counts;
}

/** The dashboard's Analytics tab: past sale outcomes and winning bids for the selected state and county. */
export function SaleAnalyticsView({ state, county, stateName }: { state: string; county: string; stateName: string }) {
  const [months, setMonths] = useState<number | undefined>(24);
  const [data, setData] = useState<SaleAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Loading until the response for the current selection arrives; the previous render stays on screen.
  const requestKey = `${state}|${county}|${months ?? "all"}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== requestKey;
  useEffect(() => {
    let active = true;
    getSaleAnalytics({ state, county: county || undefined, months })
      .then((result) => { if (active) { setData(result); setError(null); } })
      .catch(() => { if (active) setError("Sale analytics are unavailable right now."); })
      .finally(() => { if (active) setLoadedKey(requestKey); });
    return () => { active = false; };
  }, [state, county, months, requestKey]);

  const ratioBins = useMemo(() => binned(data?.points ?? [], (p) => p.bid_to_ask, RATIO_BINS), [data]);
  const valueBins = useMemo(() => binned(data?.points ?? [], (p) => p.bid_to_value, VALUE_BINS), [data]);
  const place = county ? `${county} County, ${stateName}` : stateName;
  const s = data?.summary;
  const knownBuyer = s ? s.third_party + s.plaintiff : 0;

  return <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50">
    <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h2 className="text-lg font-bold text-slate-950">Past sale analytics</h2><p className="text-sm text-slate-500">{place} · completed sheriff sales, as published by the sheriff</p></div>
        <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-1" role="group" aria-label="Time period">{PERIODS.map((p) => <button key={p.label} type="button" onClick={() => setMonths(p.months)} aria-pressed={months === p.months} className={`rounded-md px-2.5 py-1.5 text-xs font-semibold ${months === p.months ? "bg-white text-teal-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}>{p.label}</button>)}</div>
      </div>

      {error && <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      {!data && loading && <p className="p-8 text-center text-sm text-slate-500">Loading sale analytics…</p>}
      {data && s && s.completed === 0 && <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600"><p className="font-semibold text-slate-900">No completed sales with published results for {place} yet.</p><p className="mt-1">Sale results are published for New Jersey, Ohio and Florida so far. As other states publish outcomes, they will appear here.</p></div>}

      {data && s && s.completed > 0 && <div className={`space-y-4 transition-opacity ${loading ? "opacity-60" : ""}`}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile hero label="Third-party win rate" value={pct(s.third_party_rate)} detail={`${s.third_party.toLocaleString("en-US")} of ${knownBuyer.toLocaleString("en-US")} sales with a published buyer went to an outside bidder`} />
          <StatTile label="Median winning bid vs. ask" value={premium(s.median_bid_to_ask)} detail={`Third-party sales with both figures (${s.priced_with_ask.toLocaleString("en-US")})`} />
          <StatTile label="Median winning bid vs. value" value={pct(s.median_bid_to_value)} detail={`Of today's Zestimate, ${s.valued_sales.toLocaleString("en-US")} third-party sales · median bid ${s.median_winning_bid == null ? "—" : compact(s.median_winning_bid)}`} />
          <StatTile label="Completed sales" value={s.completed.toLocaleString("en-US")} detail={`${s.sold.toLocaleString("en-US")} sold${s.unsold ? ` · ${s.unsold.toLocaleString("en-US")} no bids` : ""} · ${s.cancelled.toLocaleString("en-US")} cancelled (${pct(s.completed ? s.cancelled / s.completed : null)})`} />
        </div>

        <Card title="Sale outcomes by month" subtitle="What happened on each sale date. Most scheduled sales are cancelled; of those that sell, the split between outside bidders and lender buy-backs shows how competitive the auctions are. Earlier months have published results for fewer counties.">
          <OutcomesChart months={data.months} />
        </Card>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Ask vs. winning bid" subtitle="Each dot is a sale won by a third-party bidder. Dots above the line sold for more than the ask; hover for the property.">
            <AskVsBid points={data.points} />
          </Card>
          <Card title="Winning bid as a % of the ask" subtitle="How far above the ask outside bidders go: the number of third-party sales in each range.">
            <Columns data={ratioBins} label="Third-party sales by winning bid as a percent of the ask" />
          </Card>
        </div>

        <Card title="Winning bid as a % of estimated value" subtitle={`How much of a property's value outside bidders paid: third-party sales by winning bid as a share of today's Zillow Zestimate (${s.valued_sales.toLocaleString("en-US")} sales with a value). The Zestimate was looked up after the sale, so it reflects today's market, not the day of the auction.`}>
          {s.valued_sales ? <Columns data={valueBins} label="Third-party sales by winning bid as a percent of estimated value" /> : <p className="text-sm text-slate-500">No estimated values for these sales yet.</p>}
        </Card>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Third-party win rate by county" subtitle="Share of sales with a published buyer that an outside bidder won, and how many. Counties with at least 5 such sales.">
            <CountyWinRates counties={data.counties} showState={new Set(data.counties.map((c) => c.state)).size > 1} />
          </Card>
          <Card title="Postponements before the sale" subtitle="How many times sold properties were postponed before they finally sold.">
            <Columns data={data.postponements.map((p) => ({ label: p.postponements, value: p.sales }))} label="Sold properties by number of postponements" />
          </Card>
        </div>

        <Card title="Recent third-party sales" subtitle="Sales won by outside bidders with a published winning bid, newest first. Estimated value is today's Zestimate.">
          <RecentSales points={data.points} />
        </Card>

        <p className="text-xs leading-5 text-slate-500">Winning bids and buyers come from the official sale sites: the sheriff&apos;s CivilView status history in New Jersey and the county RealAuction sites in Ohio and Florida. The ask is the minimum bid: in New Jersey the published upset price, or the judgment where none is listed; in Ohio the opening bid (two-thirds of the appraisal); in Florida the final judgment. &ldquo;No bids&rdquo; means the property was offered and nobody bid the opening price. Estimated value is the Zillow Zestimate looked up after the sale. Lenders usually buy back with a nominal bid, so bid comparisons use third-party sales only. A cancelled sale is counted on its last scheduled date. Data as of {formatDate(data.as_of)}.</p>
      </div>}
    </div>
  </div>;
}
