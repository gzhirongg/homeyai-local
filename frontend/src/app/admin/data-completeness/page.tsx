"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import { ArrowLeft, ClipboardList, Database, Loader2, RefreshCw } from "lucide-react";
import API_BASE from "@/lib/apiBase";

type CompletenessResponse = {
    computed_at: string;
    enrichment_breakdown_available: boolean;
    onemap_complete_definition: string | null;
    note: string | null;
    total_transactions: number;
    records_onemap_complete: number | null;
    unique_locations_onemap_complete: number | null;
    pct_filled_records_onemap: number | null;
    pct_filled_unique_locations_onemap: number | null;
    with_onemap: number | null;
    with_mrt_routes: number | null;
    with_hdb_building: number | null;
    with_all_three: number | null;
    pct_onemap: number | null;
    pct_mrt_routes: number | null;
    pct_hdb_building: number | null;
    pct_all_three: number | null;
    unique_locations_total: number | null;
    unique_locations_with_onemap: number | null;
    unique_locations_with_mrt_routes: number | null;
    unique_locations_with_hdb_building: number | null;
    unique_locations_with_all_three: number | null;
    gap_unique_locations_onemap: number | null;
    gap_unique_locations_mrt_routes: number | null;
    gap_unique_locations_hdb_building: number | null;
    gap_unique_locations_all_three: number | null;
    pct_unfilled_transactions_onemap: number | null;
    pct_unfilled_transactions_mrt_routes: number | null;
    pct_unfilled_transactions_hdb_building: number | null;
    pct_unfilled_transactions_all_three: number | null;
    pct_unfilled_unique_locations_onemap: number | null;
    pct_unfilled_unique_locations_mrt_routes: number | null;
    pct_unfilled_unique_locations_hdb_building: number | null;
    pct_unfilled_unique_locations_all_three: number | null;
};

function fmtPct(v: number | null | undefined): string {
    if (v === null || v === undefined) return "—";
    return `${(v * 100).toFixed(2)}%`;
}

