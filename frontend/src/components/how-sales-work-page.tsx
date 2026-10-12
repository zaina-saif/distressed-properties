import { ArrowUpRight, Ban, CalendarClock, ClipboardCheck, FileText, Gavel, Home, KeyRound, Landmark, Megaphone, Scale, Search, Wallet } from "lucide-react";
import Link from "next/link";

import { SiteFooter, SiteHeader } from "@/components/marketing-chrome";

import styles from "./marketing-home.module.css";

const STEPS = [
  {
    icon: FileText,
    title: "The borrower defaults and the lender forecloses",
    text: "After missed payments, the lender (or a taxing authority, for unpaid property taxes) starts a foreclosure. In judicial states such as New Jersey, New York, Ohio and Florida this is a court case; in others, such as Colorado and Minnesota, the lender can foreclose without a lawsuit by following a notice process.",
  },
  {
    icon: Scale,
    title: "A judgment or order sets up the sale",
    text: "In a court foreclosure, the judge enters a judgment of foreclosure that states the amount owed and orders the property sold. That judgment amount is often close to what the lender will bid, which is why we show it when no upset price or minimum bid is published.",
  },
  {
    icon: Megaphone,
    title: "The sale is scheduled and advertised",
    text: "The selling office (a sheriff, court-appointed referee or commissioner, county clerk or public trustee) sets a date and publishes the notice of sale: in a newspaper, at the courthouse and, more and more, online. The notice gives the address, case number, sale date and place, and often an upset price, minimum bid or judgment amount, plus the deposit and payment terms.",
  },
  {
    icon: CalendarClock,
    title: "Many sales are postponed or cancelled",
    text: "The borrower can pay off or catch up the loan, file for bankruptcy (which stops the sale), or the lender can ask for an adjournment. Postponements are common and can repeat for months, so a date on a list is not a promise that the property will be auctioned. Our probability-to-auction estimate is built for exactly this.",
  },
  {
    icon: Search,
    title: "You do your homework before sale day",
    text: "Properties are sold as-is, usually without an interior inspection, and the selling office gives no warranties. Check the value, look for other liens, unpaid taxes, HOA dues and municipal charges that may survive the sale, see whether the home is occupied, and read the notice for any redemption rights. Get a professional title search before you bid.",
  },
  {
    icon: Wallet,
    title: "Register and bring the deposit",
    text: "Most sales require bidders to register and to have the deposit ready in certified funds (a bank or certified check, or money already on account for online sales). Deposits range from about 5% to 20% of the winning bid depending on the state and county, and personal checks are rarely accepted.",
  },
  {
    icon: Gavel,
    title: "Auction day",
    text: "The foreclosing lender usually opens with a credit bid of up to what it is owed. Anyone can outbid it; the highest bidder wins and pays the deposit right away. If nobody bids more, the property goes back to the lender and later appears as a bank-owned (REO) listing. Auctions are held in person at a courthouse or sheriff's office, or online on platforms such as RealAuction and Bid4Assets.",
  },
  {
    icon: ClipboardCheck,
    title: "After the sale: balance, objections and confirmation",
    text: "The winner pays the rest of the price by the deadline, which can be the same day, the next business day or up to 30 days later. In many states the borrower or other parties can object or redeem for a set period, and in several states a judge must confirm the sale. Missing the payment deadline usually means losing the deposit.",
  },
  {
    icon: KeyRound,
    title: "Deed and possession",
    text: "Once the sale is final, the selling office delivers a deed (a sheriff's, referee's or trustee's deed, or a certificate of title). If someone still lives in the property, the new owner normally has to go through a court process to obtain possession; plan for that time and cost, and for transfer taxes and recording fees.",
  },
];

const SELLERS = [
  { icon: Gavel, title: "Sheriff", text: "Most states: the county sheriff auctions property under a court judgment (NJ, OH, PA, IN, WI, OK, SD and others)." },
  { icon: Scale, title: "Referee, commissioner or master", text: "Court-appointed officers: a referee in New York, the master commissioner in Kentucky, the master-in-equity in South Carolina, a committee in Connecticut." },
  { icon: Landmark, title: "Clerk or public trustee", text: "Florida's clerks of court run online foreclosure auctions; in Colorado the county public trustee conducts non-judicial foreclosure sales." },
];

