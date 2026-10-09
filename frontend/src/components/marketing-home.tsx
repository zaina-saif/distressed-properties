"use client";

import { ArrowDown, ArrowLeft, ArrowUp, ArrowUpRight, Bath, BedDouble, CalendarDays, Check, MapPin, Maximize, Play, Search, ShieldCheck, X } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Button, SiteFooter, SiteHeader } from "@/components/marketing-chrome";
import { Advantages, FounderStory } from "@/components/why-page";
import { formatSaleDate, STATES } from "@/lib/states";
import { getPropertyCoverage, getStateSummary, type StateSummary } from "@/services/properties";
import type { PropertyCoverageItem } from "@/types/property";

import styles from "./marketing-home.module.css";

// Real scheduled sales from the platform (snapshot of Oct 9, 2026): high gross equity and a good Zillow listing photo.
// Equity is the Zestimate minus the minimum bid; probability and reasons are the sale-probability model's score and drivers.
type Reason = { up?: boolean; strength: string; text: string };
type Property = { id: number; image: string; address: string; city: string; county: string; state: string; value: number; bid: number; equity: number; probability: number; beds?: number; baths?: number; sqft?: string; date: string; reasons: Reason[] };
const properties: Property[] = [
  { id: 1, image: "https://photos.zillowstatic.com/fp/c175a8e0c54ef40478506588111f538b-p_f.jpg", address: "10746 Charleston Pl", city: "Cooper City", county: "Broward", state: "FL", value: 1432900, bid: 679361, equity: 753539, probability: 18, beds: 4, baths: 3, sqft: "3,088", date: "Oct 20, 2026", reasons: [{ strength: "", text: "First sale date on record: it has never been postponed and no bankruptcy has been filed, so nothing is holding the sale back yet." }, { up: true, strength: "slightly", text: "Its minimum bid is $679,361. Sales around this price go ahead a little more often than usual." }, { up: true, strength: "slightly", text: "It is scheduled for October. Sales in that month go ahead a little more often than usual." }] },
  { id: 2, image: "https://photos.zillowstatic.com/fp/486c0fc1faf7aa80f4de34c63900d7ff-p_f.jpg", address: "840 Stone Hill Oval", city: "Aurora", county: "Portage", state: "OH", value: 669100, bid: 466667, equity: 202433, probability: 17, beds: 4, baths: 4, sqft: "3,034", date: "Oct 26, 2026", reasons: [{ strength: "", text: "First sale date on record: it has never been postponed and no bankruptcy has been filed, so nothing is holding the sale back yet." }, { up: true, strength: "slightly", text: "It is scheduled for October. Sales in that month go ahead a little more often than usual." }] },
  { id: 3, image: "https://photos.zillowstatic.com/fp/ae6aae2999e4fa9e9ff978c8f5524744-p_f.jpg", address: "70 Snyder Hollow Road", city: "New Providence", county: "Lancaster", state: "PA", value: 685800, bid: 155410, equity: 530390, probability: 18, beds: 5, baths: 3, sqft: "3,329", date: "Nov 25, 2026", reasons: [{ strength: "", text: "First sale date on record: it has never been postponed and no bankruptcy has been filed, so nothing is holding the sale back yet." }, { up: true, strength: "slightly", text: "Its minimum bid is $155,410. Sales around this price go ahead a little more often than usual." }, { up: true, strength: "slightly", text: "It is scheduled for November. Sales in that month go ahead a little more often than usual." }] },
  { id: 4, image: "https://photos.zillowstatic.com/fp/9f3fb787d95e6f18546f36d8e83881c3-p_f.jpg", address: "10472 Cobalt Ct", city: "Parkland", county: "Broward", state: "FL", value: 1442500, bid: 970206, equity: 472294, probability: 17, beds: 6, baths: 7, sqft: "4,622", date: "Oct 28, 2026", reasons: [{ strength: "", text: "First sale date on record: it has never been postponed and no bankruptcy has been filed, so nothing is holding the sale back yet." }, { up: true, strength: "slightly", text: "It is scheduled for October. Sales in that month go ahead a little more often than usual." }] },
  { id: 5, image: "https://photos.zillowstatic.com/fp/beede2eb776e965a718b8946d1609ccb-p_f.jpg", address: "621 Linden Lane", city: "Willard", county: "Huron", state: "OH", value: 571700, bid: 276667, equity: 295033, probability: 17, beds: 4, baths: 4, sqft: "6,484", date: "Oct 26, 2026", reasons: [{ strength: "", text: "First sale date on record: it has never been postponed and no bankruptcy has been filed, so nothing is holding the sale back yet." }, { up: true, strength: "slightly", text: "It is scheduled for October. Sales in that month go ahead a little more often than usual." }] },
  { id: 6, image: "https://photos.zillowstatic.com/fp/21810334999995a3d750b745236e167e-p_f.jpg", address: "3 Coleridge Terrace", city: "Fairfield", county: "Essex", state: "NJ", value: 946000, bid: 315849, equity: 630151, probability: 15, sqft: "2,857", date: "Oct 27, 2026", reasons: [{ up: false, strength: "a lot", text: "Sheriff sales in Essex County are postponed or cancelled more often than in most NJ counties." }, { up: false, strength: "a lot", text: "It has been in the sheriff-sale process for 84 days. Cases at this stage go ahead less often than usual." }, { up: true, strength: "somewhat", text: "It has been on the sale calendar twice before and is still moving forward. Cases that keep coming back tend to sell eventually." }, { up: true, strength: "slightly", text: "The sale has been postponed 3 times (1 by the lender, 2 by the owner). In similar cases that often comes just before the sale finally goes ahead." }] },
];
const money = (n: number) => "$" + n.toLocaleString("en-US");
const compactMoney = (n: number) => n >= 1e9 ? `$${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `$${(n / 1e6).toFixed(n >= 1e8 ? 0 : 1)}M` : `$${Math.round(n / 1e3)}K`;
const stateName = (code: string) => STATES.find((s) => s.code === code)?.name ?? code;

/** Live per-state totals for the states the dashboard covers, largest first. */
function StateOpportunities({ summary, coverage }: { summary: StateSummary[] | null; coverage: PropertyCoverageItem[] }) {
  const maxSales = Math.max(1, ...(summary ?? []).map((s) => s.scheduled_sales));
  const maxEquity = Math.max(1, ...(summary ?? []).map((s) => s.gross_equity));
  return <section id="states" className="states-section container"><span className="eyebrow">OPPORTUNITY BY STATE</span><div className="section-heading"><h2>Every state we cover,<br/>side by side.</h2><p>Scheduled sales and the gross equity behind them, live from the platform. Choose a state to open it on the map.</p></div>
    {summary === null ? <div className="state-grid" aria-busy="true">{STATES.map((s) => <div key={s.code} className="state-card is-loading"/>)}</div>
      : summary.length === 0 ? <p className="empty-state">State totals are unavailable right now.</p>
      : <div className="state-grid">{summary.map((s) => <Link key={s.state} href={`/dashboard?state=${s.state}`} className="state-card" aria-label={`Open ${stateName(s.state)} in the dashboard: ${s.scheduled_sales.toLocaleString("en-US")} scheduled sales`}>
        <div className="state-card-head"><div><span className="state-code">{s.state}</span><h3>{stateName(s.state)}</h3>{s.next_sale_date && <p className="state-next-sale">Next sale <b>{formatSaleDate(s.next_sale_date)}</b></p>}</div><ArrowUpRight size={18}/></div>
        <div className="state-metric"><div className="state-metric-label"><span>Properties scheduled</span><strong>{s.scheduled_sales.toLocaleString("en-US")}</strong></div><div className="state-bar"><span style={{ width: `${(s.scheduled_sales / maxSales) * 100}%` }}/></div></div>
        <div className="state-metric"><div className="state-metric-label"><span>Gross equity</span>{s.sales_with_equity ? <strong className="text-equity">{compactMoney(s.gross_equity)}</strong> : <em className="state-pending">Not estimated yet</em>}</div><div className="state-bar state-bar-equity"><span style={{ width: `${(s.gross_equity / maxEquity) * 100}%` }}/></div></div>
        <p className="state-foot">{s.counties} {s.counties === 1 ? "county" : "counties"} · {s.sales_with_equity.toLocaleString("en-US")} with an equity estimate</p>
      </Link>)}</div>}
    {summary && summary.length > 0 && coverage.length > 0 && <div className="county-lists"><h3>Counties with scheduled sales</h3><p>Choose a county to open it on the map. The number is its scheduled sales.</p>
      {summary.map((s) => {
        const counties = coverage.filter((item) => item.state === s.state && item.property_count > 0).sort((a, b) => a.county.localeCompare(b.county));
        if (!counties.length) return null;
        return <details key={s.state} className="county-list"><summary><span>{stateName(s.state)}</span><span>{counties.length} {counties.length === 1 ? "county" : "counties"}</span></summary><ul>{counties.map((item) => <li key={item.county}><Link href={`/dashboard?state=${s.state}&county=${encodeURIComponent(item.county)}`}>{item.county}<span>{item.property_count.toLocaleString("en-US")}</span></Link></li>)}</ul></details>;
      })}</div>}
    <p className="data-disclaimer">Gross equity is estimated market value minus the minimum bid, summed over sales where both are known; it is before liens, costs and fees. Sales whose value or minimum bid is not yet published are counted but not included in equity.</p></section>;
}

function AnimatedStat({ value, prefix = "", suffix = "", label }: { value: number; prefix?: string; suffix?: string; label: string }) {
  const [count, setCount] = useState(value);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const observer = new IntersectionObserver((entries) => {
      if (!entries[0]?.isIntersecting) return;
      let start: number | undefined;
      const animate = (time: number) => {
        start ??= time;
        const progress = Math.min((time - start) / 1000, 1);
        setCount(Math.round(value * (1 - Math.pow(1 - progress, 3))));
        if (progress < 1) requestAnimationFrame(animate);
      };
      requestAnimationFrame(animate); observer.disconnect();
    }, { threshold: .5 });
    observer.observe(element); return () => observer.disconnect();
  }, [value]);
  return <div className="stat" ref={ref}><strong>{prefix}{count.toLocaleString("en-US")}{suffix}</strong><p>{label}</p></div>;
}

function PropertyPhoto({ property }: { property: Property }) {
  // eslint-disable-next-line @next/next/no-img-element -- Zillow listing photo, shown as-is like the dashboard
  return <img src={property.image} alt={`${property.address}, ${property.city}, ${property.state}`} loading="lazy" referrerPolicy="no-referrer"/>;
}

function PropertyCard({ property, onSelect }: { property: Property; onSelect: (p: Property, why?: boolean) => void }) {
  return <article className="property-card"><div className="property-photo"><PropertyPhoto property={property}/><span className="county-tag"><MapPin size={12}/>{property.county} County, {property.state}</span><span className="sample-tag">Sale {property.date}</span></div><div className="property-body"><div className="property-heading"><div><h3>{property.address}</h3><p>{property.city}, {stateName(property.state)}</p></div><Button variant="outline" size="icon" aria-label={`View ${property.address}`} onClick={() => onSelect(property)}><ArrowUpRight/></Button></div><div className="property-facts">{property.beds && <span><BedDouble size={14}/>{property.beds} beds</span>}{property.baths && <span><Bath size={14}/>{property.baths} baths</span>}{property.sqft && <span><Maximize size={13}/>{property.sqft} sqft</span>}</div><div className="price-pair"><div><span>Estimated value</span><strong>{money(property.value)}</strong></div><div><span>Minimum bid</span><strong>{money(property.bid)}</strong></div></div><div className="equity-row"><div><span>Potential equity</span><strong>{money(property.equity)}<ArrowUpRight size={21}/></strong></div><div className="probability"><strong>{property.probability}%</strong><span>Auction probability</span><button type="button" className="probability-why" onClick={() => onSelect(property, true)}>Why this probability?</button></div></div></div></article>;
}

function verdict(probability: number): string {
  if (probability < 15) return "Unlikely to be sold on the next sale date. It will most likely be postponed or cancelled again.";
  if (probability < 35) return "Possible, but it is more likely to be postponed or cancelled than sold on the next date.";
  if (probability < 60) return "A real chance it is sold on the next sale date.";
  return "Likely to be sold on the next sale date.";
}

/** The sale-probability model's reasons for one property, in plain language. */
function ProbabilityReasons({ property, focus }: { property: Property; focus: boolean }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => { if (focus) ref.current?.scrollIntoView({ block: "start", behavior: "smooth" }); }, [focus, property]);
  return <section ref={ref} className="probability-reasons" aria-labelledby="probability-reasons-title"><h3 id="probability-reasons-title">Why {property.probability}% auction probability?</h3><p className="probability-verdict">{verdict(property.probability)}</p>
    <ul>{property.reasons.map((r) => <li key={r.text} className={r.up === undefined ? "is-neutral" : r.up ? "is-up" : "is-down"}><span className="reason-icon" aria-hidden="true">{r.up === undefined ? <Check size={13}/> : r.up ? <ArrowUp size={13}/> : <ArrowDown size={13}/>}</span><div><b>{r.up === undefined ? "Case history" : `${r.up ? "Raises" : "Lowers"} the chance ${r.strength}`}</b><p>{r.text}</p></div></li>)}</ul>
    <p className="data-disclaimer">{property.state !== "NJ" && "Sale outcomes are recorded for New Jersey so far, so the model learned mostly from NJ cases; with no postponement history yet, this estimate stays close to its starting point. "}Tested on 884 recent sales it had never seen, the model told a sale that went ahead from one that did not about 7 times in 10, and its numbers run a little high. Use it to compare properties, not as a promise that a sale will happen.</p></section>;
}

function PropertyExplorer({ onClose, initial, why = false }: { onClose: () => void; initial?: Property; why?: boolean }) {
  const [selected, setSelected] = useState<Property | undefined>(initial);
  const [focusWhy, setFocusWhy] = useState(why);
  const select = (p: Property, showWhy = false) => { setSelected(p); setFocusWhy(showWhy); };
  const [search, setSearch] = useState("");
  const [state, setState] = useState("All states");
  useEffect(() => {
    const previous = document.body.style.overflow; document.body.style.overflow = "hidden";
    const handleKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handleKey);
    return () => { document.body.style.overflow = previous; window.removeEventListener("keydown", handleKey); };
  }, [onClose]);
  const filtered = properties.filter((p) => (state === "All states" || p.state === state) && `${p.address} ${p.city} ${p.county} ${p.state} ${stateName(p.state)}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="modal-backdrop" onClick={onClose}><section className="explorer-modal" role="dialog" aria-modal="true" aria-labelledby="explorer-title" onClick={(e) => e.stopPropagation()}><header><div><span className="eyebrow">PROPERTY INTELLIGENCE</span><h2 id="explorer-title">{selected ? selected.address : "Explore the opportunity."}</h2></div><Button variant="ghost" size="icon" onClick={onClose} aria-label="Close property explorer"><X/></Button></header>{selected ? <div className="property-detail"><Button variant="ghost" onClick={() => setSelected(undefined)}><ArrowLeft/> All properties</Button><PropertyPhoto property={selected}/><p><MapPin size={16}/>{selected.city}, {selected.county} County, {stateName(selected.state)} · sale scheduled {selected.date}</p><div className="detail-numbers"><div><span>Estimated value</span><strong>{money(selected.value)}</strong></div><div><span>Minimum bid</span><strong>{money(selected.bid)}</strong></div><div><span>Potential equity</span><strong className="text-equity">{money(selected.equity)}</strong></div><div><span>Auction probability</span><strong>{selected.probability}%</strong></div></div><ProbabilityReasons property={selected} focus={focusWhy}/><p className="data-disclaimer">A scheduled sale from the platform as of Oct 9, 2026; it may since have sold, been postponed or cancelled. Estimated value is the Zillow Zestimate and equity is estimated value minus minimum bid, before liens, costs, and fees. Independently verify all information before bidding.</p></div> : <><div className="explorer-filters"><label className="search-field"><Search size={18}/><input aria-label="Search properties" placeholder="Search a city, address, county, or state" value={search} onChange={(e) => setSearch(e.target.value)}/></label><select aria-label="Filter by state" value={state} onChange={(e) => setState(e.target.value)}>{["All states", ...new Set(properties.map((p) => p.state))].map((c) => <option key={c}>{c}</option>)}</select></div><div className="explorer-grid">{filtered.map((p) => <PropertyCard key={p.id} property={p} onSelect={select}/>)}</div>{filtered.length === 0 && <p className="empty-state">No properties match your search.</p>}<p className="data-disclaimer">Scheduled sales from the platform as of Oct 9, 2026. Figures are estimates; equity excludes liens, costs, and fees. Sign in to see current listings.</p></>}</section></div>;
}

