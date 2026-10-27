"use client";

import { useEffect, useState, useCallback, useImperativeHandle, forwardRef, useLayoutEffect, useMemo, useRef, type MutableRefObject } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Tooltip, useMap, FeatureGroup, ZoomControl, GeoJSON, Circle } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { Layers, Map as MapIcon, Sun, Moon, Mountain, Box, Globe, Maximize, Building, Train, X } from 'lucide-react';

import API_BASE from '@/lib/apiBase';

export type MapOverlayId = "hdb_footprints" | "mrt_exits" | "ura_boundaries";

export interface MapChromeState {
    basemapLabel: string;
    overlays: { id: MapOverlayId; label: string }[];
}

export interface MapHandle {
    dismissOverlay: (id: MapOverlayId) => void;
    toggleOverlay: (id: MapOverlayId) => void;
    /** Fly map to default center/zoom (e.g. after clearing postal / filters). */
    resetToDefaultView: () => void;
    /** Pan/zoom map to a lat/lng (e.g. MRT waypoint from analytics). */
    flyToPoint: (lat: number, lng: number, zoom?: number) => void;
    /**
     * Fly to coords and show a waypoint marker with a permanent name tooltip.
     * Use `clearWaypoint` or the tooltip close control to remove it.
     */
    flyToWaypoint: (lat: number, lng: number, name: string, zoom?: number) => void;
    /** Remove the MRT waypoint marker and its tooltip. */
    clearWaypoint: () => void;
}

// Module-level Canvas renderer — shared across all polygon layers for performance
const canvasRenderer = typeof window !== 'undefined' ? L.canvas({ padding: 0.5 }) : undefined;

/** Auto-fit when a committed 6-digit postal selects HDB footprints. */
const POSTAL_AUTOFIT_MAX_ZOOM = 14;
const POSTAL_AUTOFIT_PADDING: L.PointExpression = [50, 50];

function normalizePostalToSixDigits(raw: string | undefined | null): string {
    const digits = (raw ?? "").replace(/\D/g, "");
    return digits.length === 6 ? digits : "";
}

function featurePostalDigits(props: Record<string, unknown> | undefined): string {
    const digits = String(props?.postal_cod ?? "").replace(/\D/g, "");
    if (digits.length === 6) return digits;
    if (digits.length > 0 && digits.length < 6) return digits.padStart(6, "0");
    return "";
}

function geojsonMatchesPostal(data: unknown, targetPostal: string): boolean {
    if (!targetPostal || !(data as { features?: unknown[] })?.features?.length) return false;
    const features = (data as { features: { properties?: Record<string, unknown> }[] }).features;
    return features.every(
        (f) => featurePostalDigits(f?.properties) === targetPostal
    );
}

const WAYPOINT_PIN_HTML = `<div style="width:36px;height:36px;background:linear-gradient(155deg,#0369a1,#0ea5e9);border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:3px solid #fff;box-shadow:0 2px 12px rgba(15,23,42,0.45);display:flex;align-items:center;justify-content:center;margin-top:-4px" aria-hidden="true">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="14" height="14" fill="#fff" style="transform:rotate(45deg);margin-top:2px;margin-left:2px" stroke="none"><circle cx="12" cy="11" r="3"/></svg>
</div>`;

function createWaypointIcon() {
    return L.divIcon({
        className: "leaflet-div-icon leaflet-mrt-waypoint-marker",
        html: WAYPOINT_PIN_HTML,
        iconSize: [36, 40],
        iconAnchor: [18, 38],
    });
}

/** GeoJSON display_state / pit_state / derived_state; never infer "open" when data is missing. */
function mrtDisplayBucket(props: Record<string, unknown> | undefined): "OPERATIONAL" | "PLANNED" | "UNKNOWN" {
    const pit = String(props?.pit_state ?? "").toUpperCase().trim();
    if (pit === "OPERATIONAL") return "OPERATIONAL";
    if (
        pit === "COMMITTED_DATED" ||
        pit === "COMMITTED_ESTIMATED" ||
        pit === "ANNOUNCED_UNDATED"
    ) {
        return "PLANNED";
    }
    const ds = String(props?.display_state ?? props?.derived_state ?? "").toUpperCase().trim();
    if (ds === "OPERATIONAL") return "OPERATIONAL";
    if (ds === "PLANNED") return "PLANNED";
    const st = String(props?.station_status ?? "").toLowerCase().trim();
    if (st === "open") return "OPERATIONAL";
    if (["planned", "under construction", "in development"].includes(st)) return "PLANNED";
    return "UNKNOWN";
}

