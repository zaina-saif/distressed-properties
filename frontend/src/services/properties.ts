import type {
  LienCoverageItem,
  ParcelReviewItem,
  PropertyResponse,
} from "@/types/property";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export interface PropertyFilters {
  states?: string[];
  counties?: string[];
  zipCode?: string;
  status?: string;
  futureOnly?: boolean;
  minEquity?: number;
  page?: number;
  pageSize?: number;
}

export async function getParcelReviewCandidates(): Promise<ParcelReviewItem[]> {
  const response = await fetch(`${API_URL}/api/v1/properties/parcel-review/candidates`, {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Failed to load parcel candidates: ${response.status}`);
  const result = (await response.json()) as { items: ParcelReviewItem[] };
  return result.items;
}

export async function approveParcelCandidate(propertyId: string, candidateId: number): Promise<void> {
  const response = await fetch(`${API_URL}/api/v1/properties/${propertyId}/parcel-review/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate_id: candidateId }),
  });
  if (!response.ok) throw new Error(`Failed to approve parcel candidate: ${response.status}`);
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
