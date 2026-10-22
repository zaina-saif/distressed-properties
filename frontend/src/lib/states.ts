/** States with sale listings in the dashboard, with the map view used when none is mapped. */
/** taxOnly: every listing is a tax sale, so the dashboard opens the state on "Tax sales". */
/** Phase 1 coverage (October 2026); must match SUPPORTED_STATES in backend/app/auth.py. NV joins
 *  once it has upcoming sales; other states' listings stay in the database, hidden. */
export const STATES: { code: string; name: string; view: [number, number, number]; taxOnly?: boolean }[] = [
  { code: "NJ", name: "New Jersey", view: [40.1, -74.6, 8] },
  { code: "NY", name: "New York", view: [40.72, -73.92, 10] },
  { code: "PA", name: "Pennsylvania", view: [40.9, -77.6, 7] },
  { code: "OH", name: "Ohio", view: [40.3, -82.8, 7] },
  { code: "FL", name: "Florida", view: [27.8, -82.6, 6] },
  { code: "IL", name: "Illinois", view: [40.0, -89.2, 6] },
  { code: "TX", name: "Texas", view: [31.0, -98.5, 6] },
  { code: "CA", name: "California", view: [37.3, -120.5, 6], taxOnly: true },
  { code: "AZ", name: "Arizona", view: [33.5, -112.1, 9] },
  { code: "NC", name: "North Carolina", view: [35.5, -79.4, 7] },
  { code: "GA", name: "Georgia", view: [33.8, -84.4, 9], taxOnly: true },
];

export function isTaxOnlyState(code: string): boolean {
  return STATES.some((item) => item.code === code && item.taxOnly);
}

/** "Tue, Oct 13, 2026" for a YYYY-MM-DD sale date (dates are calendar days, not times). */
export function formatSaleDate(value: string): string {
  return new Date(`${value.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}