/** Special instructions per state; sources are each office's published terms (verify before bidding). */
const STATE_NOTES: { state: string; who: string; notes: string[] }[] = [
  {
    state: "New Jersey", who: "County sheriff",
    notes: ["The winning bidder pays a 20% deposit at the sale, in certified funds.",
      "The former owner has 10 days after the sale to redeem or object; if the property is redeemed, the deposit is refunded.",
      "The balance is due no later than 30 days after the sale; counties such as Camden charge interest from day 11, and a missed deadline forfeits the deposit."],
  },
  {
    state: "New York", who: "Court-appointed referee",
    notes: ["Foreclosures are court-ordered referee auctions, not sheriff sales, usually held at the county courthouse.",
      "The notice of sale states the approximate judgment; the plaintiff sets its opening bid at the sale.",
      "Winning bidders typically pay a 10% deposit at the auction. Adjournments are frequent, so recheck the date close to the sale."],
  },
  {
    state: "Pennsylvania", who: "County sheriff",
    notes: ["Philadelphia's mortgage-foreclosure sales run online on Bid4Assets: a $10,000 deposit is required to bid, and it counts toward a 10% down payment.",
      "Any remaining down payment is due by 5 PM the next business day, and the balance 15 days after the auction; in Philadelphia, realty transfer taxes are included in the bid.",
      "Other counties set their own terms in the sheriff's conditions of sale."],
  },
  {
    state: "Ohio", who: "County sheriff (online, RealAuction)",
    notes: ["All Ohio sheriff sales are held online.",
      "Bidding generally starts at two-thirds of the appraised value, and a flat deposit (often $5,000 or $10,000, set per sale) must be on account before you bid.",
      "A court confirms the sale; the balance is due within 30 days after the confirmation entry."],
  },
  {
    state: "Florida", who: "Clerk of court (online)",
    notes: ["Foreclosure auctions are online, run by each county's clerk.",
      "The winning bidder deposits 5% of the bid, which is non-refundable; the balance deadline varies by county (same day or next business day).",
      "Parties have 10 days after the certificate of sale is filed to object; if none do, the clerk issues the certificate of title."],
  },
  {
    state: "Illinois", who: "Sheriff or a judicial sales company",
    notes: ["Typical terms are 10% down at the sale and the balance within 24 hours, in certified funds.",
      "Some Judicial Sales Corporation sales require 25% down from bidders other than the lender; check each notice.",
      "A judge must confirm the sale before the deed is issued."],
  },
  {
    state: "South Carolina", who: "Master-in-equity",
    notes: ["The winning bidder pays a 5% deposit on sale day.",
      "If the lender asked for a deficiency judgment, bidding stays open for 30 days after the sale and the property is offered again at the end.",
      "The balance is generally due within 20 to 30 days, depending on the county."],
  },
  {
    state: "Kentucky", who: "Master commissioner",
    notes: ["Judicial sales are conducted by the court's master commissioner.",
      "If the property sells for less than two-thirds of its appraised value, the former owner can redeem it within six months of the sale.",
      "Deposit and payment terms are set in the court's sale order; read them before bidding."],
  },
  {
    state: "Oklahoma", who: "County sheriff",
    notes: ["Oklahoma County's sheriff sales are online on Bid4Assets.",
      "There, 10% of the price is due to the court clerk by the end of the next business day, and the rest at least one business day before the confirmation hearing.",
      "The sale is final only after the court confirms it."],
  },
  {
    state: "Wisconsin", who: "County sheriff",
    notes: ["The winning bidder usually pays 10% at the sale in certified funds.",
      "The circuit court holds a confirmation of sale hearing; the balance is typically due within about 10 days of confirmation.",
      "Milwaukee County is moving its sales online to Bid4Assets."],
  },
  {
    state: "Minnesota", who: "County sheriff",
    notes: ["The former owner can redeem after the sale, in most cases within six months (twelve for some properties, and shorter when a property is abandoned).",
      "The owner may stay in the home during the redemption period, so plan for a wait before possession."],
  },
  {
    state: "South Dakota", who: "County sheriff",
    notes: ["The buyer receives a certificate of sale; the former owner can redeem afterwards, most commonly within 180 days and up to one year.",
      "In Minnehaha County the sheriff signs the deed on or after the 181st day if the property was not redeemed."],
  },
  {
    state: "Colorado", who: "County public trustee",
    notes: ["Most foreclosures are non-judicial sales run by the public trustee.",
      "Homeowners have no redemption right after the sale; junior lienholders can file an intent to redeem within 8 business days.",
      "The trustee issues a certificate of purchase; title passes once redemption periods end."],
  },
  {
    state: "Connecticut", who: "Court-appointed committee",
    notes: ["In a foreclosure by sale, a committee runs the auction; the deposit is usually 10% of the court-found value, by bank or certified check.",
      "The court must approve the sale; closing usually follows within 30 days."],
  },
  {
    state: "Texas", who: "Sheriff or constable",
    notes: ["Property-tax sales carry a right of redemption: the former owner can buy the property back within 2 years for a homestead or agricultural land, and 180 days for other property.",
      "The minimum bid covers the taxes, costs and fees owed."],
  },
  {
    state: "Other states", who: "Varies",
    notes: ["For Indiana, Delaware, Iowa, Kansas, Louisiana, Idaho, Oregon and Washington, read each sale notice for the deposit, payment deadline, confirmation and any redemption period, and confirm with the selling office."],
  },
];

