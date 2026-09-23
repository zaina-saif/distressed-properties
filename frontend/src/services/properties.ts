import type {
  LienCoverageItem,
  PropertyCoverageItem,
  PropertyResponse,
} from "@/types/property";
import type { WarehouseCoverage, WarehouseCursor, WarehouseMonthlyCoverage, WarehousePropertyPage } from "@/types/warehouse-valuation";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export interface PropertyFilters {
  states?: string[];
  counties?: string[];
  zipCode?: string;
  query?: string;
  status?: string;
  statusContains?: string;
  futureOnly?: boolean;
  minEquity?: number;
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

  if (filters.sort) {
    params.set("sort", filters.sort);
  }

  if (filters.sortDirection) {
    params.set("sort_direction", filters.sortDirection);
  }

  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 50));

  const response = await fetch(
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
  if (filters.sort) params.set("sort", filters.sort);
  if (filters.sortDirection) params.set("sort_direction", filters.sortDirection);
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 24));

  const response = await fetch(`${API_URL}/api/v1/properties/export.xlsx?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to export properties: ${response.status}`);
  return response.blob();
}

export async function getPropertyCoverage(): Promise<PropertyCoverageItem[]> {
  const response = await fetch(`${API_URL}/api/v1/properties/facets/coverage`, {
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
  const response = await fetch(
    `${API_URL}/api/v1/properties/${propertyId}/lien-coverage`,
    { cache: "no-store" },
  );

  if (!response.ok) {
    throw new Error(`Failed to load lien coverage: ${response.status}`);
  }

  const result = (await response.json()) as { items: LienCoverageItem[] };
  return result.items;
}

export async function getWarehouseCoverage(state: string): Promise<WarehouseCoverage> {
  const response = await fetch(`${API_URL}/api/v1/warehouse-valuations/coverage?state=${encodeURIComponent(state)}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load warehouse coverage: ${response.status}`);
  return response.json();
}

export async function getWarehouseCounties(state: string, year: number): Promise<string[]> {
  const params = new URLSearchParams({ state, year: String(year) });
  const response = await fetch(`${API_URL}/api/v1/warehouse-valuations/counties?${params}`, { cache: "no-store" });
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
  const response = await fetch(`${API_URL}/api/v1/warehouse-valuations/properties?${params}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load warehouse properties: ${response.status}`);
  return response.json();
}

export async function getWarehouseMonthlyCoverage(state: string, county: string, year: number): Promise<WarehouseMonthlyCoverage> {
  const params = new URLSearchParams({ state, county, year: String(year) });
  const response = await fetch(`${API_URL}/api/v1/warehouse-valuations/months?${params}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load monthly coverage: ${response.status}`);
  return response.json();
}
