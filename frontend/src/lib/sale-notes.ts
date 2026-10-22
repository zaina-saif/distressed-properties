import type { Property } from "@/types/property";

/** Sale-type caveats an investor needs before bidding, or null when there is none. */
export function saleTypeNote(property: Property): string | null {
  if (property.sale_type?.startsWith("Tax foreclosure sale") && property.state === "TX") {
    return "Texas property-tax sale: the former owner can buy the property back after the sale, within 2 years for a homestead or agricultural land and 180 days for other property. The minimum bid covers the taxes, costs and fees owed. Check the redemption terms and get a professional title search before bidding.";
  }
  if (property.sale_type === "Trustee sale (non-judicial foreclosure)" && property.state === "TX") {
    return "Texas trustee sale: the lender forecloses without a court, and a substitute trustee auctions the property on the first Tuesday of the month to the highest bidder for cash. This listing comes from the notice filed with the county clerk; many sales are cancelled or postponed on the day, and no opening bid is published. Liens senior to the one foreclosed survive the sale, so get a professional title search before bidding.";
  }
  if (property.sale_type === "Foreclosure sale (power of sale)" && property.state === "NC") {
    return "North Carolina foreclosure sale: a substitute trustee sells the property at the courthouse after a hearing before the Clerk of Superior Court. The lender's opening bid is posted the day before the sale, and sales are often postponed. For ten days after the sale anyone can upset the bid by at least 5% (minimum $750). Liens senior to the one foreclosed survive the sale, so get a professional title search before bidding.";
  }
  if (property.sale_type === "Tax foreclosure sale" && property.state === "NC") {
    return "North Carolina tax foreclosure sale: the county sells the property at the courthouse to collect unpaid property taxes. For ten days after the sale anyone can upset the bid by at least 5% (minimum $750), and each upset bid starts a new ten-day period; while upset bidding is open, the date shown is the deadline and the bid is the current bid to beat. Addresses on the firm's list are not certified, so check the parcel and get a professional title search before bidding.";
  }
  if (property.sale_type === "Tax-defaulted property sale" && property.state === "NV") {
    return "Nevada tax sale: the county treasurer sells property held in trust after three years of unpaid taxes at a public auction (in person in Clark County, online on Bid4Assets in several other counties). The minimum bid covers the taxes, penalties and costs, and the owner can redeem until the sale. Research the parcel and get a professional title search before bidding.";
  }
  if (property.sale_type === "Tax-defaulted property sale" && property.state === "CA") {
    return "California tax-defaulted property sale: the county sells property after five years of unpaid taxes. The minimum bid covers the taxes, penalties and costs; the owner can redeem only until the business day before the sale, and the buyer gets a tax deed. Some interests survive the sale (such as easements and federal tax liens), so research the parcel and get a title search before bidding.";
  }
  if (property.sale_type === "Judgment execution sale") {
    return "Judgment execution sale: the sheriff is selling to pay a money judgment (for example a condo association's or a creditor's), not foreclosing a mortgage. The buyer usually takes the property subject to its mortgage and any earlier liens, so the minimum bid is not what is owed on the property and no equity is shown. Get a professional title search before bidding.";
  }
  if (property.sale_type === "Master Commissioner judicial sale" && property.state === "KY") {
    return "Kentucky judicial sale: the court must confirm the sale, and if the property sells for less than two-thirds of its appraised value the owner can redeem it within six months. Deposit and payment deadlines are set in the court's sale order. Get a professional title search before bidding.";
  }
  return null;
}
