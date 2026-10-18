/**
 * How a sale works in each state, for someone interested in a property there. Used by the
 * dashboard (when a state is selected) and the How it works page. Facts come from the
 * selling offices' published terms; where they were not confirmed, the text says what to
 * check in the notice instead. Terms vary by county and change, so every guide ends with
 * "confirm with the selling office".
 */
export interface StateGuide {
  code: string;
  name: string;
  /** Who conducts the sale. */
  who: string;
  /** Where the official listing and notice are, and how bidding happens. */
  bid: string;
  /** Deposit and accepted funds. */
  deposit: string;
  /** Payment deadline, confirmation and title after a winning bid. */
  after: string;
  /** Other rules: redemption periods, frequent postponements, county specifics. */
  extra?: string[];
}

const CHECK_DEPOSIT = "The notice of sale states the deposit and the accepted payment; certified funds (a bank or certified check) are the norm, and personal checks are rarely accepted.";
const CHECK_AFTER = "Read the notice for the balance deadline, whether a court must confirm the sale, and any redemption period before you get the deed.";

export const STATE_GUIDES: StateGuide[] = [
  {
    code: "NJ", name: "New Jersey", who: "County sheriff",
    bid: "Each county sheriff posts its sales (most on CivilView); sales are held at the sheriff's office on the scheduled day. Recheck the date shortly before: New Jersey sales are frequently adjourned.",
    deposit: "The winning bidder pays a 20% deposit at the sale, in certified funds.",
    after: "The former owner has 10 days after the sale to redeem or object; if the property is redeemed, the deposit is refunded. The balance is due no later than 30 days after the sale; counties such as Camden charge interest from day 11, and a missed deadline forfeits the deposit.",
  },
  {
    code: "NY", name: "New York", who: "Court-appointed referee",
    bid: "Foreclosures are court-ordered referee auctions, not sheriff sales, held at the county courthouse (Brooklyn auctions are on Thursdays at 360 Adams Street; Bronx auctions are on Mondays). The notice of sale gives the index number, which you can look up on the court's e-filing system.",
    deposit: "Winning bidders typically pay a 10% deposit at the auction.",
    after: "The notice states the approximate judgment; the plaintiff sets its opening bid at the sale. " + CHECK_AFTER,
    extra: ["Adjournments are frequent: recheck the date close to the sale."],
  },
  {
    code: "PA", name: "Pennsylvania", who: "County sheriff",
    bid: "Philadelphia's mortgage-foreclosure sales run online on Bid4Assets; other counties post their own sale lists (Montgomery and Lehigh on CivilView) and set their own conditions of sale.",
    deposit: "In Philadelphia a $10,000 deposit is required to bid and counts toward a 10% down payment; any remaining down payment is due by 5 PM the next business day. Elsewhere, follow the sheriff's conditions of sale.",
    after: "In Philadelphia the balance is due 15 days after the auction, and realty transfer taxes are included in the bid. " + CHECK_AFTER,
  },
  {
    code: "OH", name: "Ohio", who: "County sheriff (online)",
    bid: "All Ohio sheriff sales are held online on each county's sheriff-sale auction site; bidding generally starts at two-thirds of the appraised value.",
    deposit: "A flat deposit, set per sale (often $5,000 or $10,000), must be on account before you can bid.",
    after: "A court confirms the sale; the balance is due within 30 days after the confirmation entry.",
  },
  {
    code: "FL", name: "Florida", who: "Clerk of court (online)",
    bid: "Foreclosure auctions are held online on each county clerk's RealForeclose site.",
    deposit: "The winning bidder deposits 5% of the bid, which is non-refundable; some counties require the deposit on account before the auction.",
    after: "The balance deadline varies by county (same day or next business day). Parties have 10 days after the certificate of sale is filed to object; if none do, the clerk issues the certificate of title.",
  },
  {
    code: "IN", name: "Indiana", who: "County sheriff",
    bid: "Sheriff sales are listed on SRI Services, with the case, judgment and sale details; each county sets where and how bidding happens.",
    deposit: CHECK_DEPOSIT, after: CHECK_AFTER,
  },
  {
    code: "IL", name: "Illinois", who: "Sheriff or a judicial sales company",
    bid: "Many sales are run by The Judicial Sales Corporation (tjsc.com); Lake and Champaign counties' sheriff sales are on CivilView.",
    deposit: "Typical terms are 10% down at the sale and the balance within 24 hours, in certified funds; some Judicial Sales Corporation sales require 25% down from bidders other than the lender, so check each notice.",
    after: "A judge must confirm the sale before the deed is issued.",
  },
  {
    code: "SC", name: "South Carolina", who: "Master-in-equity",
    bid: "The county master-in-equity holds the sale on the monthly sale day (Charleston and Greenville lists are on the masters' pages).",
    deposit: "The winning bidder pays a 5% deposit on sale day.",
    after: "The balance is generally due within 20 to 30 days, depending on the county.",
    extra: ["If the lender asked for a deficiency judgment, bidding stays open for 30 days after the sale and the property is offered again at the end."],
  },
  {
    code: "DE", name: "Delaware", who: "County sheriff",
    bid: "Each county sheriff (New Castle, Kent, Sussex) posts its sales on CivilView.",
    deposit: CHECK_DEPOSIT, after: CHECK_AFTER,
  },
  {
    code: "CO", name: "Colorado", who: "County public trustee",
    bid: "Most foreclosures are non-judicial sales run by the county public trustee; several counties (Adams, Denver, El Paso and others) hold them online on RealForeclose.",
    deposit: CHECK_DEPOSIT,
    after: "The trustee issues a certificate of purchase; title passes once the redemption periods end.",
    extra: ["Homeowners have no redemption right after the sale; junior lienholders can file an intent to redeem within 8 business days."],
  },
  {
    code: "MN", name: "Minnesota", who: "County sheriff",
    bid: "The county sheriff holds the sale (St. Louis and Stearns counties post on CivilView).",
    deposit: CHECK_DEPOSIT,
    after: "The former owner can redeem after the sale, in most cases within six months (twelve for some properties, and shorter when a property is abandoned).",
    extra: ["The owner may stay in the home during the redemption period, so plan for a wait before possession."],
  },
  { code: "LA", name: "Louisiana", who: "Parish sheriff", bid: "Orleans and Ascension parish sheriffs post their sales on CivilView.", deposit: CHECK_DEPOSIT, after: CHECK_AFTER },
  { code: "IA", name: "Iowa", who: "County sheriff", bid: "Pottawattamie, Scott and Story county sheriffs post their sales on CivilView.", deposit: CHECK_DEPOSIT, after: CHECK_AFTER },
  { code: "WA", name: "Washington", who: "County sheriff", bid: "Snohomish County's sheriff posts its sales on CivilView.", deposit: CHECK_DEPOSIT, after: CHECK_AFTER },
  { code: "KS", name: "Kansas", who: "County sheriff", bid: "Shawnee County's sheriff posts its sales on CivilView.", deposit: CHECK_DEPOSIT, after: CHECK_AFTER },
  { code: "ID", name: "Idaho", who: "County sheriff", bid: "Canyon County's sheriff posts its sales on CivilView.", deposit: CHECK_DEPOSIT, after: CHECK_AFTER },
  { code: "OR", name: "Oregon", who: "County sheriff", bid: "Deschutes and Josephine county sheriffs post their sales on CivilView.", deposit: CHECK_DEPOSIT, after: CHECK_AFTER },
  {
    code: "CT", name: "Connecticut", who: "Court-appointed committee",
    bid: "In a foreclosure by sale, a court-appointed committee runs the auction; sales are listed on the Judicial Branch's foreclosure sales site.",
    deposit: "The deposit is usually 10% of the court-found value, by bank or certified check.",
    after: "The court must approve the sale; closing usually follows within 30 days.",
  },
  {
    code: "TX", name: "Texas", who: "Sheriff or constable (tax sales); a substitute trustee (mortgage foreclosures)",
    bid: "Most mortgage foreclosures are trustee sales on the first Tuesday of the month at the place the county designates, from notices filed with the county clerk (Harris, Bexar, Collin and Fort Bend are listed here). Property-tax sales in many counties run online on RealAuction; Dallas, Guadalupe, McLennan and Rockwall sheriff and constable sales are on CivilView.",
    deposit: CHECK_DEPOSIT,
    after: CHECK_AFTER,
    extra: ["Property-tax sales carry a right of redemption: the former owner can buy the property back within 2 years for a homestead or agricultural land, and 180 days for other property. The minimum bid covers the taxes, costs and fees owed."],
  },
  {
    code: "KY", name: "Kentucky", who: "Master commissioner",
    bid: "Judicial sales are conducted by the court's master commissioner (Louisville's upcoming sales are on the Jefferson Circuit Court Commissioner's site).",
    deposit: "Deposit and payment terms are set in the court's sale order; read them before bidding.",
    after: "The court must confirm the sale.",
    extra: ["If the property sells for less than two-thirds of its appraised value, the former owner can redeem it within six months of the sale."],
  },
  {
    code: "OK", name: "Oklahoma", who: "County sheriff",
    bid: "Oklahoma County's sheriff sales are online on Bid4Assets. Tulsa County sales are in person on Wednesdays at 10 AM, with registration from 9:30 (pre-registration is online).",
    deposit: "In Oklahoma County, 10% of the price is due to the court clerk by the end of the next business day.",
    after: "In Oklahoma County the rest is due at least one business day before the confirmation hearing; the sale is final only after the court confirms it.",
  },
  {
    code: "WI", name: "Wisconsin", who: "County sheriff",
    bid: "Dane County sales are in person on Tuesdays at 10 AM in the City-County Building; Milwaukee County is moving its sales online to Bid4Assets.",
    deposit: "The winning bidder usually pays 10% at the sale in certified funds.",
    after: "The circuit court holds a confirmation of sale hearing; the balance is typically due within about 10 days of confirmation.",
  },
  {
    code: "SD", name: "South Dakota", who: "County sheriff",
    bid: "Minnehaha County's mortgage foreclosure sales are on Wednesdays at 11 AM at the Law Enforcement Center in Sioux Falls.",
    deposit: CHECK_DEPOSIT,
    after: "The buyer receives a certificate of sale; the former owner can redeem afterwards, most commonly within 180 days and up to one year.",
    extra: ["In Minnehaha County the sheriff signs the deed on or after the 181st day if the property was not redeemed."],
  },
  {
    code: "CA", name: "California", who: "County treasurer-tax collector",
    bid: "Listed here are the counties' tax-defaulted property sales, held online on Bid4Assets once or twice a year; each parcel's auction page has the opening and closing times. Mortgage foreclosures in California are private trustee sales and are not listed.",
    deposit: "Bid4Assets requires a deposit (set by each county, often a few thousand dollars plus a processing fee) before the sale; the sale page gives the deadline.",
    after: "The full price, plus documentary transfer tax and fees, is due within a few days of the close; the county then records a tax deed to the buyer.",
    extra: ["The owner can redeem only until the close of business on the last business day before the sale; there is no redemption after it.",
            "A tax deed clears most private liens, but some interests survive (for example easements, certain special assessments, and federal tax liens the IRS can redeem). Research the parcel and get a title search before bidding."],
  },
];

export function stateGuide(code: string): StateGuide | undefined {
  return STATE_GUIDES.find((guide) => guide.code === code);
}

/** What to do, step by step, if you are interested in a property in this state. */
export function buyerSteps(guide: StateGuide): { title: string; text: string }[] {
  return [
    { title: "Confirm the sale", text: `${guide.bid} Open the listing's source link to confirm the date and status shortly before the sale.` },
    { title: "Do your homework", text: "Properties are sold as-is, usually without an interior inspection. Check the value, other liens, unpaid taxes and occupancy, and get a professional title search." },
    { title: "Get your funds ready", text: guide.deposit },
    { title: "After you win", text: guide.after },
    ...(guide.extra ?? []).map((text) => ({ title: "Also know", text })),
    { title: "Take possession", text: "Once the sale is final you receive the deed; if someone still lives there, plan for the court process to obtain possession, and for transfer taxes and recording fees." },
  ];
}
