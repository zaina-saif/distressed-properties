import { API_URL, authFetch } from "@/lib/api";

export type SaleOutcome = "third_party" | "plaintiff" | "sold_other" | "cancelled";

export interface PricedSale {
  sale_id: string;
  address: string | null;
  city: string | null;
  state: string;
  county: string;
  sold_on: string;
  ask: number | null;
  winning_bid: number;
  bid_to_ask: number | null;
  /** Today's Zestimate, looked up after the sale. */
  estimated_value: number | null;
  bid_to_value: number | null;
}

export interface CountyResults extends Record<SaleOutcome, number> {
  state: string;
  county: string;
  sold: number;
  third_party_rate: number | null;
  median_bid_to_ask: number | null;
}

export interface SaleAnalytics {
  as_of: string;
  summary: Record<SaleOutcome, number> & {
    completed: number;
    sold: number;
    third_party_rate: number | null;
    median_bid_to_ask: number | null;
    priced_with_ask: number;
    median_bid_to_value: number | null;
    valued_sales: number;
    median_winning_bid: number | null;
    third_party_volume: number;
    priced_sales: number;
  };
  months: Array<Record<SaleOutcome, number> & { month: string }>;
  counties: CountyResults[];
  postponements: Array<{ postponements: string; sales: number }>;
  points: PricedSale[];
}

/** Past-sale outcomes and winning bids for the user's coverage (the API applies the plan's limits). */
export async function getSaleAnalytics(filters: { state: string; county?: string; months?: number }): Promise<SaleAnalytics> {
  const params = new URLSearchParams({ state: filters.state });
  if (filters.county) params.append("county", filters.county);
  if (filters.months) params.set("months", String(filters.months));
  const response = await authFetch(`${API_URL}/api/v1/analytics/sales?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load sale analytics: ${response.status}`);
  return (await response.json()) as SaleAnalytics;
}