export function MarketingHome() {
  const [explore, setExplore] = useState(false);
  const [selected, setSelected] = useState<Property>();
  const [why, setWhy] = useState(false);
  const [how, setHow] = useState(false);
  const openProperty = (p: Property, showWhy = false) => { setSelected(p); setWhy(showWhy); setExplore(true); };
  const openExplorer = () => { setSelected(undefined); setWhy(false); setExplore(true); };
  const [summary, setSummary] = useState<StateSummary[] | null>(null);
  const [coverage, setCoverage] = useState<PropertyCoverageItem[]>([]);
  useEffect(() => {
    let active = true;
    const covered = new Set(STATES.map((s) => s.code));
    getStateSummary()
      .then((rows) => { if (active) setSummary(rows.filter((row) => covered.has(row.state))); })
      .catch(() => { if (active) setSummary([]); });
    getPropertyCoverage("scheduled").then((rows) => { if (active) setCoverage(rows); }).catch(() => undefined);
    return () => { active = false; };
  }, []);
  const totals = summary?.length ? {
    sales: summary.reduce((sum, s) => sum + s.scheduled_sales, 0),
    states: summary.length,
    counties: summary.reduce((sum, s) => sum + s.counties, 0),
    equity: summary.reduce((sum, s) => sum + s.gross_equity, 0),
  } : null;
  useEffect(() => {
    if (!explore && !how) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setExplore(false); setHow(false); } };
    const previous = document.body.style.overflow; document.body.style.overflow = "hidden"; window.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = previous; window.removeEventListener("keydown", onKey); };
  }, [explore, how]);
  return <div className={styles.root}>
    <SiteHeader active="home"/>
    <main>
      <section id="home" className="hero"><Image className="hero-image" src="/marketing/nj-neighborhood.jpg" alt="Aerial view of residential properties in a leafy New Jersey neighborhood" fill priority sizes="100vw"/><div className="hero-inner container"><div className="hero-copy"><p className="hero-kicker">One Platform. {STATES.length} States. Thousands of Sheriff Sale Opportunities.</p><h1>Real equity.<br/><em>Real auction odds.</em><br/>Before you bid.</h1><h2>Sheriff sale listings consolidated in one place, so you invest in the best opportunities nationwide, not just the ones within reach.</h2><p>See estimated value, minimum bid, potential equity, liens, sale history, and the probability a property actually reaches auction.</p><div className="hero-buttons"><Link className="site-button button-default" href="/get-started?mode=login&next=%2Fdashboard">Explore Properties for Free<ArrowUpRight/></Link><Button variant="outline" onClick={() => setHow(true)}><Play size={15}/>See How It Works</Button></div><div className="hero-note"><ShieldCheck size={14}/><span>Less guesswork. More intelligence. Better opportunities. <a href="#why" className="hero-why-link">Why investors use it</a></span></div></div><div className="map-pin"><MapPin size={15}/>$307K potential equity</div><div className="intelligence-preview"><div className="preview-top"><span>PROPERTY INTELLIGENCE</span><span>High equity</span></div><h3>124 Maple Avenue</h3><p>Montclair, NJ · Essex County</p><div className="preview-values"><div><span>Estimated value</span><strong>$625,000</strong></div><div><span>Minimum bid</span><strong>$318,000</strong></div></div><div className="preview-equity"><div><span>Potential equity</span><strong>$307,000</strong></div><ArrowUpRight/></div><div className="preview-foot"><CalendarDays size={12}/>82% auction probability · Example</div></div></div></section>
      <Advantages link/>
      <section className="stats-section"><div className="container"><div className="stats-top"><span><span className="status-dot"/>STATES OF OPPORTUNITY</span><span>{STATES.map((s) => s.code).join(" · ")} · Live platform snapshot</span></div>{totals ? <div className="stats-grid"><AnimatedStat value={totals.sales} label="Scheduled sales"/><AnimatedStat value={totals.states} label="States covered"/><AnimatedStat value={totals.counties} label="Counties covered"/><AnimatedStat value={Math.round(totals.equity / 1e6)} prefix="$" suffix="M" label="Estimated gross equity"/></div> : <div className="stats-grid" aria-busy="true">{["Scheduled sales", "States covered", "Counties covered", "Estimated gross equity"].map((label) => <div key={label} className="stat"><strong>—</strong><p>{label}</p></div>)}</div>}</div></section>
      <StateOpportunities summary={summary} coverage={coverage}/>
      <FounderStory link/>
      <section id="news" className="testimonial"><div className="testimonial-inner container"><div className="testimonial-result"><span>THE OPPORTUNITY, REALIZED.</span><strong>$1.2M+</strong><p>in potential equity identified</p></div><div className="quote-area"><blockquote>“With Sheriff Sale Hunter, we were able to find a property with <strong>more than $1.2 million in potential equity.</strong>”</blockquote><div className="quote-attribution"><span className="legacy-logo" aria-label="Legacy monogram">L</span><div><b>Legacy Stays LLC</b><p>Real Estate Investor</p></div></div></div></div></section>
      <section className="opportunities container"><span className="eyebrow">THE OPPORTUNITY IS IN THE DETAILS</span><div className="section-heading"><h2>Where the numbers get interesting.</h2><Link className="site-button button-outline" href="/get-started?mode=login&next=%2Fdashboard">Explore Properties for Free<ArrowUpRight/></Link></div><p className="section-description">Real high-equity sales scheduled across the country, as of Oct 9, 2026.</p><div className="property-grid">{properties.map((p) => <PropertyCard key={p.id} property={p} onSelect={openProperty}/>)}</div><p className="data-disclaimer">Scheduled sales as listed on the platform on Oct 9, 2026; a sale may since have been postponed, cancelled or held. Estimated value is the Zillow Zestimate. Potential equity is estimated value minus the minimum bid and excludes liens, transaction costs, and fees. Always perform independent due diligence.</p></section>
      <section id="contact" className="final-cta"><div className="container"><span className="eyebrow">YOUR NEXT MOVE</span><h2>The next opportunity<br/>is already scheduled.</h2><div className="cta-bottom"><p>Find it before auction day.</p><Link className="site-button lime-button" href="/get-started">Explore Sheriff Sales<ArrowUpRight/></Link></div></div></section>
    </main>
    <SiteFooter/>
    {explore && <PropertyExplorer initial={selected} why={why} onClose={() => setExplore(false)}/>}
    {how && <div className="modal-backdrop" onClick={() => setHow(false)}><section className="explorer-modal" role="dialog" aria-modal="true" aria-labelledby="how-title" onClick={(e) => e.stopPropagation()}><header><div><span className="eyebrow">FROM RESEARCH TO OPPORTUNITY</span><h2 id="how-title">A smarter way to find your next deal.</h2></div><Button variant="ghost" size="icon" onClick={() => setHow(false)} aria-label="Close how it works"><X/></Button></header><div className="how-steps">{[{ title: "Discover", text: "Find sheriff-sale opportunities by county, city, or address. See every county and state we cover in one view instead of checking individual county websites." }, { title: "Evaluate", text: "Compare estimated value and minimum bid, then dig into potential equity, preliminary liens, and sale history." }, { title: "Make your move", text: "Use auction probability to prioritize your research. Verify the property, liens, and current sale details before bidding." }].map((s, i) => <article key={s.title}><strong>0{i + 1}</strong><h3>{s.title}</h3><p>{s.text}</p></article>)}</div><Button className="mt-8" onClick={() => { setHow(false); openExplorer(); }}>Explore Properties<Check/></Button></section></div>}
  </div>;
}
