"use client";

import { ArrowLeft, ArrowRight, ArrowUpRight, Bath, BedDouble, CalendarDays, ChartNoAxesCombined, Check, Layers, MapPin, Maximize, Menu, Play, Radar, Search, ShieldCheck, X } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import styles from "./marketing-home.module.css";

type Property = { id: number; image: string; address: string; city: string; county: string; value: number; bid: number; equity: number; probability: number; beds: number; baths: number | string; sqft: string; date: string };
const properties: Property[] = [
  { id: 1, image: "/marketing/property-colonial.jpg", address: "124 Maple Avenue", city: "Montclair", county: "Essex", value: 625000, bid: 318000, equity: 307000, probability: 82, beds: 4, baths: 2.5, sqft: "2,340", date: "Oct 20, 2026" },
  { id: 2, image: "/marketing/property-brick.jpg", address: "38 Oak Street", city: "Ridgewood", county: "Bergen", value: 540000, bid: 295000, equity: 245000, probability: 76, beds: 3, baths: 2, sqft: "1,920", date: "Oct 23, 2026" },
  { id: 3, image: "/marketing/property-cape.jpg", address: "76 Willow Lane", city: "Westfield", county: "Union", value: 485000, bid: 272000, equity: 213000, probability: 89, beds: 3, baths: 2, sqft: "1,780", date: "Oct 28, 2026" },
];
const money = (n: number) => "$" + n.toLocaleString("en-US");

function Brand() {
  return <span className="brand"><span className="brand-symbol"><svg viewBox="0 0 28 28" fill="none" aria-hidden="true"><path d="M4 23V11L14 4l10 7v12h-7v-9h-6v9H4Z" stroke="currentColor" strokeWidth="2.1"/><path d="m18 5 6-3v7" stroke="currentColor" strokeWidth="2.1"/></svg></span><span>Distressed<span className="brand-second">Properties<span className="brand-pro">PRO</span></span></span></span>;
}

