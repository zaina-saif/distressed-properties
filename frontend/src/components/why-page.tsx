import { ArrowUpRight, Briefcase, Building2, Globe, Landmark, ChartNoAxesCombined, FileSearch, Gauge, Handshake, Home, Layers, Map as MapIcon, ShieldAlert, Sparkles, TrendingUp, Users } from "lucide-react";
import Image from "next/image";
import Link from "next/link";

import { SiteFooter, SiteHeader } from "@/components/marketing-chrome";
import { STATES } from "@/lib/states";

import styles from "./marketing-home.module.css";

const ADVANTAGES = [
  {
    icon: Globe,
    title: "Selected investor opportunities at your fingertips.",
    text: `Sheriff and foreclosure sale listings from ${STATES.length} states, consolidated in one place. Compare opportunities across counties and states, and invest where the numbers are best, not only where you happen to live.`,
    tags: [`${STATES.length} states`, "One portal"],
  },
  {
    icon: Sparkles,
    title: "Equity, ranked for you.",
    text: "Every listing is compared with its estimated market value, so you see the gap between value and minimum bid at a glance. Investor Spotlight ranks the standout properties, so you know which handful deserve your time first.",
    tags: ["Market value vs. minimum bid", "Investor Spotlight"],
  },
  {
    icon: Gauge,
    title: "Will it actually sell on the day?",
    text: "Sheriff sales are uncertain. Postponements, bankruptcies and last-minute settlements pull properties off the list on sale day. Our forecasting model, trained on historical sale outcomes, estimates the probability each property really goes to auction, and shows the reasons behind it.",
    tags: ["Probability to auction", "Sale and postponement history"],
  },
  {
    icon: ShieldAlert,
    title: "Lien risk, screened early.",
    text: "Beyond the foreclosing mortgage or court order, a property can carry other liens. Our lien pre-screening flags the risks a property may be carrying, so you can rule properties in or out before paying for a full title search.",
    tags: ["Lien pre-screening", "Estimated priority"],
  },
];

const BROADER = [
  { icon: Briefcase, title: "For investors", text: "Less time chasing sales that never happen, and more time on properties with real equity, wherever they are." },
  { icon: Landmark, title: "For lenders and institutions", text: "More qualified bidders at each auction means more competition, which can mean better recoveries on defaulted loans." },
  { icon: Home, title: "For communities", text: "Distressed homes that find committed buyers get repaired and lived in again, instead of sitting vacant." },
];

const AUDIENCE = [
  { icon: Handshake, title: "Wholesalers", text: "Find deals with real spread and move on the ones that will actually reach auction." },
  { icon: Briefcase, title: "Real estate investors", text: "Build a pipeline of below-market properties across states without checking county sites one by one." },
  { icon: Users, title: "Realtors with investor clients", text: "Bring your clients vetted, high-equity opportunities before auction day." },
  { icon: Home, title: "New investors", text: "Anyone who wants real estate as an asset class can start with clear numbers instead of guesswork." },
];

const DIVERSIFY = [
  { icon: Building2, title: "A real, tangible asset", text: "Property you can see, improve, rent or sell, not just a line on a statement." },
  { icon: TrendingUp, title: "Equity from day one", text: "Buying below market value means the equity is built in at purchase, which is exactly what sheriff sales can offer." },
  { icon: ChartNoAxesCombined, title: "A different kind of return", text: "Rental income and long-term appreciation, and prices that don't move in step with the stock market." },
];