/** How a sheriff or foreclosure sale works, step by step, with state-specific notes. */
export function HowSalesWorkPage() {
  return <div className={styles.root}>
    <SiteHeader active="how"/>
    <main>
      <section className="why-hero container">
        <span className="eyebrow">HOW SHERIFF SALES WORK</span>
        <h1>From missed payment to new owner,<br/><em>step by step.</em></h1>
        <p className="why-intro">A sheriff sale is a public auction of a property to pay a debt, most often a defaulted mortgage or unpaid property taxes. The process is similar everywhere, but who runs the sale, the deposit, the deadlines and any redemption rights depend on the state and county.</p>
        <div className="hero-buttons"><Link href="/get-started" className="site-button">Find sales near you<ArrowUpRight/></Link><a href="#state-notes" className="site-button button-outline">State instructions</a></div>
      </section>

      <section className="why-advantages">
        <div className="container">
          <span className="eyebrow">THE PROCESS</span>
          <h2>Nine steps, from foreclosure to the keys.</h2>
          <div className="why-advantage-list">{STEPS.map((step, index) => <article key={step.title} className="why-advantage">
            <span className="why-number">{String(index + 1).padStart(2, "0")}</span>
            <div className="feature-icon"><step.icon size={21}/></div>
            <div><h3>{step.title}</h3><p>{step.text}</p></div>
          </article>)}</div>
        </div>
      </section>

      <section className="value-section container why-section">
        <span className="eyebrow">WHO RUNS THE SALE</span>
        <div className="section-heading"><h2>Not every foreclosure auction<br/>is run by a sheriff.</h2><p>The listing on Sheriff Sale Hunter tells you which kind of sale it is, so you know whose rules apply.</p></div>
        <div className="feature-grid">{SELLERS.map((item) => <article key={item.title} className="feature"><div className="feature-icon"><item.icon size={21}/></div><h3>{item.title}</h3><p>{item.text}</p></article>)}</div>
      </section>

      <section className="value-section container why-section">
        <span className="eyebrow">WHERE WE HELP</span>
        <div className="section-heading"><h2>The homework, done for you.</h2><p>Steps 3 to 5 are where most of the time goes. That is the part Sheriff Sale Hunter takes on.</p></div>
        <div className="feature-grid">
          <article className="feature"><div className="feature-icon"><Megaphone size={21}/></div><h3>Every list in one place</h3><p>Sale notices from sheriffs, referees, clerks and trustees, collected and updated, with status history for every postponement.</p></article>
          <article className="feature"><div className="feature-icon"><Ban size={21}/></div><h3>Will it actually sell?</h3><p>A probability-to-auction estimate for each sale, so you spend less time on properties that will be postponed or cancelled.</p></article>
          <article className="feature"><div className="feature-icon"><Home size={21}/></div><h3>Value, equity and liens</h3><p>Estimated market value against the minimum bid or judgment, plus lien pre-screening, before you order a title search.</p></article>
        </div>
      </section>

      <section id="state-notes" className="value-section container why-section">
        <span className="eyebrow">SPECIAL INSTRUCTIONS BY STATE</span>
        <div className="section-heading"><h2>State and county rules<br/>to know before you bid.</h2><p>Drawn from the selling offices&apos; published terms. Terms change and vary by county, so always read the notice of sale for the property you want.</p></div>
        <div className="state-notes">{STATE_NOTES.map((item) => <article key={item.state} className="state-note">
          <h3>{item.state}</h3><span className="state-note-who">{item.who}</span>
          <ul>{item.notes.map((note) => <li key={note}>{note}</li>)}</ul>
        </article>)}</div>
        <p className="data-disclaimer">This page is general information, not legal, tax or investment advice. Sale terms are set by state law, court orders and each selling office, and they change; confirm the current terms with the sheriff, clerk, referee or trustee, and get a professional title search before you bid.</p>
      </section>

      <section className="final-cta"><div className="container"><span className="eyebrow">READY WHEN YOU ARE</span><h2>See the sales coming up<br/>in your county.</h2><div className="cta-bottom"><p>Start free with one county. Upgrade when you&apos;re ready.</p><Link className="site-button lime-button" href="/get-started">Get started<ArrowUpRight/></Link></div></div></section>
    </main>
    <SiteFooter/>
  </div>;
}
