import type { Property } from "@/types/property";

/** Sale-type caveats an investor needs before bidding, or null when there is none. */
export function saleTypeNote(property: Property): string | null {
  if (property.sale_type?.startsWith("Tax foreclosure sale") && property.state === "TX") {
    return "Texas property-tax sale: the former owner can buy the property back after the sale, within 2 years for a homestead or agricultural land and 180 days for other property. The minimum bid covers the taxes, costs and fees owed. Check the redemption terms and get a professional title search before bidding.";
  }
  return null;
}
