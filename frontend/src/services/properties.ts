import type {
  LienCoverageItem,
  PropertyCoverageItem,
  PropertyResponse,
} from "@/types/property";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export interface PropertyFilters {
  states?: string[];
  counties?: string[];
  zipCode?: string;
  query?: string;
  status?: string;
  futureOnly?: boolean;
  minEquity?: number;
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

  if (filters.futureOnly !== undefined) {
    params.set("future_only", String(filters.futureOnly));
  }

  if (filters.minEquity !== undefined) {
    params.set("min_equity", String(filters.minEquity));
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