function escapeHtml(s: string): string {
    return s
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function formatMrtDate(v: unknown): string {
    if (v == null || v === "") return "";
    if (typeof v === "string") return v.length >= 10 ? v.slice(0, 10) : v;
    return String(v);
}

/** Popup HTML for HDB building footprints (overlay click + property waypoint). */
function buildingPopupHtml(props: Record<string, unknown> | undefined): string {
    const p = props ?? {};
    const blkNo = escapeHtml(String(p.blk_no ?? "N/A"));
    const postal = escapeHtml(String(p.postal_cod ?? "—"));
    const stCod = escapeHtml(String(p.st_cod ?? "—"));
    const shapeArea = p.shape_area != null && p.shape_area !== ""
        ? `${Math.round(Number(p.shape_area))} sqm`
        : "—";
    const shapeLen = p.shape_len != null && p.shape_len !== ""
        ? `${Math.round(Number(p.shape_len))} m`
        : "—";
    const entityId = escapeHtml(String(p.entityid ?? "—"));
    const fmelRaw = p.fmel_upd_d;
    const lastUpdated =
        fmelRaw != null && String(fmelRaw).length >= 8
            ? escapeHtml(String(fmelRaw).substring(0, 8))
            : "—";

    return `
            <div class="font-sans p-2" style="min-width:180px">
                <div class="font-bold text-sm text-blue-700 mb-2">🏢 HDB Block ${blkNo}</div>
                <table style="width:100%; font-size:11px; border-collapse:collapse">
                    <tr><td style="color:#888;padding:1px 4px">Postal</td><td><b>${postal}</b></td></tr>
                    <tr><td style="color:#888;padding:1px 4px">Street Code</td><td>${stCod}</td></tr>
                    <tr><td style="color:#888;padding:1px 4px">Area</td><td><b>${shapeArea}</b></td></tr>
                    <tr><td style="color:#888;padding:1px 4px">Perimeter</td><td>${shapeLen}</td></tr>
                    <tr><td style="color:#888;padding:1px 4px">Entity ID</td><td>${entityId}</td></tr>
                    <tr><td style="color:#888;padding:1px 4px">Last Updated</td><td>${lastUpdated}</td></tr>
                </table>
            </div>
        `;
}

// Fix for Leaflet default icon issues in Next.js
const fixLeafletIcon = () => {
    const DefaultIcon = L.icon({
        iconUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon.png',
        shadowUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
    });
    L.Marker.prototype.options.icon = DefaultIcon;
};

interface MapProps {
    center?: [number, number];
    zoom?: number;
    onAreaSelected?: (coords: [number, number][]) => void;
    onMarkerClick?: (name: string) => void;
    markers?: { name: string; lat: number; lng: number }[];
    selectedUraRegion?: string;
    selectedTowns?: string[];
    postalCode?: string;
    /** Address label for the committed property (Analytics property search). */
    selectedPropertyLabel?: string;
    onMapStateChange?: (state: MapChromeState) => void;
    radiusCircle?: { lat: number; lng: number; radiusM: number } | null;
}

const MapStyles = {
    Light: {
        url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
        icon: <Sun className="w-4 h-4" />
    },
    Satellite: {
        url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attribution: 'Tiles &copy; Esri',
        icon: <Globe className="w-4 h-4" />
    },
    Terrain: {
        url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        attribution: 'Tiles &copy; Esri',
        icon: <Mountain className="w-4 h-4" />
    },
    "OneMap Default": {
        url: "https://www.onemap.gov.sg/maps/tiles/Default/{z}/{x}/{y}.png",
        attribution: '&copy; <a href="https://www.onemap.sg">OneMap</a>',
        icon: <Box className="w-4 h-4" />
    },
    "OneMap Night": {
        url: "https://www.onemap.gov.sg/maps/tiles/Night/{z}/{x}/{y}.png",
        attribution: '&copy; <a href="https://www.onemap.sg">OneMap</a>',
        icon: <Moon className="w-4 h-4" />
    },
    "OneMap Grey": {
        url: "https://www.onemap.gov.sg/maps/tiles/Grey/{z}/{x}/{y}.png",
        attribution: '&copy; <a href="https://www.onemap.sg">OneMap</a>',
        icon: <Layers className="w-4 h-4" />
    }
};

const BASEMAP_DISPLAY_LABELS: Record<keyof typeof MapStyles, string> = {
    Light: "Light (Carto)",
    Satellite: "Satellite (Esri)",
    Terrain: "Terrain (Esri)",
    "OneMap Default": "OneMap (Default)",
    "OneMap Night": "OneMap (Night)",
    "OneMap Grey": "OneMap (Gray)",
};

const ALL_REGIONS_LABEL = "All Regions (Experimental)";

/** Maps analytics URA dropdown labels to ``region_c`` (matches backend geospatial APIs). */
const URA_REGION_TO_CODE: Record<string, string> = {
    "Central Region": "CR",
    "East Region": "ER",
    "North Region": "NR",
    "North-East Region": "NER",
    "West Region": "WR",
};

const CENTRAL_AREA_PLANNING_AREAS = [
    "DOWNTOWN CORE", "ORCHARD", "MUSEUM", "SINGAPORE RIVER", "OUTRAM", "NEWTON",
    "RIVER VALLEY", "MARINA SOUTH", "MARINA EAST", "STRAITS VIEW", "ROCHOR",
];

function planningAreaMatchesSelectedTowns(pln: string, selectedTowns: string[]): boolean {
    if (selectedTowns.includes(pln)) return true;
    if (selectedTowns.includes("CENTRAL AREA") && CENTRAL_AREA_PLANNING_AREAS.includes(pln)) return true;
    if (selectedTowns.includes("KALLANG/WHAMPOA") && pln === "KALLANG") return true;
    return false;
}

// Helper component to reset view
function ZoomToSingapore({ center, zoom }: { center: [number, number]; zoom: number }) {
    const map = useMap();
    return (
        <button
            onClick={(e) => {
                e.stopPropagation();
                map.setView(center, zoom);
            }}
            className="absolute bottom-6 right-4 z-[1000] p-3 bg-white/10 hover:bg-white/20 backdrop-blur-md rounded-full border border-white/20 text-white transition-all shadow-xl group"
            title="Reset View"
        >
            <Maximize className="w-5 h-5 group-hover:scale-110 transition-transform" />
        </button>
    );
}

// Component to auto-fit to newly loaded GeoJSON specifically for postal filtering
function AutoFitBounds({
    data,
    active,
    targetPostal = "",
}: {
    data: unknown;
    active: boolean;
    targetPostal?: string;
}) {
    const map = useMap();
    const lastFittedPostalRef = useRef<string | null>(null);

    useEffect(() => {
        if (!targetPostal) {
            lastFittedPostalRef.current = null;
        }
    }, [targetPostal]);

    useEffect(() => {
        if (!active || !targetPostal || !geojsonMatchesPostal(data, targetPostal)) return;
        if (lastFittedPostalRef.current === targetPostal) return;

        const features = (data as { features: unknown[] }).features;
        if (!features.length) return;

        const geoJsonLayer = L.geoJSON(data as GeoJSON.FeatureCollection);
        const bounds = geoJsonLayer.getBounds();
        if (bounds.isValid()) {
            map.invalidateSize();
            map.fitBounds(bounds, {
                maxZoom: POSTAL_AUTOFIT_MAX_ZOOM,
                padding: POSTAL_AUTOFIT_PADDING,
                animate: true,
                duration: 0.85,
            });
            lastFittedPostalRef.current = targetPostal;
        }
    }, [data, active, targetPostal, map]);
    return null;
}

/** Captures the Leaflet map instance for imperative reset (must render inside MapContainer). */
function MapInstanceCapture({ mapRef }: { mapRef: MutableRefObject<L.Map | null> }) {
    const map = useMap();
    useLayoutEffect(() => {
        mapRef.current = map;
        return () => {
            mapRef.current = null;
        };
    }, [map, mapRef]);
    return null;
}

function AutoFitArea({
    data,
    selectedTowns,
    selectedUraRegion,
    active,
}: {
    data: any;
    selectedTowns: string[];
    selectedUraRegion?: string;
    active: boolean;
}) {
    const map = useMap();
    useEffect(() => {
        if (!active || !data?.features?.length) return;

        let activeFeatures = data.features;
        if (selectedTowns.length > 0) {
            activeFeatures = data.features.filter((feature: any) => {
                const pln = feature?.properties?.pln_area_n?.toUpperCase();
                return pln ? planningAreaMatchesSelectedTowns(pln, selectedTowns) : false;
            });
        } else if (
            !selectedUraRegion ||
            selectedUraRegion === ALL_REGIONS_LABEL
        ) {
            return;
        }

        if (activeFeatures.length === 0) return;
        const geoJsonLayer = L.geoJSON({ type: "FeatureCollection", features: activeFeatures } as any);
        const bounds = geoJsonLayer.getBounds();
        if (bounds.isValid()) {
            map.invalidateSize();
            map.flyToBounds(bounds, { maxZoom: selectedTowns.length > 0 ? 14 : 12, duration: 1.5, padding: [60, 60] });
        }
    }, [data, selectedTowns, selectedUraRegion, active, map]);
    return null;
}

const BUILDING_CHUNK_SIZE = 250;

/** Renders HDB building GeoJSON in animation-frame chunks so the main thread stays responsive. */
function HdbBuildingsLayer({
    data,
    onEachFeature,
    style,
    onProgress,
}: {
    data: any;
    onEachFeature: (feature: any, layer: any) => void;
    style: () => L.PathOptions;
    onProgress: (loaded: number, total: number) => void;
}) {
    const map = useMap();
    const layerRef = useRef<L.GeoJSON | null>(null);
    const abortRef = useRef(false);

    useEffect(() => {
        abortRef.current = false;

        if (layerRef.current) {
            map.removeLayer(layerRef.current);
            layerRef.current = null;
        }

        if (!data?.features?.length) {
            onProgress(0, 0);
            return;
        }

        const features: any[] = data.features;
        const total = features.length;
        onProgress(0, total);

        const layer = L.geoJSON(undefined, {
            onEachFeature,
            style: style as L.StyleFunction,
            ...(canvasRenderer ? { renderer: canvasRenderer } : {}),
        }).addTo(map);
        layerRef.current = layer;

        let i = 0;
        function tick() {
            if (abortRef.current || !layerRef.current) return;
            const end = Math.min(i + BUILDING_CHUNK_SIZE, total);
            for (; i < end; i++) {
                layerRef.current.addData(features[i]);
            }
            onProgress(i, total);
            if (i < total) {
                requestAnimationFrame(tick);
            }
        }
        requestAnimationFrame(tick);

        return () => {
            abortRef.current = true;
            if (layerRef.current) {
                map.removeLayer(layerRef.current);
                layerRef.current = null;
            }
        };
        // Re-run only when the data reference changes (new fetch result)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [data]);

    return null;
}

const Map = forwardRef<MapHandle, MapProps>(function Map(
    {
        center = [1.3521, 103.8198],
        zoom = 11,
        onAreaSelected,
        markers = [],
        selectedUraRegion,
        selectedTowns = [],
        postalCode,
        selectedPropertyLabel,
        onMapStateChange,
        radiusCircle = null,
    },
    ref
) {
    const leafletMapRef = useRef<L.Map | null>(null);
    const [activeStyle, setActiveStyle] = useState<keyof typeof MapStyles>("OneMap Grey");
    const [showStyles, setShowStyles] = useState(false);
    const [showBuildings, setShowBuildings] = useState(false);
    const [geojsonData, setGeojsonData] = useState<any>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [buildingError, setBuildingError] = useState<string | null>(null);
    const [buildingProgress, setBuildingProgress] = useState<{ loaded: number; total: number } | null>(null);
    const [buildingFilter, setBuildingFilter] = useState({
        minArea: 0,
        maxArea: 999999,
        postalPrefix: ''
    });

    const [lastZoomTrigger, setLastZoomTrigger] = useState<"postal" | "town" | "region" | null>(null);

    const selectedRegionCode = useMemo(() => {
        if (!selectedUraRegion || selectedUraRegion === ALL_REGIONS_LABEL) return null;
        return URA_REGION_TO_CODE[selectedUraRegion] ?? null;
    }, [selectedUraRegion]);

    const hasAreaScope = Boolean(selectedRegionCode || (selectedTowns && selectedTowns.length > 0));

    const [showMrtExits, setShowMrtExits] = useState(false);
    const [mrtStatusFilter, setMrtStatusFilter] = useState<"ALL" | "OPEN" | "DEVELOPMENT" | "UNKNOWN">("ALL");
    const [mrtExitsData, setMrtExitsData] = useState<any>(null);
    const [mrtExitsLoading, setMrtExitsLoading] = useState(false);
    const [mrtExitsError, setMrtExitsError] = useState<string | null>(null);
    const [mrtRetry, setMrtRetry] = useState(0);

    const [showUraRegions, setShowUraRegions] = useState(false);
    const [uraRegionsData, setUraRegionsData] = useState<any>(null);
    const [uraRegionsLoading, setUraRegionsLoading] = useState(false);
    const [uraRegionsError, setUraRegionsError] = useState<string | null>(null);
    const [uraRetry, setUraRetry] = useState(0);

    /** MRT waypoint from analytics Geospatial tab (marker + tooltip). */
    const [mrtWaypoint, setMrtWaypoint] = useState<{ lat: number; lng: number; name: string } | null>(null);
    /** Selected HDB building waypoint when a 6-digit postal is committed. */
    const [propertyWaypoint, setPropertyWaypoint] = useState<{
        lat: number;
        lng: number;
        buildingProps: Record<string, unknown>;
    } | null>(null);

    const waypointIcon = useMemo(() => createWaypointIcon(), []);

    useEffect(() => {
        if (hasAreaScope) {
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setShowUraRegions(true);
        }
    }, [hasAreaScope]);

    useEffect(() => {
        if (!showUraRegions) return;
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setUraRegionsLoading(true);
        setUraRegionsError(null);
        setUraRegionsData(null);
        const controller = new AbortController();

        const fetchUrl = selectedRegionCode
            ? `${API_BASE}/api/geospatial/planning_areas?region=${selectedRegionCode}`
            : selectedTowns.length > 0
                ? `${API_BASE}/api/geospatial/planning_areas`
                : `${API_BASE}/api/geospatial/regions`;

        fetch(fetchUrl, { signal: controller.signal })
            .then(res => {
                if (!res.ok) throw new Error(`Server error: ${res.status}`);
                return res.json();
            })
            .then(data => {
                if (data?.type !== 'FeatureCollection' || !Array.isArray(data?.features)) {
                    throw new Error('Invalid boundary data from server');
                }
                if (controller.signal.aborted) return;
                setUraRegionsData(data);
                setUraRegionsLoading(false);
            })
            .catch(err => {
                if (controller.signal.aborted) return;
                setUraRegionsError(err.message ?? 'Failed to load boundaries');
                setUraRegionsLoading(false);
            });
        return () => controller.abort();
    }, [showUraRegions, selectedRegionCode, selectedTowns.length, uraRetry]);

    useEffect(() => {
        fixLeafletIcon();
    }, []);

    useImperativeHandle(
        ref,
        () => ({
            dismissOverlay(id: MapOverlayId) {
                if (id === "hdb_footprints") setShowBuildings(false);
                else if (id === "mrt_exits") setShowMrtExits(false);
                else if (id === "ura_boundaries") setShowUraRegions(false);
            },
            toggleOverlay(id: MapOverlayId) {
                if (id === "hdb_footprints") setShowBuildings(prev => !prev);
                else if (id === "mrt_exits") setShowMrtExits(prev => !prev);
                else if (id === "ura_boundaries") setShowUraRegions(prev => !prev);
            },
            resetToDefaultView() {
                const m = leafletMapRef.current;
                setPropertyWaypoint(null);
                if (!m) return;
                m.invalidateSize();
                m.setView(center, zoom, { animate: true });
            },
            flyToPoint(lat: number, lng: number, flyZoom = 17) {
                const m = leafletMapRef.current;
                if (!m || !Number.isFinite(lat) || !Number.isFinite(lng)) return;
                m.invalidateSize();
                m.flyTo([lat, lng], flyZoom, { duration: 0.85 });
            },
            flyToWaypoint(lat: number, lng: number, name: string, flyZoom = 17) {
                const label = (name || "").trim();
                if (!Number.isFinite(lat) || !Number.isFinite(lng) || !label) return;
                setMrtWaypoint({ lat, lng, name: label });
                const m = leafletMapRef.current;
                if (!m) return;
                m.invalidateSize();
                m.flyTo([lat, lng], flyZoom, { duration: 0.85 });
            },
            clearWaypoint() {
                setMrtWaypoint(null);
            },
        }),
        [center, zoom]
    );

    useLayoutEffect(() => {
        if (!onMapStateChange) return;
        const overlays: { id: MapOverlayId; label: string }[] = [];
        if (showBuildings) overlays.push({ id: "hdb_footprints", label: "HDB Footprints" });
        if (showMrtExits) overlays.push({ id: "mrt_exits", label: "MRT Stations" });
        if (showUraRegions) overlays.push({ id: "ura_boundaries", label: "URA Boundaries" });
        onMapStateChange({
            basemapLabel: BASEMAP_DISPLAY_LABELS[activeStyle],
            overlays,
        });
    }, [activeStyle, showBuildings, showMrtExits, showUraRegions, onMapStateChange]);

    // Re-fetch whenever overlay is toggled on or filters change
    useEffect(() => {
        if (!showBuildings) return;
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setIsLoading(true);
        setGeojsonData(null);
        setBuildingError(null);
        setBuildingProgress(null);
        const params = new URLSearchParams({
            min_area: String(buildingFilter.minArea),
            max_area: String(buildingFilter.maxArea),
        });
        if (buildingFilter.postalPrefix.trim()) {
            params.append('postal_prefix', buildingFilter.postalPrefix.trim());
        }
        if (selectedRegionCode) {
            params.append('region_c', selectedRegionCode);
        }
        if (selectedTowns.length > 0) {
            params.append('towns', selectedTowns.join(','));
        }
        fetch(`${API_BASE}/api/geospatial/hdb_buildings?${params}`)
            .then(res => {
                if (!res.ok) throw new Error(`Server error: ${res.status}`);
                return res.json();
            })
            .then(data => {
                if (data?.type !== 'FeatureCollection' || !Array.isArray(data?.features)) {
                    throw new Error('Invalid GeoJSON response from server');
                }
                setGeojsonData(data);
                setIsLoading(false);
            })
            .catch(err => {
                console.error("Failed to load buildings:", err);
                setBuildingError(err.message ?? 'Failed to load buildings');
                setIsLoading(false);
            });
    }, [showBuildings, buildingFilter, selectedRegionCode, selectedTowns]);

    // Handle global postal code prop — only auto-enable footprints for committed 6-digit postal
    useEffect(() => {
        const fullPostal = normalizePostalToSixDigits(postalCode);
        if (fullPostal) {
            setGeojsonData(null);
            setIsLoading(true);
            setLastZoomTrigger("postal");
            setShowBuildings(true);
            setBuildingFilter(prev => ({ ...prev, postalPrefix: fullPostal }));
        } else {
            setPropertyWaypoint(null);
            setBuildingFilter(prev => {
                if (!prev.postalPrefix.trim()) return prev;
                return { ...prev, postalPrefix: '' };
            });
        }
    }, [postalCode]);

    // Place property waypoint at HDB footprint centroid for committed postal
    useEffect(() => {
        const fullPostal = normalizePostalToSixDigits(postalCode);
        if (!fullPostal || !geojsonData?.features?.length) {
            if (!fullPostal) setPropertyWaypoint(null);
            return;
        }

        const matched = geojsonData.features.filter((feature: { properties?: Record<string, unknown> }) => {
            return featurePostalDigits(feature?.properties) === fullPostal;
        });

        if (matched.length === 0) {
            setPropertyWaypoint(null);
            return;
        }

        const layer = L.geoJSON({ type: "FeatureCollection", features: matched } as GeoJSON.FeatureCollection);
        const bounds = layer.getBounds();
        if (!bounds.isValid()) {
            setPropertyWaypoint(null);
            return;
        }

        const centerPt = bounds.getCenter();
        const buildingProps = (matched[0]?.properties ?? {}) as Record<string, unknown>;
        setPropertyWaypoint({ lat: centerPt.lat, lng: centerPt.lng, buildingProps });
    }, [geojsonData, postalCode]);

    // Handle global selected towns / region change
    useEffect(() => {
        if (selectedTowns.length > 0) {
            setLastZoomTrigger("town");
            setShowUraRegions(true);
        } else if (selectedRegionCode) {
            setLastZoomTrigger("region");
            setShowUraRegions(true);
        }
    }, [selectedTowns, selectedRegionCode]);

    useEffect(() => {
        if (!showMrtExits || mrtExitsData?.features?.length) return;
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setMrtExitsLoading(true);
        setMrtExitsError(null);
        const controller = new AbortController();
        fetch(`${API_BASE}/api/geospatial/mrt_stations`, { signal: controller.signal })
            .then(res => {
                if (!res.ok) throw new Error(`Server error: ${res.status}`);
                return res.json();
            })
            .then(data => {
                if (data?.type !== 'FeatureCollection' || !Array.isArray(data?.features)) {
                    throw new Error('Invalid GeoJSON response from server');
                }
                if (controller.signal.aborted) return;
                if (!data.features.length) throw new Error('No MRT station data is loaded.');
                setMrtExitsData(data);
                setMrtExitsLoading(false);
            })
            .catch(err => {
                if (controller.signal.aborted) return;
                setMrtExitsError(err.message ?? 'Failed to load MRT stations');
                setMrtExitsLoading(false);
            });
        return () => controller.abort();
    }, [showMrtExits, mrtExitsData, mrtRetry]);

    const _onCreate = (e: any) => {
        const { layerType, layer } = e;
        if (layerType === 'polygon' || layerType === 'rectangle') {
            const latlngs = layer.getLatLngs()[0];
            const coords = latlngs.map((ll: any) => [ll.lat, ll.lng]);
            if (onAreaSelected) onAreaSelected(coords);
        }
    };

    const onEachBuilding = useCallback((feature: any, layer: any) => {
        layer.bindPopup(buildingPopupHtml(feature.properties));

        layer.on({
            mouseover: (e: any) => {
                const l = e.target;
                l.setStyle({ fillOpacity: 0.5, weight: 2 });
            },
            mouseout: (e: any) => {
                const l = e.target;
                l.setStyle({ fillOpacity: 0.2, weight: 1 });
            }
        });
    }, []);

    const buildingStyle = useCallback(() => ({
        color: '#3b82f6',
        weight: 1,
        fillOpacity: 0.2,
        fillColor: '#3b82f6',
        ...(canvasRenderer ? { renderer: canvasRenderer } : {})
    }), []);

    const onEachMrtExit = useCallback((feature: any, layer: any) => {
        const props = feature.properties;
        const bucket = mrtDisplayBucket(props);
        const pit = String(props.pit_state ?? "").toUpperCase();
        const pitLabel: Record<string, string> = {
            OPERATIONAL: "Operational",
            COMMITTED_DATED: "Opening date set",
            COMMITTED_ESTIMATED: "Expected completion (estimate)",
            ANNOUNCED_UNDATED: "Announced (no date)",
            UNKNOWN: "Unknown",
        };
        const statusStr =
            pit && pitLabel[pit]
                ? pitLabel[pit]
                : bucket === "OPERATIONAL"
                  ? "Operational"
                  : bucket === "PLANNED"
                    ? "Planned / in development"
                    : "Unknown (no reliable date)";
        const statusColor =
            bucket === "OPERATIONAL" ? "#059669" :
            bucket === "PLANNED" ? "#d97706" :
            "#6b7280";
        const line = escapeHtml(String(props.network_line ?? ""));
        const od = formatMrtDate(props.opening_date);
        const ec = formatMrtDate(props.expected_completion);
        const ad = formatMrtDate(props.announcement_date);
        const odr = props.opening_date_raw ? escapeHtml(String(props.opening_date_raw)) : "";
        const ecr = props.expected_completion_raw ? escapeHtml(String(props.expected_completion_raw)) : "";
        const name = escapeHtml(String(props.station_name || "MRT Station"));
        const code = escapeHtml(String(props.station_code || "---"));
        const dateRows: string[] = [];
        if (od) dateRows.push(`<tr><td style="color:#888;padding:1px 4px">Opening</td><td><b>${escapeHtml(od)}</b></td></tr>`);
        else if (odr) dateRows.push(`<tr><td style="color:#888;padding:1px 4px">Opening</td><td>${odr}</td></tr>`);
        if (ec) dateRows.push(`<tr><td style="color:#888;padding:1px 4px">Expected</td><td><b>${escapeHtml(ec)}</b></td></tr>`);
        else if (ecr) dateRows.push(`<tr><td style="color:#888;padding:1px 4px">Expected</td><td>${ecr}</td></tr>`);
        if (ad) dateRows.push(`<tr><td style="color:#888;padding:1px 4px">Announced</td><td><b>${escapeHtml(ad)}</b></td></tr>`);
        layer.bindPopup(`
            <div class="font-sans p-2" style="min-width:180px">
                <div class="font-bold text-sm text-stone-800 mb-1">🚇 ${name}</div>
                <div style="font-size:11px;color:#555">Code: ${code}</div>
                ${line ? `<div style="font-size:11px;color:#555;margin-top:2px">Line: <b>${line}</b></div>` : ""}
                <div style="font-size:11px;font-weight:600;margin-top:4px;color:${statusColor}">${escapeHtml(statusStr)}</div>
                ${dateRows.length ? `<table style="width:100%;font-size:11px;border-collapse:collapse;margin-top:6px">${dateRows.join("")}</table>` : ""}
                ${props.source_note ? `<p style="font-size:10px;color:#666;margin-top:6px">${escapeHtml(String(props.source_note))}</p>` : ""}
            </div>
        `);
    }, []);

    const mrtExitPointToLayer = useCallback((feature: any, latlng: any) => {
        const bucket = mrtDisplayBucket(feature.properties);

        let strokeColor = '#059669';
        let bgStyle = 'bg-emerald-100 border-emerald-500 shadow-emerald-500/50';

        if (bucket === 'PLANNED') {
            strokeColor = '#d97706';
            bgStyle = 'bg-amber-100 border-amber-500 shadow-amber-500/50';
        } else if (bucket === 'UNKNOWN') {
            strokeColor = '#6b7280';
            bgStyle = 'bg-gray-100 border-gray-500 shadow-gray-500/40';
        }
        
        const trainSvg = `
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="${strokeColor}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <rect width="16" height="16" x="4" y="3" rx="2" />
          <path d="M4 11h16" />
          <path d="M12 3v8" />
          <path d="m8 19-2 3" />
          <path d="m18 22-2-3" />
          <path d="M8 15h.01" />
          <path d="M16 15h.01" />
        </svg>`;

        const html = `<div class="flex items-center justify-center w-6 h-6 rounded border shadow-md ${bgStyle}">
            ${trainSvg}
        </div>`;
        
        return L.marker(latlng, {
            title: `${feature.properties.station_name} (${feature.properties.station_code})`,
            icon: L.divIcon({
                className: 'bg-transparent border-0',
                html: html,
                iconSize: [24, 24],
                iconAnchor: [12, 12],
            })
        });
    }, []);

    let filteredMrtData = null;
    if (mrtExitsData) {
        if (mrtStatusFilter === 'ALL') {
            filteredMrtData = mrtExitsData;
        } else {
            filteredMrtData = {
                ...mrtExitsData,
                features: mrtExitsData.features.filter((f: any) => {
                    const bucket = mrtDisplayBucket(f.properties);
                    if (mrtStatusFilter === 'OPEN') return bucket === 'OPERATIONAL';
                    if (mrtStatusFilter === 'DEVELOPMENT') return bucket === 'PLANNED';
                    if (mrtStatusFilter === 'UNKNOWN') return bucket === 'UNKNOWN';
                    return true;
                })
            };
        }
    }

    // Interchanges have one API row per line at the same physical coordinate.
    // Show one marker per station with every matching code and line in its popup.
    if (filteredMrtData) {
        const grouped = new globalThis.Map<string, any>();
        for (const feature of filteredMrtData.features) {
            const props = feature.properties ?? {};
            const key = String(props.physical_station_id ?? props.station_code);
            const existing = grouped.get(key);
            if (!existing) {
                grouped.set(key, { ...feature, properties: { ...props } });
                continue;
            }
            for (const field of ['station_code', 'network_line']) {
                existing.properties[field] = [...new Set([
                    ...String(existing.properties[field] ?? '').split(' / '),
                    String(props[field] ?? ''),
                ])].filter(Boolean).join(' / ');
            }
            // Different lines can have different dates: do not attribute one line's
            // opening or planned date to the whole interchange.
            for (const field of ['opening_date', 'opening_date_raw', 'expected_completion', 'expected_completion_raw', 'announcement_date']) {
                if (existing.properties[field] !== props[field]) existing.properties[field] = null;
            }
            const existingBucket = mrtDisplayBucket(existing.properties);
            const bucket = mrtDisplayBucket(props);
            if (bucket === 'OPERATIONAL' || (existingBucket === 'UNKNOWN' && bucket === 'PLANNED')) {
                existing.properties.pit_state = props.pit_state;
                existing.properties.display_state = props.display_state;
                existing.properties.station_status = props.station_status;
            }
        }
        filteredMrtData = { ...filteredMrtData, features: [...grouped.values()] };
    }

    const fullPostalForFit = normalizePostalToSixDigits(postalCode);
    const postalFitReady =
        showBuildings &&
        lastZoomTrigger === "postal" &&
        !!fullPostalForFit &&
        !isLoading &&
        geojsonMatchesPostal(geojsonData, fullPostalForFit);

    return (
        <div className="relative z-0 w-full h-full rounded-2xl overflow-hidden border border-white/10 shadow-2xl bg-slate-900 group">
            {/* Elegant Style Switcher */}
            <div className="absolute top-4 right-4 z-[1000] flex max-h-[calc(100%-2rem)] min-h-0 flex-col items-end gap-2 overflow-hidden">
                <button
                    type="button"
                    onClick={() => setShowStyles(!showStyles)}
                    className="flex shrink-0 items-center gap-2 px-4 py-2 bg-black/60 hover:bg-black/80 backdrop-blur-xl rounded-2xl border border-white/10 text-white text-sm font-semibold transition-all shadow-2xl"
                >
                    <Layers className="w-4 h-4 text-accent" />
                    <span>Map Customization</span>
                </button>

                {showStyles && (
                    <div className="flex min-h-0 w-64 flex-1 flex-col overflow-y-auto overscroll-contain rounded-3xl border border-white/10 bg-black/80 p-4 shadow-3xl backdrop-blur-2xl animate-in fade-in slide-in-from-top-4 duration-300 [scrollbar-gutter:stable]">
                        <div className="mb-4">
                            <h4 className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-3 px-2">Basemaps</h4>
                            <div className="grid grid-cols-2 gap-2">
                                {Object.entries(MapStyles).map(([name, style]) => (
                                    <button
                                        key={name}
                                        onClick={() => {
                                            setActiveStyle(name as keyof typeof MapStyles);
                                        }}
                                        className={`flex flex-col items-center gap-2 p-3 rounded-2xl transition-all border ${activeStyle === name
                                                ? 'bg-accent/20 border-accent text-accent'
                                                : 'bg-white/5 border-transparent text-gray-400 hover:bg-white/10 hover:text-white'
                                            }`}
                                    >
                                        <div className={`p-2 rounded-xl ${activeStyle === name ? 'bg-accent text-white' : 'bg-white/10'}`}>
                                            {style.icon}
                                        </div>
                                        <span className="text-[10px] font-bold uppercase tracking-tighter text-center">{name.replace("OneMap ", "")}</span>
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div className="pt-4 border-t border-white/10">
                            <h4 className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-3 px-2">Overlays</h4>
                            <button
                                onClick={() => setShowBuildings(!showBuildings)}
                                className={`w-full flex items-center justify-between p-3 rounded-2xl transition-all border ${showBuildings
                                        ? 'bg-secondary/20 border-secondary text-secondary'
                                        : 'bg-white/5 border-transparent text-gray-400 hover:bg-white/10'
                                    }`}
                            >
                                <div className="flex items-center gap-2">
                                    <Building className="w-4 h-4" />
                                    <span className="text-xs font-bold">HDB Footprints</span>
                                </div>
                                <div className={`w-8 h-4 rounded-full relative transition-colors ${showBuildings ? 'bg-secondary' : 'bg-white/20'}`}>
                                    <div className={`absolute top-1 w-2 h-2 bg-white rounded-full transition-all ${showBuildings ? 'left-5' : 'left-1'}`} />
                                </div>
                            </button>

                            {showBuildings && (
                                <div className="mt-3 p-3 bg-white/5 rounded-2xl space-y-3">
                                    <div>
                                        <label className="text-[10px] text-gray-400 uppercase font-bold tracking-widest block mb-1">Area (sqm)</label>
                                        <div className="flex gap-2">
                                            <input
                                                type="number"
                                                placeholder="Min"
                                                value={buildingFilter.minArea || ''}
                                                onChange={e => setBuildingFilter(f => ({ ...f, minArea: Number(e.target.value) || 0 }))}
                                                className="w-full bg-white/10 rounded-xl px-2 py-1.5 text-xs text-white border border-white/10 focus:outline-none focus:border-secondary"
                                            />
                                            <input
                                                type="number"
                                                placeholder="Max"
                                                value={buildingFilter.maxArea === 999999 ? '' : buildingFilter.maxArea}
                                                onChange={e => setBuildingFilter(f => ({ ...f, maxArea: Number(e.target.value) || 99999 }))}
                                                className="w-full bg-white/10 rounded-xl px-2 py-1.5 text-xs text-white border border-white/10 focus:outline-none focus:border-secondary"
                                            />
                                        </div>
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-gray-400 uppercase font-bold tracking-widest block mb-1">Postal Prefix</label>
                                        <input
                                            type="text"
                                            placeholder="e.g. 64 for Pasir Ris"
                                            value={buildingFilter.postalPrefix}
                                            onChange={e => setBuildingFilter(f => ({ ...f, postalPrefix: e.target.value }))}
                                            className="w-full bg-white/10 rounded-xl px-2 py-1.5 text-xs text-white border border-white/10 focus:outline-none focus:border-secondary"
                                        />
                                    </div>
                                    {isLoading && (
                                        <p className="text-[10px] text-secondary animate-pulse text-center">Fetching buildings…</p>
                                    )}
                                    {!isLoading && buildingError && (
                                        <p className="text-[10px] text-red-400 text-center">{buildingError}</p>
                                    )}
                                    {!isLoading && buildingProgress && buildingProgress.loaded < buildingProgress.total && (
                                        <div className="space-y-1">
                                            <p className="text-[10px] text-secondary animate-pulse text-center">
                                                Rendering {buildingProgress.loaded} / {buildingProgress.total}…
                                            </p>
                                            <div className="w-full bg-white/10 rounded-full h-1">
                                                <div
                                                    className="bg-secondary h-1 rounded-full transition-all"
                                                    style={{ width: `${Math.round((buildingProgress.loaded / buildingProgress.total) * 100)}%` }}
                                                />
                                            </div>
                                        </div>
                                    )}
                                    {!isLoading && geojsonData && (!buildingProgress || buildingProgress.loaded >= buildingProgress.total) && (
                                        <p className="text-[10px] text-gray-500 text-center">
                                            {geojsonData?.features?.length ?? 0} buildings
                                            {geojsonData?.totalCount && geojsonData.totalCount > (geojsonData?.features?.length ?? 0)
                                                ? ` of ${geojsonData.totalCount} (capped)`
                                                : ""}
                                            {" "}shown
                                        </p>
                                    )}
                                </div>
                            )}

                            {/* MRT Station Exits */}
                            <button
                                onClick={() => setShowMrtExits(!showMrtExits)}
                                className={`w-full flex items-center justify-between p-3 rounded-2xl transition-all border mt-2 ${showMrtExits
                                        ? 'bg-emerald-500/20 border-emerald-500 text-emerald-400'
                                        : 'bg-white/5 border-transparent text-gray-400 hover:bg-white/10'
                                    }`}
                            >
                                <div className="flex items-center gap-2">
                                    <Train className="w-4 h-4" />
                                    <span className="text-xs font-bold">MRT Stations</span>
                                </div>
                                <div className={`w-8 h-4 rounded-full relative transition-colors ${showMrtExits ? 'bg-emerald-500' : 'bg-white/20'}`}>
                                    <div className={`absolute top-1 w-2 h-2 bg-white rounded-full transition-all ${showMrtExits ? 'left-5' : 'left-1'}`} />
                                </div>
                            </button>
                            {showMrtExits && (
                                <div className="mt-2 px-3 py-3 bg-white/5 rounded-2xl flex flex-col gap-2">
                                    <div className="flex gap-1 bg-white/10 p-1 rounded-xl">
                                        <button 
                                            onClick={() => setMrtStatusFilter("ALL")}
                                            className={`flex-1 text-[10px] uppercase tracking-wider font-bold py-1.5 rounded-lg transition-colors ${mrtStatusFilter === "ALL" ? 'bg-slate-700 text-white' : 'text-gray-400 hover:text-white'}`}
                                        >All</button>
                                        <button 
                                            onClick={() => setMrtStatusFilter("OPEN")}
                                            className={`flex-1 text-[10px] uppercase tracking-wider font-bold py-1.5 rounded-lg transition-colors ${mrtStatusFilter === "OPEN" ? 'bg-emerald-600 text-white shadow-md' : 'text-gray-400 hover:text-white'}`}
                                        >Open</button>
                                        <button 
                                            onClick={() => setMrtStatusFilter("DEVELOPMENT")}
                                            className={`flex-1 text-[10px] uppercase tracking-wider font-bold py-1.5 rounded-lg transition-colors ${mrtStatusFilter === "DEVELOPMENT" ? 'bg-amber-600 text-white shadow-md' : 'text-gray-400 hover:text-white'}`}
                                        >Planned</button>
                                        <button 
                                            onClick={() => setMrtStatusFilter("UNKNOWN")}
                                            className={`flex-1 text-[10px] uppercase tracking-wider font-bold py-1.5 rounded-lg transition-colors ${mrtStatusFilter === "UNKNOWN" ? 'bg-gray-600 text-white shadow-md' : 'text-gray-400 hover:text-white'}`}
                                        >?</button>
                                    </div>
                                    {mrtExitsLoading && <p className="text-[10px] text-emerald-400 animate-pulse text-center mt-1">Loading MRT Stations…</p>}
                                    {!mrtExitsLoading && mrtExitsError && <p className="text-[10px] text-red-400 text-center mt-1">{mrtExitsError} <button className="underline" onClick={() => setMrtRetry(n => n + 1)}>Retry</button></p>}
                                    {!mrtExitsLoading && mrtExitsData && (
                                        <p className="text-[10px] text-gray-500 text-center mt-1">{filteredMrtData?.features?.length ?? 0} stations shown</p>
                                    )}
                                    {!mrtExitsLoading && mrtExitsData && !filteredMrtData?.features?.length && <p className="text-[10px] text-gray-400 text-center mt-1">No stations match this status. Try All.</p>}
                                    {mrtExitsData?.coverage_note && <p className="text-[10px] text-gray-400 mt-2">{mrtExitsData.coverage_note}</p>}
                                </div>
                            )}

                            {/* URA Planning Boundaries */}
                            <button
                                onClick={() => setShowUraRegions(!showUraRegions)}
                                className={`w-full flex items-center justify-between p-3 rounded-2xl transition-all border mt-2 ${showUraRegions
                                        ? 'bg-amber-500/20 border-amber-500 text-amber-500'
                                        : 'bg-white/5 border-transparent text-gray-400 hover:bg-white/10'
                                    }`}
                            >
                                <div className="flex items-center gap-2">
                                    <MapIcon className="w-4 h-4" />
                                    <span className="text-xs font-bold">URA Boundaries</span>
                                </div>
                                <div className={`w-8 h-4 rounded-full relative transition-colors ${showUraRegions ? 'bg-amber-500' : 'bg-white/20'}`}>
                                    <div className={`absolute top-1 w-2 h-2 bg-white rounded-full transition-all ${showUraRegions ? 'left-5' : 'left-1'}`} />
                                </div>
                            </button>
                            {showUraRegions && (
                                <div className="mt-2 px-3 py-2 bg-white/5 rounded-2xl text-center">
                                    {uraRegionsLoading ? (
                                        <p className="text-[10px] text-amber-500 animate-pulse">Loading boundaries…</p>
                                    ) : uraRegionsError ? (
                                        <p className="text-[10px] text-red-400">{uraRegionsError} <button className="underline" onClick={() => setUraRetry(n => n + 1)}>Retry</button></p>
                                    ) : (
                                        <p className="text-[10px] text-gray-500">{uraRegionsData?.features?.length ? `${uraRegionsData.features.length} boundaries loaded` : 'No boundary data is loaded for this area.'}</p>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>

            <MapContainer
                center={center}
                zoom={zoom}
                zoomControl={false}
                style={{ height: '100%', width: '100%' }}
                scrollWheelZoom={true}
            >
                <MapInstanceCapture mapRef={leafletMapRef} />
                <TileLayer
                    attribution={MapStyles[activeStyle].attribution}
                    url={MapStyles[activeStyle].url}
                />

                {/* Radius circle rendered first so building polygons stack above it */}
                {radiusCircle && (
                    <Circle
                        center={[radiusCircle.lat, radiusCircle.lng]}
                        radius={radiusCircle.radiusM}
                        pathOptions={{
                            color: "#0ea5e9",
                            weight: 2,
                            fillColor: "#38bdf8",
                            fillOpacity: 0.12,
                            dashArray: "6 4",
                            interactive: false,
                        }}
                    />
                )}

                {showBuildings && geojsonData && (
                    <HdbBuildingsLayer
                        key={`hdb-buildings-${JSON.stringify(buildingFilter)}-${selectedRegionCode ?? ""}-${selectedTowns.join(",")}`}
                        data={geojsonData}
                        onEachFeature={onEachBuilding}
                        style={buildingStyle}
                        onProgress={(loaded, total) => {
                            setBuildingProgress(total > 0 ? { loaded, total } : null);
                        }}
                    />
                )}
                <AutoFitBounds
                    data={geojsonData}
                    targetPostal={fullPostalForFit}
                    active={postalFitReady}
                />
                <AutoFitArea
                    data={uraRegionsData}
                    selectedTowns={selectedTowns}
                    selectedUraRegion={selectedUraRegion}
                    active={
                        showUraRegions &&
                        hasAreaScope &&
                        (lastZoomTrigger === "town" || lastZoomTrigger === "region")
                    }
                />

                {showMrtExits && filteredMrtData && (
                    <GeoJSON
                        key={`mrt-exits-${mrtStatusFilter}`}
                        data={filteredMrtData}
                        onEachFeature={onEachMrtExit}
                        pointToLayer={mrtExitPointToLayer}
                    />
                )}

                {showUraRegions && uraRegionsData && !uraRegionsLoading && (
                    <GeoJSON
                        key={`ura-regions-${selectedUraRegion || 'all'}-${selectedTowns.join(',')}`}
                        data={uraRegionsData}
                        style={(feature) => {
                            let active = true;
                            if (selectedTowns.length > 0) {
                                const pln = feature?.properties?.pln_area_n?.toUpperCase();
                                active = pln ? planningAreaMatchesSelectedTowns(pln, selectedTowns) : false;
                            }
                            return {
                                color: active ? '#f59e0b' : 'transparent',
                                weight: active ? 2 : 0,
                                fillOpacity: active ? 0.25 : 0,
                                fillColor: '#fbbf24',
                            };
                        }}
                        onEachFeature={(feature, layer) => {
                            const props = feature.properties;
                            const title = props.pln_area_n || props.region_n || 'Region';
                            layer.bindPopup(`<div class="font-bold font-sans text-amber-700">${escapeHtml(String(title))}</div>`);
                        }}
                    />
                )}
                
                <ZoomControl position="bottomleft" />
                <ZoomToSingapore center={center} zoom={zoom} />

                {markers.map((m, i) => (
                    <Marker key={i} position={[m.lat, m.lng]}>
                        <Popup>
                            <div className="text-black font-semibold">{m.name}</div>
                        </Popup>
                    </Marker>
                ))}

                {propertyWaypoint && (
                    <Marker
                        position={[propertyWaypoint.lat, propertyWaypoint.lng]}
                        icon={waypointIcon}
                        zIndexOffset={2500}
                    >
                        <Popup>
                            <div
                                dangerouslySetInnerHTML={{
                                    __html: buildingPopupHtml(propertyWaypoint.buildingProps),
                                }}
                            />
                        </Popup>
                    </Marker>
                )}

                {mrtWaypoint && (
                    <Marker
                        position={[mrtWaypoint.lat, mrtWaypoint.lng]}
                        icon={waypointIcon}
                        zIndexOffset={2600}
                    >
                        <Tooltip
                            permanent
                            interactive
                            direction="top"
                            offset={[0, -34]}
                            opacity={1}
                            className="leaflet-mrt-waypoint-tooltip"
                        >
                            <div className="flex items-center gap-1.5 px-2.5 py-1.5 max-w-[min(90vw,260px)]">
                                <span
                                    className="text-xs font-bold text-slate-800 truncate flex-1 min-w-0"
                                    title={mrtWaypoint.name}
                                >
                                    {mrtWaypoint.name}
                                </span>
                                <button
                                    type="button"
                                    className="shrink-0 flex h-6 w-6 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 hover:text-slate-900 transition-colors"
                                    aria-label="Close waypoint"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        e.preventDefault();
                                        setMrtWaypoint(null);
                                    }}
                                >
                                    <X className="w-3.5 h-3.5" strokeWidth={2.5} />
                                </button>
                            </div>
                        </Tooltip>
                    </Marker>
                )}
            </MapContainer>
        </div>
    );
});

export default Map;
