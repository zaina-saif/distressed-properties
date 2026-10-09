import type {
  LienCoverageItem,
  LienEnrichment,
  LienItem,
  LienSummaryResponse,
  PublicComplaint,
  ProfessionalTitleSearch,
  PropertyCoverageItem,
  PropertyResponse,
} from "@/types/property";
import type { WarehouseCoverage, WarehouseCursor, WarehouseMonthlyCoverage, WarehousePropertyPage } from "@/types/warehouse-valuation";

import { API_URL, authFetch } from "@/lib/api";

/** Aerial photo centred on the property, from NJ's 2020 orthoimagery (404 outside NJ). */
export function aerialPhotoUrl(propertyId: string): string {
  return `${API_URL}/api/v1/properties/${encodeURIComponent(propertyId)}/aerial`;
}

/** Server-side Street View photo for a property (404 when none or not configured). */
export function streetViewUrl(propertyId: string): string {
  return `${API_URL}/api/v1/properties/${encodeURIComponent(propertyId)}/street-view`;
}

export interface PropertyFilters {
  states?: string[];
  counties?: string[];
  zipCode?: string;
  query?: string;
  status?: string;
  statusContains?: string;
  futureOnly?: boolean;
  minEquity?: number;
  investorSpotlight?: boolean;
  sort?: string;
  sortDirection?: "asc" | "desc";
  page?: number;
  pageSize?: number;
}

export async function getProperties(
  filters: PropertyFilters = {},
): Promise<PropertyResponse> {
  const params = new URLSearchParams();

  filters.states?.forEach((state) => params.append("state", state));

  if (filters.counties) {
    filters.counties.forEach((county) => params.append("county", county));
  }

  if (filters.zipCode) {
    params.set("zip_code", filters.zipCode);
  }

  if (filters.query) {
    params.set("q", filters.query);
  }

  if (filters.status) {
    params.set("status", filters.status);
  }

  if (filters.statusContains) {
    params.set("status_contains", filters.statusContains);
  }

  if (filters.futureOnly !== undefined) {
    params.set("future_only", String(filters.futureOnly));
  }

  if (filters.minEquity !== undefined) {
    params.set("min_equity", String(filters.minEquity));
  }

  if (filters.investorSpotlight) {
    params.set("investor_spotlight", "true");
  }

  if (filters.sort) {
    params.set("sort", filters.sort);
  }

  if (filters.sortDirection) {
    params.set("sort_direction", filters.sortDirection);
  }

  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 50));

  const response = await authFetch(
    `${API_URL}/api/v1/properties?${params.toString()}`,
    {
      cache: "no-store",
    },
  );

  if (!response.ok) {
    throw new Error(
      `Failed to load properties: ${response.status}`,
    );
  }

  return response.json();
}

export async function downloadPropertiesXlsx(
  filters: PropertyFilters = {},
): Promise<Blob> {
  const params = new URLSearchParams();
  filters.states?.forEach((state) => params.append("state", state));
  filters.counties?.forEach((county) => params.append("county", county));
  if (filters.zipCode) params.set("zip_code", filters.zipCode);
  if (filters.query) params.set("q", filters.query);
  if (filters.status) params.set("status", filters.status);
  if (filters.statusContains) params.set("status_contains", filters.statusContains);
  if (filters.futureOnly !== undefined) params.set("future_only", String(filters.futureOnly));
  if (filters.minEquity !== undefined) params.set("min_equity", String(filters.minEquity));
  if (filters.investorSpotlight) params.set("investor_spotlight", "true");
  if (filters.sort) params.set("sort", filters.sort);
  if (filters.sortDirection) params.set("sort_direction", filters.sortDirection);
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 24));

  const response = await authFetch(`${API_URL}/api/v1/properties/export.xlsx?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to export properties: ${response.status}`);
  return response.blob();
}

export async function getPropertyCoverage(statusContains?: string): Promise<PropertyCoverageItem[]> {
  const query = statusContains ? `?status_contains=${encodeURIComponent(statusContains)}` : "";
  const response = await fetch(`${API_URL}/api/v1/properties/facets/coverage${query}`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Failed to load property coverage: ${response.status}`);
  }

  const result = (await response.json()) as { items: PropertyCoverageItem[] };
  return result.items;
}

export interface NycAuctionCoverage {
  source_type: string;
  source_url: string;
  last_checked_at: string | null;
  boroughs: { county: string; upcoming: number }[];
  coverage_note: string;
}

export async function getNycAuctionCoverage(): Promise<NycAuctionCoverage> {
  const response = await fetch(`${API_URL}/api/v1/properties/facets/nyc-auction-coverage`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load NYC auction coverage: ${response.status}`);
  return response.json();
}

export async function getLienCoverage(
  propertyId: string,
): Promise<LienCoverageItem[]> {
  const response = await authFetch(
    `${API_URL}/api/v1/properties/${propertyId}/lien-coverage`,
    { cache: "no-store" },
  );

  if (!response.ok) {
    throw new Error(`Failed to load lien coverage: ${response.status}`);
  }

  const result = (await response.json()) as { items: LienCoverageItem[] };
  return result.items;
}