/** Why investors use Sheriff Sale Hunter: the value, the founder's story and who it is for. */
export function WhyPage() {
  return <div className={styles.root}>
    <SiteHeader active="why"/>
    <main>
      <section className="why-hero container">
        <span className="eyebrow">WHY SHERIFF SALE HUNTER</span>
        <h1>Sheriff sales hold real equity.<br/><em>Finding it shouldn&apos;t take weeks.</em></h1>
        <p className="why-intro">Foreclosure sales are public, but they aren&apos;t easy to use. Sheriff Sale Hunter brings them together, adds the numbers investors need, and tells you which properties are worth your time.</p>
        <div className="hero-buttons"><Link href="/get-started" className="site-button">Start free<ArrowUpRight/></Link><Link href="/pricing" className="site-button button-outline">See pricing</Link></div>
      </section>

      <section className="value-section container why-section">
        <span className="eyebrow">PUBLIC ISN&apos;T THE SAME AS USABLE</span>
        <div className="section-heading"><h2>Hundreds of sources.<br/>One clear view.</h2><p>Doing this by hand means checking every county, clerk and court site, every week, then working out the numbers yourself.</p></div>
        <div className="feature-grid">
          <article className="feature"><div className="feature-icon"><MapIcon size={21}/></div><h3>Scattered across counties</h3><p>Sale lists live on separate sheriff, clerk, court and trustee websites, each with its own layout and schedule. We cover {STATES.length} states in one place.</p></article>
          <article className="feature"><div className="feature-icon"><FileSearch size={21}/></div><h3>Not all of it is online</h3><p>Some of the most useful details are never posted on a portal. We extract them from sale notices and court documents.</p></article>
          <article className="feature"><div className="feature-icon"><Layers size={21}/></div><h3>Consolidated and enriched</h3><p>Listings are cleaned, de-duplicated and enriched with market values, photos, maps, status history and sale outcomes.</p></article>
        </div>
      </section>

      <Advantages/>

      <FounderStory/>

      <section className="value-section container why-section">
        <span className="eyebrow">BIGGER THAN ONE DEAL</span>
        <div className="section-heading"><h2>A nationwide buyer pool<br/>helps everyone.</h2><p>Most distressed-property auctions draw a handful of local bidders who can spare the time. Opening them up to buyers everywhere changes that.</p></div>
        <div className="feature-grid">{BROADER.map((item) => <article key={item.title} className="feature"><div className="feature-icon"><item.icon size={21}/></div><h3>{item.title}</h3><p>{item.text}</p></article>)}</div>
      </section>

      <section className="value-section container why-section">
        <span className="eyebrow">DIVERSIFY WITH BUILT-IN EQUITY</span>
        <div className="section-heading"><h2>The stock market is great.<br/>Real estate rounds it out.</h2><p>Many investors hold most of their wealth in stocks. Real estate adds an asset that behaves differently, and buying at a sheriff sale can mean buying the equity in as well.</p></div>
        <div className="feature-grid">{DIVERSIFY.map((item) => <article key={item.title} className="feature"><div className="feature-icon"><item.icon size={21}/></div><h3>{item.title}</h3><p>{item.text}</p></article>)}</div>
        <p className="data-disclaimer">This is general information, not investment, legal or tax advice. Every investment carries risk. Sheriff-sale properties are usually sold as-is and can involve liens, occupants or redemption rights, so do your own due diligence.</p>
      </section>

      <section className="value-section container why-section">
        <span className="eyebrow">WHO IT&apos;S FOR</span>
        <div className="section-heading"><h2>Built for people who<br/>buy, sell and advise.</h2><p>And for anyone ready to make real estate part of how they invest.</p></div>
        <div className="audience-grid">{AUDIENCE.map((item) => <article key={item.title} className="feature"><div className="feature-icon"><item.icon size={21}/></div><h3>{item.title}</h3><p>{item.text}</p></article>)}</div>
      </section>

      <section className="final-cta"><div className="container"><span className="eyebrow">YOUR NEXT MOVE</span><h2>Spend your time on the<br/>properties that matter.</h2><div className="cta-bottom"><p>Start free with one county. Upgrade when you&apos;re ready.</p><Link className="site-button lime-button" href="/get-started">Get started<ArrowUpRight/></Link></div></div></section>
    </main>
    <SiteFooter/>
  </div>;
}

/** The reasons to use the platform; also shown on the home page right under the hero. */
export function Advantages({ link = false }: { link?: boolean }) {
  return <section id="why" className="why-advantages">
    <div className="container">
      <span className="eyebrow">WHY SHERIFF SALE HUNTER</span>
      <h2>Four reasons every investor should use Sheriff Sale Hunter.</h2>
      <div className="why-advantage-list">{ADVANTAGES.map((item, index) => <article key={item.title} className="why-advantage">
        <span className="why-number">0{index + 1}</span>
        <div className="feature-icon"><item.icon size={21}/></div>
        <div><h3>{item.title}</h3><p>{item.text}</p><div className="feature-tags">{item.tags.map((tag) => <span key={tag}>{tag}</span>)}</div></div>
      </article>)}</div>
      {link && <Link href="/why" className="founder-link">Read the full story: why investors use Sheriff Sale Hunter<ArrowUpRight size={15}/></Link>}
      <p className="data-disclaimer">Values, equity and probabilities are estimates. Lien results are a pre-screening aid, not a title search or legal advice; get a professional title search before you bid.</p>
    </div>
  </section>;
}


/** The founder's sheriff-sale experience; also shown on the home page. */
export function FounderStory({ link = false }: { link?: boolean }) {
  return <section id="story" className="testimonial">
    <div className="testimonial-inner container">
      <div className="testimonial-result">
        <h2 className="founder-heading">Our Story</h2>
        <span>WHY WE BUILT THIS</span>
        <p className="founder-property"><b>51 Hiering Ave, Unit B14</b><br/>Seaside Heights, NJ · bought at sheriff sale</p>
        <figure className="founder-photo">
          <Image src="/marketing/founder/seaside-balcony-view.jpg" alt="Ocean view from the balcony of the founder's Seaside Heights condo" width={1400} height={1050} sizes="(max-width: 900px) 90vw, 400px"/>
          <figcaption>Now running successfully as a short-term rental.</figcaption>
        </figure>
        <strong>≈$200K</strong>
        <p>in equity at purchase</p>
      </div>
      <div className="quote-area">
        <blockquote>“Before I bought my condo, I spent <strong>hundreds of hours</strong> searching for the right property. Even when I found one, I made trip after trip to the sheriff&apos;s office with certified checks, only to see the property <strong>not sold or rescheduled.</strong> That&apos;s what gave me the idea for Sheriff Sale Hunter: calculate the equity, predict whether the sale will happen, give a preliminary lien risk, and show the top properties not just in one area but <strong>across the region, and ultimately the whole country, from one portal.</strong>”</blockquote>
        <div className="quote-attribution"><span className="legacy-logo" aria-hidden="true">S</span><div><b>Founder, Sheriff Sale Hunter</b><p>Real estate investor</p></div></div>
        {link && <Link href="/why" className="founder-link">Why investors use Sheriff Sale Hunter<ArrowUpRight size={15}/></Link>}
        <p className="founder-note">One investor&apos;s experience; results vary and are not guaranteed.</p>
      </div>
    </div>
  </section>;
}
