"use client";
import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import ChatDrawer from "@/components/ChatDrawer";
import { useAuth } from "@/context/AuthContext";
import { motion, AnimatePresence } from "framer-motion";
import {
    LineChart, Line,
    XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import {
    Sparkles, Save, TrendingUp, BarChart3,
    Loader2, MapPinned, MessageSquare,
    Lock, X, Plus,
    TreePine, Train, GraduationCap, Library, MapPin,
    ChevronDown, PersonStanding, Car, Bus,
    PanelLeftClose, PanelLeftOpen, ShoppingBag,
    Store, UtensilsCrossed, Route, Layers, Navigation2, CircleHelp,
} from "lucide-react";
import { useState, useEffect, useCallback, useRef, useMemo, type ComponentType } from "react";
import type { MapChromeState, MapHandle, MapOverlayId } from "@/components/Map";

const OVERLAY_TAG_CLASS: Record<MapOverlayId, string> = {
    hdb_footprints:
        "border-secondary/45 bg-secondary/15 text-secondary hover:bg-secondary/25",
    mrt_exits:
        "border-emerald-500/45 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/18",
    ura_boundaries:
        "border-amber-500/45 bg-amber-500/10 text-amber-800 hover:bg-amber-500/18",
};
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import Link from "next/link";
import AnalyticsDateRange from "@/components/AnalyticsDateRange";
import MarketSentimentPanel from "@/components/MarketSentimentPanel";

import API_BASE from "@/lib/apiBase";
import { subscriptionAwareHeaders } from "@/lib/subscriptionPreview";
import PropertySearchInput from "@/components/PropertySearchInput";
import type { PropertySearchHit } from "@/lib/propertySearch";

const Map = dynamic(() => import("@/components/Map").then((m) => m.default), {
    ssr: false,
    loading: () => (
        <div className="w-full h-[690px] bg-slate-900 animate-pulse rounded-3xl flex items-center justify-center text-white/20">
            Loading Map...
        </div>
    ),
});



const PLANS_HREF = "/#pricing";

type WorkspaceTab = "geospatial" | "resale" | "sentiment" | "chat";

type TabIcon = ComponentType<{ className?: string }>;

function AnalyticsPremiumFeatureGate({
    title,
    subtitle,
    body,
    icon: Icon,
}: {
    title: string;
    subtitle: string;
    body: string;
    icon: TabIcon;
}) {
    return (
        <div className="glass rounded-3xl border border-white/10 p-8 sm:p-12 text-center shadow-xl mt-4">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/10 text-accent mb-5 ring-1 ring-accent/20">
                <Icon className="w-7 h-7" aria-hidden />
            </div>
            <div className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/12 text-amber-800 text-[10px] font-bold uppercase tracking-wider px-3 py-1 mb-4 border border-amber-500/25">
                <Lock className="w-3 h-3 shrink-0" aria-hidden />
                Premium
            </div>
            <h2 className="text-2xl font-black text-slate-900 mb-2">{title}</h2>
            <p className="text-sm font-semibold text-slate-700 mb-3 max-w-md mx-auto">{subtitle}</p>
            <p className="text-sm text-slate-500 max-w-lg mx-auto leading-relaxed">{body}</p>
            <div className="mt-8 flex flex-col sm:flex-row gap-3 justify-center items-stretch sm:items-center">
                <Link
                    href={PLANS_HREF}
                    className="inline-flex justify-center items-center gap-2 px-6 py-3 rounded-xl bg-accent text-white font-bold text-sm shadow-lg shadow-accent/25 hover:bg-accent/90 transition-colors"
                >
                    Upgrade to Premium
                </Link>
                <Link
                    href={PLANS_HREF}
                    className="inline-flex justify-center items-center px-6 py-3 rounded-xl border-2 border-slate-200 text-slate-800 font-bold text-sm hover:bg-slate-100/80 transition-colors"
                >
                    View plans
                </Link>
            </div>
        </div>
    );
}

type ChartGroupBy = "month" | "quarter" | "year";

interface FilterState {
    towns: string[];
    flat_types: string[];
    date_from: string;
    date_to: string;
    price_min: number | null;
    price_max: number | null;
    floor_levels: string[];
    group_by: ChartGroupBy;
    floor_area_min: number | null;
    floor_area_max: number | null;
    lease_remaining_min: number | null;
    lease_remaining_max: number | null;
    postal_code: string;
    property_name: string;
}

const DEFAULT_FILTERS: FilterState = {
    towns: [],
    flat_types: [],
    date_from: "",
    date_to: "",
    price_min: null,
    price_max: null,
    floor_levels: [],
    group_by: "year",
    floor_area_min: null,
    floor_area_max: null,
    lease_remaining_min: null,
    lease_remaining_max: null,
    postal_code: "",
    property_name: "",
};

const FLOOR_LEVELS = ["Low", "Mid", "High", "Very High"];

const CHART_PERIOD_OPTIONS: { value: ChartGroupBy; label: string }[] = [
    { value: "month", label: "Month" },
    { value: "quarter", label: "Quarter" },
    { value: "year", label: "Year" },
];

/** Maps analytics URA dropdown to ``region_c`` (matches backend analytics / geospatial). */
const URA_REGION_TO_CODE: Record<string, string> = {
    "Central Region": "CR",
    "East Region": "ER",
    "North Region": "NR",
    "North-East Region": "NER",
    "West Region": "WR",
};

function pitStateLabel(pit: string | undefined): string {
    switch ((pit || "").toUpperCase()) {
        case "OPERATIONAL":
            return "Operational";
        case "COMMITTED_DATED":
            return "Opening scheduled";
        case "COMMITTED_ESTIMATED":
            return "Expected completion";
        case "ANNOUNCED_UNDATED":
            return "Announced";
        case "UNKNOWN":
            return "Unknown";
        default:
            return pit || "—";
    }
}

/** Approximate official Singapore rail line colours for tags (LTA-style hex accents). */
function mrtLineTagClasses(networkLine: string | null | undefined): string {
    const s = (networkLine || "").toLowerCase();
    if (s.includes("north-south") || s.includes("north south")) return "border-[#E1251B] bg-[#E1251B]/10 text-[#991b1b]";
    if (s.includes("east-west") || s.includes("east west")) return "border-[#009639] bg-[#009639]/10 text-[#166534]";
    if (s.includes("north east")) return "border-[#9F479C] bg-[#9F479C]/12 text-[#6b2f73]";
    if (s.includes("circle")) return "border-[#FF9E18] bg-[#FF9E18]/14 text-[#9a3412]";
    if (s.includes("downtown")) return "border-[#005BA8] bg-[#005BA8]/12 text-[#1e40af]";
    if (s.includes("thomson") || s.includes("east coast")) return "border-[#9D591F] bg-[#9D591F]/12 text-[#7c2d12]";
    if (s.includes("lrt") || s.includes("bukit panjang")) return "border-[#718472] bg-[#718472]/15 text-[#3f3f46]";
    if (s.includes("sengkang") || s.includes("punggol")) return "border-[#748477] bg-[#748477]/15 text-[#334155]";
    return "border-slate-300 bg-slate-50 text-slate-700";
}

/** PIT / lifecycle tag beside line metadata — operational in solid green. */
function mrtLinePitStatusTagClasses(pit: string | undefined): string {
    const p = (pit || "").toUpperCase();
    if (p === "OPERATIONAL") {
        return "bg-emerald-600 text-white border-emerald-700 shadow-sm";
    }
    if (p === "UNKNOWN") {
        return "bg-slate-100 text-slate-700 border-slate-300";
    }
    return "bg-amber-100 text-amber-950 border-amber-300";
}

/** Unique station codes from line rows, sorted for display e.g. `DT19 / NE4`. */
function mrtStationCodesFromLines(lines: unknown): string {
    if (!Array.isArray(lines)) return "";
    const codes = new Set<string>();
    for (const ln of lines) {
        const c = String((ln as { station_code?: unknown })?.station_code ?? "").trim();
        if (c) codes.add(c);
    }
    return [...codes].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" })).join(" / ");
}

/** Card / pane title: `Chinatown (DT19 / NE4)` using canonical or name + codes. */
function mrtPhysicalStationDisplayTitle(st: {
    name?: string;
    canonical_name?: string;
    lines?: unknown;
}): string {
    const codeStr = mrtStationCodesFromLines(st.lines);
    let raw =
        (typeof st.canonical_name === "string" && st.canonical_name.trim()) ||
        (typeof st.name === "string" && st.name.trim()) ||
        "Station";
    raw = raw.replace(/\s+MRT$/i, "").trim();
    if (!raw) raw = "Station";
    const titled = raw
        .toLowerCase()
        .split(/\s+/)
        .map((w) => (w.length ? w[0].toUpperCase() + w.slice(1) : w))
        .join(" ");
    return codeStr ? `${titled} (${codeStr})` : titled;
}

function poiTypeIcon(poiType: string): ComponentType<{ className?: string }> {
    switch (poiType) {
        case "school_top20":
        case "school_any":
            return GraduationCap;
        case "mall":
            return ShoppingBag;
        case "supermarket":
            return Store;
        case "park":
            return TreePine;
        case "market":
            return UtensilsCrossed;
        case "pcn":
            return Route;
        default:
            return MapPin;
    }
}

const MRT_STATION_CARD_TOP = 3;

function MrtPhysicalStationCards({
    stations,
    selectedPhysicalId,
    onSelect,
}: {
    stations: any[];
    selectedPhysicalId: number | null;
    onSelect: (physicalId: number) => void;
}) {
    const primary = stations.slice(0, MRT_STATION_CARD_TOP);
    const rest = stations.slice(MRT_STATION_CARD_TOP);

    const renderCard = (st: any) => {
        const selected = selectedPhysicalId === st.physical_station_id;
        const lines = Array.isArray(st.lines) ? st.lines : [];
        return (
            <button
                key={st.physical_station_id}
                type="button"
                onClick={() => onSelect(Number(st.physical_station_id))}
                className={`flex flex-col text-left p-4 rounded-2xl border transition-all ${
                    selected
                        ? "ring-2 ring-sky-500 border-sky-400 shadow-md bg-sky-50/50"
                        : "border-slate-200/80 bg-white hover:border-sky-200 hover:shadow-sm"
                }`}
            >
                <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-xl bg-emerald-500/10 flex items-center justify-center shrink-0 border border-emerald-500/20">
                        <Train className="w-5 h-5 text-emerald-600" />
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="text-sm font-black text-slate-900 leading-snug whitespace-normal break-words">
                            {mrtPhysicalStationDisplayTitle(st)}
                        </div>
                        <div className="text-[11px] font-mono font-bold text-emerald-700 mt-1">
                            {typeof st.distance_m === "number" ? `${st.distance_m} m` : "—"}
                            <span className="text-slate-400 font-semibold normal-case ml-1">straight-line</span>
                        </div>
                        <div className="flex flex-wrap gap-1.5 mt-2">
                            {lines.map((ln: any) => (
                                <span
                                    key={ln.line_id}
                                    className={`inline-flex items-center px-2 py-0.5 rounded-md border text-[9px] font-black uppercase tracking-tight ${mrtLineTagClasses(ln.network_line)}`}
                                >
                                    {ln.network_line || "Line"}
                                </span>
                            ))}
                        </div>
                    </div>
                </div>
            </button>
        );
    };

    return (
        <div className="space-y-3">
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-[repeat(auto-fill,minmax(min(100%,220px),1fr))]">
                {primary.map(renderCard)}
            </div>
            {rest.length > 0 && (
                <details className="group rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-sm">
                    <summary className="cursor-pointer select-none list-none flex items-center justify-between px-4 py-3 text-sm font-bold text-slate-700 hover:bg-slate-50 [&::-webkit-details-marker]:hidden">
                        <span>
                            Show {rest.length} more station{rest.length === 1 ? "" : "s"}
                        </span>
                        <ChevronDown className="w-4 h-4 text-slate-400 transition-transform group-open:rotate-180" />
                    </summary>
                    <div className="px-3 pb-3 pt-0 grid gap-3 grid-cols-1 sm:grid-cols-[repeat(auto-fill,minmax(min(100%,220px),1fr))] border-t border-slate-100 bg-slate-50/40">
                        {rest.map(renderCard)}
                    </div>
                </details>
            )}
        </div>
    );
}

function PhysicalMrtStationSection({
    title,
    stations,
    selectedPhysicalId,
    onSelect,
}: {
    title: string;
    stations: any[];
    selectedPhysicalId: number | null;
    onSelect: (physicalId: number) => void;
}) {
    if (!stations?.length) return null;
    return (
        <div className="space-y-3 mb-8">
            <div className="flex items-center gap-2 border-b border-slate-100 pb-2">
                <Train className="w-3.5 h-3.5 text-emerald-500" />
                <h4 className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">{title}</h4>
                <span className="text-[9px] font-bold text-slate-500 ml-auto bg-slate-50 px-2 py-0.5 rounded-full border border-slate-100">
                    {stations.length}
                </span>
            </div>
            <MrtPhysicalStationCards
                stations={stations}
                selectedPhysicalId={selectedPhysicalId}
                onSelect={onSelect}
            />
        </div>
    );
}

function MrtStationDetailPane({
    station,
    onClose,
    onFlyToMap,
}: {
    station: any;
    onClose: () => void;
    onFlyToMap?: (lat: number, lng: number, mrtName: string) => void;
}) {
    const lat = station.lat != null ? Number(station.lat) : null;
    const lng = station.lng != null ? Number(station.lng) : null;
    const lines = Array.isArray(station.lines) ? station.lines : [];
    const mapUrl =
        lat != null && lng != null && Number.isFinite(lat) && Number.isFinite(lng)
            ? `https://staticmap.openstreetmap.de/staticmap.php?center=${lat},${lng}&zoom=16&size=640x300&markers=${lat},${lng},red-pushpin`
            : null;

    const TRAVEL_MODES = [
        { key: "walk", label: "Walk", Icon: PersonStanding, color: "text-sky-600", bg: "bg-sky-50", border: "border-sky-100" },
        { key: "drive", label: "Drive", Icon: Car, color: "text-amber-600", bg: "bg-amber-50", border: "border-amber-100" },
        { key: "pt", label: "Transit", Icon: Bus, color: "text-emerald-600", bg: "bg-emerald-50", border: "border-emerald-100" },
    ];

    return (
        <aside className="w-full lg:w-[360px] shrink-0 rounded-2xl border border-slate-200 bg-white shadow-xl overflow-hidden lg:sticky lg:top-24 max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 bg-slate-50">
                <h4 className="text-sm font-black text-slate-900 truncate pr-2">Station details</h4>
                <button
                    type="button"
                    onClick={onClose}
                    className="p-2 rounded-lg hover:bg-slate-200/80 text-slate-600 transition-colors"
                    aria-label="Close station details"
                >
                    <X className="w-4 h-4" />
                </button>
            </div>
            <div className="p-4 space-y-4">
                <div>
                    <p className="text-[10px] font-black uppercase tracking-wider text-slate-400 mb-1">Location</p>
                    <p className="text-lg font-black text-slate-900 leading-snug break-words">
                        {mrtPhysicalStationDisplayTitle(station)}
                    </p>
                </div>
                {mapUrl ? (
                    <div>
                        <p className="text-[10px] font-black uppercase tracking-wider text-slate-400 mb-2">Map preview</p>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={mapUrl} alt="" className="w-full h-auto rounded-xl border border-slate-200 bg-slate-100" />
                        <p className="text-[9px] text-slate-400 mt-1">
                            Map ©{" "}
                            <a href="https://www.openstreetmap.org/copyright" className="underline" target="_blank" rel="noreferrer">
                                OpenStreetMap
                            </a>
                        </p>
                    </div>
                ) : (
                    <p className="text-xs text-slate-400 font-semibold">No coordinates available for map preview.</p>
                )}
                <div className="rounded-xl border border-slate-100 bg-slate-50/80 p-3 space-y-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-[10px] font-black uppercase tracking-wider text-slate-400">Coordinates</p>
                        {onFlyToMap != null &&
                            lat != null &&
                            lng != null &&
                            Number.isFinite(lat) &&
                            Number.isFinite(lng) && (
                                <button
                                    type="button"
                                    onClick={() =>
                                        onFlyToMap(lat, lng, mrtPhysicalStationDisplayTitle(station))
                                    }
                                    className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-sky-200 bg-white px-2.5 py-1.5 text-[10px] font-black uppercase tracking-wide text-sky-700 shadow-sm hover:bg-sky-50 transition-colors"
                                >
                                    <Navigation2 className="w-3.5 h-3.5" aria-hidden />
                                    Waypoint
                                </button>
                            )}
                    </div>
                    <p className="text-xs font-mono font-bold text-slate-800 break-all">
                        {lat != null && lng != null && Number.isFinite(lat) && Number.isFinite(lng) ? (
                            <>
                                {lat.toFixed(6)}, {lng.toFixed(6)}
                            </>
                        ) : (
                            "—"
                        )}
                    </p>
                    <p className="text-[10px] text-slate-500">
                        Station centre distance (straight-line):{" "}
                        <span className="font-bold text-slate-800">{typeof station.distance_m === "number" ? `${station.distance_m} m` : "—"}</span>
                    </p>
                </div>
                {station.travel_times && (
                    <div className="rounded-xl border border-slate-100 bg-slate-50/90 p-3">
                        <p className="text-[10px] font-black uppercase tracking-wider text-slate-500 mb-1">
                            Routing from your address
                        </p>
                        <p className="text-[10px] text-slate-500 mb-3 leading-snug">
                            Pre-computed in{" "}
                            <code className="text-[9px] bg-white px-1 rounded border border-slate-200">hdb_mrt_routes</code>{" "}
                            per line; shown here once per physical interchange (best time per mode across lines).
                        </p>
                        <div className="grid grid-cols-3 gap-2">
                            {TRAVEL_MODES.map((mode) => {
                                const tData = station.travel_times?.[mode.key];
                                const timeVal = tData?.time_mins ?? tData?.time;
                                return (
                                    <div
                                        key={mode.key}
                                        className={`flex flex-col items-center p-2 rounded-lg border ${mode.border} ${mode.bg}`}
                                    >
                                        <mode.Icon className={`w-3.5 h-3.5 ${mode.color} mb-1`} />
                                        <span className="text-[9px] font-black uppercase text-slate-400">{mode.label}</span>
                                        <span className={`text-[11px] font-black ${mode.color}`}>
                                            {timeVal != null ? `${timeVal} min` : "—"}
                                        </span>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}
                <div className="space-y-3">
                    <p className="text-[10px] font-black uppercase tracking-wider text-slate-400">Lines serving this station</p>
                    <ul className="space-y-3">
                        {lines.map((ln: any) => (
                            <li key={ln.line_id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                                <div className="mb-3">
                                    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end sm:gap-x-4 sm:gap-y-2">
                                        <p className="text-lg sm:text-xl font-black font-mono tracking-tight text-slate-900 leading-tight tabular-nums">
                                            {ln.station_code ? String(ln.station_code).trim() : "—"}
                                        </p>
                                        <div className="flex flex-wrap items-center gap-2">
                                            <span
                                                className={`inline-flex items-center px-2.5 py-1 rounded-lg border text-[10px] font-black uppercase tracking-tight ${mrtLineTagClasses(ln.network_line)}`}
                                            >
                                                {ln.network_line || "Line"}
                                            </span>
                                            <span
                                                className={`inline-flex items-center px-2.5 py-1 rounded-lg border text-[10px] font-black uppercase tracking-wide ${mrtLinePitStatusTagClasses(ln.pit_state)}`}
                                            >
                                                {pitStateLabel(ln.pit_state)}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                                <dl className="grid grid-cols-1 gap-1 text-[11px] text-slate-600">
                                    {(ln.announcement_date || ln.announcement_date_raw) && (
                                        <div className="flex justify-between gap-2">
                                            <dt className="text-slate-400 shrink-0">Announced</dt>
                                            <dd className="font-semibold text-right">
                                                {ln.announcement_date || ln.announcement_date_raw}
                                            </dd>
                                        </div>
                                    )}
                                    {(ln.expected_completion || ln.expected_completion_raw) && (
                                        <div className="flex justify-between gap-2">
                                            <dt className="text-slate-400 shrink-0">Expected</dt>
                                            <dd className="font-semibold text-right">{ln.expected_completion || ln.expected_completion_raw}</dd>
                                        </div>
                                    )}
                                    {(ln.opening_date || ln.opening_date_raw) && (
                                        <div className="flex justify-between gap-2">
                                            <dt className="text-slate-400 shrink-0">Opened</dt>
                                            <dd className="font-semibold text-right">{ln.opening_date || ln.opening_date_raw}</dd>
                                        </div>
                                    )}
                                        <div className="flex justify-between gap-2">
                                            <dt className="text-slate-400 shrink-0">Distance</dt>
                                            <dd className="font-mono font-bold text-right text-slate-800 text-[11px]">
                                                {ln.straight_line_distance_m != null && (
                                                    <span className="block">{ln.straight_line_distance_m} m (line geometry)</span>
                                                )}
                                                {ln.distance_m != null && (
                                                    <span className="block text-slate-600">{ln.distance_m} m (routed where available)</span>
                                                )}
                                            </dd>
                                        </div>
                                    {ln.subproject_or_stage && (
                                        <div className="flex justify-between gap-2">
                                            <dt className="text-slate-400 shrink-0">Stage</dt>
                                            <dd className="font-semibold text-right">{ln.subproject_or_stage}</dd>
                                        </div>
                                    )}
                                </dl>
                                {ln.source_url && (
                                    <a
                                        href={ln.source_url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="inline-block mt-2 text-[10px] font-bold text-accent hover:underline"
                                    >
                                        Official source
                                    </a>
                                )}
                            </li>
                        ))}
                    </ul>
                </div>
            </div>
        </aside>
    );
}

type NearbyPoiPayload = {
    poi_total: number;
    counts_by_type: Record<string, number>;
    by_type: { poi_type: string; label: string; count: number; items: { id: number; name: string | null; distance_m: number }[] }[];
    radius_m: number;
    lat: number;
    lng: number;
    address?: string;
};

type PlacesSuperGroupId = "schools" | "food_hawker" | "nature_parks" | "malls_supermarkets" | "community_illustrative";

type MergedPlaceItem = {
    id: number;
    name: string;
    distance_m: number;
    source: "poi" | "illustrative";
    detail: string;
};

type PlacesSuperGroupRow = {
    id: PlacesSuperGroupId;
    label: string;
    hint: string;
    Icon: TabIcon;
    items: MergedPlaceItem[];
};

const POI_TYPE_DETAIL: Record<string, string> = {
    school_top20: "Top primary schools",
    school_any: "Primary schools",
    mall: "Shopping malls",
    supermarket: "Supermarkets",
    park: "Parks & nature",
    market: "Markets & food centres",
    pcn: "Park connectors",
};

const PLACES_SUPER_GROUP_DEFS: readonly {
    id: PlacesSuperGroupId;
    label: string;
    hint: string;
    Icon: TabIcon;
    poiTypes: readonly string[];
    stubTypes: readonly string[];
}[] = [
    {
        id: "schools",
        label: "Schools & learning",
        hint: "Verified primary schools from POI data, plus illustrative school rows from the geospatial enrichment API.",
        Icon: GraduationCap,
        poiTypes: ["school_top20", "school_any"],
        stubTypes: ["School", "Primary School", "Secondary School", "Tertiary"],
    },
    {
        id: "food_hawker",
        label: "Food (Hawker)",
        hint: "Markets and hawker centres from verified POI data.",
        Icon: UtensilsCrossed,
        poiTypes: ["market"],
        stubTypes: [],
    },
    {
        id: "nature_parks",
        label: "Nature and Parks",
        hint: "Parks, nature reserves, and park connectors; illustrative park rows from the enrichment API are listed together for context.",
        Icon: TreePine,
        poiTypes: ["park", "pcn"],
        stubTypes: ["Park", "Nature"],
    },
    {
        id: "malls_supermarkets",
        label: "Malls and Supermarkets",
        hint: "Shopping malls and supermarkets from verified POI data.",
        Icon: ShoppingBag,
        poiTypes: ["mall", "supermarket"],
        stubTypes: ["Mall", "Lifestyle", "Community Club"],
    },
    {
        id: "community_illustrative",
        label: "Community (illustrative)",
        hint: "Placeholders from the geospatial enrichment API only (not from the primary POI database), e.g. place of worship.",
        Icon: Library,
        poiTypes: [],
        stubTypes: ["Mosque", "Clinic", "Hospital"],
    },
];

function syntheticIllustrativeId(stubType: string, name: string, distance_m: number): number {
    const s = `${stubType}\0${name}\0${distance_m}`;
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) {
        h ^= s.charCodeAt(i);
        h = Math.imul(h, 16777619);
    }
    return -Math.abs(h) - 1;
}

/** Normalized name for deduping human-readable POI labels (same school in top20 + all-schools, etc.). */
function normalizeMergedPlaceName(name: string): string {
    const t = name.trim().toLowerCase().replace(/\s+/g, " ");
    return t === "" || t === "—" ? "" : t;
}

function stubIllustrativeRowsFromMrtGeo(mrtGeoData: unknown): { type: string; name: string; distance_m: number }[] {
    const sd = mrtGeoData as { amenities?: unknown[] } | null | undefined;
    const raw = Array.isArray(sd?.amenities) ? sd.amenities : [];
    const out: { type: string; name: string; distance_m: number }[] = [];
    for (const row of raw) {
        const r = row as { type?: unknown; name?: unknown; distance_m?: unknown };
        const t = typeof r.type === "string" ? r.type : "";
        if (t === "MRT") continue;
        const name = typeof r.name === "string" ? r.name : "—";
        const distance_m = typeof r.distance_m === "number" ? r.distance_m : 999_999;
        out.push({ type: t, name, distance_m });
    }
    return out;
}

function buildPlacesSuperGroups(mrtGeoData: unknown, poiData: NearbyPoiPayload | null): PlacesSuperGroupRow[] {
    const byPoiType = new globalThis.Map<string, { label: string; items: { id: number; name: string | null; distance_m: number }[] }>();
    for (const grp of poiData?.by_type ?? []) {
        byPoiType.set(grp.poi_type, { label: grp.label, items: grp.items });
    }
    const stubs = stubIllustrativeRowsFromMrtGeo(mrtGeoData);

    return PLACES_SUPER_GROUP_DEFS.map((def) => {
        const items: MergedPlaceItem[] = [];
        const seenPoiIds = new globalThis.Set<number>();
        const seenSchoolNames = def.id === "schools" ? new globalThis.Set<string>() : null;
        const verifiedNormNames = new globalThis.Set<string>();
        const seenIllustrativeTriples = new globalThis.Set<string>();

        for (const pt of def.poiTypes) {
            const g = byPoiType.get(pt);
            if (!g) continue;
            const detail = POI_TYPE_DETAIL[pt] ?? g.label;
            for (const it of g.items) {
                if (seenPoiIds.has(it.id)) continue;
                const name = (it.name && String(it.name).trim()) || "—";
                const nk = normalizeMergedPlaceName(name);
                if (def.id === "schools" && nk && seenSchoolNames!.has(nk)) continue;
                if (def.id === "schools" && nk) seenSchoolNames!.add(nk);
                seenPoiIds.add(it.id);
                items.push({
                    id: it.id,
                    name,
                    distance_m: it.distance_m,
                    source: "poi",
                    detail,
                });
                if (nk) verifiedNormNames.add(nk);
            }
        }
        for (const st of stubs) {
            if (!def.stubTypes.includes(st.type)) continue;
            const triple = `${st.type}\0${st.name}\0${st.distance_m}`;
            if (seenIllustrativeTriples.has(triple)) continue;
            seenIllustrativeTriples.add(triple);
            const snk = normalizeMergedPlaceName(st.name);
            if (snk && verifiedNormNames.has(snk)) continue;
            items.push({
                id: syntheticIllustrativeId(st.type, st.name, st.distance_m),
                name: st.name,
                distance_m: st.distance_m,
                source: "illustrative",
                detail: "Illustrative (enrichment API)",
            });
        }
        items.sort((a, b) => a.distance_m - b.distance_m);
        return { id: def.id, label: def.label, hint: def.hint, Icon: def.Icon, items };
    }).filter((g) => g.items.length > 0);
}

function UnifiedAmenitiesPreview({
    mrtGeoData,
    poiData,
    poiLoading,
}: {
    mrtGeoData: { mrt?: { operational?: unknown[] }; amenities?: unknown[] } | null;
    poiData: NearbyPoiPayload | null;
    poiLoading: boolean;
}) {
    const mrtTiles = useMemo(() => {
        const op = mrtGeoData?.mrt?.operational;
        if (!Array.isArray(op)) return [];
        return op.slice(0, 1).map((st: any) => ({
            key: `mrt-${st.physical_station_id}`,
            Icon: Train,
            label: "MRT",
            name: mrtPhysicalStationDisplayTitle(st),
            distance_m: typeof st.distance_m === "number" ? st.distance_m : null,
            iconClass: "text-emerald-600",
        }));
    }, [mrtGeoData]);

    const placeTiles = useMemo(() => {
        const groups = buildPlacesSuperGroups(mrtGeoData, poiData);
        return groups.map((g) => {
            const nearest = g.items[0];
            return {
                key: g.id,
                Icon: g.Icon,
                label: g.label,
                name: nearest?.name ?? "—",
                distance_m: nearest?.distance_m ?? 0,
                nearestIllustrative: nearest?.source === "illustrative",
                iconClass: "text-sky-600",
            };
        });
    }, [mrtGeoData, poiData]);

    if (!mrtTiles.length && !placeTiles.length && !poiLoading) return null;

    return (
        <div className="mb-8 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-[10px] font-black uppercase tracking-wider text-slate-500 mb-2">Preview — nearest by category</p>
            <ul className="divide-y divide-slate-100 border border-slate-200/80 rounded-xl overflow-hidden bg-slate-50/50">
                {mrtTiles.map((t) => (
                    <li key={t.key} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                        <t.Icon className={`w-4 h-4 shrink-0 ${t.iconClass}`} aria-hidden />
                        <span className="text-[10px] font-black uppercase tracking-tight text-slate-500 w-[8.5rem] sm:w-40 shrink-0">
                            {t.label}
                        </span>
                        <span className="min-w-0 flex-1 truncate font-semibold text-slate-800">{t.name}</span>
                        <span className="shrink-0 text-xs font-mono font-bold text-emerald-700 tabular-nums">
                            {t.distance_m != null ? `${t.distance_m} m` : "—"}
                        </span>
                    </li>
                ))}
                {placeTiles.map((t) => (
                    <li key={t.key} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                        <t.Icon className={`w-4 h-4 shrink-0 ${t.iconClass}`} aria-hidden />
                        <span className="text-[10px] font-black uppercase tracking-tight text-slate-500 w-[8.5rem] sm:w-40 shrink-0 truncate">
                            {t.label}
                        </span>
                        <span className="flex min-w-0 flex-1 items-center gap-1.5 font-semibold text-slate-800">
                            <span className="min-w-0 flex-1 truncate">{t.name}</span>
                            {t.nearestIllustrative && (
                                <span
                                    className="inline-block w-1.5 h-1.5 shrink-0 rounded-full bg-amber-400 ring-2 ring-amber-100"
                                    title="Illustrative — enrichment API placeholder, not from poi_locations"
                                    aria-label="Illustrative: enrichment API placeholder"
                                />
                            )}
                        </span>
                        <span className="shrink-0 text-xs font-mono font-bold text-emerald-700 tabular-nums">{t.distance_m} m</span>
                    </li>
                ))}
                {poiLoading && !placeTiles.length && (
                    <li className="flex items-center gap-2 px-3 py-3 text-slate-400 text-xs font-semibold">
                        <Loader2 className="w-4 h-4 animate-spin shrink-0" aria-hidden />
                        Loading POI preview…
                    </li>
                )}
            </ul>
        </div>
    );
}

function TransportMrtSection({
    data,
    searchRadiusM,
    onFlyToMap,
}: {
    data: any;
    searchRadiusM?: number;
    onFlyToMap?: (lat: number, lng: number, mrtName: string) => void;
}) {
    const [selectedPhysicalId, setSelectedPhysicalId] = useState<number | null>(null);
    const mrt = data.mrt;
    const radiusHint = typeof data.mrt_search_radius_m === "number" ? data.mrt_search_radius_m : searchRadiusM;

    const allPhysicalStations = useMemo(() => [...(mrt?.operational || []), ...(mrt?.upcoming || []), ...(mrt?.unknown || [])], [mrt]);

    const selectedStation = useMemo(() => {
        if (selectedPhysicalId == null) return null;
        return allPhysicalStations.find((s: any) => Number(s.physical_station_id) === Number(selectedPhysicalId)) ?? null;
    }, [allPhysicalStations, selectedPhysicalId]);

    const noMrts = mrt && allPhysicalStations.length === 0;

    if (!mrt) return null;

    return (
        <div className="flex flex-col xl:flex-row gap-6 items-start min-w-0">
            <div className="min-w-0 w-full xl:flex-1 space-y-6">
                {noMrts ? (
                    <div className="space-y-3">
                        <p className="text-xs text-slate-400 font-semibold py-2">No MRT stations found within the search radius.</p>
                    </div>
                ) : (
                    <>
                        {radiusHint != null && (
                            <p className="text-[11px] text-slate-500 font-semibold leading-relaxed">
                                Physical stations within{" "}
                                <span className="font-black text-slate-800">{radiusHint} m</span> (straight-line). Routed legs from enrichment when present.
                            </p>
                        )}
                        <PhysicalMrtStationSection
                            title="Operational"
                            stations={mrt.operational || []}
                            selectedPhysicalId={selectedPhysicalId}
                            onSelect={(id) => setSelectedPhysicalId((prev) => (prev === id ? null : id))}
                        />
                        <PhysicalMrtStationSection
                            title="Upcoming / in development"
                            stations={mrt.upcoming || []}
                            selectedPhysicalId={selectedPhysicalId}
                            onSelect={(id) => setSelectedPhysicalId((prev) => (prev === id ? null : id))}
                        />
                        <PhysicalMrtStationSection
                            title="Status unavailable"
                            stations={mrt.unknown || []}
                            selectedPhysicalId={selectedPhysicalId}
                            onSelect={(id) => setSelectedPhysicalId((prev) => (prev === id ? null : id))}
                        />
                    </>
                )}
            </div>
            {selectedStation && (
                <MrtStationDetailPane
                    station={selectedStation}
                    onClose={() => setSelectedPhysicalId(null)}
                    onFlyToMap={onFlyToMap}
                />
            )}
        </div>
    );
}

function PoiPlacesSection({
    mrtGeoData,
    poiData,
    poiLoading,
    expandedPlacesGroup,
    setExpandedPlacesGroup,
}: {
    mrtGeoData: unknown;
    poiData: NearbyPoiPayload | null;
    poiLoading: boolean;
    expandedPlacesGroup: string | null;
    setExpandedPlacesGroup: (v: string | null) => void;
}) {
    const superGroups = useMemo(() => buildPlacesSuperGroups(mrtGeoData, poiData), [mrtGeoData, poiData]);
    const stubOnlyFallback = stubIllustrativeRowsFromMrtGeo(mrtGeoData).length > 0;

    if (poiLoading && !poiData && !stubOnlyFallback) {
        return (
            <div className="flex items-center gap-2 text-slate-500 text-sm font-semibold py-4">
                <Loader2 className="w-4 h-4 animate-spin text-sky-500" />
                Loading places of interest…
            </div>
        );
    }

    if (!superGroups.length && !poiLoading) {
        return <p className="text-xs text-slate-400 font-semibold py-2">No places in range for this view.</p>;
    }

    if (!superGroups.length && poiLoading) {
        return (
            <div className="flex items-center gap-2 text-slate-500 text-sm font-semibold py-4">
                <Loader2 className="w-4 h-4 animate-spin text-sky-500" />
                Loading places of interest…
            </div>
        );
    }

    const illustrativeInView = superGroups.some((g) => g.items.some((it) => it.source === "illustrative"));

    return (
        <div className="space-y-6">
            {illustrativeInView && (
                <p className="text-[11px] text-slate-500 leading-snug flex items-start gap-2">
                    <CircleHelp className="w-3.5 h-3.5 shrink-0 mt-0.5 text-slate-400" aria-hidden />
                    <span>
                        Rows tagged <span className="font-semibold text-slate-600">Illustrative</span> are enrichment-API
                        placeholders, not the verified POI database. All other rows are from{" "}
                        <code className="text-[10px] bg-slate-100 px-1 rounded">poi_locations</code>.
                    </span>
                </p>
            )}

            {poiData ? (
                <div className="flex flex-wrap gap-4 items-stretch">
                    <div className="rounded-2xl border border-slate-200 bg-white p-5 flex-1 min-w-[200px] shadow-sm">
                        <p className="text-[10px] font-black uppercase tracking-wider text-slate-500 mb-2">Counts by browse group</p>
                        <div className="flex flex-wrap gap-2">
                            {superGroups.map((g) => {
                                const nIll = g.items.filter((it) => it.source === "illustrative").length;
                                return (
                                    <span
                                        key={g.id}
                                        className="text-[11px] font-bold bg-emerald-50 text-emerald-900 px-2.5 py-1 rounded-full border border-emerald-200/60"
                                        title={g.hint}
                                    >
                                        {g.label}: {g.items.length}
                                        {nIll > 0 ? ` (${nIll} illustrative ${nIll === 1 ? "placeholder" : "placeholders"})` : ""}
                                    </span>
                                );
                            })}
                        </div>
                        <p className="text-[11px] text-slate-400 mt-2">
                            {poiData.poi_total} verified POIs within {poiData.radius_m} m
                        </p>
                    </div>
                </div>
            ) : poiLoading ? (
                <p className="text-xs text-sky-600 font-semibold flex items-center gap-2">
                    <Loader2 className="w-4 h-4 animate-spin shrink-0" />
                    Loading verified POIs…
                </p>
            ) : null}

            <div className="space-y-2">
                <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-500">Browse by area (nearest first)</h4>
                {superGroups.map((grp) => {
                    const Icon = grp.Icon;
                    const open = expandedPlacesGroup === grp.id;
                    const illCount = grp.items.filter((it) => it.source === "illustrative").length;
                    return (
                        <div key={grp.id} className="rounded-2xl border border-slate-200/80 bg-white overflow-hidden shadow-sm">
                            <button
                                type="button"
                                onClick={() => setExpandedPlacesGroup(open ? null : grp.id)}
                                className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 transition-colors"
                            >
                                <div className="w-9 h-9 rounded-xl bg-slate-50 border border-slate-100 flex items-center justify-center shrink-0">
                                    <Icon className="w-4 h-4 text-sky-600" />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <div className="text-sm font-bold text-slate-800 truncate">{grp.label}</div>
                                        {illCount > 0 && (
                                            <span
                                                className="text-[9px] font-bold text-amber-700 bg-amber-50 border border-amber-100 px-1.5 py-0.5 rounded shrink-0 cursor-default tracking-tight"
                                                title="Illustrative rows come from the geospatial enrichment API, mixed here with verified poi_locations rows for browsing."
                                            >
                                                Illustrative ({illCount})
                                            </span>
                                        )}
                                    </div>
                                    <div className="text-[10px] font-semibold text-slate-400 leading-snug mt-0.5">{grp.hint}</div>
                                </div>
                                <span className="text-xs font-black text-sky-700 bg-sky-50 px-2 py-1 rounded-lg border border-sky-100 shrink-0">
                                    {grp.items.length}
                                </span>
                                <ChevronDown className={`w-4 h-4 text-slate-400 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
                            </button>
                            <AnimatePresence>
                                {open && (
                                    <motion.div
                                        initial={{ height: 0, opacity: 0 }}
                                        animate={{ height: "auto", opacity: 1 }}
                                        exit={{ height: 0, opacity: 0 }}
                                        className="border-t border-slate-100 bg-slate-50/50"
                                    >
                                        <ul className="max-h-56 overflow-y-auto divide-y divide-slate-100">
                                            {grp.items.map((it) => (
                                                <li
                                                    key={`${it.source}:${it.id}`}
                                                    className="px-4 py-2.5 flex items-start justify-between gap-3 text-sm"
                                                >
                                                    <div className="min-w-0">
                                                        <span className="text-slate-800 font-medium block truncate">{it.name}</span>
                                                        <span className="text-[10px] text-slate-500 font-semibold">{it.detail}</span>
                                                        {it.source === "illustrative" && (
                                                            <span className="inline-block mt-1 text-[9px] font-bold uppercase text-amber-800 bg-amber-50 border border-amber-100 px-1.5 py-0.5 rounded">
                                                                Illustrative
                                                            </span>
                                                        )}
                                                    </div>
                                                    <span className="text-emerald-700 font-mono text-xs font-bold shrink-0">{it.distance_m} m</span>
                                                </li>
                                            ))}
                                        </ul>
                                    </motion.div>
                                )}
                            </AnimatePresence>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

function UnifiedAmenitiesExplorer({
    mrtGeoData,
    poiData,
    poiLoading,
    searchRadiusM,
    onFlyToMap,
    expandedPlacesGroup,
    setExpandedPlacesGroup,
}: {
    mrtGeoData: any | null;
    poiData: NearbyPoiPayload | null;
    poiLoading: boolean;
    searchRadiusM?: number;
    onFlyToMap?: (lat: number, lng: number, mrtName: string) => void;
    expandedPlacesGroup: string | null;
    setExpandedPlacesGroup: (v: string | null) => void;
}) {
    return (
        <div className="space-y-10 relative z-10 w-full mb-2 mt-1">
            <section className="space-y-4">
                <div className="flex items-center gap-2 border-b border-slate-200 pb-2">
                    <Train className="w-4 h-4 text-emerald-600 shrink-0" />
                    <h3 className="text-xs font-black uppercase tracking-[0.2em] text-slate-700">Transport — MRT</h3>
                </div>
                {mrtGeoData?.mrt ? (
                    <TransportMrtSection
                        key={`${String(mrtGeoData.postal_code ?? "")}|${String(mrtGeoData.address ?? "")}|${
                            typeof mrtGeoData.mrt_search_radius_m === "number"
                                ? mrtGeoData.mrt_search_radius_m
                                : searchRadiusM ?? ""
                        }`}
                        data={mrtGeoData}
                        searchRadiusM={searchRadiusM}
                        onFlyToMap={onFlyToMap}
                    />
                ) : (
                    <p className="text-xs text-slate-400 font-semibold">MRT data not loaded.</p>
                )}
            </section>

            <section className="space-y-4">
                <div className="flex items-center gap-2 border-b border-slate-200 pb-2">
                    <Layers className="w-4 h-4 text-sky-600 shrink-0" />
                    <h3 className="text-xs font-black uppercase tracking-[0.2em] text-slate-700">Places — POIs</h3>
                </div>
                <PoiPlacesSection
                    mrtGeoData={mrtGeoData}
                    poiData={poiData}
                    poiLoading={poiLoading}
                    expandedPlacesGroup={expandedPlacesGroup}
                    setExpandedPlacesGroup={setExpandedPlacesGroup}
                />
            </section>
        </div>
    );
}

// Separate component for fetching data to keep the logic clean
/** Merged "Nearby Amenities" panel: MRT + illustrative POIs, unified radius control in header row. */
function NearbyAmenitiesPanel({
    postalCode,
    propertyName,
    onRadiusCircleChange,
    onMapWaypoint,
}: {
    postalCode: string;
    propertyName?: string;
    onRadiusCircleChange?: (circle: { lat: number; lng: number; radiusM: number } | null) => void;
    onMapWaypoint?: (lat: number, lng: number, mrtName: string) => void;
}) {
    const pc = (postalCode || "").trim();
    const pn = (propertyName || "").trim();
    const pcDigits = pc.replace(/\D/g, "");
    const hasFullPostal = /^\d{6}$/.test(pcDigits);
    const locationReady = hasFullPostal || pn.length >= 2;

    // MRT + illustrative amenity rows (geospatial API)
    const [mrtGeoData, setMrtGeoData] = useState<any>(null);
    const [mrtGeoLoading, setMrtGeoLoading] = useState(false);
    const [mrtGeoErr, setMrtGeoErr] = useState<string | null>(null);

    /** Numeric draft for the slider & apply logic. */
    const [radiusDraft, setRadiusDraft] = useState(1000);
    /** Free-text metres field — do not clamp on every keystroke (allows typing multi-digit values). */
    const [radiusFieldStr, setRadiusFieldStr] = useState("1000");
    const [radiusApplied, setRadiusApplied] = useState(1000);
    const [poiData, setPoiData] = useState<NearbyPoiPayload | null>(null);
    const [poiLoading, setPoiLoading] = useState(false);
    const [poiErr, setPoiErr] = useState<string | null>(null);
    const [expandedPlacesGroup, setExpandedPlacesGroup] = useState<string | null>(null);

    // Geospatial API: MRT stations within radius (ST_DWithin); same radius as POI search
    const fetchMrtGeo = useCallback(
        async (radiusM: number) => {
            if (!locationReady) return;
            setMrtGeoLoading(true);
            setMrtGeoErr(null);
            const qs = new URLSearchParams();
            if (hasFullPostal) qs.set("postal_code", pcDigits);
            if (pn.length >= 2) qs.set("property_name", pn);
            qs.set("radius_km", String(radiusM / 1000));
            try {
                const res = await fetch(`${API_BASE}/api/geospatial/amenity_score?${qs.toString()}`);
                const d = await res.json().catch(() => null);
                if (!res.ok) {
                    const detail = typeof d?.detail === "string" ? d.detail : `HTTP ${res.status}`;
                    setMrtGeoErr(`MRT data unavailable: ${detail}`);
                    setMrtGeoData(null);
                } else if (d?.no_coordinates === true) {
                    setMrtGeoErr(typeof d.message === "string" ? d.message : "Geographical Analysis Unavailable: No Lat-long");
                    setMrtGeoData(null);
                } else {
                    setMrtGeoData(d);
                }
            } catch {
                setMrtGeoErr("Failed to load MRT / geospatial data");
            } finally {
                setMrtGeoLoading(false);
            }
        },
        [locationReady, hasFullPostal, pcDigits, pn]
    );

    // Fetch POIs (depends on radiusM)
    const fetchPois = useCallback(async (radiusM: number) => {
        if (!locationReady) return;
        setPoiLoading(true);
        setPoiErr(null);
        try {
            const res = await fetch(`${API_BASE}/api/geospatial/pois_nearby`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    postal_code: hasFullPostal ? pcDigits : undefined,
                    property_name: pn.length >= 2 ? pn : undefined,
                    radius_m: radiusM,
                }),
            });
            const j = await res.json().catch(() => ({}));
            if (res.ok && (j as { no_coordinates?: boolean }).no_coordinates === true) {
                setPoiErr(typeof (j as { message?: string }).message === "string"
                    ? (j as { message: string }).message
                    : "Geographical Analysis Unavailable: No Lat-long");
                setPoiData(null);
                onRadiusCircleChange?.(null);
                return;
            }
            if (!res.ok) {
                const d = (j as { detail?: unknown }).detail;
                const msg = typeof d === "string" ? d
                    : Array.isArray(d) ? (d as { msg?: string }[]).map(x => x?.msg || "").join("; ") || res.statusText
                    : res.statusText;
                throw new Error(msg);
            }
            setPoiData(j as NearbyPoiPayload);
            const lat = Number((j as { lat?: number }).lat);
            const lng = Number((j as { lng?: number }).lng);
            if (Number.isFinite(lat) && Number.isFinite(lng)) {
                onRadiusCircleChange?.({ lat, lng, radiusM: radiusM });
            } else {
                onRadiusCircleChange?.(null);
            }
        } catch (e: unknown) {
            setPoiData(null);
            setPoiErr(e instanceof Error ? e.message : "Request failed");
            onRadiusCircleChange?.(null);
        } finally {
            setPoiLoading(false);
        }
    }, [locationReady, hasFullPostal, pcDigits, pn, onRadiusCircleChange]);

    // Re-fetch both when location changes
    useEffect(() => {
        if (!locationReady) {
            setMrtGeoData(null); setMrtGeoErr(null);
            setPoiData(null); setPoiErr(null);
            setRadiusDraft(1000); setRadiusFieldStr("1000"); setRadiusApplied(1000);
            setExpandedPlacesGroup(null);
            onRadiusCircleChange?.(null);
            return;
        }
        setRadiusDraft(1000);
        setRadiusFieldStr("1000");
        setRadiusApplied(1000);
        setExpandedPlacesGroup(null);
        void fetchMrtGeo(1000);
        void fetchPois(1000);
    }, [locationReady, pc, pn]); // eslint-disable-line react-hooks/exhaustive-deps

    const clampRadiusM = (n: number) => Math.min(10000, Math.max(50, n));

    /** Effective metres for “Apply” / slider display; uses clamped numeric from the text field. */
    const radiusFromField = () => {
        const t = radiusFieldStr.trim();
        if (t === "") return radiusDraft;
        const v = Number(t);
        return Number.isFinite(v) ? clampRadiusM(v) : radiusDraft;
    };

    const onApplyRadius = () => {
        const clamped = radiusFromField();
        setRadiusDraft(clamped);
        setRadiusFieldStr(String(clamped));
        setRadiusApplied(clamped);
        void fetchMrtGeo(clamped);
        void fetchPois(clamped);
    };

    if (!locationReady) return null;

    /** Pending if typed value would differ from last applied fetch (after 50–10000 clamp at commit time). */
    const pendingRadius = radiusFromField() !== radiusApplied;
    const anyLoading = mrtGeoLoading || poiLoading;
    const noCoordinatesEmpty =
        !anyLoading &&
        !mrtGeoData &&
        !poiData &&
        [mrtGeoErr, poiErr].some((e) => e != null && (e.includes("No Lat-long") || e.includes("Unavailable")));
    const showUnifiedSummary =
        !noCoordinatesEmpty && (mrtGeoData != null || poiData != null || mrtGeoLoading || poiLoading);

    return (
        <div className="relative z-10 w-full">
            {/* Top row: title (left) + radius control (right) */}
            <div className="flex flex-wrap items-start gap-4 mb-6">
                {/* Title block */}
                <div className="flex items-center gap-3 min-w-0 flex-1">
                    <div className="w-11 h-11 rounded-2xl bg-emerald-500/10 flex items-center justify-center shrink-0 border border-emerald-500/20">
                        <MapPinned className="w-5 h-5 text-emerald-600" />
                    </div>
                    <div className="min-w-0">
                        <div className="flex items-center gap-3 flex-wrap">
                            <h3 className="text-xl font-black text-slate-900 tracking-tight">Nearby Amenities</h3>
                            <span className="text-[10px] font-bold uppercase tracking-wide text-slate-400">
                                MRT + POIs — same radius
                            </span>
                        </div>
                        {(mrtGeoData?.address || poiData?.address) && (
                            <div className="flex items-center gap-1.5 mt-0.5">
                                <MapPin className="w-3 h-3 text-emerald-500 shrink-0" />
                                <span className="text-[11px] font-semibold text-slate-500 truncate max-w-xs">
                                    {mrtGeoData?.address || poiData?.address}
                                </span>
                            </div>
                        )}
                    </div>
                </div>

                {/* Radius control (right) */}
                <div className="shrink-0 rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-3 flex flex-wrap items-center gap-3 min-w-0 max-w-sm w-full sm:w-auto">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 shrink-0">Radius</label>
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                        <input
                            type="range"
                            min={50}
                            max={10000}
                            step={50}
                            value={Math.min(10000, Math.max(50, radiusDraft))}
                            onChange={(e) => {
                                const v = Number(e.target.value);
                                if (!Number.isFinite(v)) return;
                                setRadiusDraft(v);
                                setRadiusFieldStr(String(v));
                            }}
                            className="flex-1 h-1.5 accent-sky-600 min-w-[80px]"
                            aria-valuemin={50}
                            aria-valuemax={10000}
                        />
                        <input
                            type="text"
                            inputMode="numeric"
                            maxLength={6}
                            aria-label="Search radius in metres"
                            value={radiusFieldStr}
                            onChange={(e) => {
                                const next = e.target.value.replace(/\D/g, "");
                                setRadiusFieldStr(next);
                                if (next.trim() === "") return;
                                const v = Number(next);
                                if (Number.isFinite(v)) {
                                    setRadiusDraft(Math.min(10000, v));
                                }
                            }}
                            onBlur={() => {
                                const t = radiusFieldStr.trim();
                                if (t === "") {
                                    setRadiusFieldStr(String(radiusApplied));
                                    return;
                                }
                                const v = Number(t);
                                if (!Number.isFinite(v)) {
                                    setRadiusFieldStr(String(radiusApplied));
                                    return;
                                }
                                const c = clampRadiusM(v);
                                setRadiusDraft(c);
                                setRadiusFieldStr(String(c));
                            }}
                            className="w-20 rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm font-mono font-bold text-slate-800"
                        />
                        <span className="text-[10px] text-slate-500 shrink-0">m</span>
                    </div>
                    <button
                        type="button"
                        onClick={onApplyRadius}
                        disabled={anyLoading}
                        className="px-3 py-1.5 rounded-lg bg-sky-600 text-white text-xs font-bold shadow-sm hover:bg-sky-700 disabled:opacity-50 transition-colors shrink-0 flex items-center gap-1.5"
                    >
                        {poiLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                        {pendingRadius ? "Apply" : `${radiusApplied} m`}
                    </button>
                </div>
            </div>

            {/* Loading state */}
            {anyLoading && !mrtGeoData && !poiData && (
                <div className="w-full flex flex-col items-center justify-center min-h-[160px] gap-3">
                    <Loader2 className="w-10 h-10 text-emerald-500 animate-spin" />
                    <p className="text-xs font-bold text-slate-400 uppercase tracking-widest animate-pulse">Analyzing Proximity…</p>
                </div>
            )}

            {/* No-coordinates state */}
            {!anyLoading && noCoordinatesEmpty && (
                <div className="flex flex-col items-center justify-center text-center py-12 px-6">
                    <div className="w-16 h-16 rounded-3xl bg-amber-50 flex items-center justify-center mb-4 border border-amber-100">
                        <MapPinned className="w-8 h-8 text-amber-500" />
                    </div>
                    <h3 className="text-slate-800 font-bold mb-1">Geographical analysis unavailable</h3>
                    <p className="text-sm text-slate-600 max-w-[280px]">{mrtGeoErr || poiErr || "No coordinates for this address."}</p>
                </div>
            )}

            {!noCoordinatesEmpty && mrtGeoErr && (
                <p className="text-sm text-red-600 font-semibold mb-2">{mrtGeoErr}</p>
            )}
            {!noCoordinatesEmpty && poiErr && (
                <p className="text-sm text-red-600 font-semibold mb-2">{poiErr}</p>
            )}

            {/* No profile found */}
            {!anyLoading && !mrtGeoErr && !poiErr && !mrtGeoData && !poiData && (
                <div className="flex flex-col items-center justify-center text-center py-12 px-6">
                    <div className="w-16 h-16 rounded-3xl bg-slate-50 flex items-center justify-center mb-4 border border-slate-100">
                        <MapPinned className="w-8 h-8 text-slate-300" />
                    </div>
                    <h3 className="text-slate-800 font-bold mb-1">No Profile Found</h3>
                    <p className="text-sm text-slate-500 max-w-[240px]">We could not generate a geospatial profile for this address.</p>
                </div>
            )}

            {showUnifiedSummary && (
                <UnifiedAmenitiesPreview mrtGeoData={mrtGeoData} poiData={poiData} poiLoading={poiLoading} />
            )}

            {!noCoordinatesEmpty && (mrtGeoData || poiData) && (
                <UnifiedAmenitiesExplorer
                    mrtGeoData={mrtGeoData}
                    poiData={poiData}
                    poiLoading={poiLoading}
                    searchRadiusM={radiusApplied}
                    onFlyToMap={onMapWaypoint}
                    expandedPlacesGroup={expandedPlacesGroup}
                    setExpandedPlacesGroup={setExpandedPlacesGroup}
                />
            )}
        </div>
    );
}


const AREA_POI_TYPE_ORDER = [
    "school_top20",
    "school_any",
    "mall",
    "supermarket",
    "park",
    "market",
    "pcn",
] as const;

const AREA_POI_LABELS: Record<string, string> = {
    school_top20: "Top primary schools",
    school_any: "Primary schools",
    mall: "Shopping malls",
    supermarket: "Supermarkets",
    park: "Parks & nature",
    market: "Markets & food centres",
    pcn: "Park connectors",
};

type AreaAmenityApi = {
    area_names: string[];
    region_c: string | null;
    mrts: {
        operational: any[];
        upcoming: any[];
        unknown?: any[];
        count: number;
    };
    pois: {
        counts_by_type: Record<string, number>;
        by_type: Record<string, { id: number; name: string | null; lat: number; lon: number }[]>;
        pcn_capped: boolean;
        poi_total: number;
    };
};

/** Line-level MRT cards for area breakdown API (still one row per line). */
function AreaMrtLineCardsSection({
    title,
    items,
    groupOffset,
    expandedIndex,
    setExpandedIndex,
}: {
    title: string;
    items: any[];
    groupOffset: number;
    expandedIndex: number | null;
    setExpandedIndex: (v: number | null) => void;
}) {
    const TRAVEL_MODES = [
        { key: "walk", label: "Walk", Icon: PersonStanding, color: "text-sky-600", bg: "bg-sky-50", border: "border-sky-100" },
        { key: "drive", label: "Drive", Icon: Car, color: "text-amber-600", bg: "bg-amber-50", border: "border-amber-100" },
        { key: "pt", label: "Transit", Icon: Bus, color: "text-emerald-600", bg: "bg-emerald-50", border: "border-emerald-100" },
    ];
    if (!items?.length) return null;
    return (
        <div className="space-y-3 mb-8">
            <div className="flex items-center gap-2 border-b border-slate-100 pb-2">
                <Train className="w-3.5 h-3.5 text-emerald-500" />
                <h4 className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">{title}</h4>
                <span className="text-[9px] font-bold text-slate-500 ml-auto bg-slate-50 px-2 py-0.5 rounded-full border border-slate-100">
                    {items.length}
                </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {items.map((am: any, i: number) => {
                    const currentIndex = groupOffset + i;
                    const isExpanded = expandedIndex === currentIndex;
                    const hasTravelData = !!am.travel_times;
                    const pit = (am.pit_state || "").toUpperCase();
                    const pitColor =
                        pit === "OPERATIONAL"
                            ? "bg-emerald-500/12 text-emerald-800 border-emerald-200/60"
                            : pit === "UNKNOWN"
                              ? "bg-slate-100 text-slate-600 border-slate-200"
                              : "bg-amber-500/12 text-amber-900 border-amber-200/60";
                    return (
                        <div
                            key={am.id ?? `${am.name}-${i}`}
                            className={`flex flex-col bg-white border ${isExpanded ? "border-emerald-200 shadow-md" : "border-slate-200/60"} rounded-2xl hover:border-emerald-200 transition-all relative overflow-hidden h-fit`}
                        >
                            <button
                                type="button"
                                className="flex items-center gap-3 p-3 w-full text-left"
                                onClick={() => setExpandedIndex(isExpanded ? null : currentIndex)}
                                disabled={!hasTravelData}
                            >
                                <div className="w-9 h-9 rounded-xl bg-slate-50 flex flex-col items-center justify-center shrink-0 border border-slate-100 shadow-sm">
                                    <Train className="w-4 h-4 text-emerald-500" />
                                </div>
                                <div className="min-w-0 flex-1 leading-tight">
                                    <div className="text-[13px] font-bold text-slate-800 truncate">{am.name}</div>
                                    {am.network_line && (
                                        <div className="text-[10px] font-semibold text-slate-500 truncate">{am.network_line}</div>
                                    )}
                                    <div className={`mt-1 inline-block text-[9px] font-bold uppercase tracking-tight px-2 py-0.5 rounded-md border ${pitColor}`}>
                                        {pitStateLabel(am.pit_state)}
                                    </div>
                                    {(am.announcement_date || am.announcement_date_raw) && (
                                        <div className="text-[10px] text-slate-500 mt-1">
                                            Announced: {am.announcement_date || am.announcement_date_raw}
                                        </div>
                                    )}
                                    {(am.opening_date || am.opening_date_raw) && (
                                        <div className="text-[10px] text-slate-500 mt-1">
                                            Open: {am.opening_date || am.opening_date_raw}
                                        </div>
                                    )}
                                    {(am.expected_completion || am.expected_completion_raw) && (
                                        <div className="text-[10px] text-slate-500">
                                            Expected: {am.expected_completion || am.expected_completion_raw}
                                        </div>
                                    )}
                                    {am.source_url && (
                                        <a
                                            href={am.source_url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="text-[10px] text-accent font-bold mt-1 inline-block hover:underline"
                                            onClick={(e) => e.stopPropagation()}
                                        >
                                            Source
                                        </a>
                                    )}
                                </div>
                                <div className="flex flex-col items-end shrink-0">
                                    {am.distance_m != null && (
                                        <div className="text-[11px] font-black text-emerald-600 font-mono tracking-tighter">
                                            {am.distance_m}m
                                        </div>
                                    )}
                                    {hasTravelData && (
                                        <ChevronDown
                                            className={`w-3 h-3 text-slate-300 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                                        />
                                    )}
                                </div>
                            </button>
                            <AnimatePresence>
                                {isExpanded && hasTravelData && (
                                    <motion.div
                                        initial={{ height: 0, opacity: 0 }}
                                        animate={{ height: "auto", opacity: 1 }}
                                        exit={{ height: 0, opacity: 0 }}
                                        className="overflow-hidden border-t border-slate-100 bg-slate-50/30"
                                    >
                                        <div className="p-3 grid grid-cols-2 gap-2">
                                            {TRAVEL_MODES.map((mode) => {
                                                const tData = am.travel_times?.[mode.key];
                                                const timeVal = tData?.time_mins ?? tData?.time;
                                                return (
                                                    <div
                                                        key={mode.key}
                                                        className={`flex items-center gap-2 p-2 rounded-xl border ${mode.border} ${mode.bg} transition-all`}
                                                    >
                                                        <mode.Icon className={`w-3.5 h-3.5 ${mode.color}`} />
                                                        <div className="min-w-0">
                                                            <div className="text-[9px] font-black uppercase tracking-wider text-slate-400 leading-none mb-1">
                                                                {mode.label}
                                                            </div>
                                                            <div className={`text-[11px] font-black ${mode.color} leading-none`}>
                                                                {timeVal != null ? `${timeVal} min` : "--"}
                                                            </div>
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </motion.div>
                                )}
                            </AnimatePresence>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

/** MRT + POI amenity breakdown inside the selected URA planning-area union. */
function AreaAmenityBreakdownPanel(props: { regionCode: string | null; towns: string[] }) {
    const scopeKey = `${props.regionCode ?? ""}|${props.towns.join("|")}`;
    return <AreaAmenityBreakdownPanelInner key={scopeKey} {...props} />;
}

function AreaAmenityBreakdownPanelInner({
    regionCode,
    towns,
}: {
    regionCode: string | null;
    towns: string[];
}) {
    const [expandedMrtIndex, setExpandedMrtIndex] = useState<number | null>(null);
    const [expandedPoiType, setExpandedPoiType] = useState<string | null>(null);
    const [data, setData] = useState<AreaAmenityApi | null>(null);
    const [loading, setLoading] = useState(true);
    const [err, setErr] = useState<string | null>(null);

    useEffect(() => {
        const params = new URLSearchParams();
        if (regionCode) params.set("region_c", regionCode);
        if (towns.length) params.set("towns", towns.join(","));
        fetch(`${API_BASE}/api/geospatial/area_amenity_breakdown?${params.toString()}`)
            .then(async (res) => {
                const j = await res.json().catch(() => ({}));
                if (!res.ok) {
                    const d = (j as { detail?: unknown }).detail;
                    const msg =
                        typeof d === "string"
                            ? d
                            : Array.isArray(d)
                              ? (d as { msg?: string }[]).map((x) => x?.msg || "").join("; ") || res.statusText
                              : res.statusText;
                    throw new Error(msg);
                }
                return j as AreaAmenityApi;
            })
            .then((d) => {
                setData(d);
                setLoading(false);
            })
            .catch((e: Error) => {
                setErr(e.message || "Request failed");
                setLoading(false);
            });
    }, []); // region/towns captured at mount; parent remounts this inner panel via key when they change

    const MAX_AREA_MRT_RENDER = 180;

    if (loading) {
        return (
            <div className="w-full flex flex-col items-center justify-center min-h-[200px] gap-3">
                <Loader2 className="w-10 h-10 text-emerald-500 animate-spin" />
                <p className="text-xs font-bold text-slate-400 uppercase tracking-widest animate-pulse">
                    Loading area amenities…
                </p>
            </div>
        );
    }

    if (err) {
        return (
            <div className="flex flex-col items-center justify-center text-center py-12 px-6">
                <p className="text-sm text-red-600 font-semibold">{err}</p>
            </div>
        );
    }

    if (!data) return null;

    const mrtCount = data.mrts?.count ?? 0;
    const opRaw = data.mrts?.operational ?? [];
    const upRaw = data.mrts?.upcoming ?? [];
    const unknownRaw = data.mrts?.unknown ?? [];
    const opShow = opRaw.slice(0, MAX_AREA_MRT_RENDER);
    const rem = MAX_AREA_MRT_RENDER - opShow.length;
    const upShow = rem > 0 ? upRaw.slice(0, rem) : [];
    const unknownShow = unknownRaw.slice(0, Math.max(0, rem - upShow.length));
    const stationsTruncated = opRaw.length + upRaw.length + unknownRaw.length > MAX_AREA_MRT_RENDER;

    const poiTotal = data.pois?.poi_total ?? 0;
    const counts = data.pois?.counts_by_type ?? {};
    const byType = data.pois?.by_type ?? {};
    const pcnCapped = data.pois?.pcn_capped ?? false;

    const areaLabel =
        data.area_names?.length > 0
            ? data.area_names.join(", ")
            : data.region_c
              ? `Region ${data.region_c}`
              : "Selected area";

    const emptyMrtAndPoi = mrtCount === 0 && poiTotal === 0;

    if (emptyMrtAndPoi) {
        return (
            <div className="flex flex-col items-center justify-center text-center py-12 px-6">
                <MapPinned className="w-10 h-10 text-slate-300 mb-3" />
                <h3 className="text-slate-800 font-bold mb-1">No amenities in selection</h3>
                <p className="text-sm text-slate-500 max-w-md">
                    No MRT or POI points fall inside the union of the selected URA planning areas, or data is incomplete.
                </p>
            </div>
        );
    }

    return (
        <div className="relative z-10 w-full mb-4 mt-2 space-y-10">
            <p className="text-xs text-slate-500">
                <span className="font-semibold text-slate-600">{areaLabel}</span>
                {" — "}
                MRT lines: {mrtCount}
                {stationsTruncated ? ` (showing first ${MAX_AREA_MRT_RENDER} on map cards)` : ""}. POIs: {poiTotal}{" "}
                from <code className="text-[10px] bg-slate-100 px-1 rounded">poi_locations</code>.
            </p>

            {mrtCount > 0 && (
                <div>
                    <h3 className="text-sm font-black uppercase tracking-wider text-emerald-800 mb-3 flex items-center gap-2">
                        <Train className="w-4 h-4" /> MRT in area
                    </h3>
                    <AreaMrtLineCardsSection
                        title="Operational in area"
                        items={opShow}
                        groupOffset={100}
                        expandedIndex={expandedMrtIndex}
                        setExpandedIndex={setExpandedMrtIndex}
                    />
                    <AreaMrtLineCardsSection
                        title="Upcoming / in development in area"
                        items={upShow}
                        groupOffset={800}
                        expandedIndex={expandedMrtIndex}
                        setExpandedIndex={setExpandedMrtIndex}
                    />
                    <AreaMrtLineCardsSection
                        title="Status unavailable in area"
                        items={unknownShow}
                        groupOffset={1400}
                        expandedIndex={expandedMrtIndex}
                        setExpandedIndex={setExpandedMrtIndex}
                    />
                </div>
            )}

            {poiTotal > 0 && (
                <div>
                    <h3 className="text-sm font-black uppercase tracking-wider text-sky-800 mb-3 flex items-center gap-2">
                        <Layers className="w-4 h-4" /> Amenities in area
                    </h3>
                    <div className="space-y-2">
                        {AREA_POI_TYPE_ORDER.map((poiType) => {
                            const n = counts[poiType] ?? 0;
                            const items = byType[poiType] ?? [];
                            const Icon = poiTypeIcon(poiType);
                            const open = expandedPoiType === poiType;
                            const hideList = poiType === "pcn" && pcnCapped;
                            return (
                                <div
                                    key={poiType}
                                    className="rounded-2xl border border-slate-200/80 bg-white overflow-hidden shadow-sm"
                                >
                                    <button
                                        type="button"
                                        onClick={() => {
                                            if (hideList && n > 0) return;
                                            setExpandedPoiType(open ? null : poiType);
                                        }}
                                        className={`w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 transition-colors ${
                                            hideList && n > 0 ? "cursor-default" : ""
                                        }`}
                                    >
                                        <div className="w-9 h-9 rounded-xl bg-slate-50 border border-slate-100 flex items-center justify-center shrink-0">
                                            <Icon className="w-4 h-4 text-sky-600" />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="text-sm font-bold text-slate-800 truncate">
                                                {AREA_POI_LABELS[poiType] ?? poiType}
                                            </div>
                                            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-tight">
                                                {poiType}
                                            </div>
                                        </div>
                                        <span className="text-xs font-black text-sky-700 bg-sky-50 px-2 py-1 rounded-lg border border-sky-100">
                                            {n}
                                        </span>
                                        {!hideList || n === 0 ? (
                                            <ChevronDown
                                                className={`w-4 h-4 text-slate-400 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
                                            />
                                        ) : (
                                            <span className="text-[10px] font-bold text-amber-700 uppercase">Dense</span>
                                        )}
                                    </button>
                                    {hideList && n > 0 && (
                                        <p className="text-[11px] text-amber-800 bg-amber-50/80 px-4 py-2 border-t border-amber-100">
                                            PCN is dense ({n} points). List capped on server — count shows full coverage in
                                            polygon.
                                        </p>
                                    )}
                                    <AnimatePresence>
                                        {open && !hideList && items.length > 0 && (
                                            <motion.div
                                                initial={{ height: 0, opacity: 0 }}
                                                animate={{ height: "auto", opacity: 1 }}
                                                exit={{ height: 0, opacity: 0 }}
                                                className="border-t border-slate-100 bg-slate-50/50"
                                            >
                                                <ul className="max-h-56 overflow-y-auto divide-y divide-slate-100">
                                                    {items.map((it) => (
                                                        <li key={it.id} className="px-4 py-2.5 text-sm text-slate-800">
                                                            {it.name || "—"}
                                                        </li>
                                                    ))}
                                                </ul>
                                            </motion.div>
                                        )}
                                    </AnimatePresence>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}

export default function AnalyticsPage() {
    const { user, isPremiumExperience: isPremium } = useAuth();
    const router = useRouter();
    const [activeTab, setActiveTab] = useState<WorkspaceTab>("geospatial");
    const [isFilterPanelOpen, setIsFilterPanelOpen] = useState(true);

    // Explorer state
    const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);
    const [debouncedFilters, setDebouncedFilters] = useState<FilterState>(DEFAULT_FILTERS);
    const [filterOptions, setFilterOptions] = useState<any>(null);
    const [data, setData] = useState<any>(null);
    const [isLoading, setIsLoading] = useState(false);

    const [committedAddress, setCommittedAddress] = useState<PropertySearchHit | null>(null);

    // Debounce filter changes
    useEffect(() => {
        const timer = setTimeout(() => {
            setDebouncedFilters(filters);
        }, 500); // 500ms delay to prevent API spam while typing or clicking
        return () => clearTimeout(timer);
    }, [filters]);

    // AI Insight
    const [insight, setInsight] = useState<string | null>(null);
    const [insightSource, setInsightSource] = useState<string>("");
    const [isInsightLoading, setIsInsightLoading] = useState(false);

    // Save Report modal
    const [showSaveModal, setShowSaveModal] = useState(false);
    const [reportTitle, setReportTitle] = useState("");
    const [isSaving, setIsSaving] = useState(false);

    // Geospatial state
    const [selectedUraRegion, setSelectedUraRegion] = useState<string>("All Regions (Experimental)");
    const mapRef = useRef<MapHandle>(null);
    const [mapChrome, setMapChrome] = useState<MapChromeState | null>(null);
    const [mapRadiusCircle, setMapRadiusCircle] = useState<{ lat: number; lng: number; radiusM: number } | null>(null);
    const onMapStateChange = useCallback((s: MapChromeState) => setMapChrome(s), []);

    const handlePropertyCommit = useCallback((hit: PropertySearchHit | null) => {
        setCommittedAddress(hit);
        if (hit) {
            setFilters((f) => ({
                ...f,
                property_name: hit.name,
                postal_code: hit.postal_code || "",
            }));
        } else {
            setFilters((f) => ({ ...f, property_name: "", postal_code: "" }));
            mapRef.current?.resetToDefaultView();
        }
    }, []);

    const prevPostalForMapRef = useRef<string | null>(null);
    useEffect(() => {
        const p = (debouncedFilters.postal_code || "").trim();
        const prevStored = prevPostalForMapRef.current;
        prevPostalForMapRef.current = debouncedFilters.postal_code ?? "";
        if (prevStored === null) return;
        const hadPostal = (prevStored || "").trim().length > 0;
        if (hadPostal && p.length === 0) {
            mapRef.current?.resetToDefaultView();
        }
    }, [debouncedFilters.postal_code]);

    useEffect(() => {
        fetch(`${API_BASE}/api/analytics/filters`)
            .then(r => r.json())
            .then(setFilterOptions)
            .catch(console.error);
    }, []);

    const runQuery = useCallback(async () => {
        setIsLoading(true);
        setInsight(null);
        try {
            const res = await fetch(`${API_BASE}/api/analytics/query`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    towns: debouncedFilters.towns.length ? debouncedFilters.towns : null,
                    flat_types: debouncedFilters.flat_types.length ? debouncedFilters.flat_types : null,
                    date_from: debouncedFilters.date_from || null,
                    date_to: debouncedFilters.date_to || null,
                    price_min: debouncedFilters.price_min,
                    price_max: debouncedFilters.price_max,
                    floor_levels: debouncedFilters.floor_levels.length ? debouncedFilters.floor_levels : null,
                    floor_area_min: debouncedFilters.floor_area_min,
                    floor_area_max: debouncedFilters.floor_area_max,
                    lease_remaining_min: debouncedFilters.lease_remaining_min,
                    lease_remaining_max: debouncedFilters.lease_remaining_max,
                    postal_code: debouncedFilters.postal_code || null,
                    property_name: debouncedFilters.property_name || null,
                    group_by: debouncedFilters.group_by,
                    ...(debouncedFilters.towns.length > 0 &&
                    selectedUraRegion !== "All Regions (Experimental)"
                        ? { ura_region: selectedUraRegion }
                        : {}),
                }),
            });
            if (!res.ok) {
                const errBody = await res.text().catch(() => "");
                console.error("Analytics query failed:", res.status, errBody.slice(0, 500));
                return;
            }
            setData(await res.json());
        } catch (e) {
            console.error("Query failed:", e);
        } finally {
            setIsLoading(false);
        }
    }, [debouncedFilters, selectedUraRegion]);

    useEffect(() => { runQuery(); }, [runQuery]);

    const generateInsight = async () => {
        if (!isPremium || !data) return;
        setIsInsightLoading(true);
        try {
            const token = localStorage.getItem("token");
            const res = await fetch(`${API_BASE}/api/analytics/insight`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...subscriptionAwareHeaders(token),
                },
                body: JSON.stringify({
                    filter_state: { ...filters, selected_ura_region: selectedUraRegion, active_tab: activeTab },
                    data_summary: data,
                }),
            });
            const json = await res.json();
            setInsight(json.insight);
            setInsightSource(json.source);
        } catch (e) {
            console.error("Insight generation failed:", e);
        } finally {
            setIsInsightLoading(false);
        }
    };

    const saveReport = async () => {
        if (!reportTitle.trim()) return;
        setIsSaving(true);
        const token = localStorage.getItem("token");
        const fullPageState = {
            ...filters,
            selected_ura_region: selectedUraRegion,
            active_tab: activeTab,
        };
        try {
            const res = await fetch(`${API_BASE}/api/reports`, {
                method: "POST",
                headers: { "Content-Type": "application/json", ...subscriptionAwareHeaders(token) },
                body: JSON.stringify({
                    title: reportTitle,
                    filter_state: fullPageState,
                    ai_commentary: insight,
                    chart_config: {
                        group_by: filters.group_by,
                        selected_ura_region: selectedUraRegion,
                        active_tab: activeTab,
                    },
                }),
            });
            if (res.ok) {
                setShowSaveModal(false);
                setReportTitle("");
                router.push("/reports");
            }
        } catch (e) {
            console.error("Save failed:", e);
        } finally {
            setIsSaving(false);
        }
    };

    const toggleArrayFilter = (key: "towns" | "flat_types" | "floor_levels", value: string) => {
        setFilters(prev => {
            const arr = prev[key];
            return { ...prev, [key]: arr.includes(value) ? arr.filter(v => v !== value) : [...arr, value] };
        });
    };

    const summary = data?.summary;
    const timeSeries = data?.time_series || [];
    const chatContext = data
        ? { filters: { ...filters, selected_ura_region: selectedUraRegion, active_tab: activeTab }, summary: data.summary }
        : null;

    const dataMinYm =
        typeof filterOptions?.date_range?.min === "string"
            ? filterOptions.date_range.min.slice(0, 7)
            : undefined;
    const dataMaxYm =
        typeof filterOptions?.date_range?.max === "string"
            ? filterOptions.date_range.max.slice(0, 7)
            : undefined;

    const postalMrt = debouncedFilters.postal_code?.trim() ?? "";
    const propMrt = (debouncedFilters.property_name || "").trim();
    const postalDigitsMrt = postalMrt.replace(/\D/g, "");
    const hasDeterministicPostal = /^\d{6}$/.test(postalDigitsMrt);
    const hasPropertyMrt = propMrt.length >= 2 || hasDeterministicPostal;
    const hasAreaMrt =
        selectedUraRegion !== "All Regions (Experimental)" ||
        debouncedFilters.towns.length > 0;
    const mrtExplorerMode: "property" | "area" | "none" = hasPropertyMrt
        ? "property"
        : hasAreaMrt
          ? "area"
          : "none";
    useEffect(() => {
        if (mrtExplorerMode !== "property") {
            setMapRadiusCircle(null);
        }
    }, [mrtExplorerMode]);
    const areaRegionCode =
        selectedUraRegion === "All Regions (Experimental)"
            ? null
            : URA_REGION_TO_CODE[selectedUraRegion] ?? null;

    return (
        <RequireAuth>
            <main className="min-h-screen bg-slate-50 pb-20">
                <Navbar />
                <div className="max-w-[1400px] mx-auto pt-28 px-4 sm:px-6 lg:px-8">
                    {/* Header */}
                    <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 sm:gap-6 mb-8">
                        <div className="min-w-0">
                            <h1 className="text-4xl font-black tracking-tight text-slate-900 flex items-center gap-3 flex-wrap">
                                <BarChart3 className="w-10 h-10 text-accent shrink-0" /> HomeyAI Analytics
                            </h1>
                            <p className="text-slate-500 mt-2 text-lg">
                                Comprehensive market insights, geospatial analysis, and AI chat.
                            </p>
                        </div>
                        <div className="shrink-0 sm:pt-1">
                            <button
                                type="button"
                                onClick={() => setShowSaveModal(true)}
                                className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-white text-slate-800 font-bold text-sm border border-emerald-200/80 shadow-sm hover:bg-emerald-50/80 hover:border-emerald-300 transition-all w-full sm:w-auto"
                            >
                                <Save className="w-4 h-4 text-emerald-600" /> Save Report
                            </button>
                            {!isFilterPanelOpen && (
                                <button
                                    type="button"
                                    onClick={() => setIsFilterPanelOpen(true)}
                                    className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-accent text-white font-bold text-sm shadow-lg shadow-accent/25 hover:bg-accent/90 transition-all w-full sm:w-auto mt-2 sm:mt-0 sm:ml-2"
                                >
                                    <PanelLeftOpen className="w-4 h-4" /> Show Filters
                                </button>
                            )}
                        </div>
                    </div>

                    {/* Left: filters only · Right: map + tabbed outputs */}
                    <div className="flex flex-col lg:flex-row gap-8 lg:items-start mb-10">
                        {/* LEFT: filter panel */}
                        <AnimatePresence mode="popLayout">
                            {isFilterPanelOpen && (
                                <motion.aside
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    exit={{ opacity: 0 }}
                                    className="w-full lg:w-80 shrink-0"
                                >
                                    <div className="glass rounded-3xl p-6 shadow-xl border border-white/20 flex flex-col">
                                        <div className="flex justify-between items-center mb-6 flex-shrink-0">
                                            <h3 className="font-bold flex items-center gap-2 text-slate-900 border-l-4 border-accent pl-3">
                                                Filters
                                            </h3>
                                            <div className="flex items-center gap-2">
                                                <button
                                                    type="button"
                                                    onClick={() => {
                                                        setFilters(DEFAULT_FILTERS);
                                                        setSelectedUraRegion("All Regions (Experimental)");
                                                        setCommittedAddress(null);
                                                        mapRef.current?.resetToDefaultView();
                                                    }}
                                                    className="text-xs font-bold text-slate-400 hover:text-accent transition-colors px-2 py-1"
                                                >
                                                    Reset
                                                </button>
                                                <button
                                                    onClick={() => setIsFilterPanelOpen(false)}
                                                    className="w-8 h-8 rounded-lg bg-slate-100 flex items-center justify-center text-slate-500 hover:bg-slate-200 hover:text-slate-900 transition-all shadow-sm"
                                                    title="Hide Panel"
                                                >
                                                    <PanelLeftClose className="w-4 h-4" />
                                                </button>
                                            </div>
                                        </div>
                                        <div className="space-y-6">
                                            <div>
                                                <label className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-2">
                                                    URA Planning Region
                                                    <span className="text-[9px] bg-accent/10 text-accent px-1.5 py-0.5 rounded-md font-bold">New</span>
                                                </label>
                                                <p className="text-[10px] text-slate-400 mb-2 leading-tight">Filter data and map by Master Plan 2019 boundaries.</p>
                                                <div className="relative">
                                                    <select
                                                        className="w-full px-3 py-2.5 rounded-xl border border-slate-200 bg-white text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-secondary/50 transition-all text-slate-700"
                                                        value={selectedUraRegion}
                                                        onChange={e => {
                                                            setSelectedUraRegion(e.target.value);
                                                            setFilters(prev => ({ ...prev, towns: [] }));
                                                        }}
                                                    >
                                                        <option value="All Regions (Experimental)">All Regions</option>
                                                        <option value="Central Region">Central Region</option>
                                                        <option value="East Region">East Region</option>
                                                        <option value="North Region">North Region</option>
                                                        <option value="North-East Region">North-East Region</option>
                                                        <option value="West Region">West Region</option>
                                                    </select>
                                                </div>
                                            </div>

                                            <div>
                                                <label className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-2">
                                                    Towns
                                                </label>
                                                {selectedUraRegion === "Central Region" && (
                                                    <p className="text-[10px] text-amber-500 mb-2 leading-tight font-semibold">
                                                        {`Note: Due to data grouping, resale constraints only offer a consolidated 'CENTRAL AREA' matching multiple downtown planning zones.`}
                                                    </p>
                                                )}
                                                <div className="flex flex-wrap gap-2 p-1 max-h-48 overflow-y-auto beautiful-scrollbar">
                                                    {(() => {
                                                        const REGION_TOWNS: Record<string, string[]> = {
                                                            "All Regions (Experimental)": ["ANG MO KIO", "BEDOK", "BISHAN", "BUKIT BATOK", "BUKIT MERAH", "BUKIT PANJANG", "BUKIT TIMAH", "CENTRAL AREA", "CHOA CHU KANG", "CLEMENTI", "GEYLANG", "HOUGANG", "JURONG EAST", "JURONG WEST", "KALLANG/WHAMPOA", "MARINE PARADE", "PASIR RIS", "PUNGGOL", "QUEENSTOWN", "SEMBAWANG", "SENGKANG", "SERANGOON", "TAMPINES", "TOA PAYOH", "WOODLANDS", "YISHUN"],
                                                            "Central Region": ["BISHAN", "BUKIT MERAH", "BUKIT TIMAH", "CENTRAL AREA", "GEYLANG", "KALLANG/WHAMPOA", "MARINE PARADE", "QUEENSTOWN", "TOA PAYOH"],
                                                            "East Region": ["BEDOK", "PASIR RIS", "TAMPINES"],
                                                            "North Region": ["SEMBAWANG", "WOODLANDS", "YISHUN"],
                                                            "North-East Region": ["ANG MO KIO", "HOUGANG", "PUNGGOL", "SENGKANG", "SERANGOON"],
                                                            "West Region": ["BUKIT BATOK", "BUKIT PANJANG", "CHOA CHU KANG", "CLEMENTI", "JURONG EAST", "JURONG WEST"],
                                                        };
                                                        const displayedTowns = REGION_TOWNS[selectedUraRegion] || REGION_TOWNS["All Regions (Experimental)"];
                                                        return displayedTowns.map((town: string) => (
                                                            <button
                                                                key={town}
                                                                onClick={() => toggleArrayFilter("towns", town)}
                                                                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${filters.towns.includes(town)
                                                                    ? "bg-accent text-white shadow-md shadow-accent/20"
                                                                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                                                                    }`}
                                                            >
                                                                {town}
                                                            </button>
                                                        ));
                                                    })()}
                                                </div>
                                            </div>

                                            <div>
                                                <label className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-3 block">Flat Type</label>
                                                <div className="flex flex-wrap gap-2">
                                                    {filterOptions?.flat_types.map((type: string) => (
                                                        <button
                                                                key={type}
                                                                onClick={() => toggleArrayFilter("flat_types", type)}
                                                                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${filters.flat_types.includes(type)
                                                                ? "bg-accent text-white shadow-md shadow-accent/20"
                                                                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                                                                }`}
                                                        >
                                                            {type}
                                                        </button>
                                                    ))}
                                                </div>
                                            </div>

                                            <div>
                                                <label className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 block">Floor Area (sqm)</label>
                                                <div className="flex gap-2">
                                                    <input
                                                        type="number"
                                                        placeholder="Min"
                                                        value={filters.floor_area_min || ''}
                                                        onChange={e => setFilters(f => ({ ...f, floor_area_min: e.target.value ? Number(e.target.value) : null }))}
                                                        className="w-full bg-white rounded-xl px-3 py-2.5 text-sm text-slate-700 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-secondary/50 transition-all"
                                                    />
                                                    <input
                                                        type="number"
                                                        placeholder="Max"
                                                        value={filters.floor_area_max || ''}
                                                        onChange={e => setFilters(f => ({ ...f, floor_area_max: e.target.value ? Number(e.target.value) : null }))}
                                                        className="w-full bg-white rounded-xl px-3 py-2.5 text-sm text-slate-700 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-secondary/50 transition-all"
                                                    />
                                                </div>
                                            </div>

                                            <div>
                                                <label className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 block">Lease Remaining (Yrs)</label>
                                                <div className="flex gap-2">
                                                    <input
                                                        type="number"
                                                        placeholder="Min"
                                                        value={filters.lease_remaining_min || ''}
                                                        onChange={e => setFilters(f => ({ ...f, lease_remaining_min: e.target.value ? Number(e.target.value) : null }))}
                                                        className="w-full bg-white rounded-xl px-3 py-2.5 text-sm text-slate-700 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-secondary/50 transition-all"
                                                    />
                                                    <input
                                                        type="number"
                                                        placeholder="Max"
                                                        value={filters.lease_remaining_max || ''}
                                                        onChange={e => setFilters(f => ({ ...f, lease_remaining_max: e.target.value ? Number(e.target.value) : null }))}
                                                        className="w-full bg-white rounded-xl px-3 py-2.5 text-sm text-slate-700 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-secondary/50 transition-all"
                                                    />
                                                </div>
                                            </div>


                                            <div>
                                                <label className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-3 block">Floor Level</label>
                                                <div className="grid grid-cols-2 gap-2">
                                                    {FLOOR_LEVELS.map(level => (
                                                        <button
                                                            key={level}
                                                            onClick={() => toggleArrayFilter("floor_levels", level)}
                                                            className={`px-3 py-2 rounded-xl text-xs font-semibold transition-all border ${filters.floor_levels.includes(level)
                                                                ? "bg-secondary/10 border-secondary text-secondary shadow-sm"
                                                                : "bg-white/50 border-slate-200 text-slate-600 hover:bg-slate-50"
                                                                }`}
                                                        >
                                                            {level}
                                                        </button>
                                                    ))}
                                                </div>
                                            </div>

                                            <div>
                                                <label className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 block">Floor Area (sqm)</label>
                                                <div className="flex gap-2">
                                                    <input
                                                        type="number"
                                                        placeholder="Min"
                                                        value={filters.floor_area_min || ''}
                                                        onChange={e => setFilters(f => ({ ...f, floor_area_min: e.target.value ? Number(e.target.value) : null }))}
                                                        className="w-full bg-white rounded-xl px-3 py-2.5 text-sm text-slate-700 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-secondary/50 transition-all"
                                                    />
                                                    <input
                                                        type="number"
                                                        placeholder="Max"
                                                        value={filters.floor_area_max || ''}
                                                        onChange={e => setFilters(f => ({ ...f, floor_area_max: e.target.value ? Number(e.target.value) : null }))}
                                                        className="w-full bg-white rounded-xl px-3 py-2.5 text-sm text-slate-700 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-secondary/50 transition-all"
                                                    />
                                                </div>
                                            </div>

                                            <div>
                                                <label className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 block">Lease Remaining (Yrs)</label>
                                                <div className="flex gap-2">
                                                    <input
                                                        type="number"
                                                        placeholder="Min"
                                                        value={filters.lease_remaining_min || ''}
                                                        onChange={e => setFilters(f => ({ ...f, lease_remaining_min: e.target.value ? Number(e.target.value) : null }))}
                                                        className="w-full bg-white rounded-xl px-3 py-2.5 text-sm text-slate-700 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-secondary/50 transition-all"
                                                    />
                                                    <input
                                                        type="number"
                                                        placeholder="Max"
                                                        value={filters.lease_remaining_max || ''}
                                                        onChange={e => setFilters(f => ({ ...f, lease_remaining_max: e.target.value ? Number(e.target.value) : null }))}
                                                        className="w-full bg-white rounded-xl px-3 py-2.5 text-sm text-slate-700 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-secondary/50 transition-all"
                                                    />
                                                </div>
                                            </div>


                                            <div>
                                                <label className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 block">
                                                    Time period
                                                </label>
                                                <p className="text-[10px] text-slate-400 mb-3 leading-snug">
                                                    Type a month or use the calendar on the right. Press Enter or leave the field to apply.
                                                </p>
                                                <AnalyticsDateRange
                                                    dateFrom={filters.date_from}
                                                    dateTo={filters.date_to}
                                                    minYm={dataMinYm}
                                                    maxYm={dataMaxYm}
                                                    onDatesChange={({ date_from, date_to }) =>
                                                        setFilters((prev) => ({ ...prev, date_from, date_to }))
                                                    }
                                                />
                                            </div>
                                        </div>
                                    </div>
                                </motion.aside>
                            )}
                        </AnimatePresence>

                        {/* RIGHT: map + tabs + outputs */}
                        <div className="flex-1 min-w-0 flex flex-col gap-6">
                            <div className="w-full relative z-[10050] isolate">
                                <label className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 block">
                                    Property Search
                                </label>
                                <PropertySearchInput
                                    mode="commit"
                                    commit={committedAddress}
                                    onCommitChange={handlePropertyCommit}
                                    className="w-full"
                                    inputClassName="bg-white text-sm text-slate-700 border-slate-200 font-semibold"
                                />
                            </div>

                            <div className="glass rounded-3xl p-5 shadow-lg border border-accent/20 flex flex-col min-h-[490px] sm:min-h-[345px] h-[min(55.2vh,575px)] lg:h-[min(52.9vh,598px)] relative z-0">
                                <div className="mb-3 shrink-0 space-y-2">
                                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 w-full">
                                        <h3 className="font-bold text-sm tracking-wide text-accent flex items-center gap-2">
                                            <MapPinned className="w-4 h-4 shrink-0" aria-hidden />
                                            <span>HomeyGeo</span>
                                        </h3>
                                        {mapChrome && mapChrome.overlays.length > 0 && (
                                            <div
                                                className="flex flex-wrap items-center gap-1.5"
                                                role="list"
                                                aria-label="Active map overlays"
                                            >
                                                {mapChrome.overlays.map((o) => (
                                                    <button
                                                        key={o.id}
                                                        type="button"
                                                        role="listitem"
                                                        onClick={() => mapRef.current?.dismissOverlay(o.id)}
                                                        className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide transition-colors ${OVERLAY_TAG_CLASS[o.id]}`}
                                                        aria-label={`Turn off ${o.label}`}
                                                    >
                                                        {o.label}
                                                        <X className="w-3 h-3 shrink-0 opacity-80" strokeWidth={2.5} aria-hidden />
                                                    </button>
                                                ))}
                                            </div>
                                        )}
                                        <div className="flex-1" />
                                        {mapChrome && (
                                            <div className="flex flex-wrap items-center justify-end gap-1.5">
                                                {([
                                                    { id: "hdb_footprints", label: "HDB Footprints" },
                                                    { id: "mrt_exits", label: "MRT Stations" },
                                                    { id: "ura_boundaries", label: "URA Boundaries" }
                                                ] as const).filter(o => !mapChrome.overlays.some(act => act.id === o.id)).map(o => (
                                                    <button
                                                        key={o.id}
                                                        type="button"
                                                        onClick={() => mapRef.current?.toggleOverlay(o.id)}
                                                        className="inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-white px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-slate-500 hover:bg-slate-50 transition-colors shadow-sm"
                                                    >
                                                        <Plus className="w-3 h-3 shrink-0" strokeWidth={2.5} />
                                                        {o.label}
                                                    </button>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                </div>
                                <div className="flex-1 min-h-0 min-w-0 rounded-xl flex flex-col lg:flex-row gap-4 relative">
                                    <div className="flex-1 min-h-[300px] min-w-0 rounded-xl overflow-hidden shadow-inner border border-white/20 glass">
                                        <Map
                                            ref={mapRef}
                                            onMapStateChange={onMapStateChange}
                                            selectedUraRegion={selectedUraRegion}
                                            selectedTowns={debouncedFilters.towns}
                                            postalCode={debouncedFilters.postal_code || undefined}
                                            selectedPropertyLabel={debouncedFilters.property_name || undefined}
                                            radiusCircle={mapRadiusCircle}
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                                <div className="flex bg-slate-200/50 p-1.5 rounded-2xl border border-slate-300/30 w-full lg:w-auto overflow-x-auto">
                                    {(["geospatial", "resale", "sentiment", "chat"] as const).map((tab) => {
                                        const locked = !isPremium && (tab === "sentiment" || tab === "chat");
                                        const tabLabel =
                                            tab === "geospatial"
                                                ? "Geospatial"
                                                : tab === "resale"
                                                  ? "Resale Transactions"
                                                  : tab === "sentiment"
                                                    ? "Market Sentiment"
                                                    : "AI Chat";
                                        return (
                                            <button
                                                key={tab}
                                                type="button"
                                                onClick={() => setActiveTab(tab)}
                                                aria-label={
                                                    locked ? `${tabLabel} (Premium — view upgrade options)` : undefined
                                                }
                                                className={`relative px-4 sm:px-6 py-2.5 rounded-xl text-sm font-bold transition-all duration-300 shrink-0 ${activeTab === tab
                                                    ? "text-slate-900 shadow-sm"
                                                    : "text-slate-500 hover:text-slate-700"
                                                    }`}
                                            >
                                                {activeTab === tab && (
                                                    <motion.div layoutId="activeTab" className="absolute inset-0 bg-white rounded-xl shadow-sm border border-slate-200/50" />
                                                )}
                                                <span className="relative z-10 flex items-center gap-2 font-bold whitespace-nowrap">
                                                    {tab === "geospatial" && (
                                                        <>
                                                            <MapPinned className="w-4 h-4 shrink-0" aria-hidden />
                                                            Geospatial
                                                        </>
                                                    )}
                                                    {tab === "resale" && (
                                                        <>
                                                            <BarChart3 className="w-4 h-4 shrink-0" aria-hidden />
                                                            Resale Transactions
                                                        </>
                                                    )}
                                                    {tab === "sentiment" && (
                                                        <>
                                                            <TrendingUp className="w-4 h-4 shrink-0" aria-hidden />
                                                            Market Sentiment
                                                            {locked && (
                                                                <Lock
                                                                    className="w-3.5 h-3.5 shrink-0 text-amber-600 drop-shadow-[0_0_6px_rgba(245,158,11,0.35)]"
                                                                    aria-hidden
                                                                />
                                                            )}
                                                        </>
                                                    )}
                                                    {tab === "chat" && (
                                                        <>
                                                            <MessageSquare className="w-4 h-4 shrink-0" aria-hidden />
                                                            AI Chat
                                                            {locked && (
                                                                <Lock
                                                                    className="w-3.5 h-3.5 shrink-0 text-amber-600 drop-shadow-[0_0_6px_rgba(245,158,11,0.35)]"
                                                                    aria-hidden
                                                                />
                                                            )}
                                                        </>
                                                    )}
                                                </span>
                                            </button>
                                        );
                                    })}
                                </div>
                                <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                                    {isLoading && (
                                        <span className="text-xs font-bold text-accent animate-pulse flex items-center gap-1 shrink-0 mr-auto lg:mr-0">
                                            <Loader2 className="w-3 h-3 animate-spin" /> Loading market data…
                                        </span>
                                    )}
                                    <button
                                        type="button"
                                        onClick={generateInsight}
                                        disabled={isInsightLoading || !data || !isPremium}
                                        title={!isPremium ? "Premium subscription required" : undefined}
                                        className="px-4 py-2 rounded-xl bg-gradient-to-r from-accent/10 to-transparent text-accent font-bold text-sm border border-accent/20 hover:bg-accent/20 transition-all flex items-center gap-2 disabled:opacity-50"
                                    >
                                        {isInsightLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                                        Generate AI Insight
                                        {!isPremium && <Lock className="w-3.5 h-3.5 opacity-60" aria-hidden />}
                                    </button>
                                </div>
                            </div>

                            <div className="w-full min-h-0 flex-1">
                                <AnimatePresence mode="wait">
                                    {activeTab === "geospatial" && (
                                        <motion.div
                                            key="geospatial"
                                            initial={{ opacity: 0, x: 20 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            exit={{ opacity: 0, x: -20 }}
                                            className="space-y-8"
                                        >
                                            {/* Nearby Amenities (address) / Area amenities */}
                                            {mrtExplorerMode !== "none" && (
                                                <div className="mb-8 p-6 glass rounded-3xl border border-emerald-500/20 shadow-lg animate-in fade-in slide-in-from-bottom-4">
                                                    {mrtExplorerMode === "property" ? (
                                                        <NearbyAmenitiesPanel
                                                            postalCode={postalMrt}
                                                            propertyName={propMrt}
                                                            onRadiusCircleChange={setMapRadiusCircle}
                                                            onMapWaypoint={(la, ln, name) => {
                                                                mapRef.current?.flyToWaypoint(la, ln, name);
                                                            }}
                                                        />
                                                    ) : (
                                                        <AreaAmenityBreakdownPanel
                                                            regionCode={areaRegionCode}
                                                            towns={debouncedFilters.towns}
                                                        />
                                                    )}
                                                </div>
                                            )}
                                            {mrtExplorerMode === "none" && (
                                                <div className="glass rounded-3xl border border-slate-200/80 p-8 text-center text-slate-500 text-sm font-semibold">
                                                    Select a full postal code or property name, or choose towns / a URA region to see geospatial amenities.
                                                </div>
                                            )}
                                        </motion.div>
                                    )}

                                    {activeTab === "resale" && (
                                        <motion.div
                                            key="resale"
                                            initial={{ opacity: 0, x: 20 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            exit={{ opacity: 0, x: -20 }}
                                            className="space-y-8"
                                        >
                                            <div className="flex items-center gap-4 pt-4 mb-2">
                                                <div className="h-0.5 max-w-[40px] w-full bg-accent/50 rounded-full flex-shrink-0" />
                                                <h2 className="text-3xl font-black text-slate-900 tracking-tigher whitespace-nowrap">Historical Resale Data</h2>
                                                <div className="h-0.5 w-full bg-slate-200/80 rounded-full" />
                                            </div>

                                            {/* Data Summary Stats */}
                                            {summary && (
                                                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                                                    <div className="glass rounded-2xl p-5 border border-white/20">
                                                        <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Total Transactions</p>
                                                        <p className="text-3xl font-black text-slate-800">{summary.total?.toLocaleString() ?? 0}</p>
                                                    </div>
                                                    <div className="glass rounded-2xl p-5 border border-white/20 relative overflow-hidden">
                                                        <div className="absolute -right-4 -bottom-4 bg-accent/10 w-20 h-20 rounded-full blur-2xl" />
                                                        <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Avg Price</p>
                                                        <p className="text-3xl font-black text-accent">S${summary.avg_price?.toLocaleString() ?? 0}</p>
                                                    </div>
                                                    <div className="glass rounded-2xl p-5 border border-white/20 relative overflow-hidden">
                                                        <div className="absolute -right-4 -bottom-4 bg-secondary/10 w-20 h-20 rounded-full blur-2xl" />
                                                        <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Avg PSF</p>
                                                        <p className="text-3xl font-black text-secondary">S${summary.avg_psf?.toLocaleString() ?? 0}</p>
                                                    </div>
                                                    <div className="glass rounded-2xl p-5 border border-white/20">
                                                        <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">Regions Covered</p>
                                                        <p className="text-3xl font-black text-slate-800">{summary.towns_count ?? 0}</p>
                                                    </div>
                                                </div>
                                            )}

                                            {/* Charts Area */}
                                            {data && (
                                                <div className="space-y-6">
                                                    <div
                                                        className={`glass rounded-3xl p-6 shadow-xl border border-white/20 flex flex-col ${timeSeries.length > 0
                                                            ? "min-h-[22rem] h-[min(28rem,55vh)] max-h-[32rem]"
                                                            : "min-h-0"
                                                            }`}
                                                    >
                                                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between shrink-0 mb-2">
                                                            <h3 className="font-bold text-lg">Price Trend Analysis</h3>
                                                            <div className="flex flex-wrap items-center gap-2">
                                                                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                                                                    View by
                                                                </span>
                                                                <div
                                                                    className="inline-flex rounded-xl border border-slate-200/90 bg-slate-100/90 p-0.5 shadow-inner"
                                                                    role="group"
                                                                    aria-label="Chart period"
                                                                >
                                                                    {CHART_PERIOD_OPTIONS.map(({ value, label }) => (
                                                                        <button
                                                                            key={value}
                                                                            type="button"
                                                                            onClick={() =>
                                                                                setFilters((prev) => ({ ...prev, group_by: value }))
                                                                            }
                                                                            className={`px-3 sm:px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all ${filters.group_by === value
                                                                                ? "bg-white text-slate-900 shadow-sm border border-slate-200/60"
                                                                                : "text-slate-500 hover:text-slate-800"
                                                                                }`}
                                                                        >
                                                                            {label}
                                                                        </button>
                                                                    ))}
                                                                </div>
                                                            </div>
                                                        </div>
                                                        {timeSeries.length > 0 ? (
                                                            <div className="relative w-full min-h-[240px] flex-1 min-w-0">
                                                                <ResponsiveContainer width="100%" height="100%">
                                                                    <LineChart
                                                                        data={timeSeries}
                                                                        margin={{
                                                                            top: 8,
                                                                            right: 8,
                                                                            left: 4,
                                                                            bottom: timeSeries.length > 8 ? 56 : 28,
                                                                        }}
                                                                    >
                                                                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                                                                        <XAxis
                                                                            dataKey="period"
                                                                            tick={{
                                                                                fill: "#64748b",
                                                                                fontSize: 11,
                                                                                ...(timeSeries.length > 8 ? { dy: 6 } : {}),
                                                                            }}
                                                                            axisLine={false}
                                                                            tickLine={false}
                                                                            angle={timeSeries.length > 8 ? -32 : 0}
                                                                            textAnchor={timeSeries.length > 8 ? "end" : "middle"}
                                                                            interval="preserveStartEnd"
                                                                            minTickGap={12}
                                                                        />
                                                                        <YAxis
                                                                            yAxisId="left"
                                                                            width={48}
                                                                            tick={{ fill: "#0ea5e9", fontSize: 11 }}
                                                                            axisLine={false}
                                                                            tickLine={false}
                                                                            tickFormatter={(v) => `S$${v / 1000}k`}
                                                                        />
                                                                        <YAxis
                                                                            yAxisId="right"
                                                                            orientation="right"
                                                                            width={44}
                                                                            tick={{ fill: "#8b5cf6", fontSize: 11 }}
                                                                            axisLine={false}
                                                                            tickLine={false}
                                                                        />
                                                                        <Tooltip
                                                                            formatter={(v: any, n: any) => [
                                                                                n === "avg_price" ? `S$${Number(v).toLocaleString()}` : v,
                                                                                n === "avg_price" ? "Avg Price" : "Avg PSF",
                                                                            ]}
                                                                        />
                                                                        <Line yAxisId="left" type="monotone" dataKey="avg_price" stroke="#0ea5e9" strokeWidth={3} dot={{ r: 3 }} />
                                                                        <Line yAxisId="right" type="monotone" dataKey="avg_psf" stroke="#8b5cf6" strokeWidth={3} dot={{ r: 3 }} />
                                                                    </LineChart>
                                                                </ResponsiveContainer>
                                                            </div>
                                                        ) : (
                                                            <p className="text-sm text-slate-500 py-10 text-center">
                                                                No time buckets for this period and filters. Widen the date range or choose Year / Quarter.
                                                            </p>
                                                        )}
                                                    </div>

                                                    {/* Raw Resale Data Table */}
                                                    <div className="glass rounded-3xl p-6 shadow-xl border border-white/20 mt-4 flex flex-col h-[400px]">
                                                        <h3 className="font-bold text-lg mb-4 shrink-0 flex items-center gap-2">
                                                            Raw Transactions
                                                            <span className="text-xs font-semibold text-slate-400 bg-white px-2 py-0.5 rounded-full border border-slate-200">Latest 100</span>
                                                        </h3>
                                                        <div className="overflow-auto relative beautiful-scrollbar rounded-xl border border-slate-200/60 bg-white/40">
                                                            <table className="w-full text-left text-sm">
                                                                <thead className="sticky top-0 bg-white/95 backdrop-blur-md shadow-[0_1px_0_rgba(200,200,200,0.5)] z-10 text-slate-500 font-bold uppercase text-[10px] tracking-wider">
                                                                    <tr>
                                                                        <th className="py-3 px-4 rounded-tl-xl whitespace-nowrap">Month</th>
                                                                        <th className="py-3 px-4 whitespace-nowrap min-w-[200px]">Blk · Street</th>
                                                                        <th className="py-3 px-4 whitespace-nowrap">Town</th>
                                                                        <th className="py-3 px-4 whitespace-nowrap">Type</th>
                                                                        <th className="py-3 px-4 whitespace-nowrap">Storey</th>
                                                                        <th className="py-3 px-4 whitespace-nowrap text-right">Size</th>
                                                                        <th className="py-3 px-4 rounded-tr-xl whitespace-nowrap text-right">Price</th>
                                                                    </tr>
                                                                </thead>
                                                                <tbody className="divide-y divide-slate-100/80">
                                                                    {data.raw_data && data.raw_data.map((row: any, i: number) => (
                                                                        <tr key={i} className="hover:bg-slate-50 transition-colors">
                                                                            <td className="py-3 px-4 whitespace-nowrap text-xs text-slate-500">{row.month}</td>
                                                                            <td className="py-3 px-4">
                                                                                <div className="font-bold text-slate-700 text-xs">{row.block} {row.street_name}</div>
                                                                                <div className="text-[10px] text-slate-400 uppercase tracking-wide">Postal: {row.postal_code || 'N/A'}</div>
                                                                            </td>
                                                                            <td className="py-3 px-4 text-xs font-semibold text-slate-600">{row.town}</td>
                                                                            <td className="py-3 px-4 text-xs text-slate-500">{row.flat_type}</td>
                                                                            <td className="py-3 px-4 text-xs text-slate-500 whitespace-nowrap">{row.storey_range}</td>
                                                                            <td className="py-3 px-4 text-xs text-slate-500 text-right whitespace-nowrap">{row.floor_area_sqm} <span className="text-[10px]">sqm</span></td>
                                                                            <td className="py-3 px-4 font-black text-accent text-right whitespace-nowrap">S${row.resale_price.toLocaleString()}</td>
                                                                        </tr>
                                                                    ))}
                                                                    {(!data.raw_data || data.raw_data.length === 0) && (
                                                                        <tr>
                                                                            <td colSpan={7} className="py-12 text-center text-slate-400 text-sm font-semibold">No transactions found for the current filters.</td>
                                                                        </tr>
                                                                    )}
                                                                </tbody>
                                                            </table>
                                                        </div>
                                                    </div>
                                                </div>
                                            )}
                                        </motion.div>
                                    )}

                                    {activeTab === "sentiment" && (
                                        <motion.div
                                            key="sentiment"
                                            initial={{ opacity: 0, x: 20 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            exit={{ opacity: 0, x: -20 }}
                                        >
                                            {isPremium ? (
                                                <MarketSentimentPanel variant="embedded" />
                                            ) : (
                                                <AnalyticsPremiumFeatureGate
                                                    title="Market Sentiment"
                                                    subtitle="Read the market beyond the numbers"
                                                    body="Premium unlocks sentiment dashboards, news context, and narrative signals around HDB resale—so you can see how the market feels before you buy or sell, not just where prices moved."
                                                    icon={TrendingUp}
                                                />
                                            )}
                                        </motion.div>
                                    )}
                                    {activeTab === "chat" && (
                                        <motion.div
                                            key="chat"
                                            initial={{ opacity: 0, x: 20 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            exit={{ opacity: 0, x: -20 }}
                                        >
                                            {isPremium ? (
                                                <ChatDrawer open={true} onClose={() => { }} analyticsContext={chatContext} inline={true} />
                                            ) : (
                                                <AnalyticsPremiumFeatureGate
                                                    title="AI Chat"
                                                    subtitle="Your analyst inside the workspace"
                                                    body="Premium includes conversational AI that respects your filters and live analytics—ask in plain language, get cited trends, and request charts without leaving this page."
                                                    icon={MessageSquare}
                                                />
                                            )}
                                        </motion.div>
                                    )}
                                </AnimatePresence>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Save Report Modal */}
                {showSaveModal && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
                        <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="glass rounded-3xl p-8 shadow-2xl max-w-md w-full mx-4 border border-emerald-200/40">
                            <div className="flex items-center gap-2 mb-4">
                                <div className="p-2 rounded-xl bg-emerald-100 border border-emerald-200/60">
                                    <Save className="w-5 h-5 text-emerald-700" />
                                </div>
                                <h2 className="text-xl font-bold">Save as Report</h2>
                            </div>
                            <input
                                type="text"
                                placeholder="Report title..."
                                value={reportTitle}
                                onChange={e => setReportTitle(e.target.value)}
                                className="w-full px-4 py-3 rounded-xl border border-slate-200/90 bg-white/70 text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-400/50"
                                autoFocus
                            />
                            <div className="flex gap-3">
                                <button
                                    type="button"
                                    onClick={() => setShowSaveModal(false)}
                                    className="flex-1 py-2.5 rounded-xl text-sm font-bold border border-slate-200 text-slate-700 hover:bg-slate-50 transition-all"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="button"
                                    onClick={saveReport}
                                    disabled={!reportTitle.trim() || isSaving}
                                    className="flex-1 py-2.5 rounded-xl text-sm font-bold bg-emerald-600 text-white hover:bg-emerald-700 shadow-md shadow-emerald-600/20 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
                                >
                                    {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                                    Save
                                </button>
                            </div>
                        </motion.div>
                    </div>
                )}
            </main>
        </RequireAuth>
    );
}
