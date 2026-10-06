"use client";

import { Home } from "lucide-react";
import { useEffect, useState } from "react";

import { authFetch } from "@/lib/api";
import { propertyPhotoUrl } from "@/lib/zillow";
import { aerialPhotoUrl, streetViewUrl } from "@/services/properties";
import type { Property } from "@/types/property";

type Source = { url: string; kind: "listing" | "street" | "aerial" };

/**
 * Zillow listing photo, else our Street View photo, else an NJ aerial view, else a placeholder.
 * Street View and aerial images come from our API, which needs the user's token, so they are
 * fetched and shown from a local object URL instead of a plain <img src>.
 */
export function PropertyPhoto({ property, showMissingText = false }: { property: Property; showMissingText?: boolean }) {
  const listing = propertyPhotoUrl(property, "large");
  const sources: Source[] = [
    ...(listing ? [{ url: listing, kind: "listing" as const }] : []),
    { url: streetViewUrl(property.property_id), kind: "street" },
    { url: aerialPhotoUrl(property.property_id), kind: "aerial" },
  ];
  const [failed, setFailed] = useState(0);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const source = sources[failed];
  const protectedUrl = source && source.kind !== "listing" ? source.url : null;

  useEffect(() => {
    if (!protectedUrl) return;
    let active = true;
    let created: string | null = null;
    authFetch(protectedUrl)
      .then((response) => (response.ok ? response.blob() : Promise.reject(new Error(String(response.status)))))
      .then((blob) => {
        if (!active) return;
        created = URL.createObjectURL(blob);
        setObjectUrl(created);
      })
      .catch(() => { if (active) setFailed((count) => count + 1); });
    return () => {
      active = false;
      if (created) URL.revokeObjectURL(created);
      setObjectUrl(null);
    };
  }, [protectedUrl]);

  if (!source) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-slate-400">
        <Home className={showMissingText ? "h-12 w-12" : "h-10 w-10"} aria-hidden="true" />
        {showMissingText && <span className="text-xs">No photo available</span>}
      </div>
    );
  }
  const src = protectedUrl ? objectUrl : source.url;
  if (!src) return <div className="absolute inset-0 animate-pulse bg-slate-200" aria-hidden="true" />;
  return (
    <>
      {/* eslint-disable-next-line @next/next/no-img-element -- remote or locally fetched photo, shown as-is */}
      <img
        key={src}
        src={src}
        alt={source.kind === "aerial" ? `Aerial view of ${property.street_address}` : `Photo of ${property.street_address}`}
        loading="lazy"
        onError={() => setFailed((count) => count + 1)}
        className="absolute inset-0 h-full w-full object-cover"
      />
      {source.kind === "aerial" && (
        <>
          <span className="pointer-events-none absolute left-1/2 top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-red-600 shadow-[0_0_0_3px_rgba(220,38,38,0.35)]" aria-hidden="true" />
          <span className="pointer-events-none absolute bottom-1.5 right-1.5 rounded bg-slate-950/70 px-1.5 py-0.5 text-[9px] font-medium text-white">Aerial · NJ 2020</span>
        </>
      )}
    </>
  );
}