export default function DataCompletenessPage() {
    const [data, setData] = useState<CompletenessResponse | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);

    const fetchCompleteness = useCallback(async () => {
        setLoading(true);
        setError(null);

        const token =
            typeof window !== "undefined" ? localStorage.getItem("token") : null;
        if (!token) {
            setLoading(false);
            setError("Missing auth token. Reload the page or sign in again to load completeness data.");
            return;
        }

        const timeoutMs = 120_000;
        const controller = new AbortController();
        const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
        try {
            const res = await fetch(`${API_BASE}/api/admin/hdb-enrichment-completeness`, {
                headers: { Authorization: `Bearer ${token}` },
                signal: controller.signal,
            });

            if (!res.ok) {
                const txt = await res.text();
                throw new Error(txt || `HTTP ${res.status}`);
            }

            setData(await res.json());
        } catch (e) {
            setData(null);
            if ((e instanceof Error || e instanceof DOMException) && e.name === "AbortError") {
                setError(
                    `Request timed out after ${timeoutMs / 1000}s. The completeness query scans the full resale table; try again or check database load.`,
                );
            } else {
                setError(e instanceof Error ? e.message : String(e));
            }
        } finally {
            window.clearTimeout(timeoutId);
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchCompleteness();
    }, [fetchCompleteness]);

    const total = data?.total_transactions ?? 0;

    const breakdownRows: {
        label: string;
        table: string;
        count: number | null;
        pct: number | null;
        gapUnique: number | null;
        pctUnfilledTxn: number | null;
        pctUnfilledLoc: number | null;
    }[] =
        data && data.enrichment_breakdown_available
            ? [
                  {
                      label: "MRT routing legs",
                      table: "hdb_mrt_routes",
                      count: data.with_mrt_routes,
                      pct: data.pct_mrt_routes,
                      gapUnique: data.gap_unique_locations_mrt_routes,
                      pctUnfilledTxn: data.pct_unfilled_transactions_mrt_routes,
                      pctUnfilledLoc: data.pct_unfilled_unique_locations_mrt_routes,
                  },
                  {
                      label: "HDB building footprint (postal match)",
                      table: "hdb_buildings",
                      count: data.with_hdb_building,
                      pct: data.pct_hdb_building,
                      gapUnique: data.gap_unique_locations_hdb_building,
                      pctUnfilledTxn: data.pct_unfilled_transactions_hdb_building,
                      pctUnfilledLoc: data.pct_unfilled_unique_locations_hdb_building,
                  },
                  {
                      label: "All three (ML-ready overlap)",
                      table: "onemap ∩ mrt ∩ building",
                      count: data.with_all_three,
                      pct: data.pct_all_three,
                      gapUnique: data.gap_unique_locations_all_three,
                      pctUnfilledTxn: data.pct_unfilled_transactions_all_three,
                      pctUnfilledLoc: data.pct_unfilled_unique_locations_all_three,
                  },
              ]
            : [];

    return (
        <RequireAuth role="admin">
            <main className="min-h-screen bg-slate-50 pb-20">
                <Navbar />

                <div className="max-w-5xl mx-auto pt-32 px-4 sm:px-6 lg:px-8">
                    <Link
                        href="/admin"
                        className="inline-flex items-center gap-1 text-sm text-foreground/50 hover:text-foreground mb-8 transition-colors"
                    >
                        <ArrowLeft className="w-4 h-4" /> Admin Dashboard
                    </Link>

                    <div className="mb-10">
                        <span className="text-red-500 font-bold uppercase tracking-widest text-xs">
                            System Administration
                        </span>
                        <h1 className="text-4xl font-extrabold tracking-tight mt-2 flex items-center gap-3 flex-wrap">
                            <ClipboardList className="w-9 h-9 text-accent shrink-0" />
                            HDB enrichment completeness
                        </h1>
                        <p className="text-foreground/50 mt-3 text-sm max-w-2xl">
                            OneMap-complete coverage counts rows and distinct addresses only when the linked enrichment row
                            has postal code, latitude, and longitude. Additional rows cover MRT routes and building
                            footprints (still requiring OneMap-complete linkage for consistency).{" "}
                            <span className="font-medium text-foreground/60">Unique locations</span> group resale rows by
                            normalized block and street (trimmed and uppercased): a location counts as covered if any row
                            at that address satisfies the dimension.
                        </p>
                        {data?.computed_at && (
                            <p className="text-xs text-foreground/40 mt-2">
                                Computed: {new Date(data.computed_at).toLocaleString()}
                            </p>
                        )}
                    </div>

                    <div className="flex flex-wrap gap-3 mb-8">
                        <button
                            type="button"
                            onClick={() => fetchCompleteness()}
                            disabled={loading}
                            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-accent text-white font-semibold shadow-sm hover:shadow-md transition-all disabled:opacity-50 text-sm"
                        >
                            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                            Refresh
                        </button>
                        <span className="text-xs text-foreground/45 self-center">
                            First load aggregates the full resale table; it may take tens of seconds over a remote DB.
                        </span>
                    </div>

                    {error && (
                        <div className="mb-8 rounded-2xl border border-red-200 bg-red-50 text-red-800 px-4 py-3 text-sm">
                            {error}
                        </div>
                    )}

                    <div className="glass rounded-3xl p-8 shadow-xl border border-foreground/5 mb-8">
                        <div className="flex items-start gap-3 mb-6">
                            <div className="w-11 h-11 rounded-xl bg-accent/10 flex items-center justify-center text-accent shrink-0">
                                <Database className="w-6 h-6" />
                            </div>
                            <div>
                                <h2 className="text-xl font-bold">HDB resale transactions</h2>
                                <p className="text-sm text-foreground/50 mt-0.5">Total rows in hdb_resale_transactions</p>
                            </div>
                        </div>
                        <p className="text-4xl font-black tracking-tight">
                            {loading && !data ? "—" : total.toLocaleString()}
                        </p>
                    </div>

                    {!data?.enrichment_breakdown_available && data && (
                        <div className="rounded-2xl border border-amber-200 bg-amber-50 text-amber-900 px-4 py-3 text-sm mb-8">
                            {data.note ||
                                "Enrichment breakdown is not available on this deployment (PostgreSQL / PostGIS backend required)."}
                        </div>
                    )}

                    {data?.enrichment_breakdown_available && (
                        <>
                            <div className="grid sm:grid-cols-2 gap-4 mb-6">
                                <div className="glass rounded-2xl p-6 shadow-lg border border-foreground/5">
                                    <h3 className="text-xs font-semibold uppercase tracking-wide text-foreground/45">
                                        OneMap-complete locations
                                    </h3>
                                    <p className="text-2xl font-black tabular-nums mt-2">
                                        {(data.unique_locations_onemap_complete ?? 0).toLocaleString()}
                                        <span className="text-lg font-semibold text-foreground/35 mx-1">/</span>
                                        {(data.unique_locations_total ?? 0).toLocaleString()}
                                    </p>
                                    <p className="text-sm text-accent font-semibold mt-1 tabular-nums">
                                        {fmtPct(data.pct_filled_unique_locations_onemap)} filled
                                    </p>
                                    <p className="text-xs text-foreground/45 mt-2 leading-relaxed">
                                        Distinct normalized block+street pairs with a linked enrichment row where postal
                                        code, latitude, and longitude are all present.
                                    </p>
                                </div>
                                <div className="glass rounded-2xl p-6 shadow-lg border border-foreground/5">
                                    <h3 className="text-xs font-semibold uppercase tracking-wide text-foreground/45">
                                        OneMap-complete resale rows
                                    </h3>
                                    <p className="text-2xl font-black tabular-nums mt-2">
                                        {(data.records_onemap_complete ?? 0).toLocaleString()}
                                        <span className="text-lg font-semibold text-foreground/35 mx-1">/</span>
                                        {total.toLocaleString()}
                                    </p>
                                    <p className="text-sm text-accent font-semibold mt-1 tabular-nums">
                                        {fmtPct(data.pct_filled_records_onemap)} filled
                                    </p>
                                    <p className="text-xs text-foreground/45 mt-2 leading-relaxed">
                                        Rows in <span className="font-mono">hdb_resale_transactions</span> whose{" "}
                                        <span className="font-mono">enriched_addr_id</span> resolves to complete OneMap
                                        fields above.
                                    </p>
                                </div>
                            </div>
                            {data.onemap_complete_definition && (
                                <p className="text-xs text-foreground/40 mb-6 max-w-3xl">{data.onemap_complete_definition}</p>
                            )}

                            <div className="glass rounded-3xl shadow-xl border border-foreground/5 overflow-hidden mb-8">
                                <div className="px-6 py-5 border-b border-foreground/5">
                                    <h2 className="text-lg font-bold">Further dimensions (after OneMap-complete join)</h2>
                                    <p className="text-sm text-foreground/50 mt-1">
                                        Row counts use all{" "}
                                        <span className="font-semibold text-foreground/70">{total.toLocaleString()}</span>{" "}
                                        transactions; unique-location gaps use{" "}
                                        <span className="font-semibold text-foreground/70">
                                            {(data.unique_locations_total ?? 0).toLocaleString()}
                                        </span>{" "}
                                        normalized block+street pairs. Gap cells show count and % unfilled for that column.
                                        MRT and building overlap require OneMap-complete linkage.
                                    </p>
                                </div>

                                <div className="overflow-x-auto">
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className="text-left border-b border-foreground/5 bg-black/[0.02]">
                                            <th className="px-6 py-3 font-semibold text-foreground/60">Dimension</th>
                                            <th className="px-6 py-3 font-semibold text-foreground/60">Source table</th>
                                            <th className="px-6 py-3 font-semibold text-foreground/60 whitespace-nowrap">
                                                Count
                                            </th>
                                            <th className="px-6 py-3 font-semibold text-foreground/60 whitespace-nowrap">
                                                % of total
                                            </th>
                                            <th className="px-6 py-3 font-semibold text-foreground/60 whitespace-nowrap">
                                                Gap + % unfilled (txn)
                                            </th>
                                            <th className="px-6 py-3 font-semibold text-foreground/60 whitespace-nowrap">
                                                Gap + % unfilled (loc.)
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {breakdownRows.map((row) => {
                                            const c = row.count ?? 0;
                                            const gapTxn = total - c;
                                            const gapLoc = row.gapUnique ?? 0;
                                            return (
                                                <tr key={row.table} className="border-b border-foreground/5 last:border-0">
                                                    <td className="px-6 py-3.5 font-medium">{row.label}</td>
                                                    <td className="px-6 py-3.5 font-mono text-xs text-foreground/55">
                                                        {row.table}
                                                    </td>
                                                    <td className="px-6 py-3.5 tabular-nums">{c.toLocaleString()}</td>
                                                    <td className="px-6 py-3.5 tabular-nums text-foreground/80">
                                                        {fmtPct(row.pct)}
                                                    </td>
                                                    <td className="px-6 py-3.5 text-red-600/90">
                                                        <span className="tabular-nums font-medium block">
                                                            {gapTxn > 0 ? gapTxn.toLocaleString() : "0"}
                                                        </span>
                                                        <span className="tabular-nums text-xs text-red-600/70 block mt-0.5">
                                                            {fmtPct(row.pctUnfilledTxn)}
                                                        </span>
                                                    </td>
                                                    <td className="px-6 py-3.5 text-amber-700/90">
                                                        <span className="tabular-nums font-medium block">
                                                            {gapLoc > 0 ? gapLoc.toLocaleString() : "0"}
                                                        </span>
                                                        <span className="tabular-nums text-xs text-amber-700/70 block mt-0.5">
                                                            {fmtPct(row.pctUnfilledLoc)}
                                                        </span>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                                </div>
                            </div>
                        </>
                    )}
                </div>
            </main>
        </RequireAuth>
    );
}