export async function getLiens(propertyId: string): Promise<LienItem[]> {
  const response = await authFetch(`${API_URL}/api/v1/properties/${propertyId}/liens`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load liens: ${response.status}`);
  const result = (await response.json()) as { items: LienItem[] };
  return result.items;
}

export async function getLienEnrichment(propertyId: string): Promise<LienEnrichment | null> {
  const response = await authFetch(`${API_URL}/api/v1/properties/${propertyId}/lien-enrichment`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load public-record enrichment: ${response.status}`);
  const result = (await response.json()) as { item: LienEnrichment | null };
  return result.item;
}

export async function getLienSummary(propertyId: string): Promise<LienSummaryResponse> {
  const response = await authFetch(`${API_URL}/api/v1/properties/${propertyId}/lien-summary`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load lien summary: ${response.status}`);
  return response.json() as Promise<LienSummaryResponse>;
}

export async function getPublicComplaints(propertyId: string): Promise<PublicComplaint[]> {
  const response = await authFetch(`${API_URL}/api/v1/properties/${propertyId}/complaints`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load public complaints: ${response.status}`);
  const result = (await response.json()) as { items: PublicComplaint[] };
  return result.items;
}

export async function getProfessionalTitleSearch(
  propertyId: string,
): Promise<ProfessionalTitleSearch> {
  const response = await authFetch(
    `${API_URL}/api/v1/properties/${propertyId}/professional-title-search`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Failed to load professional title-search provider: ${response.status}`);
  }
  const result = (await response.json()) as { professional_title_search: ProfessionalTitleSearch };
  return result.professional_title_search;
}

export async function getWarehouseCoverage(state: string): Promise<WarehouseCoverage> {
  const response = await authFetch(`${API_URL}/api/v1/warehouse-valuations/coverage?state=${encodeURIComponent(state)}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load warehouse coverage: ${response.status}`);
  return response.json();
}

export async function getWarehouseCounties(state: string, year: number): Promise<string[]> {
  const params = new URLSearchParams({ state, year: String(year) });
  const response = await authFetch(`${API_URL}/api/v1/warehouse-valuations/counties?${params}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load warehouse counties: ${response.status}`);
  const result = (await response.json()) as { counties: string[] };
  return result.counties;
}

export async function getWarehouseProperties(filters: {
  state: string;
  year: number;
  county: string;
  query?: string;
  cursor?: WarehouseCursor | null;
}): Promise<WarehousePropertyPage> {
  const params = new URLSearchParams({ state: filters.state, year: String(filters.year), county: filters.county, page_size: "25" });
  if (filters.query) params.set("q", filters.query);
  if (filters.cursor) {
    params.set("after_parcel", filters.cursor.parcel);
    params.set("after_source", filters.cursor.source);
  }
  const response = await authFetch(`${API_URL}/api/v1/warehouse-valuations/properties?${params}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load warehouse properties: ${response.status}`);
  return response.json();
}

export async function getWarehouseMonthlyCoverage(state: string, county: string, year: number): Promise<WarehouseMonthlyCoverage> {
  const params = new URLSearchParams({ state, county, year: String(year) });
  const response = await authFetch(`${API_URL}/api/v1/warehouse-valuations/months?${params}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load monthly coverage: ${response.status}`);
  return response.json();
}

export interface SalePage {
  title: string | null;
  county: string;
  sheriff_number: string;
  listing: "open" | "sold_or_cancelled";
  fields: Array<{ label: string; value: string }>;
  status_history: Array<{ status: string; date: string }>;
  notes: string[];
  county_search_url: string;
  fetched_at: string;
  source: string;
  sale_logistics: {
    date: string | null;
    time: string | null;
    location: string | null;
    basis: { time: "notice" | "county_typical" | null; location: "notice" | "county_typical" | null };
  };
}

/** Live copy of the sale's CivilView detail page, looked up by sheriff number. */
export async function getSalePage(sheriffSaleId: string): Promise<SalePage> {
  const response = await authFetch(`${API_URL}/api/v1/sale-pages/${encodeURIComponent(sheriffSaleId)}`, { cache: "no-store" });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? "The sheriff sale page could not be loaded.");
  }
  return response.json() as Promise<SalePage>;
}

export interface LandingSummary {
  state: string;
  upcoming_sales: number;
  counties: number;
  next_7_days: number;
  new_this_week: number;
  sales_with_equity: number;
  equity_behind_debt: number;
  last_updated: string | null;
  county_counts: Array<{ county: string; upcoming_sales: number; equity_behind_debt: number }>;
}

/** Headline numbers for the landing page (upcoming NJ sales and equity). */
export async function getLandingSummary(): Promise<LandingSummary> {
  const response = await fetch(`${API_URL}/api/v1/properties/facets/landing-summary?state=NJ`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Landing summary request failed: ${response.status}`);
  return response.json() as Promise<LandingSummary>;
}

export interface StateSummary {
  state: string;
  scheduled_sales: number;
  counties: number;
  sales_with_equity: number;
  gross_equity: number;
  last_updated: string | null;
  next_sale_date: string | null;
}

/** Scheduled sales and gross equity per state, counted the way the dashboard counts them. */
export async function getStateSummary(): Promise<StateSummary[]> {
  const response = await fetch(`${API_URL}/api/v1/properties/facets/state-summary`, { cache: "no-store" });
  if (!response.ok) throw new Error(`State summary request failed: ${response.status}`);
  return ((await response.json()) as { states: StateSummary[] }).states;
}
