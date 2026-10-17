import type { Property } from "@/types/property";

/** Sale-type caveats an investor needs before bidding, or null when there is none. */
export function saleTypeNote(property: Property): string | null {
  if (property.sale_type?.startsWith("Tax foreclosure sale") && property.state === "TX") {
    return "Texas property-tax sale: the former owner can buy the property back after the sale, within 2 years for a homestead or agricultural land and 180 days for other property. The minimum bid covers the taxes, costs and fees owed. Check the redemption terms and get a professional title search before bidding.";
  }
  if (property.sale_type === "Trustee sale (non-judicial foreclosure)" && property.state === "TX") {
    return "Texas trustee sale: the lender forecloses without a court, and a substitute trustee auctions the property on the first Tuesday of the month to the highest bidder for cash. This listing comes from the notice filed with the county clerk; many sales are cancelled or postponed on the day, and no opening bid is published. Liens senior to the one foreclosed survive the sale, so get a professional title search before bidding.";
  }
  if (property.sale_type === "Judgment execution sale") {
    return "Judgment execution sale: the sheriff is selling to pay a money judgment (for example a condo association's or a creditor's), not foreclosing a mortgage. The buyer usually takes the property subject to its mortgage and any earlier liens, so the minimum bid is not what is owed on the property and no equity is shown. Get a professional title search before bidding.";
  }
  if (property.sale_type === "Master Commissioner judicial sale" && property.state === "KY") {
    return "Kentucky judicial sale: the court must confirm the sale, and if the property sells for less than two-thirds of its appraised value the owner can redeem it within six months. Deposit and payment deadlines are set in the court's sale order. Get a professional title search before bidding.";
  }
  return null;
}
