"use client";

import { useState, useEffect } from "react";
import Navbar from "@/components/Navbar";
import {
    Database, Search, Layers, Server, Play, Table, Code,
    RefreshCw, Globe, Tag, Hash, Columns, ChevronDown, ChevronRight,
    Folder, FileText,
} from "lucide-react";
import API_BASE from "@/lib/apiBase";

export default function DataCatalogPage() {
    const [data, setData] = useState<any>(null);
    const [catalogLoading, setCatalogLoading] = useState(true);
    const [catalogError, setCatalogError] = useState("");
    const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set());

    // Query State
    const [activeTable, setActiveTable] = useState("");
    const [sqlQuery, setSqlQuery] = useState("SELECT * FROM hdb_resale_transactions LIMIT 10;");
    const [queryResult, setQueryResult] = useState<any>(null);
    const [queryLoading, setQueryLoading] = useState(false);
    const [queryError, setQueryError] = useState("");

    useEffect(() => {
        fetchCatalog();
    }, []);

    const fetchCatalog = async () => {
        setCatalogLoading(true);
        setCatalogError("");
        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
            const res = await fetch(`${API_BASE}/api/admin/data-catalog`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (!res.ok) throw new Error("Failed to load data catalog.");
            const json = await res.json();
            setData(json);
            // Default active table to first serving layer table
            const tables = Object.keys(json.serving_layer || {});
            if (tables.length > 0) {
                setActiveTable(tables[0]);
                setSqlQuery(`SELECT * FROM ${tables[0]} LIMIT 10;`);
            }
        } catch (err: any) {
            setCatalogError(err.message);
        } finally {
            setCatalogLoading(false);
        }
    };

    const runQuery = async (type: 'sample' | 'sql') => {
        setQueryLoading(true);
        setQueryError("");
        try {
            const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
            const body = type === 'sample'
                ? { query_type: 'sample', table_name: activeTable, n: 20 }
                : { query_type: 'sql', sql: sqlQuery };
            const res = await fetch(`${API_BASE}/api/admin/data-query`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                body: JSON.stringify(body),
            });
            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || "Query failed");
            }
            setQueryResult(await res.json());
        } catch (err: any) {
            setQueryError(err.message);
        } finally {
            setQueryLoading(false);
        }
    };

    const toggleExpand = (table: string) => {
        setExpandedTables(prev => {
            const next = new Set(prev);
            next.has(table) ? next.delete(table) : next.add(table);
            return next;
        });
    };

    const servingTables = data ? Object.entries(data.serving_layer || {}) : [];
    const geoTables = servingTables.filter(([, v]: any) => v.is_geospatial);
    const relTables = servingTables.filter(([, v]: any) => !v.is_geospatial && !v.error);

    return (
        <main className="min-h-screen bg-slate-50 pb-20">
            <Navbar />

            <div className="max-w-7xl mx-auto pt-32 px-4 sm:px-6 lg:px-8">
                {/* Header */}
                <div className="mb-10">
                    <span className="text-blue-500 font-bold uppercase tracking-widest text-xs">Data Architecture</span>
                    <h1 className="text-4xl font-extrabold tracking-tight mt-2 flex items-center gap-3">
                        <Database className="w-8 h-8 text-blue-500" /> Data Catalog
                    </h1>
                    <p className="text-sm text-foreground/50 mt-2">
                        Explore all tables in the serving layer. Click any table to inspect its schema and query it.
                    </p>
                </div>

                {catalogLoading ? (
                    <div className="flex justify-center py-20"><RefreshCw className="animate-spin text-blue-500 w-12 h-12" /></div>
                ) : catalogError ? (
                    <div className="bg-red-500/10 border border-red-500/20 text-red-600 rounded-xl p-6">{catalogError}</div>
                ) : (
                    <div className="space-y-12">

                        {/* ── Object Storage (MinIO) — folder tree + preview ─ */}
                        <section className="glass rounded-3xl p-6 border-foreground/5">
                            <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                                <Layers className="text-orange-500 w-5 h-5" /> Object Storage (MinIO)
                            </h2>
                            <p className="text-xs text-foreground/45 mb-4">
                                Browse buckets like a file system. CSV and Parquet show up to five data rows; JSON and GeoJSON show the first 20 lines. Parquet files load fully up to 64&nbsp;MiB.
                            </p>
                            <MinioCatalogExplorer />
                        </section>

                        {/* ── Serving Layer (PostgreSQL) ─────────────────── */}
                        <section>
                            <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                                <Server className="text-green-500 w-5 h-5" /> Serving Layer (PostgreSQL + PostGIS)
                            </h2>

                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                                {/* Relational tables */}
                                {relTables.map(([name, info]: any) => (
                                    <TableCard
                                        key={name}
                                        name={name}
                                        info={info}
                                        expanded={expandedTables.has(name)}
                                        onToggle={() => toggleExpand(name)}
                                        onQuery={() => {
                                            setActiveTable(name);
                                            setSqlQuery(`SELECT * FROM ${name} LIMIT 20;`);
                                            document.getElementById('query-console')?.scrollIntoView({ behavior: 'smooth' });
                                        }}
                                        type="relational"
                                    />
                                ))}

                                {/* Geospatial tables */}
                                {geoTables.map(([name, info]: any) => (
                                    <TableCard
                                        key={name}
                                        name={name}
                                        info={info}
                                        expanded={expandedTables.has(name)}
                                        onToggle={() => toggleExpand(name)}
                                        onQuery={() => {
                                            setActiveTable(name);
                                            setSqlQuery(`SELECT objectid, blk_no, postal_cod, shape_area, shape_len FROM ${name} LIMIT 20;`);
                                            document.getElementById('query-console')?.scrollIntoView({ behavior: 'smooth' });
                                        }}
                                        type="geospatial"
                                    />
                                ))}
                            </div>
                        </section>

                        {/* ── Query Console ─────────────────────────── */}
                        <section id="query-console" className="glass rounded-3xl shadow-2xl border-foreground/5 overflow-hidden">
                            <div className="p-8 border-b border-foreground/5 bg-white/20 flex items-center justify-between">
                                <div>
                                    <h2 className="text-2xl font-bold flex items-center gap-2">
                                        <Search className="text-blue-500" /> Query Console
                                    </h2>
                                    <p className="text-sm text-foreground/60 mt-1">Run SELECT queries against any table in the serving layer.</p>
                                </div>
                                {activeTable && (
                                    <span className="text-xs px-3 py-1.5 bg-blue-500/10 text-blue-600 rounded-full font-bold border border-blue-500/20">
                                        Active: {activeTable}
                                    </span>
                                )}
                            </div>

                            <div className="p-8">
                                <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
                                    {/* Table Selector */}
                                    <div className="lg:col-span-1 space-y-4">
                                        <div>
                                            <label className="text-xs font-bold uppercase tracking-wider text-foreground/50 block mb-2">Table</label>
                                            <select
                                                value={activeTable}
                                                onChange={(e) => {
                                                    const t = e.target.value;
                                                    setActiveTable(t);
                                                    const isGeo = data?.serving_layer?.[t]?.is_geospatial;
                                                    setSqlQuery(isGeo
                                                        ? `SELECT objectid, blk_no, postal_cod, shape_area, shape_len FROM ${t} LIMIT 20;`
                                                        : `SELECT * FROM ${t} LIMIT 20;`
                                                    );
                                                }}
                                                className="w-full bg-white border-foreground/10 rounded-xl p-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                                            >
                                                {servingTables.map(([name]: any) => (
                                                    <option key={name} value={name}>{name}</option>
                                                ))}
                                            </select>
                                        </div>
                                        <button
                                            onClick={() => runQuery('sample')}
                                            disabled={queryLoading || !activeTable}
                                            className="w-full bg-slate-800 text-white p-3 rounded-xl font-bold text-sm hover:bg-slate-900 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                                        >
                                            <Table className="w-4 h-4" /> Sample 20 Rows
                                        </button>
                                    </div>

                                    {/* SQL Editor */}
                                    <div className="lg:col-span-3 space-y-4">
                                        <div className="relative">
                                            <label className="text-xs font-bold uppercase tracking-wider text-foreground/50 block mb-2 flex items-center gap-2">
                                                <Code className="w-3 h-3" /> SQL Editor
                                            </label>
                                            <textarea
                                                value={sqlQuery}
                                                onChange={(e) => setSqlQuery(e.target.value)}
                                                className="w-full h-32 bg-slate-900 text-green-400 font-mono text-sm p-4 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none resize-none shadow-inner"
                                            />
                                            <button
                                                onClick={() => runQuery('sql')}
                                                disabled={queryLoading}
                                                className="absolute bottom-4 right-4 bg-blue-500 text-white px-4 py-2 rounded-lg font-bold text-sm hover:shadow-lg transition-all flex items-center gap-2 disabled:opacity-50"
                                            >
                                                {queryLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-3 h-3 fill-current" />}
                                                Execute
                                            </button>
                                        </div>
                                    </div>
                                </div>

                                {/* Results */}
                                <div className="mt-8">
                                    {queryError && (
                                        <div className="bg-red-500/10 border border-red-500/20 text-red-600 rounded-xl p-4 text-sm mb-4">{queryError}</div>
                                    )}
                                    {queryResult ? (
                                        <div>
                                            <p className="text-xs text-foreground/40 mb-2">{queryResult.data.length} row(s) returned</p>
                                            <div className="overflow-x-auto rounded-xl border border-foreground/5">
                                                <table className="w-full text-left text-sm">
                                                    <thead className="bg-slate-100 text-foreground/60 font-medium">
                                                        <tr>
                                                            {queryResult.columns.map((col: string) => (
                                                                <th key={col} className="p-3 whitespace-nowrap text-xs uppercase tracking-wider">{col}</th>
                                                            ))}
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-foreground/5">
                                                        {queryResult.data.map((row: any, i: number) => (
                                                            <tr key={i} className="hover:bg-slate-50 transition-colors">
                                                                {queryResult.columns.map((col: string) => (
                                                                    <td key={col} className="p-3 whitespace-nowrap tabular-nums text-xs max-w-[200px] truncate">
                                                                        {row[col]?.toString() ?? <span className="text-foreground/30">null</span>}
                                                                    </td>
                                                                ))}
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            </div>
                                        </div>
                                    ) : !queryLoading && (
                                        <div className="h-48 border-2 border-dashed border-foreground/10 rounded-2xl flex flex-col items-center justify-center text-foreground/30">
                                            <Database className="w-10 h-10 mb-2 opacity-20" />
                                            <p className="text-sm">Select a table or write a query above</p>
                                        </div>
                                    )}
                                    {queryLoading && (
                                        <div className="h-48 flex items-center justify-center">
                                            <RefreshCw className="animate-spin text-blue-500 w-8 h-8" />
                                        </div>
                                    )}
                                </div>
                            </div>
                        </section>
                    </div>
                )}
            </div>
        </main>
    );
}

// ── MinIO folder browser + file preview ─────────────────────────────────────
function MinioCatalogExplorer() {
    const [bucket, setBucket] = useState<"datasets" | "models">("datasets");
    const [prefix, setPrefix] = useState("");
    const [browse, setBrowse] = useState<{
        prefix: string;
        parent_prefix: string;
        folders: { name: string; prefix: string }[];
        objects: { name: string; key: string; size_mb: number; last_modified: string | null }[];
        error?: string;
    } | null>(null);
    const [browseLoading, setBrowseLoading] = useState(false);
    const [browseError, setBrowseError] = useState("");
    const [previewKey, setPreviewKey] = useState<string | null>(null);
    const [preview, setPreview] = useState<any>(null);
    const [previewLoading, setPreviewLoading] = useState(false);
    const [previewError, setPreviewError] = useState("");

    useEffect(() => {
        setPreviewKey(null);
        setPreview(null);
        setPreviewError("");
    }, [bucket, prefix]);

    useEffect(() => {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
        let cancelled = false;
        (async () => {
            setBrowseLoading(true);
            setBrowseError("");
            try {
                const u = new URL(`${API_BASE}/api/admin/minio/browse`);
                u.searchParams.set("bucket", bucket);
                if (prefix) u.searchParams.set("prefix", prefix);
                const res = await fetch(u.toString(), {
                    headers: { Authorization: `Bearer ${token}` },
                });
                if (!res.ok) {
                    const errData = await res.json().catch(() => ({}));
                    throw new Error(errData.detail || "Failed to browse MinIO");
                }
                const json = await res.json();
                if (!cancelled) setBrowse(json);
            } catch (e: any) {
                if (!cancelled) {
                    setBrowseError(e.message);
                    setBrowse(null);
                }
            } finally {
                if (!cancelled) setBrowseLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [API_BASE, bucket, prefix]);

    const loadPreview = async (key: string) => {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
        setPreviewKey(key);
        setPreviewLoading(true);
        setPreviewError("");
        setPreview(null);
        try {
            const u = new URL(`${API_BASE}/api/admin/minio/preview`);
            u.searchParams.set("bucket", bucket);
            u.searchParams.set("key", key);
            const res = await fetch(u.toString(), {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || "Preview failed");
            }
            setPreview(await res.json());
        } catch (e: any) {
            setPreviewError(e.message);
        } finally {
            setPreviewLoading(false);
        }
    };

    const crumbs: { label: string; path: string }[] = [
        { label: bucket, path: "" },
    ];
    const segs = prefix.replace(/\/+$/, "").split("/").filter(Boolean);
    let acc = "";
    for (const seg of segs) {
        acc = acc ? `${acc}/${seg}` : seg;
        crumbs.push({ label: seg, path: `${acc}/` });
    }

    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="bg-white/30 rounded-2xl p-4 min-h-[280px]">
                <div className="flex flex-wrap gap-2 mb-3">
                    {(["datasets", "models"] as const).map((b) => (
                        <button
                            key={b}
                            type="button"
                            onClick={() => {
                                setBucket(b);
                                setPrefix("");
                            }}
                            className={`text-xs font-bold uppercase tracking-wider px-3 py-1.5 rounded-lg border transition-colors ${
                                bucket === b
                                    ? "bg-orange-500/20 border-orange-500/40 text-orange-700"
                                    : "border-foreground/10 text-foreground/50 hover:bg-white/20"
                            }`}
                        >
                            {b}
                        </button>
                    ))}
                </div>

                <div className="flex flex-wrap items-center gap-1 text-xs font-mono text-foreground/55 mb-3 break-all">
                    {crumbs.map((c, i) => (
                        <span key={`${c.path}-${i}`} className="flex items-center gap-1">
                            {i > 0 && <ChevronRight className="w-3 h-3 shrink-0 opacity-40" />}
                            <button
                                type="button"
                                className={`hover:text-orange-600 ${i === crumbs.length - 1 ? "text-foreground font-semibold" : ""}`}
                                onClick={() => setPrefix(c.path)}
                            >
                                {c.label}
                            </button>
                        </span>
                    ))}
                </div>

                {browse?.parent_prefix !== undefined && prefix ? (
                    <button
                        type="button"
                        onClick={() => setPrefix(browse.parent_prefix)}
                        className="text-xs text-blue-600 hover:underline mb-2"
                    >
                        ↑ Up to parent folder
                    </button>
                ) : null}

                {browseLoading ? (
                    <div className="flex justify-center py-12">
                        <RefreshCw className="animate-spin text-orange-500 w-8 h-8" />
                    </div>
                ) : browseError ? (
                    <div className="text-sm text-red-600 bg-red-500/10 rounded-lg p-3">{browseError}</div>
                ) : browse?.error ? (
                    <div className="text-sm text-red-600 bg-red-500/10 rounded-lg p-3">{browse.error}</div>
                ) : (
                    <ul className="space-y-1 max-h-[320px] overflow-y-auto pr-1">
                        {(browse?.folders || []).map((f) => (
                            <li key={f.prefix}>
                                <button
                                    type="button"
                                    onClick={() => setPrefix(f.prefix)}
                                    className="w-full flex items-center gap-2 text-left text-sm py-2 px-2 rounded-lg hover:bg-white/40 font-mono"
                                >
                                    <Folder className="w-4 h-4 text-amber-500 shrink-0" />
                                    <span className="truncate">{f.name}</span>
                                </button>
                            </li>
                        ))}
                        {(browse?.objects || []).map((o) => (
                            <li key={o.key}>
                                <button
                                    type="button"
                                    onClick={() => loadPreview(o.key)}
                                    className={`w-full flex items-center justify-between gap-2 text-left text-sm py-2 px-2 rounded-lg font-mono ${
                                        previewKey === o.key
                                            ? "bg-orange-500/15 border border-orange-500/25"
                                            : "hover:bg-white/40"
                                    }`}
                                >
                                    <span className="flex items-center gap-2 min-w-0">
                                        <FileText className="w-4 h-4 text-foreground/40 shrink-0" />
                                        <span className="truncate">{o.name}</span>
                                    </span>
                                    <span className="text-[10px] text-foreground/40 shrink-0 tabular-nums">
                                        {o.size_mb} MB
                                    </span>
                                </button>
                            </li>
                        ))}
                        {!browse?.folders?.length && !browse?.objects?.length ? (
                            <li className="text-xs text-foreground/35 italic py-4 text-center">This folder is empty</li>
                        ) : null}
                    </ul>
                )}
            </div>

            <div className="bg-white/30 rounded-2xl p-4 min-h-[280px] flex flex-col">
                <div className="text-xs font-bold uppercase tracking-widest text-foreground/40 mb-2">Preview</div>
                {!previewKey && !previewLoading ? (
                    <div className="flex-1 flex flex-col items-center justify-center text-foreground/35 text-sm border border-dashed border-foreground/10 rounded-xl">
                        <FileText className="w-10 h-10 mb-2 opacity-30" />
                        Select a file to preview
                    </div>
                ) : null}
                {previewLoading ? (
                    <div className="flex-1 flex items-center justify-center py-16">
                        <RefreshCw className="animate-spin text-orange-500 w-8 h-8" />
                    </div>
                ) : null}
                {previewError ? (
                    <div className="text-sm text-red-600 bg-red-500/10 rounded-lg p-3">{previewError}</div>
                ) : null}
                {preview && !previewLoading ? (
                    <div className="flex-1 min-h-0 flex flex-col gap-2">
                        <div className="text-[10px] font-mono text-foreground/45 truncate" title={preview.key}>
                            {preview.key}
                        </div>
                        {preview.truncated && preview.kind === "csv" ? (
                            <p className="text-[10px] text-amber-700">
                                Preview truncated (only the start of the object was read).
                            </p>
                        ) : null}
                        {preview.truncated && preview.kind === "json" ? (
                            <p className="text-[10px] text-amber-700">
                                Showing the first 20 lines only.
                            </p>
                        ) : null}
                        {preview.truncated && preview.kind === "text" ? (
                            <p className="text-[10px] text-amber-700">
                                Preview truncated (beginning of file only).
                            </p>
                        ) : null}
                        {preview.truncated && preview.kind === "parquet" && typeof preview.total_row_count === "number" ? (
                            <p className="text-[10px] text-amber-700">
                                Showing 5 of {preview.total_row_count.toLocaleString()} rows
                                {typeof preview.column_count === "number" ? ` · ${preview.column_count} columns` : ""}
                            </p>
                        ) : null}
                        {(preview.kind === "csv" || preview.kind === "parquet") ? (
                            <div className="overflow-x-auto rounded-lg border border-foreground/10 text-xs">
                                <table className="w-full text-left">
                                    <thead>
                                        <tr className="bg-slate-100">
                                            {(preview.header || []).map((h: string, i: number) => (
                                                <th key={i} className="p-2 font-semibold whitespace-nowrap max-w-[160px] truncate">
                                                    {h}
                                                </th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-foreground/5">
                                        {(preview.rows || []).map((row: string[], ri: number) => (
                                            <tr key={ri}>
                                                {row.map((cell, ci) => (
                                                    <td key={ci} className="p-2 whitespace-nowrap max-w-[160px] truncate">
                                                        {cell}
                                                    </td>
                                                ))}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                                <p className="p-2 text-[10px] text-foreground/40 border-t border-foreground/5">
                                    {preview.kind === "parquet"
                                        ? `Parquet · ${preview.column_count ?? "—"} columns · ${typeof preview.total_row_count === "number" ? preview.total_row_count.toLocaleString() : "—"} total rows (first 5 shown)`
                                        : "Header + up to five data rows"}
                                </p>
                            </div>
                        ) : null}
                        {preview.kind === "json" ? (
                            <pre className="flex-1 overflow-auto text-xs font-mono p-3 rounded-lg bg-slate-900/90 text-green-100/90 max-h-[360px] whitespace-pre-wrap break-all">
                                {(preview.lines || []).join("\n")}
                            </pre>
                        ) : null}
                        {preview.kind === "text" ? (
                            <pre className="flex-1 overflow-auto text-xs font-mono p-3 rounded-lg bg-slate-900/90 text-slate-200 max-h-[360px] whitespace-pre-wrap break-all">
                                {preview.content}
                            </pre>
                        ) : null}
                        {preview.kind === "unsupported" ? (
                            <p className="text-sm text-foreground/70 p-3 rounded-lg bg-foreground/5 border border-foreground/10">
                                {preview.message}
                            </p>
                        ) : null}
                    </div>
                ) : null}
            </div>
        </div>
    );
}

// ── Sub-component: Table Card ────────────────────────────────────────────────
function TableCard({ name, info, expanded, onToggle, onQuery, type }: {
    name: string; info: any; expanded: boolean;
    onToggle: () => void; onQuery: () => void; type: "relational" | "geospatial";
}) {
    const isGeo = type === "geospatial";
    return (
        <div className={`glass rounded-2xl overflow-hidden border transition-all ${isGeo ? 'border-purple-500/20 bg-purple-500/5' : 'border-foreground/5'}`}>
            <button onClick={onToggle} className="w-full flex items-center justify-between p-5 text-left hover:bg-white/10 transition-colors">
                <div className="flex items-center gap-3">
                    {isGeo
                        ? <Globe className="w-5 h-5 text-purple-500 shrink-0" />
                        : <Server className="w-5 h-5 text-green-500 shrink-0" />}
                    <div>
                        <div className="font-bold text-sm font-mono">{name}</div>
                        <div className="text-xs text-foreground/40 mt-0.5">{info.description}</div>
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    <span className="text-sm font-bold text-foreground/60">
                        {info.row_count?.toLocaleString() ?? '—'}<span className="text-xs font-normal ml-1">rows</span>
                    </span>
                    {expanded ? <ChevronDown className="w-4 h-4 opacity-40" /> : <ChevronRight className="w-4 h-4 opacity-40" />}
                </div>
            </button>

            {expanded && (
                <div className="px-5 pb-5 space-y-3">
                    {/* Column Schema */}
                    <div>
                        <div className="text-[10px] font-bold uppercase tracking-widest text-foreground/40 mb-2 flex items-center gap-1">
                            <Columns className="w-3 h-3" /> Schema ({info.columns?.length} columns)
                        </div>
                        <div className="grid grid-cols-2 gap-1 max-h-48 overflow-y-auto pr-1">
                            {info.columns?.map((col: any) => (
                                <div key={col.name} className="flex items-center gap-1.5 text-xs py-1 px-2 rounded-lg bg-white/20">
                                    {col.name === 'geom' || col.name === 'wkb_geometry'
                                        ? <Globe className="w-3 h-3 text-purple-400 shrink-0" />
                                        : col.type.includes('int') || col.type === 'numeric' || col.type === 'double precision'
                                            ? <Hash className="w-3 h-3 text-blue-400 shrink-0" />
                                            : <Tag className="w-3 h-3 text-yellow-400 shrink-0" />}
                                    <span className="font-mono truncate">{col.name}</span>
                                    <span className="text-foreground/30 shrink-0 ml-auto text-[10px]">{col.type.replace('character varying', 'varchar').replace('double precision', 'float')}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                    <button
                        onClick={onQuery}
                        className={`w-full text-xs font-bold py-2 px-4 rounded-xl flex items-center justify-center gap-2 transition-all ${isGeo
                            ? 'bg-purple-500/20 text-purple-600 hover:bg-purple-500/30 border border-purple-500/30'
                            : 'bg-blue-500/10 text-blue-600 hover:bg-blue-500/20 border border-blue-500/20'}`}
                    >
                        <Play className="w-3 h-3" /> Query in Console ↓
                    </button>
                </div>
            )}
        </div>
    );
}
