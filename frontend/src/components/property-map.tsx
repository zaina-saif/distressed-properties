"use client";

import type { Map as LeafletMap, Marker as LeafletMarker } from "leaflet";
import { useEffect, useRef, useState } from "react";

import type { Property } from "@/types/property";

type GeocodeResult = {
  county?: string;
  state_code?: string;
};

const GEOAPIFY_KEY = process.env.NEXT_PUBLIC_GEOAPIFY_API_KEY;
const NJ_VIEW: [number, number, number] = [40.1, -74.6, 8];

export function PropertyMap({
  properties,
  selectedPropertyId,
  onPropertyClick,
  onCountySelect,
  visibilityKey,
  defaultView = NJ_VIEW,
}: {
  properties: Property[];
  selectedPropertyId?: string;
  onPropertyClick: (property: Property) => void;
  onCountySelect: (state: string, county: string) => void;
  visibilityKey: string;
  /** Latitude, longitude and zoom shown when no property has coordinates. */
  defaultView?: [number, number, number];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const markersRef = useRef<LeafletMarker[]>([]);
  const fitRef = useRef<(() => void) | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function initializeMap() {
      if (!containerRef.current || mapRef.current) return;
      try {
        const L = await import("leaflet");
        if (!active || !containerRef.current) return;

        const map = L.map(containerRef.current, {
          zoomControl: true,
        }).setView([NJ_VIEW[0], NJ_VIEW[1]], NJ_VIEW[2]);
        mapRef.current = map;

        const tiles = L.tileLayer(
          GEOAPIFY_KEY
            ? `https://maps.geoapify.com/v1/tile/positron/{z}/{x}/{y}.png?apiKey=${GEOAPIFY_KEY}`
            : "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
          {
            maxZoom: 20,
            attribution: GEOAPIFY_KEY
              ? "© Geoapify © OpenMapTiles © OpenStreetMap contributors"
              : "© OpenStreetMap contributors",
          },
        ).addTo(map);
        tiles.on("tileerror", (event) => {
          console.error("Leaflet tile error", event);
          setMapError("The base-map tiles could not load. Check the map service or network connection.");
        });
        tiles.once("load", () => setMapError(null));

        setMapReady(true);
        window.setTimeout(() => map.invalidateSize(), 0);

      if (GEOAPIFY_KEY) {
        map.on("click", async (event) => {
          try {
            const response = await fetch(
                `https://api.geoapify.com/v1/geocode/reverse?lat=${event.latlng.lat}&lon=${event.latlng.lng}&apiKey=${GEOAPIFY_KEY}`,
            );
            if (!response.ok) return;
            const data = (await response.json()) as {
              features?: Array<{ properties: GeocodeResult }>;
            };
            const result = data.features?.[0]?.properties;
            const state = result?.state_code?.toUpperCase();
            const county = result?.county?.replace(/\s+(County|Parish|Borough)$/i, "");
            if (!state || !county) return;

            const content = document.createElement("div");
            const heading = document.createElement("strong");
            heading.textContent = `${county} County, ${state}`;
            const action = document.createElement("button");
            action.type = "button";
            action.className = "map-county-action";
            action.textContent = "Show sheriff sales";
            content.append(heading, action);

              const popup = L.popup()
                .setLatLng(event.latlng)
                .setContent(content)
                .openOn(map);
            action.addEventListener("click", () => {
              onCountySelect(state, county);
                popup.close();
            });
          } catch {
            // The map remains usable when reverse geocoding is unavailable.
          }
        });
      }
      } catch (error) {
        console.error("Unable to initialize Leaflet", error);
        if (active) {
          setMapError("The map renderer could not start.");
        }
      }
    }

    void initializeMap();
    return () => {
      active = false;
      markersRef.current.forEach((marker) => marker.remove());
      markersRef.current = [];
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, [onCountySelect]);

  useEffect(() => {
    if (!mapRef.current) return;
    // A map laid out while hidden (the phone list tab) has no size, so refit once it shows.
    const frame = window.requestAnimationFrame(() => {
      mapRef.current?.invalidateSize();
      if (fitRef.current) fitRef.current();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [visibilityKey]);

  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    let active = true;

    async function updateMarkers() {
      const L = await import("leaflet");
      if (!active || !mapRef.current) return;

      markersRef.current.forEach((marker) => marker.remove());
      markersRef.current = [];
      const bounds = L.latLngBounds([]);

      for (const property of properties) {
        if (property.latitude == null || property.longitude == null) continue;
        const latitude = Number(property.latitude);
        const longitude = Number(property.longitude);
        if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) continue;

        const marker = L.marker([latitude, longitude], {
          icon: L.divIcon({
            className: property.property_id === selectedPropertyId
              ? "property-map-marker property-map-marker-selected"
              : "property-map-marker",
            html: "",
            iconSize: [14, 14],
            iconAnchor: [7, 7],
          }),
          keyboard: true,
          title: `View ${property.normalized_address}`,
        })
          .on("click", () => onPropertyClick(property))
          .addTo(mapRef.current);
        markersRef.current.push(marker);
        bounds.extend([latitude, longitude]);
      }

      const fit = () => {
        if (!mapRef.current) return;
        if (bounds.isValid()) {
          mapRef.current.fitBounds(bounds, { padding: [70, 70], maxZoom: 13 });
        } else {
          mapRef.current.setView([defaultView[0], defaultView[1]], defaultView[2]);
        }
      };
      fitRef.current = fit;
      fit();
    }

    void updateMarkers();
    return () => { active = false; };
  }, [defaultView, mapReady, onPropertyClick, properties, selectedPropertyId]);

  const mappedCount = properties.filter((property) =>
    property.latitude != null
      && property.longitude != null
      && Number.isFinite(Number(property.latitude))
      && Number.isFinite(Number(property.longitude)),
  ).length;

  return (
    <section className="relative isolate h-full min-h-96 overflow-hidden bg-slate-100" aria-label="Property map">
      <div ref={containerRef} className="absolute inset-0" />

      {(!mapReady || mapError) && (
        <div className={`pointer-events-none absolute bottom-4 right-4 z-[1000] max-w-sm rounded-lg border px-3 py-2 text-xs shadow ${mapError ? "border-red-200 bg-red-50/95 text-red-700" : "border-slate-200 bg-white/95 text-slate-500"}`}>
          {mapError ?? "Loading map…"}
        </div>
      )}

      <div className="absolute bottom-4 left-4 z-[1000] rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-xs text-slate-600 shadow">
        <span className="font-semibold text-slate-900">{mappedCount}</span> of {properties.length} loaded properties have verified coordinates
      </div>
    </section>
  );
}
