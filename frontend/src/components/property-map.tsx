"use client";

import { MapPin, Search, X } from "lucide-react";
import type { Map as LeafletMap, Marker as LeafletMarker } from "leaflet";
import { FormEvent, useEffect, useRef, useState } from "react";

import type { Property } from "@/types/property";

type GeocodeResult = {
  lat: number;
  lon: number;
  formatted: string;
  county?: string;
  state?: string;
  state_code?: string;
};

const GEOAPIFY_KEY = process.env.NEXT_PUBLIC_GEOAPIFY_API_KEY;

export function PropertyMap({
  properties,
  selectedPropertyId,
  onPropertyClick,
  onCountySelect,
}: {
  properties: Property[];
  selectedPropertyId?: string;
  onPropertyClick: (property: Property) => void;
  onCountySelect: (state: string, county: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const markersRef = useRef<LeafletMarker[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [searching, setSearching] = useState(false);
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
        }).setView([40.4, -77.2], 5);
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
          setMapError("The base-map tiles could not load. Check Geoapify access settings.");
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
            html: "$",
            iconSize: [32, 32],
            iconAnchor: [16, 16],
          }),
          keyboard: true,
          title: `View ${property.normalized_address}`,
        })
          .on("click", () => onPropertyClick(property))
          .addTo(mapRef.current);
        markersRef.current.push(marker);
        bounds.extend([latitude, longitude]);
      }

      if (bounds.isValid()) {
        mapRef.current.fitBounds(bounds, { padding: [70, 70], maxZoom: 13 });
      }
    }

    void updateMarkers();
    return () => { active = false; };
  }, [mapReady, onPropertyClick, properties, selectedPropertyId]);

  async function searchMap(event: FormEvent) {
    event.preventDefault();
    if (!query.trim() || !GEOAPIFY_KEY) return;
    setSearching(true);
    try {
      const response = await fetch(
        `https://api.geoapify.com/v1/geocode/search?text=${encodeURIComponent(query)}&filter=countrycode:us&limit=5&apiKey=${GEOAPIFY_KEY}`,
      );
      if (!response.ok) throw new Error(`Map search failed: ${response.status}`);
      const data = (await response.json()) as {
        features?: Array<{ properties: GeocodeResult }>;
      };
      setResults((data.features ?? []).map((feature) => feature.properties));
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  function chooseResult(result: GeocodeResult) {
    mapRef.current?.flyTo([result.lat, result.lon], 12, { duration: 0.9 });
    setResults([]);
    setQuery("");
  }

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

      <div className="absolute left-4 right-16 top-4 z-[1000] max-w-md">
        <form onSubmit={searchMap} className="flex items-center rounded-xl border border-slate-200 bg-white p-1.5 shadow-lg">
          <Search className="ml-2 h-4 w-4 text-slate-400" aria-hidden="true" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={GEOAPIFY_KEY ? "Find a place on the map" : "Set Geoapify key for map search"}
            disabled={!GEOAPIFY_KEY}
            className="min-w-0 flex-1 bg-transparent px-2 py-2 text-sm outline-none disabled:cursor-not-allowed"
          />
          {query && (
            <button type="button" onClick={() => { setQuery(""); setResults([]); }} className="rounded p-1 text-slate-400 hover:bg-slate-100">
              <X className="h-4 w-4" />
            </button>
          )}
          <button disabled={!GEOAPIFY_KEY || searching || !query.trim()} className="rounded-lg bg-teal-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">
            {searching ? "Searching…" : "Search"}
          </button>
        </form>
        {results.length > 0 && (
          <div className="mt-1 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
            {results.map((result) => (
              <button key={`${result.lat}-${result.lon}`} type="button" onClick={() => chooseResult(result)} className="flex w-full items-start gap-2 border-b border-slate-100 px-3 py-3 text-left text-sm hover:bg-teal-50 last:border-0">
                <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-teal-600" />
                {result.formatted}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="absolute bottom-4 left-4 z-[1000] rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-xs text-slate-600 shadow">
        <span className="font-semibold text-slate-900">{mappedCount}</span> of {properties.length} loaded properties have verified coordinates
      </div>
    </section>
  );
}
