"use client";

import { ArrowLeft, ArrowUpRight, Bath, BedDouble, CalendarDays, ChartNoAxesCombined, Check, Layers, MapPin, Maximize, Play, Radar, Search, ShieldCheck, X } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Button, SiteFooter, SiteHeader } from "@/components/marketing-chrome";
import { FounderStory } from "@/components/why-page";
import { STATES } from "@/lib/states";
import { getPropertyCoverage, getStateSummary, type StateSummary } from "@/services/properties";
import type { PropertyCoverageItem } from "@/types/property";

import styles from "./marketing-home.module.css";

type Property = { id: number; image: string; address: string; city: string; county: string; value: number; bid: number; equity: number; probability: number; beds: number; baths: number | string; sqft: string; date: string };
const properties: Property[] = [
  { id: 1, image: "/marketing/property-colonial.jpg", address: "124 Maple Avenue", city: "Montclair", county: "Essex", value: 625000, bid: 318000, equity: 307000, probability: 82, beds: 4, baths: 2.5, sqft: "2,340", date: "Oct 20, 2026" },
  { id: 2, image: "/marketing/property-brick.jpg", address: "38 Oak Street", city: "Ridgewood", county: "Bergen", value: 540000, bid: 295000, equity: 245000, probability: 76, beds: 3, baths: 2, sqft: "1,920", date: "Oct 23, 2026" },
  { id: 3, image: "/marketing/property-cape.jpg", address: "76 Willow Lane", city: "Westfield", county: "Union", value: 485000, bid: 272000, equity: 213000, probability: 89, beds: 3, baths: 2, sqft: "1,780", date: "Oct 28, 2026" },
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
        <div className="state-card-head"><div><span className="state-code">{s.state}</span><h3>{stateName(s.state)}</h3></div><ArrowUpRight size={18}/></div>
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

function PropertyCard({ property, onSelect }: { property: Property; onSelect: (p: Property) => void }) {
  return <article className="property-card"><div className="property-photo"><Image src={property.image} alt={`Example home in ${property.city}, New Jersey`} fill sizes="(max-width: 600px) 100vw, (max-width: 800px) 50vw, 33vw"/><span className="county-tag"><MapPin size={12}/>{property.county} County</span><span className="sample-tag">Example property</span></div><div className="property-body"><div className="property-heading"><div><h3>{property.address}</h3><p>{property.city}, NJ</p></div><Button variant="outline" size="icon" aria-label={`View ${property.address}`} onClick={() => onSelect(property)}><ArrowUpRight/></Button></div><div className="property-facts"><span><BedDouble size={14}/>{property.beds} beds</span><span><Bath size={14}/>{property.baths} baths</span><span><Maximize size={13}/>{property.sqft} sqft</span></div><div className="price-pair"><div><span>Estimated value</span><strong>{money(property.value)}</strong></div><div><span>Minimum bid</span><strong>{money(property.bid)}</strong></div></div><div className="equity-row"><div><span>Potential equity</span><strong>{money(property.equity)}<ArrowUpRight size={21}/></strong></div><div className="probability"><strong>{property.probability}%</strong><span>Auction probability</span></div></div></div></article>;
}

function PropertyExplorer({ onClose, initial }: { onClose: () => void; initial?: Property }) {
  const [selected, setSelected] = useState<Property | undefined>(initial);
  const [search, setSearch] = useState("");
  const [county, setCounty] = useState("All counties");
  useEffect(() => {
    const previous = document.body.style.overflow; document.body.style.overflow = "hidden";
    const handleKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handleKey);
    return () => { document.body.style.overflow = previous; window.removeEventListener("keydown", handleKey); };
  }, [onClose]);
  const filtered = properties.filter((p) => (county === "All counties" || p.county === county) && `${p.address} ${p.city} ${p.county}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="modal-backdrop" onClick={onClose}><section className="explorer-modal" role="dialog" aria-modal="true" aria-labelledby="explorer-title" onClick={(e) => e.stopPropagation()}><header><div><span className="eyebrow">PROPERTY INTELLIGENCE</span><h2 id="explorer-title">{selected ? selected.address : "Explore the opportunity."}</h2></div><Button variant="ghost" size="icon" onClick={onClose} aria-label="Close property explorer"><X/></Button></header>{selected ? <div className="property-detail"><Button variant="ghost" onClick={() => setSelected(undefined)}><ArrowLeft/> All properties</Button><Image src={selected.image} alt={`Example property in ${selected.city}`} width={1024} height={768}/><p><MapPin size={16}/>{selected.city}, {selected.county} County, NJ</p><div className="detail-numbers"><div><span>Estimated value</span><strong>{money(selected.value)}</strong></div><div><span>Minimum bid</span><strong>{money(selected.bid)}</strong></div><div><span>Potential equity</span><strong className="text-equity">{money(selected.equity)}</strong></div><div><span>Auction probability</span><strong>{selected.probability}%</strong></div></div><p className="data-disclaimer">Illustrative property and figures, not an active listing. Equity is estimated value minus minimum bid, before liens, costs, and fees. Independently verify all information before bidding.</p></div> : <><div className="explorer-filters"><label className="search-field"><Search size={18}/><input aria-label="Search properties" placeholder="Search a city, address, or county" value={search} onChange={(e) => setSearch(e.target.value)}/></label><select aria-label="Filter by county" value={county} onChange={(e) => setCounty(e.target.value)}>{["All counties", "Essex", "Bergen", "Union"].map((c) => <option key={c}>{c}</option>)}</select></div><div className="explorer-grid">{filtered.map((p) => <PropertyCard key={p.id} property={p} onSelect={setSelected}/>)}</div>{filtered.length === 0 && <p className="empty-state">No example properties match your search.</p>}<p className="data-disclaimer">A preview of property intelligence. These properties and figures are illustrative, not live auction listings.</p></>}</section></div>;
}

export function MarketingHome() {
  const [explore, setExplore] = useState(false);
  const [selected, setSelected] = useState<Property>();
  const [how, setHow] = useState(false);
  const openProperty = (p: Property) => { setSelected(p); setExplore(true); };
  const openExplorer = () => { setSelected(undefined); setExplore(true); };
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
      <section id="home" className="hero"><Image className="hero-image" src="/marketing/nj-neighborhood.jpg" alt="Aerial view of residential properties in a leafy New Jersey neighborhood" fill priority sizes="100vw"/><div className="hero-inner container"><div className="hero-copy"><div className="hero-label"><span className="status-dot"/>YOUR SHERIFF SALE EXPERT</div><h1>Find the opportunity<br/><em>before everyone</em><br/>else does.</h1><h2>Sheriff and foreclosure sales across {STATES.length} states. One intelligent platform.</h2><p>See estimated value, minimum bid, potential equity, liens, sale history, and the probability a property actually reaches auction.</p><div className="hero-buttons"><Button onClick={openExplorer}>Explore Properties<ArrowUpRight/></Button><Button variant="outline" onClick={() => setHow(true)}><Play size={15}/>See How It Works</Button></div><div className="hero-note"><ShieldCheck size={14}/>Less guesswork. More intelligence. Better opportunities.</div></div><div className="map-pin"><MapPin size={15}/>$307K potential equity</div><div className="intelligence-preview"><div className="preview-top"><span>PROPERTY INTELLIGENCE</span><span>High equity</span></div><h3>124 Maple Avenue</h3><p>Montclair, NJ · Essex County</p><div className="preview-values"><div><span>Estimated value</span><strong>$625,000</strong></div><div><span>Minimum bid</span><strong>$318,000</strong></div></div><div className="preview-equity"><div><span>Potential equity</span><strong>$307,000</strong></div><ArrowUpRight/></div><div className="preview-foot"><CalendarDays size={12}/>82% auction probability · Example</div></div></div></section>
      <section className="stats-section"><div className="container"><div className="stats-top"><span><span className="status-dot"/>STATES OF OPPORTUNITY</span><span>{STATES.map((s) => s.code).join(" · ")} · Live platform snapshot</span></div>{totals ? <div className="stats-grid"><AnimatedStat value={totals.sales} label="Scheduled sales"/><AnimatedStat value={totals.states} label="States covered"/><AnimatedStat value={totals.counties} label="Counties covered"/><AnimatedStat value={Math.round(totals.equity / 1e6)} prefix="$" suffix="M" label="Estimated gross equity"/></div> : <div className="stats-grid" aria-busy="true">{["Scheduled sales", "States covered", "Counties covered", "Estimated gross equity"].map((label) => <div key={label} className="stat"><strong>—</strong><p>{label}</p></div>)}</div>}</div></section>
      <StateOpportunities summary={summary} coverage={coverage}/>
      <section id="company" className="value-section container"><span className="eyebrow">LESS SEARCHING. MORE SIGNAL.</span><div className="section-heading"><h2>Stop searching sheriff websites.<br/>Start finding deals.</h2><p>We turn fragmented public sheriff-sale information into clear, investor-ready intelligence. Your research, finally connected.</p></div><div className="feature-grid"><article className="feature"><div className="feature-icon"><Layers size={21}/></div><h3>One platform. Every opportunity.</h3><p>Find sheriff and foreclosure sales across {STATES.length} states in one place. Discover properties on a map, track upcoming auctions, and put the whole picture together.</p><div className="feature-tags"><span>Map-based discovery</span><span>{STATES.length} states</span></div></article><article className="feature"><div className="feature-icon"><ChartNoAxesCombined size={21}/></div><h3>Know the numbers that matter.</h3><p>Compare estimated values, minimum bids, and potential equity. Surface the highest-equity opportunities, not just another listing.</p><div className="feature-tags"><span>Equity estimates</span><span>Investor rankings</span></div></article><article className="feature"><div className="feature-icon"><Radar size={21}/></div><h3>See beyond the sale date.</h3><p>Understand preliminary liens, sale and postponement history, and the probability a property actually makes it to auction.</p><div className="feature-tags"><span>Lien intelligence</span><span>Auction probability</span></div></article></div><Link href="/why" className="founder-link">Why investors use Sheriff Sale Hunter<ArrowUpRight size={15}/></Link></section>
      <FounderStory link/>
      <section id="news" className="testimonial"><div className="testimonial-inner container"><div className="testimonial-result"><span>THE OPPORTUNITY, REALIZED.</span><strong>$1.2M+</strong><p>in potential equity identified</p></div><div className="quote-area"><blockquote>“With Sheriff Sale Hunter, we were able to find a property with <strong>more than $1.2 million in potential equity.</strong>”</blockquote><div className="quote-attribution"><span className="legacy-logo" aria-label="Legacy monogram">L</span><div><b>Legacy Stays LLC</b><p>Real Estate Investor</p></div></div></div></div></section>
      <section className="opportunities container"><span className="eyebrow">THE OPPORTUNITY IS IN THE DETAILS</span><div className="section-heading"><h2>Where the numbers get interesting.</h2><Button variant="outline" onClick={openExplorer}>Explore Properties<ArrowUpRight/></Button></div><p className="section-description">A closer look at what investor-ready intelligence can uncover.</p><div className="property-grid">{properties.map((p) => <PropertyCard key={p.id} property={p} onSelect={openProperty}/>)}</div><p className="data-disclaimer">Illustrative properties and estimates. Potential equity excludes liens, transaction costs, and fees. Always perform independent due diligence.</p></section>
      <section id="contact" className="final-cta"><div className="container"><span className="eyebrow">YOUR NEXT MOVE</span><h2>The next opportunity<br/>is already scheduled.</h2><div className="cta-bottom"><p>Find it before auction day.</p><Link className="site-button lime-button" href="/get-started">Explore Sheriff Sales<ArrowUpRight/></Link></div></div></section>
    </main>
    <SiteFooter/>
    {explore && <PropertyExplorer initial={selected} onClose={() => setExplore(false)}/>}
    {how && <div className="modal-backdrop" onClick={() => setHow(false)}><section className="explorer-modal" role="dialog" aria-modal="true" aria-labelledby="how-title" onClick={(e) => e.stopPropagation()}><header><div><span className="eyebrow">FROM RESEARCH TO OPPORTUNITY</span><h2 id="how-title">A smarter way to find your next deal.</h2></div><Button variant="ghost" size="icon" onClick={() => setHow(false)} aria-label="Close how it works"><X/></Button></header><div className="how-steps">{[{ title: "Discover", text: "Find sheriff-sale opportunities by county, city, or address. See every county and state we cover in one view instead of checking individual county websites." }, { title: "Evaluate", text: "Compare estimated value and minimum bid, then dig into potential equity, preliminary liens, and sale history." }, { title: "Make your move", text: "Use auction probability to prioritize your research. Verify the property, liens, and current sale details before bidding." }].map((s, i) => <article key={s.title}><strong>0{i + 1}</strong><h3>{s.title}</h3><p>{s.text}</p></article>)}</div><Button className="mt-8" onClick={() => { setHow(false); openExplorer(); }}>Explore Properties<Check/></Button></section></div>}
  </div>;
}