function Button({ children, className = "", variant = "default", size = "default", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "outline" | "ghost"; size?: "default" | "icon" }) {
  return <button className={`site-button button-${variant} ${size === "icon" ? "button-icon" : ""} ${className}`} {...props}>{children}</button>;
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
  const [mobile, setMobile] = useState(false);
  const [explore, setExplore] = useState(false);
  const [selected, setSelected] = useState<Property>();
  const [how, setHow] = useState(false);
  const openProperty = (p: Property) => { setSelected(p); setExplore(true); };
  const openExplorer = () => { setSelected(undefined); setExplore(true); };
  useEffect(() => {
    if (!explore && !how) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setExplore(false); setHow(false); } };
    const previous = document.body.style.overflow; document.body.style.overflow = "hidden"; window.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = previous; window.removeEventListener("keydown", onKey); };
  }, [explore, how]);
  return <div className={styles.root}>
    <header className="site-header"><div className="nav-inner"><Link href="/" aria-label="Distressed Properties Pro home"><Brand/></Link><nav aria-label="Main navigation" className={mobile ? "main-nav is-open" : "main-nav"}><a href="#home" className="active" onClick={() => setMobile(false)}>Home</a><a href="#company" onClick={() => setMobile(false)}>Company</a><a href="#news" onClick={() => setMobile(false)}>News</a><a href="#contact" onClick={() => setMobile(false)}>Contact</a></nav><div className="nav-actions"><Link href="/get-started" className="site-button nav-cta">Get Started<ArrowUpRight/></Link><Button variant="ghost" size="icon" className="mobile-menu" aria-label={mobile ? "Close menu" : "Open menu"} onClick={() => setMobile(!mobile)}>{mobile ? <X/> : <Menu/>}</Button></div></div></header>
    <main>
      <section id="home" className="hero"><Image className="hero-image" src="/marketing/nj-neighborhood.jpg" alt="Aerial view of residential properties in a leafy New Jersey neighborhood" fill priority sizes="100vw"/><div className="hero-inner container"><div className="hero-copy"><div className="hero-label"><span className="status-dot"/>YOUR DISTRESSED PROPERTY EXPERT</div><h1>Find the opportunity<br/><em>before everyone</em><br/>else does.</h1><h2>Every NJ sheriff sale. One intelligent platform.</h2><p>See estimated value, minimum bid, potential equity, liens, sale history, and the probability a property actually reaches auction.</p><div className="hero-buttons"><Button onClick={openExplorer}>Explore Properties<ArrowUpRight/></Button><Button variant="outline" onClick={() => setHow(true)}><Play size={15}/>See How It Works</Button></div><div className="hero-note"><ShieldCheck size={14}/>Less guesswork. More intelligence. Better opportunities.</div></div><div className="map-pin"><MapPin size={15}/>$307K potential equity</div><div className="intelligence-preview"><div className="preview-top"><span>PROPERTY INTELLIGENCE</span><span>High equity</span></div><h3>124 Maple Avenue</h3><p>Montclair, NJ · Essex County</p><div className="preview-values"><div><span>Estimated value</span><strong>$625,000</strong></div><div><span>Minimum bid</span><strong>$318,000</strong></div></div><div className="preview-equity"><div><span>Potential equity</span><strong>$307,000</strong></div><ArrowUpRight/></div><div className="preview-foot"><CalendarDays size={12}/>82% auction probability · Example</div></div></div></section>
      <section className="stats-section"><div className="container"><div className="stats-top"><span><span className="status-dot"/>A STATE OF OPPORTUNITY</span><span>New Jersey coverage · Platform snapshot</span></div><div className="stats-grid"><AnimatedStat value={1327} label="Upcoming sheriff sales"/><AnimatedStat value={181} label="Sales in the next 7 days"/><AnimatedStat value={17} label="NJ counties covered"/><AnimatedStat value={217} prefix="$" suffix="M" label="Estimated equity opportunities"/></div></div></section>
      <section id="company" className="value-section container"><span className="eyebrow">LESS SEARCHING. MORE SIGNAL.</span><div className="section-heading"><h2>Stop searching sheriff websites.<br/>Start finding deals.</h2><p>We turn fragmented public sheriff-sale information into clear, investor-ready intelligence. Your research, finally connected.</p></div><div className="feature-grid"><article className="feature"><div className="feature-icon"><Layers size={21}/></div><h3>One platform. Every opportunity.</h3><p>Find NJ sheriff sales in one place. Discover properties on a map, track upcoming auctions, and put the whole picture together.</p><div className="feature-tags"><span>Map-based discovery</span><span>17 NJ counties</span></div></article><article className="feature"><div className="feature-icon"><ChartNoAxesCombined size={21}/></div><h3>Know the numbers that matter.</h3><p>Compare estimated values, minimum bids, and potential equity. Surface the highest-equity opportunities, not just another listing.</p><div className="feature-tags"><span>Equity estimates</span><span>Investor rankings</span></div></article><article className="feature"><div className="feature-icon"><Radar size={21}/></div><h3>See beyond the sale date.</h3><p>Understand preliminary liens, sale and postponement history, and the probability a property actually makes it to auction.</p><div className="feature-tags"><span>Lien intelligence</span><span>Auction probability</span></div></article></div></section>
      <section id="news" className="testimonial"><div className="testimonial-inner container"><div className="testimonial-result"><span>THE OPPORTUNITY, REALIZED.</span><strong>$1.2M+</strong><p>in potential equity identified</p></div><div className="quote-area"><blockquote>“With Distressed Properties Pro, we were able to find a property with <strong>more than $1.2 million in potential equity.</strong>”</blockquote><div className="quote-attribution"><span className="legacy-logo" aria-label="Legacy monogram">L</span><div><b>Legacy Sales LLC</b><p>Real Estate Investor</p></div></div></div></div></section>
      <section className="opportunities container"><span className="eyebrow">THE OPPORTUNITY IS IN THE DETAILS</span><div className="section-heading"><h2>Where the numbers get interesting.</h2><Button variant="outline" onClick={openExplorer}>Explore Properties<ArrowUpRight/></Button></div><p className="section-description">A closer look at what investor-ready intelligence can uncover.</p><div className="property-grid">{properties.map((p) => <PropertyCard key={p.id} property={p} onSelect={openProperty}/>)}</div><p className="data-disclaimer">Illustrative properties and estimates. Potential equity excludes liens, transaction costs, and fees. Always perform independent due diligence.</p></section>
      <section id="contact" className="final-cta"><div className="container"><span className="eyebrow">YOUR NEXT MOVE</span><h2>The next opportunity<br/>is already scheduled.</h2><div className="cta-bottom"><p>Find it before auction day.</p><Link className="site-button lime-button" href="/get-started">Explore Distressed Properties<ArrowUpRight/></Link></div></div></section>
    </main>
    <footer className="site-footer"><div className="footer-top"><Link href="/"><Brand/></Link><span>Your Distressed Property Expert.</span><nav aria-label="Footer navigation"><a href="#company">Company</a><a href="#news">News</a><a href="#contact">Contact</a></nav></div><div className="footer-bottom"><span>© {new Date().getFullYear()} Distressed Properties Pro. All rights reserved.</span><span>Intelligence for better-informed investments.<ArrowRight size={14}/></span></div></footer>
    {explore && <PropertyExplorer initial={selected} onClose={() => setExplore(false)}/>}
    {how && <div className="modal-backdrop" onClick={() => setHow(false)}><section className="explorer-modal" role="dialog" aria-modal="true" aria-labelledby="how-title" onClick={(e) => e.stopPropagation()}><header><div><span className="eyebrow">FROM RESEARCH TO OPPORTUNITY</span><h2 id="how-title">A smarter way to find your next deal.</h2></div><Button variant="ghost" size="icon" onClick={() => setHow(false)} aria-label="Close how it works"><X/></Button></header><div className="how-steps">{[{ title: "Discover", text: "Find sheriff-sale opportunities by county, city, or address. Get a statewide view instead of checking individual county websites." }, { title: "Evaluate", text: "Compare estimated value and minimum bid, then dig into potential equity, preliminary liens, and sale history." }, { title: "Make your move", text: "Use auction probability to prioritize your research. Verify the property, liens, and current sale details before bidding." }].map((s, i) => <article key={s.title}><strong>0{i + 1}</strong><h3>{s.title}</h3><p>{s.text}</p></article>)}</div><Button className="mt-8" onClick={() => { setHow(false); openExplorer(); }}>Explore Properties<Check/></Button></section></div>}
  </div>;
}
