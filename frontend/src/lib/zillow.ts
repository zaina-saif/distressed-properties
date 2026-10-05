import type { Property } from "@/types/property";

// Only Zillow-hosted listing photos. Zillow's payload also carries Google
// Street View URLs signed with Zillow's own API key; those are not ours to use.
const ZILLOW_PHOTO_HOST = "https://photos.zillowstatic.com/";

function zillowPhoto(value: unknown): string | null {
  return typeof value === "string" && value.startsWith(ZILLOW_PHOTO_HOST) ? value : null;
}

export function propertyPhotoUrl(property: Property, size: "thumbnail" | "large" = "large"): string | null {
  const data = property.apify_data ?? {};
  const main = (data.mainImage ?? {}) as Record<string, unknown>;
  const listing = Array.isArray(data.listingPhotos) ? (data.listingPhotos as Array<Record<string, unknown>>) : [];
  const candidates = size === "thumbnail"
    ? [main.thumbnail, main.hiRes, listing[0]?.url]
    : [main.hiRes, listing[0]?.url, main.thumbnail];
  for (const candidate of candidates) {
    const url = zillowPhoto(candidate);
    if (url) return url;
  }
  return null;
}

/** The property's Zillow page, from the stored URL or its Zillow ID. */
export function zillowListingUrl(property: Property): string | null {
  const data = property.apify_data ?? {};
  const url = data.propertyUrl;
  if (typeof url === "string" && url.startsWith("https://www.zillow.com/")) return url;
  const zpid = data.zpid;
  if ((typeof zpid === "string" || typeof zpid === "number") && /^\d+$/.test(String(zpid))) {
    return `https://www.zillow.com/homedetails/${zpid}_zpid/`;
  }
  return null;
}

/** Google Maps search for the property's address (public Maps URL, no API key). */
export function googleMapsUrl(property: Property): string {
  const address = [property.street_address, property.city, property.state, property.zip_code].filter(Boolean).join(", ");
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}`;
}
