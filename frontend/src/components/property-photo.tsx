"use client";

import { Home } from "lucide-react";
import { useState } from "react";

import { propertyPhotoUrl } from "@/lib/zillow";
import { streetViewUrl } from "@/services/properties";
import type { Property } from "@/types/property";

/** Zillow listing photo, else our Street View photo, else a placeholder. */
export function PropertyPhoto({ property, showMissingText = false }: { property: Property; showMissingText?: boolean }) {
  const sources = [propertyPhotoUrl(property, "large"), streetViewUrl(property.property_id)].filter(
    (value): value is string => Boolean(value),
  );
  const [failed, setFailed] = useState(0);
  const source = sources[failed];

  if (!source) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-slate-400">
        <Home className={showMissingText ? "h-12 w-12" : "h-10 w-10"} aria-hidden="true" />
        {showMissingText && <span className="text-xs">No photo available</span>}
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- remote photo, shown as-is
    <img
      key={source}
      src={source}
      alt={`Photo of ${property.street_address}`}
      loading="lazy"
      onError={() => setFailed((count) => count + 1)}
      className="absolute inset-0 h-full w-full object-cover"
    />
  );
}
