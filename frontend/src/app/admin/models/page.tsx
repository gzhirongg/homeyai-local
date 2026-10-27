"use client";

import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import { AdminAlertStack, type AdminAlertItem } from "@/components/admin/AdminAlertStack";
import {
    type ExperimentReportNotice,
} from "@/components/admin/ExperimentReportDownloadButton";
import { ExperimentRunDetailModal } from "@/components/admin/ExperimentRunDetailModal";
import {
    ArrowLeft,
    Activity,
    RefreshCw,
    AlertTriangle,
    Brain,
    Box,
    Clock,
    Layers,
    Sparkles,
    BarChart3,
    ChevronUp,
    ChevronDown,
} from "lucide-react";

import API_BASE from "@/lib/apiBase";
import {
    formatFeatureSelectionPolicyShort,
    unifiedFeatureSelectionPolicy,
} from "@/lib/featureSelectionPolicy";
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
    ResponsiveContainer,
} from "recharts";

type VersionInfo = {
    version?: string;
    model_env?: string;
    commit?: string;
};

type ExperimentRow = {
    id: string;
    experiment_id?: string;
    estimator: string;
    feature_set: string;
    feature_set_id?: string;
    model_id?: string;
    rmse: number;
    mae: number | null;
    r2: number | null;
    cv_rmse: number | null;
    n_train: number | null;
    n_test?: number | null;
    mape?: number | null;
    mrt_pit_min_years?: number | null;
    /** Wall seconds for ``train_from_frame`` (from metrics.training_context). */
    training_wall_seconds?: number | null;
    run_directory?: string | null;
    run_timestamp?: string | null;
    test_fraction?: number | null;
    cv_splits?: number | null;
    max_train_rows?: number | null;
    feature_selection_policy?: string | null;
    feature_selection_columns_removed_count?: number | null;
};

type ModelMetricsPayload = {
    experiments: ExperimentRow[];
    best: Partial<ExperimentRow> & {
        id: string;
        rmse?: number | null;
        mae?: number | null;
        r2?: number | null;
        cv_rmse?: number | null;
        n_train?: number | null;
        n_test?: number | null;
        mape?: number | null;
        mrt_pit_min_years?: number | null;
        training_wall_seconds?: number | null;
        feature_selection_policy?: string | null;
        feature_selection_columns_removed_count?: number | null;
    };
    shap_chart_available: boolean;
};

type MLRun = {
    id: string;
    has_minio_artifact?: boolean;
    config?: {
        experiment?: {
            model_id?: string;
            feature_set_id?: string;
            id?: string;
        };
    };
    metrics?: {
        test_metrics?: {
            rmse?: number;
        };
        training_context?: Record<string, unknown>;
    };
    best_params?: Record<string, string>;
};

/** Experiment catalog from MinIO (slim rows from dashboard when ``experiments_detail=false``). */
type CatalogExperimentRow = MLRun & {
    published: boolean;
    /** True when ``{MODEL_ENV}/valuation/experiments/<run_id>/model.pkl`` exists (canonical store). */
    has_minio_experiment?: boolean;
    /** MinIO key to POST /api/admin/model/promote when this run lives under experiments/ */
    publish_object_key?: string | null;
    has_metrics: boolean;
    /** Present on slim dashboard rows only */
    rmse?: number | null;
    model_id?: string | null;
    feature_set_id?: string | null;
    /** Slim dashboard only — from metrics.training_context (enables year filter without leaderboard match). */
    mrt_pit_min_years?: number | null;
    /** Slim dashboard only — ``train_from_frame`` wall time (seconds). */
    training_wall_seconds?: number | null;
    feature_selection_policy?: string | null;
    feature_selection_columns_removed_count?: number | null;
};

type ValuationArtifactRow = {
    object_key: string;
    artifact_folder?: string | null;
    uploaded_at?: string | null;
    experiment_id?: string | null;
    feature_set_id?: string | null;
    model_id?: string | null;
    metrics_summary?: { rmse?: number | null; mae?: number | null; r2?: number | null };
    is_active: boolean;
};

type ModelServingStatus = {
    is_ready: boolean;
    feature_set_id: string | null;
    experiment_id: string | null;
    model_id: string | null;
    model_object_key: string | null;
    load_error: string | null;
    /** Holdout / test RMSE from loaded model's metrics.json (same as live API). */
    holdout_rmse?: number | null;
    promoted_at?: string | null;
    promoted_by?: string | null;
};

/** Response shape for ``GET /api/admin/dashboard``. */
type AdminDashboardPayload = {
    version: VersionInfo;
    env: string;
    artifacts: { env: string; artifacts: ValuationArtifactRow[] };
    experiments: { env: string; experiments: CatalogExperimentRow[] };
    model_status: ModelServingStatus;
    metrics: ModelMetricsPayload;
};

type DataQualityReport = {
    generated_at?: string;
    windows?: Record<
        string,
        {
            findings?: { severity?: string; message?: string; code?: string }[];
        }
    >;
};

type SortKey =
    | "rmse"
    | "mae"
    | "r2"
    | "cv_rmse"
    | "n_train"
    | "n_test"
    | "training_wall_seconds"
    | "mape"
    | "run_timestamp"
    | "mrt_pit_min_years"
    | "run_id"
    | "estimator"
    | "feature_set"
    | "has_metrics"
    | "has_minio_experiment";

const PAGE_SIZE = 5;

const EXPERIMENTS_POLL_INTERVAL_MS = 15_000;

/** One merged row: catalog (disk / MinIO flags) plus optional leaderboard metrics. */
type UnifiedExperimentRow = {
    catalog: CatalogExperimentRow;
    leaderboard: ExperimentRow | undefined;
};

const MODEL_MULTI_OPTIONS = [
    { value: "linear", label: "Linear" },
    { value: "random_forest", label: "Random Forest" },
    { value: "xgboost", label: "XGBoost" },
];

const FEATURE_MULTI_OPTIONS = [
    { value: "baseline_v1", label: "baseline_v1" },
    { value: "mrt_pit", label: "mrt_pit" },
    { value: "poi_distancing", label: "poi_distancing" },
    { value: "mrt_pit__poi_distancing", label: "mrt_pit__poi_distancing" },
];

const YEARS_MULTI_OPTIONS = [
    { value: "5", label: "5 years" },
    { value: "10", label: "10 years" },
    { value: "15", label: "15 years" },
    { value: "20", label: "20 years" },
];

function formatSgdCompact(n: number) {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function formatSgdFull(n: number | null | undefined) {
    if (n == null || typeof n !== "number" || Number.isNaN(n)) return "—";
    return `S$${Math.round(n).toLocaleString()}`;
}

/** Format ``train_from_frame`` wall seconds for tables and modal (compact). */
function formatTrainingWallHuman(sec: number | null | undefined): string {
    if (sec == null || typeof sec !== "number" || Number.isNaN(sec) || !Number.isFinite(sec)) return "—";
    if (sec >= 60) {
        const m = Math.floor(sec / 60);
        const rem = sec - m * 60;
        return `${m}m ${rem.toFixed(1)}s`;
    }
    return `${sec.toFixed(1)} s`;
}

function buildPromoteSuccessNotice(estimator: string, mae: number | null | undefined): string {
    const label = estimator.trim() || "Model";
    if (mae != null && typeof mae === "number" && Number.isFinite(mae)) {
        return `${label} (${formatSgdFull(mae)} MAE) promoted to production successfully.`;
    }
    return `${label} promoted to production successfully.`;
}

function artifactEstimatorLabel(a: ValuationArtifactRow): string {
    const raw = String(a.model_id ?? "").trim();
    if (!raw) return "Model";
    return raw
        .split("_")
        .map((w) => (w ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : ""))
        .filter(Boolean)
        .join(" ");
}

function authHeaders(): Record<string, string> {
    if (typeof window === "undefined") return {};
    const token = localStorage.getItem("token");
    const h: Record<string, string> = {};
    if (token) h.Authorization = `Bearer ${token}`;
    return h;
}

/** FastAPI may return ``detail`` as a string, object, or validation error array */
function formatApiErrorDetail(detail: unknown): string {
    if (detail == null) return "Request failed";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
        return detail
            .map((d) => {
                if (d && typeof d === "object" && "msg" in d) {
                    const o = d as { msg?: string; loc?: unknown };
                    return typeof o.msg === "string" ? o.msg : JSON.stringify(d);
                }
                return JSON.stringify(d);
            })
            .join("; ");
    }
    if (typeof detail === "object") {
        try {
            return JSON.stringify(detail);
        } catch {
            return "Request failed";
        }
    }
    return String(detail);
}

function catalogRowModelId(r: CatalogExperimentRow): string {
    return r.config?.experiment?.model_id ?? r.model_id ?? "—";
}

function catalogRowFeatureSetId(r: CatalogExperimentRow): string {
    return r.config?.experiment?.feature_set_id ?? r.feature_set_id ?? "—";
}

function catalogRowRmse(r: CatalogExperimentRow): number | null | undefined {
    return r.metrics?.test_metrics?.rmse ?? r.rmse;
}

function deriveTrainPayload(run: MLRun | null | undefined): { experiment_id: string; feature_set_id: string } | null {
    if (!run) return null;
    const exp = run.config?.experiment;
    const experiment_id = String(exp?.id || run.id).trim();
    const fs =
        exp?.feature_set_id ??
        ("feature_set_id" in run ? (run as CatalogExperimentRow).feature_set_id : undefined);
    const feature_set_id = String(fs || "mrt_pit").trim();
    if (!experiment_id || !feature_set_id) return null;
    return { experiment_id, feature_set_id };
}

/** Match filesystem run dir id to leaderboard logical id (e.g. ``linear__mrt_pit__y5`` → ``linear__mrt_pit__y5__20260510…``). */
function resolveMlRun(runs: MLRun[], leaderboardOrRunId: string | null): MLRun | undefined {
    if (!leaderboardOrRunId) return undefined;
    const exact = runs.find((r) => r.id === leaderboardOrRunId);
    if (exact) return exact;
    const prefix = `${leaderboardOrRunId}__`;
    const matches = runs.filter((r) => r.id.startsWith(prefix));
    return matches[0];
}

/** Whole-string training stamp ``YYYYMMDDTHHMMSS`` / ``…Z`` (UTC). ``Date.parse`` does not accept this form. */
function utcMsFromCompactWhole(s: string): number | null {
    const m = /^(\d{4})(\d{2})(\d{2})[Tt](\d{2})(\d{2})(\d{2})([Zz])?$/.exec(s.trim());
    if (!m) return null;
    return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
}

/** ISO-8601, compact training stamp-only, or compact token embedded in a longer id. */
function parseExperimentTimestampMs(ts: string | null | undefined): number | null {
    if (!ts || typeof ts !== "string") return null;
    const t = ts.trim();
    if (!t) return null;
    const compactWhole = utcMsFromCompactWhole(t);
    if (compactWhole != null) return compactWhole;
    const parsed = Date.parse(t);
    if (!Number.isNaN(parsed)) return parsed;
    return utcMsFromRunIdCompact(t);
}

/** Rightmost compact UTC stamp ``YYYYMMDDTHHMMSSz`` anywhere in ``run_id`` (case-insensitive). */
function utcMsFromRunIdCompact(runId: string): number | null {
    const re = /(\d{4})(\d{2})(\d{2})[Tt](\d{2})(\d{2})(\d{2})[Zz]/g;
    let m: RegExpExecArray | null;
    let last: RegExpExecArray | null = null;
    while ((m = re.exec(runId)) !== null) last = m;
    if (!last) return null;
    return Date.UTC(+last[1], +last[2] - 1, +last[3], +last[4], +last[5], +last[6]);
}

/** Last ``__`` segment when all digits — legacy ordering when compact UTC suffix absent. */
function idTailNumericMs(runId: string): number | null {
    if (!runId.includes("__")) return null;
    const tail = runId.split("__").pop() ?? "";
    if (!/^\d+$/.test(tail)) return null;
    const n = parseInt(tail, 10);
    return Number.isFinite(n) ? n : null;
}

function parsedRunSuffixTimestampMs(runId: string): number | null {
    const z = utcMsFromRunIdCompact(runId);
    if (z != null) return z;
    return idTailNumericMs(runId);
}

function effectiveSortTimestampMs(u: UnifiedExperimentRow): number | null {
    const fromLb = parseExperimentTimestampMs(u.leaderboard?.run_timestamp ?? null);
    if (fromLb != null) return fromLb;
    return parsedRunSuffixTimestampMs(u.catalog.id);
}

function findLeaderboardForCatalog(catalogId: string, lbRows: ExperimentRow[]): ExperimentRow | undefined {
    const exact = lbRows.find((e) => e.id === catalogId);
    if (exact) return exact;
    let bestMatch: ExperimentRow | undefined;
    let bestLen = -1;
    for (const e of lbRows) {
        if (!catalogId.startsWith(`${e.id}__`)) continue;
        if (e.id.length > bestLen) {
            bestMatch = e;
            bestLen = e.id.length;
        }
    }
    return bestMatch;
}

/** Leaderboard row that corresponds to the **served** model (not ``metrics.best``). */
function leaderboardRowForServing(
    rows: ExperimentRow[] | null | undefined,
    ms: ModelServingStatus | null,
): ExperimentRow | undefined {
    if (!rows?.length || !ms) return undefined;
    const eid = (ms.experiment_id ?? "").trim();
    const mid = (ms.model_id ?? "").trim().toLowerCase();
    const fs = (ms.feature_set_id ?? "").trim().toLowerCase();

    if (eid) {
        const exact = rows.find((r) => r.id === eid);
        if (exact) return exact;
        const prefixed = rows.find((r) => r.id.startsWith(`${eid}__`));
        if (prefixed) return prefixed;
        const byMeta = rows.find((r) => {
            const rex = (r.experiment_id ?? "").trim();
            return rex === eid;
        });
        if (byMeta) return byMeta;
    }
    if (mid && fs) {
        return rows.find((r) => {
            const rid = (r.model_id ?? "").trim().toLowerCase();
            const rfs = (r.feature_set_id ?? r.feature_set ?? "").trim().toLowerCase();
            return rid === mid && rfs === fs;
        });
    }
    return undefined;
}

function syntheticCatalogFromLeaderboard(lb: ExperimentRow): CatalogExperimentRow {
    const fs = lb.feature_set_id ?? lb.feature_set;
    const mid = lb.model_id ?? "";
    return {
        id: lb.id,
        published: false,
        has_minio_experiment: false,
        has_metrics: true,
        has_minio_artifact: false,
        model_id: mid || null,
        feature_set_id: fs || null,
        rmse: lb.rmse,
        feature_selection_policy: lb.feature_selection_policy ?? undefined,
        feature_selection_columns_removed_count: lb.feature_selection_columns_removed_count ?? undefined,
        metrics: { test_metrics: { rmse: lb.rmse } },
        config: {
            experiment: {
                id: lb.experiment_id ?? lb.id,
                model_id: mid || undefined,
                feature_set_id: fs || undefined,
            },
        },
    };
}

function buildUnifiedExperiments(
    catalog: CatalogExperimentRow[],
    lbRows: ExperimentRow[],
): UnifiedExperimentRow[] {
    const usedLb = new Set<string>();
    const unified: UnifiedExperimentRow[] = [];
    for (const c of catalog) {
        const lb = findLeaderboardForCatalog(c.id, lbRows);
        if (lb) usedLb.add(lb.id);
        unified.push({ catalog: c, leaderboard: lb });
    }
    for (const lb of lbRows) {
        if (usedLb.has(lb.id)) continue;
        unified.push({ catalog: syntheticCatalogFromLeaderboard(lb), leaderboard: lb });
    }
    return unified;
}

function unifiedModelFilterKey(u: UnifiedExperimentRow): string {
    return (u.leaderboard?.model_id ?? catalogRowModelId(u.catalog)).toLowerCase();
}

function unifiedFeatureFilterKey(u: UnifiedExperimentRow): string {
    const lb = u.leaderboard;
    return lb?.feature_set_id ?? lb?.feature_set ?? catalogRowFeatureSetId(u.catalog);
}

function unifiedMrtYears(u: UnifiedExperimentRow): number | null {
    const y = u.leaderboard?.mrt_pit_min_years;
    if (typeof y === "number" && !Number.isNaN(y)) return y;
    const c = u.catalog.mrt_pit_min_years;
    if (typeof c === "number" && !Number.isNaN(c)) return c;
    return null;
}

function unifiedTrainingWallSeconds(u: UnifiedExperimentRow): number | null {
    const tw = u.leaderboard?.training_wall_seconds;
    if (typeof tw === "number" && Number.isFinite(tw)) return tw;
    const c = u.catalog.training_wall_seconds;
    if (typeof c === "number" && Number.isFinite(c)) return c;
    const raw = u.catalog.metrics?.training_context?.training_wall_seconds;
    if (typeof raw === "number" && Number.isFinite(raw)) return raw;
    return null;
}

type FeatureSelectionBadgeVariant = "apply" | "advisory" | "unknown";

function featureSelectionBadgeVariantFromPolicy(policy: string | null): FeatureSelectionBadgeVariant {
    if (policy === "apply_recommended_drops") return "apply";
    if (policy === "advisory_only") return "advisory";
    return "unknown";
}

function FeatureSelectionTableBadge({
    policy,
    columnsRemoved,
}: {
    policy: string | null;
    columnsRemoved: number | null;
}) {
    const label = formatFeatureSelectionPolicyShort(policy);
    const v = featureSelectionBadgeVariantFromPolicy(policy);
    const tipParts = [label];
    if (v === "apply" && columnsRemoved != null && columnsRemoved > 0) {
        tipParts.push(`${columnsRemoved} column(s) removed before fit`);
    }
    const tip = tipParts.join(" — ");
    const cls =
        v === "apply"
            ? "bg-emerald-500/15 text-emerald-900 border-emerald-500/35"
            : v === "advisory"
              ? "bg-slate-500/10 text-slate-700 border-slate-400/25"
              : "bg-foreground/10 text-foreground/50 border-foreground/15";
    return (
        <span title={tip} className={`font-semibold px-2 py-0.5 rounded-md border text-[11px] ${cls}`}>
            {label}
        </span>
    );
}

function unifiedEstimatorLabel(u: UnifiedExperimentRow): string {
    const lb = u.leaderboard;
    return String(lb?.estimator ?? catalogRowModelId(u.catalog) ?? "").trim();
}

function unifiedFeatureSetLabel(u: UnifiedExperimentRow): string {
    const lb = u.leaderboard;
    return String(lb?.feature_set_id ?? lb?.feature_set ?? catalogRowFeatureSetId(u.catalog) ?? "").trim();
}

function unifiedDisplayRmse(u: UnifiedExperimentRow): number | null | undefined {
    const lb = u.leaderboard;
    if (lb?.rmse != null && typeof lb.rmse === "number") return lb.rmse;
    return catalogRowRmse(u.catalog);
}

function unifiedSortMetric(
    u: UnifiedExperimentRow,
    key: Exclude<
        SortKey,
        | "run_timestamp"
        | "mrt_pit_min_years"
        | "run_id"
        | "estimator"
        | "feature_set"
        | "has_metrics"
        | "has_minio_experiment"
    >,
): number | null {
    const lb = u.leaderboard;
    if (lb && lb[key] != null && typeof lb[key] === "number") return lb[key] as number;
    if (key === "rmse") {
        const r = unifiedDisplayRmse(u);
        return r != null ? Number(r) : null;
    }
    return null;
}

/** Display experiment instants in Singapore time (UTC+8, no DST). */
function formatMsHumanSingapore(ms: number): string {
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "Asia/Singapore",
    }).format(new Date(ms));
}

function rowMatchesBest(u: UnifiedExperimentRow, bestId: string | undefined): boolean {
    if (!bestId) return false;
    return u.catalog.id === bestId || u.catalog.id.startsWith(`${bestId}__`);
}

function displayStamp(u: UnifiedExperimentRow): string {
    const lbTs = u.leaderboard?.run_timestamp;
    if (lbTs) {
        const ms = parseExperimentTimestampMs(lbTs);
        if (ms != null) return formatMsHumanSingapore(ms);
        return lbTs.trim() || "—";
    }
    const fromId = parsedRunSuffixTimestampMs(u.catalog.id);
    if (fromId != null) return formatMsHumanSingapore(fromId);
    const tail = u.catalog.id.includes("__") ? u.catalog.id.split("__").pop() ?? "" : "";
    return tail || "—";
}

function buildRmseChartRows(exps: ExperimentRow[]) {
    const by = (mid: string, fs: string) =>
        exps.find((e) => e.model_id === mid && e.feature_set_id === fs)?.rmse ?? null;
    const rows: { name: string; baseline: number | null; mrt: number | null }[] = [];
    const models = [
        { id: "linear", label: "Linear" },
        { id: "random_forest", label: "Random Forest" },
        { id: "xgboost", label: "XGBoost" },
    ];
    for (const m of models) {
        const baseline = by(m.id, "baseline_v1");
        const mrt = by(m.id, "mrt_pit");
        if (baseline != null || mrt != null) {
            rows.push({ name: m.label, baseline, mrt });
        }
    }
    return rows;
}

function severityCounts(findings: { severity?: string }[] | undefined) {
    let critical = 0;
    let warn = 0;
    for (const f of findings || []) {
        if (f.severity === "critical") critical += 1;
        else if (f.severity === "warn") warn += 1;
    }
    return { critical, warn };
}

function SortHeader({
    label,
    active,
    asc,
    onClick,
}: {
    label: string;
    active: boolean;
    asc: boolean;
    onClick: () => void;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            className="inline-flex items-center gap-0.5 font-semibold hover:text-foreground text-foreground/80"
        >
            {label}
            {active ? asc ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" /> : null}
        </button>
    );
}

function FilterMultiDropdown({
    label,
    options,
    selected,
    onChange,
}: {
    label: string;
    options: { value: string; label: string }[];
    selected: Set<string>;
    onChange: (next: Set<string>) => void;
}) {
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!open) return;
        function close(ev: PointerEvent) {
            if (ref.current && !ref.current.contains(ev.target as Node)) setOpen(false);
        }
        document.addEventListener("pointerdown", close);
        return () => document.removeEventListener("pointerdown", close);
    }, [open]);

    const summary =
        selected.size === 0
            ? "All"
            : selected.size <= 2
              ? [...selected]
                    .map((v) => options.find((o) => o.value === v)?.label ?? v)
                    .join(", ")
              : `${selected.size} selected`;

    function toggle(v: string) {
        const n = new Set(selected);
        if (n.has(v)) n.delete(v);
        else n.add(v);
        onChange(n);
    }

    return (
        <div className="relative" ref={ref}>
            <span className="flex flex-col text-xs font-semibold text-foreground/50 gap-1">
                {label}
                <button
                    type="button"
                    onClick={() => setOpen((o) => !o)}
                    className="rounded-lg border border-foreground/15 bg-white px-2 py-1.5 text-sm font-normal text-foreground text-left inline-flex items-center justify-between gap-2 min-w-[11rem]"
                >
                    <span className="truncate">{summary}</span>
                    <ChevronDown className={`w-4 h-4 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
                </button>
            </span>
            {open && (
                <div className="absolute left-0 top-full z-[60] mt-1 min-w-full max-h-56 overflow-y-auto rounded-lg border border-foreground/15 bg-white py-1 shadow-lg">
                    {options.map((o) => (
                        <label
                            key={o.value}
                            className="flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-foreground/[0.04] cursor-pointer"
                        >
                            <input
                                type="checkbox"
                                checked={selected.has(o.value)}
                                onChange={() => toggle(o.value)}
                                className="rounded border-foreground/30"
                            />
                            {o.label}
                        </label>
                    ))}
                </div>
            )}
        </div>
    );
}

function ExperimentsTableSkeleton() {
    return (
        <div className="space-y-8 mb-10 animate-pulse" aria-busy="true" aria-label="Loading experiments">
            <div className="glass rounded-2xl p-6 border border-foreground/5">
                <div className="h-6 w-52 bg-slate-200 rounded mb-4" />
                <div className="h-4 w-full max-w-2xl bg-slate-100 rounded mb-6" />
                <div className="flex flex-wrap gap-3 mb-4">
                    <div className="h-9 w-28 bg-slate-100 rounded-lg" />
                    <div className="h-9 w-36 bg-slate-100 rounded-lg" />
                    <div className="h-9 w-32 bg-slate-100 rounded-lg" />
                </div>
                <div className="h-56 rounded-xl bg-slate-100 border border-slate-200/80" />
            </div>
        </div>
    );
}

export default function AdminModelManagementPage() {
    const [version, setVersion] = useState<VersionInfo | null>(null);
    const [metrics, setMetrics] = useState<ModelMetricsPayload | null>(null);
    const [catalogExperiments, setCatalogExperiments] = useState<CatalogExperimentRow[]>([]);
    const [dataReport, setDataReport] = useState<DataQualityReport | null>(null);
    const [filterModels, setFilterModels] = useState<Set<string>>(new Set());
    const [filterFeatures, setFilterFeatures] = useState<Set<string>>(new Set());
    const [filterYearSet, setFilterYearSet] = useState<Set<string>>(new Set());
    const [sortKey, setSortKey] = useState<SortKey>("run_timestamp");
    const [sortAsc, setSortAsc] = useState(false);
    const [experimentsPage, setExperimentsPage] = useState(1);
    const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
    const [dashboardRefreshKey, setDashboardRefreshKey] = useState(0);
    const [dashboardLoading, setDashboardLoading] = useState(false);
    const [dashboardError, setDashboardError] = useState<string | null>(null);

    const [artifacts, setArtifacts] = useState<ValuationArtifactRow[]>([]);
    const [artifactsError, setArtifactsError] = useState<string | null>(null);
    const [modelStatus, setModelStatus] = useState<ModelServingStatus | null>(null);
    const [promotingKey, setPromotingKey] = useState<string | null>(null);
    const [promoteError, setPromoteError] = useState<string | null>(null);
    const [notice, setNotice] = useState<ExperimentReportNotice | null>(null);

    const [activeFlowRunId, setActiveFlowRunId] = useState<string | null>(null);
    const [trainPanelOpen, setTrainPanelOpen] = useState(true);
    const [trainState, setTrainState] = useState<string | null>(null);
    const [trainMessage, setTrainMessage] = useState<string | null>(null);
    const [trainError, setTrainError] = useState<string | null>(null);
    const [trainStarting, setTrainStarting] = useState(false);
    const [dataReportLoading, setDataReportLoading] = useState(false);
    const [artifactsSectionLoading, setArtifactsSectionLoading] = useState(false);
    const [experimentDetailById, setExperimentDetailById] = useState<Record<string, CatalogExperimentRow>>({});
    /** After first fetch completes for a run id (success or missing detail). */
    const [experimentDetailAttempted, setExperimentDetailAttempted] = useState<Record<string, boolean>>({});
    const [runModalOpen, setRunModalOpen] = useState(false);
    const [assetsZipBusy, setAssetsZipBusy] = useState(false);

    /** Run ids known after last full dashboard refresh; null until a successful load. */
    const baselineRunIdsRef = useRef<Set<string> | null>(null);
    const experimentsPollInFlightRef = useRef(false);
    const [unreadNewRunIds, setUnreadNewRunIds] = useState<Set<string>>(() => new Set());

    const dismissAdminAlert = useCallback((id: string) => {
        switch (id) {
            case "dashboard":
                setDashboardError(null);
                break;
            case "promote":
                setPromoteError(null);
                break;
            case "train":
                setTrainError(null);
                break;
            case "artifacts":
                setArtifactsError(null);
                break;
            case "notice":
                setNotice(null);
                break;
            default:
                break;
        }
    }, []);

    const openExperimentRow = useCallback((runId: string) => {
        setUnreadNewRunIds((prev) => {
            if (!prev.has(runId)) return prev;
            const next = new Set(prev);
            next.delete(runId);
            return next;
        });
        setSelectedRunId(runId);
        setRunModalOpen(true);
    }, []);

    useEffect(() => {
        let cancelled = false;
        setDashboardLoading(true);
        setDashboardError(null);
        setArtifactsSectionLoading(true);
        setExperimentDetailById({});
        setExperimentDetailAttempted({});
        (async () => {
            try {
                const qs = new URLSearchParams({
                    include: "metrics,status,experiments",
                    experiments_detail: "false",
                    _v: String(dashboardRefreshKey),
                });
                const dashUrl = `${API_BASE}/api/admin/dashboard?${qs}`;
                // #region agent log
                const _dbgT0 = Date.now();
                fetch("http://127.0.0.1:7594/ingest/ed3a15b2-49f0-497a-963f-670e5d951c23", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "e7e3d5" },
                    body: JSON.stringify({
                        sessionId: "e7e3d5",
                        runId: "pre-fix",
                        hypothesisId: "H5",
                        location: "admin/models/page.tsx:dashboard_fetch",
                        message: "dashboard_fetch_start",
                        data: { dashboardRefreshKey, apiBaseLen: API_BASE.length },
                        timestamp: Date.now(),
                    }),
                }).catch(() => {});
                // #endregion agent log
                const res = await fetch(dashUrl, {
                    headers: authHeaders(),
                    cache: "no-store",
                });
                // #region agent log
                fetch("http://127.0.0.1:7594/ingest/ed3a15b2-49f0-497a-963f-670e5d951c23", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "e7e3d5" },
                    body: JSON.stringify({
                        sessionId: "e7e3d5",
                        runId: "pre-fix",
                        hypothesisId: "H5",
                        location: "admin/models/page.tsx:dashboard_fetch",
                        message: "dashboard_fetch_response",
                        data: {
                            ms: Date.now() - _dbgT0,
                            ok: res.ok,
                            status: res.status,
                        },
                        timestamp: Date.now(),
                    }),
                }).catch(() => {});
                // #endregion agent log
                let body: AdminDashboardPayload | { detail?: unknown } | null = null;
                try {
                    body = (await res.json()) as AdminDashboardPayload | { detail?: unknown };
                } catch {
                    body = null;
                }
                if (cancelled) return;
                if (!res.ok) {
                    const det =
                        body && typeof body === "object" && "detail" in body ? body.detail : null;
                    setDashboardError(typeof det === "string" ? det : `HTTP ${res.status}`);
                    baselineRunIdsRef.current = null;
                    setVersion(null);
                    setMetrics(null);
                    setCatalogExperiments([]);
                    setArtifacts([]);
                    setModelStatus(null);
                    setArtifactsError(null);
                    setArtifactsSectionLoading(false);
                    return;
                }
                const b = body as AdminDashboardPayload;
                const catRows = Array.isArray(b.experiments?.experiments) ? b.experiments.experiments : [];
                baselineRunIdsRef.current = new Set(catRows.map((r) => r.id));
                setUnreadNewRunIds(new Set());
                setDashboardError(null);
                setVersion(b.version ?? null);
                setMetrics(b.metrics ?? null);
                setCatalogExperiments(catRows);
                setModelStatus(b.model_status ?? null);
                setArtifactsError(null);
            } catch (e) {
                if (!cancelled) {
                    setDashboardError(e instanceof Error ? e.message : "Failed to load dashboard");
                    baselineRunIdsRef.current = null;
                    setVersion(null);
                    setMetrics(null);
                    setCatalogExperiments([]);
                    setArtifacts([]);
                    setModelStatus(null);
                    setArtifactsError(null);
                    setArtifactsSectionLoading(false);
                }
            } finally {
                if (!cancelled) setDashboardLoading(false);
            }

            if (cancelled) return;

            try {
                const artQs = new URLSearchParams({ _v: String(dashboardRefreshKey) });
                const artRes = await fetch(`${API_BASE}/api/admin/model/artifacts?${artQs}`, {
                    headers: authHeaders(),
                    cache: "no-store",
                });
                let artBody: { detail?: unknown; artifacts?: ValuationArtifactRow[] } | null = null;
                try {
                    artBody = await artRes.json();
                } catch {
                    artBody = null;
                }
                if (cancelled) return;
                if (!artRes.ok) {
                    setArtifacts([]);
                    const det = artBody?.detail;
                    setArtifactsError(typeof det === "string" ? det : `HTTP ${artRes.status}`);
                    return;
                }
                setArtifacts(Array.isArray(artBody?.artifacts) ? artBody!.artifacts! : []);
                setArtifactsError(null);
            } catch (err) {
                if (!cancelled) {
                    setArtifacts([]);
                    setArtifactsError(err instanceof Error ? err.message : "Failed to load artifacts");
                }
            } finally {
                if (!cancelled) setArtifactsSectionLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [dashboardRefreshKey]);

    /** Silent poll: refresh experiments + metrics without full-page loading or clearing lazy detail cache. */
    useEffect(() => {
        if (dashboardLoading || dashboardError) return;

        const tick = async () => {
            if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
            if (baselineRunIdsRef.current == null) return;
            if (experimentsPollInFlightRef.current) return;
            experimentsPollInFlightRef.current = true;
            try {
                const qs = new URLSearchParams({
                    include: "metrics,experiments",
                    experiments_detail: "false",
                    _v: String(Date.now()),
                });
                const res = await fetch(`${API_BASE}/api/admin/dashboard?${qs}`, {
                    headers: authHeaders(),
                    cache: "no-store",
                });
                let body: AdminDashboardPayload | { detail?: unknown } | null = null;
                try {
                    body = (await res.json()) as AdminDashboardPayload | { detail?: unknown };
                } catch {
                    body = null;
                }
                if (!res.ok) return;
                const b = body as AdminDashboardPayload;
                const rows = Array.isArray(b.experiments?.experiments) ? b.experiments.experiments : [];
                setCatalogExperiments(rows);
                setMetrics(b.metrics ?? null);
                const baseline = baselineRunIdsRef.current;
                const fresh = rows.map((r) => r.id).filter((id) => !baseline.has(id));
                if (fresh.length > 0) {
                    setUnreadNewRunIds((prev) => new Set([...prev, ...fresh]));
                }
            } catch {
                /* ignore — next interval retries */
            } finally {
                experimentsPollInFlightRef.current = false;
            }
        };

        const id = setInterval(tick, EXPERIMENTS_POLL_INTERVAL_MS);
        return () => {
            clearInterval(id);
        };
    }, [dashboardLoading, dashboardError]);

    useEffect(() => {
        if (!selectedRunId) return;
        const rid = selectedRunId;
        let cancelled = false;
        (async () => {
            try {
                const res = await fetch(
                    `${API_BASE}/api/admin/ml/experiment-run-detail?run_id=${encodeURIComponent(rid)}`,
                    { headers: authHeaders() },
                );
                let raw: { run?: CatalogExperimentRow; detail?: unknown } | null = null;
                try {
                    raw = await res.json();
                } catch {
                    raw = null;
                }
                if (cancelled) return;
                if (res.ok && raw?.run) {
                    setExperimentDetailById((prev) => {
                        if (prev[rid]) return prev;
                        return { ...prev, [rid]: raw!.run! };
                    });
                }
            } catch {
                /* ignore */
            } finally {
                if (!cancelled) {
                    setExperimentDetailAttempted((prev) => ({ ...prev, [rid]: true }));
                }
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [selectedRunId]);

    /** Lazy-load training DQ JSON only when exactly one rolling window is selected. */
    useEffect(() => {
        if (!metrics) {
            setDataReportLoading(false);
            return;
        }
        const oneYear = filterYearSet.size === 1 ? [...filterYearSet][0] : null;
        if (!oneYear) {
            setDataReportLoading(false);
            return;
        }
        let cancelled = false;
        setDataReportLoading(true);
        (async () => {
            try {
                const res = await fetch(`${API_BASE}/api/admin/ml/data-report`, {
                    headers: authHeaders(),
                });
                if (cancelled) return;
                setDataReport(res.ok ? ((await res.json()) as DataQualityReport) : null);
            } catch {
                if (!cancelled) setDataReport(null);
            } finally {
                if (!cancelled) setDataReportLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [metrics, filterYearSet, dashboardRefreshKey]);

    useEffect(() => {
        setExperimentsPage(1);
    }, [filterModels, filterFeatures, filterYearSet]);

    useEffect(() => {
        if (!activeFlowRunId) return;

        let cancelled = false;

        const tick = async () => {
            try {
                const res = await fetch(
                    `${API_BASE}/api/admin/model/train/status/${encodeURIComponent(activeFlowRunId)}`,
                    { headers: authHeaders() },
                );
                let data: { detail?: unknown; state?: string; state_message?: string } | null = null;
                try {
                    data = await res.json();
                } catch {
                    data = null;
                }
                if (cancelled) return;
                if (!res.ok) {
                    const det = data?.detail;
                    setTrainError(typeof det === "string" ? det : `HTTP ${res.status}`);
                    setActiveFlowRunId(null);
                    return;
                }
                const st = typeof data?.state === "string" ? data.state : "Running";
                const msg = typeof data?.state_message === "string" ? data.state_message : "";
                setTrainState(st);
                setTrainMessage(msg || null);
                if (st === "Completed") {
                    setNotice({
                        message: "Training completed. Artifacts list refreshed — promote when ready.",
                        variant: "success",
                    });
                    setDashboardRefreshKey((k) => k + 1);
                    setActiveFlowRunId(null);
                }
                if (st === "Failed") {
                    setTrainError(msg || "Training failed");
                    setActiveFlowRunId(null);
                }
            } catch (e) {
                if (!cancelled) {
                    setTrainError(e instanceof Error ? e.message : "Poll failed");
                    setActiveFlowRunId(null);
                }
            }
        };

        tick();
        const id = setInterval(tick, 5000);
        return () => {
            cancelled = true;
            clearInterval(id);
        };
    }, [activeFlowRunId]);

    const unifiedExperimentsBase = useMemo(
        () => buildUnifiedExperiments(catalogExperiments, metrics?.experiments ?? []),
        [catalogExperiments, metrics?.experiments],
    );

    const catalogRowsForResolve = useMemo(
        () => unifiedExperimentsBase.map((u) => u.catalog),
        [unifiedExperimentsBase],
    );

    const singleSelectedYearKey = useMemo(() => {
        if (filterYearSet.size !== 1) return null;
        return [...filterYearSet][0] ?? null;
    }, [filterYearSet]);

    const filteredSortedExperiments = useMemo(() => {
        let rows = [...unifiedExperimentsBase];
        if (filterModels.size > 0) {
            rows = rows.filter((u) => filterModels.has(unifiedModelFilterKey(u)));
        }
        if (filterFeatures.size > 0) {
            rows = rows.filter((u) => filterFeatures.has(unifiedFeatureFilterKey(u)));
        }
        if (filterYearSet.size > 0) {
            rows = rows.filter((u) => {
                const y = unifiedMrtYears(u);
                return y !== null && filterYearSet.has(String(y));
            });
        }

        rows.sort((a, b) => {
            const tiebreak = (primary: number): number => {
                if (primary !== 0) return primary;
                return a.catalog.id.localeCompare(b.catalog.id, undefined, { numeric: true, sensitivity: "base" });
            };

            if (sortKey === "run_id") {
                const cmp = a.catalog.id.localeCompare(b.catalog.id, undefined, { numeric: true, sensitivity: "base" });
                return tiebreak(sortAsc ? cmp : -cmp);
            }
            if (sortKey === "estimator") {
                const cmp = unifiedEstimatorLabel(a).localeCompare(unifiedEstimatorLabel(b), undefined, {
                    numeric: true,
                    sensitivity: "base",
                });
                return tiebreak(sortAsc ? cmp : -cmp);
            }
            if (sortKey === "feature_set") {
                const cmp = unifiedFeatureSetLabel(a).localeCompare(unifiedFeatureSetLabel(b), undefined, {
                    numeric: true,
                    sensitivity: "base",
                });
                return tiebreak(sortAsc ? cmp : -cmp);
            }
            if (sortKey === "has_metrics") {
                const va = a.catalog.has_metrics ? 1 : 0;
                const vb = b.catalog.has_metrics ? 1 : 0;
                const cmp = va < vb ? -1 : va > vb ? 1 : 0;
                return tiebreak(sortAsc ? cmp : -cmp);
            }
            if (sortKey === "has_minio_experiment") {
                const va = a.catalog.has_minio_experiment === true ? 1 : 0;
                const vb = b.catalog.has_minio_experiment === true ? 1 : 0;
                const cmp = va < vb ? -1 : va > vb ? 1 : 0;
                return tiebreak(sortAsc ? cmp : -cmp);
            }
            if (sortKey === "run_timestamp") {
                const ta = effectiveSortTimestampMs(a);
                const tb = effectiveSortTimestampMs(b);
                if (ta == null && tb == null) return tiebreak(0);
                if (ta == null) return tiebreak(sortAsc ? -1 : 1);
                if (tb == null) return tiebreak(sortAsc ? 1 : -1);
                const cmp = ta < tb ? -1 : ta > tb ? 1 : 0;
                return tiebreak(sortAsc ? cmp : -cmp);
            }
            let va: number | null;
            let vb: number | null;
            if (sortKey === "mrt_pit_min_years") {
                va = unifiedMrtYears(a);
                vb = unifiedMrtYears(b);
            } else if (sortKey === "training_wall_seconds") {
                va = unifiedTrainingWallSeconds(a);
                vb = unifiedTrainingWallSeconds(b);
            } else {
                va = unifiedSortMetric(a, sortKey);
                vb = unifiedSortMetric(b, sortKey);
            }
            if (va == null && vb == null) return tiebreak(0);
            if (va == null) return tiebreak(1);
            if (vb == null) return tiebreak(-1);
            const cmp = va < vb ? -1 : va > vb ? 1 : 0;
            return tiebreak(sortAsc ? cmp : -cmp);
        });
        return rows;
    }, [
        unifiedExperimentsBase,
        filterModels,
        filterFeatures,
        filterYearSet,
        sortKey,
        sortAsc,
    ]);

    const experimentsTotalPages = Math.max(1, Math.ceil(filteredSortedExperiments.length / PAGE_SIZE));

    const paginatedExperiments = useMemo(() => {
        const start = (experimentsPage - 1) * PAGE_SIZE;
        return filteredSortedExperiments.slice(start, start + PAGE_SIZE);
    }, [filteredSortedExperiments, experimentsPage]);

    useEffect(() => {
        if (experimentsPage > experimentsTotalPages) setExperimentsPage(experimentsTotalPages);
    }, [experimentsPage, experimentsTotalPages]);

    const rmseChartData = useMemo(() => {
        if (!metrics?.experiments || !singleSelectedYearKey) return [];
        const y = Number(singleSelectedYearKey);
        if (Number.isNaN(y)) return [];
        const scoped = metrics.experiments.filter((e) => e.mrt_pit_min_years === y);
        return buildRmseChartRows(scoped);
    }, [metrics, singleSelectedYearKey]);

    const dqForYear = useMemo(() => {
        if (!dataReport?.windows || !singleSelectedYearKey) return null;
        return dataReport.windows[singleSelectedYearKey] ?? null;
    }, [dataReport, singleSelectedYearKey]);

    const dqBadge = useMemo(() => {
        if (!dqForYear?.findings) return null;
        const { critical, warn } = severityCounts(dqForYear.findings);
        if (critical === 0 && warn === 0) {
            return (
                <span className="text-xs font-semibold px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-800 border border-emerald-500/30">
                    Data report: OK
                </span>
            );
        }
        return (
            <span className="inline-flex flex-wrap items-center gap-1.5 text-xs">
                {critical > 0 && (
                    <span className="font-semibold px-2 py-0.5 rounded-md bg-red-500/15 text-red-800 border border-red-500/30">
                        Critical {critical}
                    </span>
                )}
                {warn > 0 && (
                    <span className="font-semibold px-2 py-0.5 rounded-md bg-amber-500/15 text-amber-900 border border-amber-500/30">
                        Warn {warn}
                    </span>
                )}
            </span>
        );
    }, [dqForYear]);

    const selectedRun = useMemo(() => {
        const base = resolveMlRun(catalogRowsForResolve, selectedRunId);
        if (!selectedRunId || !base) return base;
        const extra = experimentDetailById[selectedRunId];
        if (!extra) return base;
        return {
            ...base,
            ...extra,
            config: extra.config ?? base.config,
            metrics: extra.metrics ?? base.metrics,
            best_params: extra.best_params ?? base.best_params,
        };
    }, [catalogRowsForResolve, selectedRunId, experimentDetailById]);

    const modalUnified = useMemo(() => {
        if (!selectedRunId) return null;
        return (
            filteredSortedExperiments.find((u) => u.catalog.id === selectedRunId) ??
            unifiedExperimentsBase.find((u) => u.catalog.id === selectedRunId) ??
            null
        );
    }, [selectedRunId, filteredSortedExperiments, unifiedExperimentsBase]);

    const modalSummaryLines = useMemo(() => {
        if (!modalUnified) return [];
        const lb = modalUnified.leaderboard;
        const rmse = unifiedDisplayRmse(modalUnified);
        const mrt = unifiedMrtYears(modalUnified);
        const lines: { label: string; value: string }[] = [
            { label: "Estimator", value: unifiedEstimatorLabel(modalUnified) },
            { label: "Feature set", value: unifiedFeatureSetLabel(modalUnified) },
            { label: "Timestamp (SGT)", value: displayStamp(modalUnified) },
            { label: "MRT window (years)", value: mrt != null ? String(mrt) : "—" },
            {
                label: "RMSE",
                value: rmse != null && typeof rmse === "number" ? formatSgdFull(rmse) : "—",
            },
            {
                label: "MAE",
                value: lb?.mae != null && typeof lb.mae === "number" ? formatSgdFull(lb.mae) : "—",
            },
            {
                label: "R²",
                value:
                    lb?.r2 != null && typeof lb.r2 === "number" && !Number.isNaN(Number(lb.r2))
                        ? Number(lb.r2).toFixed(4)
                        : "—",
            },
            {
                label: "MAPE",
                value:
                    lb?.mape != null && typeof lb.mape === "number"
                        ? `${(lb.mape * 100).toFixed(2)}%`
                        : "—",
            },
            {
                label: "CV RMSE",
                value:
                    lb?.cv_rmse != null && typeof lb.cv_rmse === "number"
                        ? formatSgdFull(lb.cv_rmse)
                        : "—",
            },
            {
                label: "N train",
                value: lb?.n_train != null ? lb.n_train.toLocaleString() : "—",
            },
            {
                label: "N test",
                value: lb?.n_test != null ? lb.n_test.toLocaleString() : "—",
            },
            {
                label: "Train time",
                value: formatTrainingWallHuman(unifiedTrainingWallSeconds(modalUnified)),
            },
        ];
        const dm = selectedRun?.metrics as Record<string, unknown> | undefined;
        const fsV = unifiedFeatureSelectionPolicy({
            leaderboard: lb ?? undefined,
            catalog: modalUnified.catalog,
            detailMetrics: dm,
        });
        let fsLine = formatFeatureSelectionPolicyShort(fsV.policy);
        if (
            fsV.policy === "apply_recommended_drops" &&
            fsV.columnsRemovedCount != null &&
            fsV.columnsRemovedCount > 0
        ) {
            fsLine += ` (${fsV.columnsRemovedCount} columns removed)`;
        }
        lines.push({ label: "Feature selection", value: fsLine });
        const pok = modalUnified.catalog.publish_object_key;
        if (pok) lines.push({ label: "Publish object key", value: pok });
        return lines;
    }, [modalUnified, selectedRun?.metrics]);

    const modalJsonPretty = useMemo(() => {
        const pretty = (v: unknown): string | null => {
            if (v === undefined || v === null) return null;
            try {
                return JSON.stringify(v, null, 2);
            } catch {
                return null;
            }
        };
        return {
            config: pretty(selectedRun?.config),
            metrics: pretty(selectedRun?.metrics),
            bestParams: pretty(selectedRun?.best_params),
        };
    }, [selectedRun]);

    const modalDetailLoading =
        !!selectedRunId && experimentDetailAttempted[selectedRunId] !== true;

    const modalFeatureSelectionBadge = useMemo(() => {
        if (!modalUnified) return null;
        const dm = selectedRun?.metrics as Record<string, unknown> | undefined;
        const fsV = unifiedFeatureSelectionPolicy({
            leaderboard: modalUnified.leaderboard,
            catalog: modalUnified.catalog,
            detailMetrics: dm,
        });
        return {
            policyLabel: formatFeatureSelectionPolicyShort(fsV.policy),
            variant: featureSelectionBadgeVariantFromPolicy(fsV.policy),
        };
    }, [modalUnified, selectedRun?.metrics]);

    const canZipAssets = useMemo(() => {
        const r = selectedRun as CatalogExperimentRow | MLRun | undefined;
        if (!r) return false;
        const cat = r as CatalogExperimentRow;
        return !!(
            cat.published ||
            cat.has_minio_experiment === true ||
            cat.has_minio_artifact === true
        );
    }, [selectedRun]);

    const toggleSort = (key: SortKey) => {
        if (sortKey === key) {
            setSortAsc(!sortAsc);
        } else {
            setSortKey(key);
            /** Ascending first for label columns; descending first for numeric booleans (stronger signal first). */
            const ascFirst =
                key === "mrt_pit_min_years" ||
                key === "run_id" ||
                key === "estimator" ||
                key === "feature_set";
            setSortAsc(ascFirst);
        }
    };

    const startTraining = async (run: MLRun | null | undefined) => {
        const payload = deriveTrainPayload(run);
        if (!payload) {
            setTrainError("Select a run with experiment metadata.");
            return;
        }
        setTrainStarting(true);
        setTrainError(null);
        setNotice(null);
        try {
            const res = await fetch(`${API_BASE}/api/admin/model/train`, {
                method: "POST",
                headers: { ...authHeaders(), "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            let data: { detail?: unknown; flow_run_id?: string } = {};
            try {
                data = await res.json();
            } catch {
                data = {};
            }
            if (res.status === 503) {
                setTrainError(
                    typeof data.detail === "string"
                        ? data.detail
                        : "Prefect not configured. Set PREFECT_API_URL or train via CLI.",
                );
                return;
            }
            if (!res.ok) {
                setTrainError(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
                return;
            }
            if (!data.flow_run_id) {
                setTrainError("Prefect did not return flow_run_id.");
                return;
            }
            setTrainPanelOpen(true);
            setTrainState("Running");
            setTrainMessage("Flow run started…");
            setActiveFlowRunId(String(data.flow_run_id));
        } finally {
            setTrainStarting(false);
        }
    };

    const promoteArtifact = async (
        objectKey: string,
        meta?: { estimator: string; mae?: number | null },
    ) => {
        setPromotingKey(objectKey);
        setPromoteError(null);
        try {
            const res = await fetch(`${API_BASE}/api/admin/model/promote`, {
                method: "POST",
                headers: { ...authHeaders(), "Content-Type": "application/json" },
                body: JSON.stringify({ object_key: objectKey }),
            });
            let data: { detail?: unknown; model_status?: ModelServingStatus } = {};
            try {
                data = await res.json();
            } catch {
                data = {};
            }
            if (!res.ok) {
                setPromoteError(formatApiErrorDetail(data.detail) || `HTTP ${res.status}`);
                return;
            }
            setPromoteError(null);
            if (data.model_status && typeof data.model_status === "object") {
                setModelStatus(data.model_status);
            }
            setNotice({
                message: meta
                    ? buildPromoteSuccessNotice(meta.estimator, meta.mae)
                    : "Production model updated (registry + hot-reload).",
                variant: "success",
            });
            setDashboardRefreshKey((k) => k + 1);
        } catch (e) {
            setPromoteError(e instanceof Error ? e.message : "Network error while publishing");
        } finally {
            setPromotingKey(null);
        }
    };

    const modelEnv = version?.model_env ?? "…";
    const modelEnvForApi = version?.model_env?.trim() || "prod";
    const best = metrics?.best;
    const productionLb = useMemo(
        () => leaderboardRowForServing(metrics?.experiments, modelStatus),
        [metrics?.experiments, modelStatus],
    );
    /** Default retrain target: served model's run on the leaderboard, else global best */
    const trainFallbackRunId = productionLb?.id ?? metrics?.best?.id ?? null;
    const productionDisplayRmse =
        modelStatus?.holdout_rmse != null && typeof modelStatus.holdout_rmse === "number"
            ? modelStatus.holdout_rmse
            : productionLb?.rmse ?? null;
    const productionTitleEstimator =
        modelStatus?.model_id ?? productionLb?.model_id ?? productionLb?.estimator ?? "—";

    const adminAlerts = useMemo((): AdminAlertItem[] => {
        const list: AdminAlertItem[] = [];
        if (dashboardError) {
            list.push({
                id: "dashboard",
                variant: "error",
                message: `Dashboard load failed: ${dashboardError}`,
                actions: (
                    <button
                        type="button"
                        className="text-xs font-semibold underline underline-offset-2"
                        onClick={() => setDashboardRefreshKey((k) => k + 1)}
                    >
                        Retry
                    </button>
                ),
            });
        }
        if (promoteError) {
            list.push({
                id: "promote",
                variant: "error",
                message: `Publish failed: ${promoteError}`,
            });
        }
        if (trainError) {
            list.push({
                id: "train",
                variant: "error",
                message: `Training failed: ${trainError}\n\nTip: training uploads to models/${modelEnv}/valuation/experiments/<run>/model.pkl`,
            });
        }
        if (artifactsError) {
            list.push({
                id: "artifacts",
                variant: "warning",
                message: artifactsError,
            });
        }
        if (notice) {
            list.push({
                id: "notice",
                variant: notice.variant,
                message: notice.message,
                autoDismissMs: notice.variant === "success" ? 9000 : undefined,
            });
        }
        return list;
    }, [dashboardError, promoteError, trainError, artifactsError, notice, modelEnv]);

    return (
        <RequireAuth role="admin">
            <main className="min-h-screen bg-slate-50 pb-20">
                <Navbar />

                <div className="max-w-6xl mx-auto pt-28 px-4 sm:px-6 lg:px-8">
                    <AdminAlertStack alerts={adminAlerts} onDismiss={dismissAdminAlert} />

                    <Link
                        href="/admin"
                        className="inline-flex items-center gap-1 text-sm text-foreground/50 hover:text-foreground mb-6 transition-colors"
                    >
                        <ArrowLeft className="w-4 h-4" /> Admin dashboard
                    </Link>

                    <div className="rounded-2xl border border-slate-200 bg-white/90 px-4 py-3 mb-8 flex flex-col gap-3 text-sm text-slate-700">
                        <div className="flex flex-wrap items-start gap-2">
                            <Sparkles className="w-4 h-4 shrink-0 mt-0.5 text-violet-600" />
                            <p>
                                Leaderboard rows come from MinIO{" "}
                                <code className="text-[11px] bg-slate-100 px-1 rounded">valuation/experiments</code> and legacy{" "}
                                <code className="text-[11px] bg-slate-100 px-1 rounded">artifacts</code>. Retrain triggers your Prefect training
                                deployment when <code className="text-[11px] bg-slate-100 px-1 rounded">PREFECT_API_URL</code> is set.
                            </p>
                        </div>
                        {(activeFlowRunId || trainError || trainState) && (
                            <div className="rounded-xl border border-violet-500/25 bg-violet-500/5 overflow-hidden">
                                <button
                                    type="button"
                                    className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left text-xs font-bold uppercase tracking-wide text-violet-900"
                                    onClick={() => setTrainPanelOpen((o) => !o)}
                                >
                                    <span className="inline-flex items-center gap-2">
                                        <Activity className="w-4 h-4" />
                                        Training job
                                        {activeFlowRunId && (
                                            <span className="font-mono font-normal normal-case text-[11px] opacity-80">
                                                {activeFlowRunId.slice(0, 8)}…
                                            </span>
                                        )}
                                    </span>
                                    {trainPanelOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                                </button>
                                {trainPanelOpen && (
                                    <div className="px-3 pb-3 pt-0 space-y-2 text-sm text-slate-700">
                                        {trainError ? (
                                            <p className="text-xs text-foreground/55">
                                                Error details are in the banner above (copy supported).
                                            </p>
                                        ) : (
                                            <>
                                                <p className="text-xs font-semibold text-violet-800">
                                                    State: {trainState ?? "—"}
                                                </p>
                                                <p className="text-xs text-foreground/70 whitespace-pre-wrap">{trainMessage ?? "—"}</p>
                                                {activeFlowRunId && (
                                                    <p className="text-[11px] text-foreground/45">
                                                        Polling <code className="bg-slate-100 px-1 rounded">/api/admin/model/train/status</code>{" "}
                                                        every 5s.
                                                    </p>
                                                )}
                                            </>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>

                    <div className="mb-8">
                        <span className="text-red-500 font-bold uppercase tracking-widest text-xs">Machine learning</span>
                        <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight mt-2 flex flex-wrap items-center gap-3">
                            Model management
                            <span className="text-sm font-medium px-2 py-1 rounded-md bg-violet-500/15 text-violet-700 border border-violet-500/25 inline-flex items-center gap-1">
                                <Brain className="w-4 h-4" /> Admin
                            </span>
                        </h1>
                        <p className="text-foreground/50 mt-2 text-sm max-w-2xl">
                            Monitor valuation models, kick off retraining, and review drift signals — one place for ML operations.
                        </p>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-10">
                        <div className="rounded-xl border border-foreground/10 bg-white/60 px-4 py-3">
                            <p className="text-[10px] font-bold uppercase tracking-wider text-foreground/40">MODEL_ENV</p>
                            <p className="text-lg font-bold font-mono text-violet-600">{modelEnv}</p>
                            <p className="text-xs text-foreground/45 mt-1">
                                {version ? `MinIO prefix: models/${modelEnv}/` : "Loading…"}
                            </p>
                        </div>
                        <div className="rounded-xl border border-foreground/10 bg-white/60 px-4 py-3">
                            <p className="text-[10px] font-bold uppercase tracking-wider text-foreground/40">API version</p>
                            <p className="text-lg font-bold font-mono">{version?.version ?? "—"}</p>
                            <p className="text-xs text-foreground/45 mt-1 truncate" title={version?.commit}>
                                {version?.commit ? `Git ${version.commit.slice(0, 7)}` : "Commit unknown"}
                            </p>
                        </div>
                        <div className="rounded-xl border border-foreground/10 bg-white/60 px-4 py-3">
                            <p className="text-[10px] font-bold uppercase tracking-wider text-foreground/40">Serving</p>
                            <p
                                className={`text-lg font-bold ${
                                    modelStatus?.is_ready ? "text-emerald-600" : "text-amber-600"
                                }`}
                            >
                                {modelStatus?.is_ready ? "Ready" : "Not ready"}
                            </p>
                            <p className="text-xs text-foreground/45 mt-1 font-mono truncate" title={modelStatus?.model_object_key ?? ""}>
                                {modelStatus?.feature_set_id ?? "—"}
                                {modelStatus?.model_id ? ` · ${modelStatus.model_id}` : ""}
                            </p>
                            {modelStatus?.load_error && (
                                <p className="text-[11px] text-red-700 mt-2 leading-snug">{modelStatus.load_error}</p>
                            )}
                            {modelStatus?.experiment_id && (
                                <p className="text-[10px] text-foreground/40 mt-1 truncate" title={modelStatus.experiment_id}>
                                    Exp <span className="font-mono">{modelStatus.experiment_id}</span>
                                </p>
                            )}
                            {modelStatus?.promoted_at && (
                                <p className="text-[10px] text-foreground/40 mt-1">
                                    Registry{" "}
                                    <span className="font-mono">{new Date(modelStatus.promoted_at).toLocaleString()}</span>
                                    {modelStatus.promoted_by ? ` · ${modelStatus.promoted_by}` : ""}
                                </p>
                            )}
                            <p className="text-[10px] text-foreground/35 mt-2">
                                Live from <code className="bg-foreground/10 px-1 rounded">/api/admin/model/status</code>
                            </p>
                        </div>
                    </div>

                    <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                        <Layers className="w-5 h-5 text-secondary" /> Registered models
                    </h2>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-10">
                        <div className="glass rounded-2xl p-6 border-2 border-secondary/30 border-l-4 border-l-secondary shadow-lg">
                            <div className="flex items-start justify-between gap-3 mb-4">
                                <div>
                                    <p className="text-xs font-bold uppercase tracking-wider text-secondary">Production (live API)</p>
                                    <h3 className="text-xl font-bold mt-1">
                                        Valuation — <span className="capitalize">{productionTitleEstimator}</span>
                                    </h3>
                                    <p className="text-sm text-foreground/50 mt-1">
                                        Primary HDB / condo price estimator — metrics below match what is loaded for{" "}
                                        <code className="text-[10px] bg-secondary/10 px-1 rounded">/api/valuation</code>
                                        {modelStatus?.experiment_id && (
                                            <span className="block mt-1 font-mono text-[11px] text-secondary/80">
                                                Served run / experiment:{" "}
                                                <code className="bg-secondary/10 px-1 rounded">{modelStatus.experiment_id}</code>
                                            </span>
                                        )}
                                        {best && productionLb?.id !== best.id && (
                                            <span className="block mt-1 text-[11px] text-foreground/50">
                                                Leaderboard lowest-RMSE row (for comparison):{" "}
                                                <code className="bg-foreground/10 px-1 rounded font-mono">{best.id}</code>
                                            </span>
                                        )}
                                    </p>
                                </div>
                                <Box className="w-10 h-10 text-secondary opacity-80 shrink-0" />
                            </div>
                            <div className="grid grid-cols-2 gap-3 mb-5">
                                <div className="rounded-xl bg-white/50 border border-foreground/5 p-3">
                                    <p className="text-[10px] font-semibold text-foreground/45 uppercase">R²</p>
                                    <p className="text-2xl font-black text-secondary">
                                        {productionLb?.r2 != null ? Number(productionLb.r2).toFixed(4) : "—"}
                                    </p>
                                </div>
                                <div className="rounded-xl bg-white/50 border border-foreground/5 p-3">
                                    <p className="text-[10px] font-semibold text-foreground/45 uppercase">MAE (holdout)</p>
                                    <p className="text-2xl font-black text-secondary">
                                        {productionLb?.mae != null ? formatSgdCompact(productionLb.mae) : "—"}
                                    </p>
                                    <p className="text-[10px] text-foreground/40">S$</p>
                                </div>
                                <div className="rounded-xl bg-white/50 border border-foreground/5 p-3">
                                    <p className="text-[10px] font-semibold text-foreground/45 uppercase">RMSE (holdout)</p>
                                    <p className="text-xl font-bold">
                                        {productionDisplayRmse != null ? formatSgdCompact(productionDisplayRmse) : "—"}
                                    </p>
                                    <p className="text-[10px] text-foreground/40">S$</p>
                                </div>
                                <div className="rounded-xl bg-white/50 border border-foreground/5 p-3">
                                    <p className="text-[10px] font-semibold text-foreground/45 uppercase">N train</p>
                                    <p className="text-xl font-bold">
                                        {productionLb?.n_train != null ? productionLb.n_train.toLocaleString() : "—"}
                                    </p>
                                </div>
                            </div>
                            <div className="flex flex-wrap items-center gap-2 text-xs text-foreground/50 mb-4">
                                <Clock className="w-3.5 h-3.5" />
                                R² / MAE / N train from the leaderboard row matched to the served experiment when possible;
                                RMSE prefers the live model&apos;s holdout metric (sidecar) when available.
                            </div>
                            <button
                                type="button"
                                disabled={trainStarting || !!activeFlowRunId}
                                onClick={() =>
                                    startTraining(selectedRun ?? resolveMlRun(catalogRowsForResolve, trainFallbackRunId))
                                }
                                title={
                                    !deriveTrainPayload(
                                        selectedRun ?? resolveMlRun(catalogRowsForResolve, trainFallbackRunId),
                                    )
                                        ? "Select a leaderboard/run row with experiment metadata"
                                        : undefined
                                }
                                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-secondary text-white font-bold shadow-md hover:shadow-lg transition-all disabled:opacity-60"
                            >
                                {trainStarting || activeFlowRunId ? (
                                    <>
                                        <RefreshCw className="w-4 h-4 animate-spin" /> Training…
                                    </>
                                ) : (
                                    <>
                                        <Activity className="w-4 h-4" /> Start retrain (Prefect)
                                    </>
                                )}
                            </button>
                            <p className="text-[11px] text-foreground/45 mt-2">
                                Uses selected run; otherwise the served model&apos;s leaderboard row when it matches, else the
                                lowest-RMSE &quot;best&quot; row. Requires{" "}
                                <code className="bg-foreground/10 px-1 rounded">PREFECT_API_URL</code>.
                            </p>
                        </div>

                        <div className="rounded-2xl p-6 border border-dashed border-foreground/20 bg-foreground/[0.02] opacity-80">
                            <p className="text-xs font-bold uppercase tracking-wider text-foreground/40">Experimental</p>
                            <h3 className="text-lg font-bold mt-2 text-foreground/70">Ensemble / calibration</h3>
                            <p className="text-sm text-foreground/45 mt-2 mb-4">
                                Placeholder for a second stage (e.g. conformal intervals or stacked models). Not deployed.
                            </p>
                            <span className="inline-flex text-xs font-semibold px-2 py-1 rounded-md bg-foreground/10 text-foreground/50">
                                Coming soon
                            </span>
                        </div>
                    </div>

                    {dashboardLoading && unifiedExperimentsBase.length === 0 ? (
                        <ExperimentsTableSkeleton />
                    ) : unifiedExperimentsBase.length > 0 ? (
                        <div className="space-y-8 mb-10">
                            <div className="glass rounded-2xl p-6 border border-foreground/5">
                                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-4">
                                    <div>
                                        <h2 className="text-lg font-bold mb-1 flex items-center gap-2">
                                            <BarChart3 className="w-5 h-5" /> Experiments
                                            {unreadNewRunIds.size > 0 && (
                                                <span
                                                    className="w-2 h-2 rounded-full bg-blue-500 shrink-0"
                                                    title="New experiments"
                                                    aria-hidden
                                                />
                                            )}
                                        </h2>
                                        <p className="text-sm text-foreground/50">
                                            All catalog runs merged with leaderboard metrics. Sortable; default newest first. Multi-select filters;
                                            empty = all. Click a row for details and downloads.
                                        </p>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-2 shrink-0">
                                        {singleSelectedYearKey && dataReportLoading ? (
                                            <span className="inline-flex items-center gap-1 text-xs font-semibold text-foreground/55 px-2 py-1 rounded-md border border-foreground/10 bg-white">
                                                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                                                Data report…
                                            </span>
                                        ) : (
                                            dqBadge
                                        )}
                                        <button
                                            type="button"
                                            onClick={() => setDashboardRefreshKey((k) => k + 1)}
                                            className="inline-flex items-center gap-1.5 rounded-lg border border-foreground/15 bg-white px-2.5 py-1.5 text-xs font-semibold text-foreground/80 hover:bg-foreground/[0.04]"
                                        >
                                            <RefreshCw className="w-3.5 h-3.5" />
                                            Refresh
                                        </button>
                                    </div>
                                </div>

                                <div className="flex flex-wrap gap-4 mb-4">
                                    <FilterMultiDropdown
                                        label="Model"
                                        options={MODEL_MULTI_OPTIONS}
                                        selected={filterModels}
                                        onChange={setFilterModels}
                                    />
                                    <FilterMultiDropdown
                                        label="Feature set"
                                        options={FEATURE_MULTI_OPTIONS}
                                        selected={filterFeatures}
                                        onChange={setFilterFeatures}
                                    />
                                    <FilterMultiDropdown
                                        label="Rolling window"
                                        options={YEARS_MULTI_OPTIONS}
                                        selected={filterYearSet}
                                        onChange={setFilterYearSet}
                                    />
                                </div>

                                {dqForYear && dqForYear.findings && dqForYear.findings.length > 0 && singleSelectedYearKey && (
                                    <div className="mb-4 rounded-xl border border-foreground/10 bg-foreground/[0.02] p-3 text-xs max-h-40 overflow-y-auto">
                                        <p className="font-bold text-foreground/70 mb-2">
                                            Data quality ({singleSelectedYearKey}y window)
                                        </p>
                                        <ul className="space-y-1 text-foreground/65 list-disc list-inside">
                                            {dqForYear.findings.slice(0, 12).map((f, i) => (
                                                <li key={`${f.code ?? i}-${i}`}>
                                                    <span className="font-semibold text-foreground/50">[{f.severity}]</span>{" "}
                                                    {f.message}
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                )}

                                <div className="overflow-x-auto rounded-xl border border-foreground/10">
                                    <table className="w-full text-sm text-left min-w-[1320px]">
                                        <thead>
                                            <tr className="border-b border-foreground/10 bg-foreground/[0.03]">
                                                <th className="px-3 py-2">
                                                    <SortHeader
                                                        label="Run"
                                                        active={sortKey === "run_id"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("run_id")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2 text-left">
                                                    <SortHeader
                                                        label="Timestamp (SGT)"
                                                        active={sortKey === "run_timestamp"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("run_timestamp")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2">
                                                    <SortHeader
                                                        label="Estimator"
                                                        active={sortKey === "estimator"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("estimator")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2">
                                                    <SortHeader
                                                        label="Feature set"
                                                        active={sortKey === "feature_set"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("feature_set")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2 text-center">
                                                    <span className="text-xs font-semibold text-foreground/70">
                                                        Feature selection
                                                    </span>
                                                </th>
                                                <th className="px-3 py-2 text-right">
                                                    <SortHeader
                                                        label="Years"
                                                        active={sortKey === "mrt_pit_min_years"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("mrt_pit_min_years")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2 text-center">
                                                    <SortHeader
                                                        label="Metrics"
                                                        active={sortKey === "has_metrics"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("has_metrics")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2 text-center">
                                                    <SortHeader
                                                        label="In MinIO"
                                                        active={sortKey === "has_minio_experiment"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("has_minio_experiment")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2 text-right">
                                                    <SortHeader
                                                        label="RMSE"
                                                        active={sortKey === "rmse"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("rmse")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2 text-right">
                                                    <SortHeader
                                                        label="MAE"
                                                        active={sortKey === "mae"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("mae")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2 text-right">
                                                    <SortHeader
                                                        label="R²"
                                                        active={sortKey === "r2"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("r2")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2 text-right">
                                                    <SortHeader
                                                        label="MAPE"
                                                        active={sortKey === "mape"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("mape")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2 text-right">
                                                    <SortHeader
                                                        label="CV RMSE"
                                                        active={sortKey === "cv_rmse"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("cv_rmse")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2 text-right">
                                                    <SortHeader
                                                        label="N train"
                                                        active={sortKey === "n_train"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("n_train")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2 text-right">
                                                    <SortHeader
                                                        label="N test"
                                                        active={sortKey === "n_test"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("n_test")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2 text-right">
                                                    <SortHeader
                                                        label="Train time"
                                                        active={sortKey === "training_wall_seconds"}
                                                        asc={sortAsc}
                                                        onClick={() => toggleSort("training_wall_seconds")}
                                                    />
                                                </th>
                                                <th className="px-3 py-2">Publish live</th>
                                                <th className="px-3 py-2">Retrain</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {paginatedExperiments.length === 0 ? (
                                                <tr>
                                                    <td colSpan={18} className="px-3 py-6 text-center text-foreground/50 text-sm">
                                                        No experiments match the current filters.
                                                    </td>
                                                </tr>
                                            ) : (
                                                paginatedExperiments.map((u) => {
                                                    const row = u.leaderboard;
                                                    const cid = u.catalog.id;
                                                    const rmseVal = unifiedDisplayRmse(u);
                                                    const isBest = rowMatchesBest(u, metrics?.best?.id);
                                                    const isSel = cid === selectedRunId;
                                                    const isUnreadNew = unreadNewRunIds.has(cid);
                                                    const rowDetailMetrics = experimentDetailById[cid]?.metrics as
                                                        | Record<string, unknown>
                                                        | undefined;
                                                    const fsRow = unifiedFeatureSelectionPolicy({
                                                        leaderboard: row ?? undefined,
                                                        catalog: u.catalog,
                                                        detailMetrics: rowDetailMetrics,
                                                    });
                                                    return (
                                                        <tr
                                                            key={cid}
                                                            role="button"
                                                            tabIndex={0}
                                                            onClick={() => openExperimentRow(cid)}
                                                            onKeyDown={(ev) => {
                                                                if (ev.key === "Enter" || ev.key === " ") {
                                                                    ev.preventDefault();
                                                                    openExperimentRow(cid);
                                                                }
                                                            }}
                                                            className={`border-b border-foreground/5 cursor-pointer hover:bg-foreground/[0.04] ${
                                                                isBest ? "bg-emerald-500/10" : ""
                                                            } ${!isBest && isUnreadNew ? "bg-blue-500/5" : ""} ${
                                                                isSel ? "ring-1 ring-inset ring-violet-400/50" : ""
                                                            }`}
                                                        >
                                                            <td
                                                                className="px-3 py-2.5 font-mono text-[11px] max-w-[14rem] truncate"
                                                                title={cid}
                                                            >
                                                                <span className="inline-flex items-center gap-1.5 min-w-0">
                                                                    {isUnreadNew && (
                                                                        <span
                                                                            className="w-2 h-2 rounded-full bg-blue-500 shrink-0"
                                                                            aria-label="New experiment"
                                                                        />
                                                                    )}
                                                                    <span className="truncate">{cid}</span>
                                                                </span>
                                                            </td>
                                                            <td
                                                                className="px-3 py-2.5 text-left text-xs tabular-nums whitespace-nowrap"
                                                                title={displayStamp(u)}
                                                            >
                                                                {displayStamp(u)}
                                                            </td>
                                                            <td className="px-3 py-2.5">
                                                                {row?.estimator ?? catalogRowModelId(u.catalog)}
                                                            </td>
                                                            <td className="px-3 py-2.5 font-mono text-[11px]">
                                                                {row?.feature_set_id || row?.feature_set || catalogRowFeatureSetId(u.catalog)}
                                                            </td>
                                                            <td className="px-3 py-2.5 text-center whitespace-nowrap">
                                                                <FeatureSelectionTableBadge
                                                                    policy={fsRow.policy}
                                                                    columnsRemoved={fsRow.columnsRemovedCount}
                                                                />
                                                            </td>
                                                            <td className="px-3 py-2.5 text-right tabular-nums">
                                                                {unifiedMrtYears(u) ?? "—"}
                                                            </td>
                                                            <td className="px-3 py-2.5 text-center">
                                                                {u.catalog.has_metrics ? (
                                                                    <span className="text-[11px] font-semibold text-emerald-700">Yes</span>
                                                                ) : (
                                                                    <span className="text-[11px] font-semibold text-foreground/45">No</span>
                                                                )}
                                                            </td>
                                                            <td className="px-3 py-2.5 text-center">
                                                                {u.catalog.has_minio_experiment === true ? (
                                                                    <span className="font-semibold px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-800 border border-emerald-500/30 text-[11px]">
                                                                        Yes
                                                                    </span>
                                                                ) : (
                                                                    <span className="font-semibold px-2 py-0.5 rounded-md bg-amber-500/15 text-amber-900 border border-amber-500/30 text-[11px]">
                                                                        No
                                                                    </span>
                                                                )}
                                                            </td>
                                                            <td className="px-3 py-2.5 text-right font-mono text-[11px]">
                                                                {rmseVal != null ? formatSgdFull(rmseVal) : "—"}
                                                            </td>
                                                            <td className="px-3 py-2.5 text-right font-mono text-[11px]">
                                                                {row?.mae != null ? formatSgdFull(row.mae) : "—"}
                                                            </td>
                                                            <td className="px-3 py-2.5 text-right">
                                                                {row?.r2 != null && !Number.isNaN(Number(row.r2))
                                                                    ? Number(row.r2).toFixed(4)
                                                                    : "—"}
                                                            </td>
                                                            <td className="px-3 py-2.5 text-right text-xs">
                                                                {row?.mape != null ? `${(row.mape * 100).toFixed(2)}%` : "—"}
                                                            </td>
                                                            <td className="px-3 py-2.5 text-right font-mono text-[11px]">
                                                                {row?.cv_rmse != null ? formatSgdFull(row.cv_rmse) : "—"}
                                                            </td>
                                                            <td className="px-3 py-2.5 text-right tabular-nums">
                                                                {row?.n_train != null ? row.n_train.toLocaleString() : "—"}
                                                            </td>
                                                            <td className="px-3 py-2.5 text-right tabular-nums">
                                                                {row?.n_test != null ? row.n_test.toLocaleString() : "—"}
                                                            </td>
                                                            <td className="px-3 py-2.5 text-right tabular-nums text-xs whitespace-nowrap">
                                                                {formatTrainingWallHuman(unifiedTrainingWallSeconds(u))}
                                                            </td>
                                                            <td className="px-3 py-2.5">
                                                                {u.catalog.publish_object_key ? (
                                                                    <button
                                                                        type="button"
                                                                        className="inline-flex items-center gap-1 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[11px] font-bold text-emerald-900 hover:bg-emerald-500/15 disabled:opacity-45"
                                                                        disabled={
                                                                            promotingKey === u.catalog.publish_object_key
                                                                        }
                                                                        title="Set as production model (Postgres registry + hot-reload)"
                                                                        onClick={(ev) => {
                                                                            ev.stopPropagation();
                                                                            if (u.catalog.publish_object_key)
                                                                                promoteArtifact(u.catalog.publish_object_key, {
                                                                                    estimator: unifiedEstimatorLabel(u),
                                                                                    mae: u.leaderboard?.mae ?? null,
                                                                                });
                                                                        }}
                                                                    >
                                                                        {promotingKey === u.catalog.publish_object_key ? (
                                                                            <RefreshCw className="w-3 h-3 animate-spin" />
                                                                        ) : null}
                                                                        Publish live
                                                                    </button>
                                                                ) : (
                                                                    <span className="text-[11px] text-foreground/40">—</span>
                                                                )}
                                                            </td>
                                                            <td className="px-3 py-2.5">
                                                                <button
                                                                    type="button"
                                                                    className="inline-flex items-center gap-1 rounded-lg border border-secondary/40 bg-secondary/10 px-2 py-1 text-[11px] font-bold text-secondary hover:bg-secondary/15 disabled:opacity-45 disabled:cursor-not-allowed"
                                                                    disabled={trainStarting || !!activeFlowRunId}
                                                                    title="Trigger Prefect training (requires PREFECT_API_URL)"
                                                                    onClick={(ev) => {
                                                                        ev.stopPropagation();
                                                                        startTraining(u.catalog);
                                                                    }}
                                                                >
                                                                    <Activity className="w-3 h-3" /> Retrain
                                                                </button>
                                                            </td>
                                                        </tr>
                                                    );
                                                })
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mt-3">
                                    <p className="text-xs text-foreground/45">
                                        {filteredSortedExperiments.length === 0 ? (
                                            <>0 rows after filters.</>
                                        ) : (
                                            <>
                                                Showing {(experimentsPage - 1) * PAGE_SIZE + 1}–
                                                {Math.min(experimentsPage * PAGE_SIZE, filteredSortedExperiments.length)} of{" "}
                                                {filteredSortedExperiments.length} · Page {experimentsPage} / {experimentsTotalPages}
                                            </>
                                        )}{" "}
                                        Run directory (for artefacts):{" "}
                                        <span className="font-mono">{selectedRun?.id ?? "—"}</span>
                                    </p>
                                    <div className="flex items-center gap-2 shrink-0">
                                        <button
                                            type="button"
                                            disabled={experimentsPage <= 1}
                                            onClick={() => setExperimentsPage((p) => Math.max(1, p - 1))}
                                            className="rounded-lg border border-foreground/15 bg-white px-3 py-1.5 text-xs font-semibold text-foreground/80 hover:bg-foreground/[0.04] disabled:opacity-40 disabled:cursor-not-allowed"
                                        >
                                            Previous
                                        </button>
                                        <button
                                            type="button"
                                            disabled={experimentsPage >= experimentsTotalPages}
                                            onClick={() => setExperimentsPage((p) => Math.min(experimentsTotalPages, p + 1))}
                                            className="rounded-lg border border-foreground/15 bg-white px-3 py-1.5 text-xs font-semibold text-foreground/80 hover:bg-foreground/[0.04] disabled:opacity-40 disabled:cursor-not-allowed"
                                        >
                                            Next
                                        </button>
                                    </div>
                                </div>
                            </div>

                            {singleSelectedYearKey && rmseChartData.length > 0 && (
                                <div className="glass rounded-2xl p-6 border border-foreground/5">
                                    <h2 className="text-lg font-bold mb-1">
                                        RMSE: baseline_v1 vs mrt_pit ({singleSelectedYearKey}-year window)
                                    </h2>
                                    <p className="text-sm text-foreground/50 mb-4">
                                        Chart is scoped to a single rolling window so bars stay comparable.
                                    </p>
                                    <div className="h-72 w-full min-w-0">
                                        <ResponsiveContainer width="100%" height="100%">
                                            <BarChart data={rmseChartData} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                                                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                                                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                                                <YAxis
                                                    tick={{ fontSize: 11 }}
                                                    tickFormatter={(v) => `${Number(v) / 1000}k`}
                                                    width={48}
                                                />
                                                <Tooltip
                                                    formatter={(value: number | undefined) =>
                                                        value != null ? formatSgdFull(value) : ""
                                                    }
                                                />
                                                <Legend />
                                                <Bar dataKey="baseline" name="baseline_v1" fill="#64748b" radius={[4, 4, 0, 0]} />
                                                <Bar dataKey="mrt" name="mrt_pit" fill="#0d9488" radius={[4, 4, 0, 0]} />
                                            </BarChart>
                                        </ResponsiveContainer>
                                    </div>
                                </div>
                            )}

                            {filterYearSet.size !== 1 && (
                                <p className="text-sm text-foreground/45 -mt-4">
                                    Select exactly one rolling window in the filter to show the baseline vs MRT RMSE chart and detailed data quality
                                    for that window.
                                </p>
                            )}

                            {metrics?.shap_chart_available && (
                                <div className="glass rounded-2xl p-6 border border-violet-500/25">
                                    <h2 className="text-lg font-bold mb-1 flex items-center gap-2">
                                        <Brain className="w-5 h-5 text-violet-600" /> Global SHAP (RF baseline)
                                    </h2>
                                    <p className="text-sm text-foreground/50 mb-4">
                                        Mean |SHAP| from <code className="text-xs bg-foreground/10 px-1 rounded">report_mrt_shap.py</code>
                                        — served at <code className="text-xs bg-foreground/10 px-1 rounded">/api/model/shap_chart</code>
                                    </p>
                                    <div className="rounded-xl border border-foreground/10 bg-white/80 p-4 overflow-x-auto">
                                        {/* eslint-disable-next-line @next/next/no-img-element */}
                                        <img
                                            src={`${API_BASE}/api/model/shap_chart`}
                                            alt="Mean absolute SHAP values for Random Forest baseline"
                                            className="max-w-full h-auto mx-auto"
                                        />
                                    </div>
                                </div>
                            )}
                        </div>
                    ) : !dashboardLoading ? (
                        <div className="rounded-2xl border border-dashed border-foreground/15 bg-foreground/[0.02] px-4 py-6 mb-10 text-sm text-foreground/55">
                            No experiments in the catalog yet. Train via Prefect/Modal or{" "}
                            <code className="text-[11px] bg-foreground/10 px-1 rounded">modelling/runners/run_experiment.py</code> (uploads to
                            MinIO).
                        </div>
                    ) : null}

                    <div className="glass rounded-2xl p-6 border border-foreground/5 mb-10">
                        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
                            <div>
                                <h2 className="text-lg font-bold mb-1">MinIO valuation artifacts</h2>
                                <p className="text-sm text-foreground/50">
                                    Legacy <code className="text-xs bg-foreground/10 px-1 rounded">model.pkl</code> trees under{" "}
                                    <code className="text-xs bg-foreground/10 px-1 rounded">models/{modelEnv}/valuation/artifacts/</code>. New training
                                    writes to <code className="text-xs bg-foreground/10 px-1 rounded">…/experiments/</code>; publish live points the
                                    API via Postgres registry.
                                </p>
                            </div>
                            <button
                                type="button"
                                onClick={() => setDashboardRefreshKey((k) => k + 1)}
                                className="inline-flex items-center gap-1.5 rounded-lg border border-foreground/15 bg-white px-2.5 py-1.5 text-xs font-semibold text-foreground/80 hover:bg-foreground/[0.04]"
                            >
                                <RefreshCw className={`w-3.5 h-3.5 ${dashboardLoading || artifactsSectionLoading ? "animate-spin" : ""}`} />
                                Refresh artifacts
                            </button>
                        </div>
                        <div className="overflow-x-auto rounded-xl border border-foreground/10">
                            <table className="w-full text-sm text-left min-w-[960px]">
                                <thead>
                                    <tr className="border-b border-foreground/10 bg-foreground/[0.03]">
                                        <th className="px-3 py-2">Active</th>
                                        <th className="px-3 py-2">Object key</th>
                                        <th className="px-3 py-2">Experiment</th>
                                        <th className="px-3 py-2">Feature set</th>
                                        <th className="px-3 py-2">Uploaded</th>
                                        <th className="px-3 py-2 text-right">RMSE</th>
                                        <th className="px-3 py-2">Publish live</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {dashboardLoading || artifactsSectionLoading ? (
                                        <tr>
                                            <td colSpan={7} className="px-3 py-8 text-center text-foreground/50">
                                                <RefreshCw className="w-5 h-5 animate-spin inline mr-2 align-middle" />
                                                Loading artifacts…
                                            </td>
                                        </tr>
                                    ) : artifacts.length === 0 ? (
                                        <tr>
                                            <td colSpan={7} className="px-3 py-6 text-center text-foreground/50 text-sm">
                                                No valuation artifacts in MinIO for this env.
                                            </td>
                                        </tr>
                                    ) : (
                                        artifacts.map((a) => (
                                            <tr key={a.object_key} className="border-b border-foreground/5">
                                                <td className="px-3 py-2.5">
                                                    {a.is_active ? (
                                                        <span className="text-[11px] font-bold px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-800 border border-emerald-500/30">
                                                            Active
                                                        </span>
                                                    ) : (
                                                        <span className="text-foreground/35 text-xs">—</span>
                                                    )}
                                                </td>
                                                <td className="px-3 py-2.5 font-mono text-[10px] max-w-[18rem] truncate" title={a.object_key}>
                                                    {a.object_key}
                                                </td>
                                                <td className="px-3 py-2.5 font-mono text-[11px]">{a.experiment_id ?? "—"}</td>
                                                <td className="px-3 py-2.5 font-mono text-[11px]">{a.feature_set_id ?? "—"}</td>
                                                <td className="px-3 py-2.5 text-[11px] text-foreground/70">{a.uploaded_at ?? "—"}</td>
                                                <td className="px-3 py-2.5 text-right font-mono text-[11px]">
                                                    {a.metrics_summary?.rmse != null ? formatSgdFull(a.metrics_summary.rmse) : "—"}
                                                </td>
                                                <td className="px-3 py-2.5">
                                                    <button
                                                        type="button"
                                                        disabled={a.is_active || promotingKey === a.object_key}
                                                        onClick={() =>
                                                            promoteArtifact(a.object_key, {
                                                                estimator: artifactEstimatorLabel(a),
                                                                mae: a.metrics_summary?.mae ?? null,
                                                            })
                                                        }
                                                        className="inline-flex items-center gap-1 rounded-lg bg-violet-600 text-white px-2.5 py-1 text-[11px] font-bold hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed"
                                                    >
                                                        {promotingKey === a.object_key ? (
                                                            <>
                                                                <RefreshCw className="w-3 h-3 animate-spin" /> Publishing…
                                                            </>
                                                        ) : (
                                                            <>Publish live</>
                                                        )}
                                                    </button>
                                                </td>
                                            </tr>
                                        ))
                                    )}
                                </tbody>
                            </table>
                        </div>
                        <ul className="text-sm text-foreground/55 space-y-2 list-disc list-inside mt-4">
                            <li>
                                Batch sweep:{" "}
                                <code className="text-xs bg-foreground/10 px-1 rounded">
                                    python modelling/runners/run_model_sweep.py --from-db
                                </code>
                            </li>
                            <li>
                                Data report JSON:{" "}
                                <code className="text-xs bg-foreground/10 px-1 rounded">/api/admin/ml/data-report</code>
                            </li>
                        </ul>
                    </div>

                    <div className="mb-10">
                        <div className="rounded-2xl p-5 border border-orange-500/25 bg-orange-500/10 text-orange-800 max-w-3xl">
                            <h3 className="font-bold flex items-center gap-2 mb-2">
                                <AlertTriangle className="w-4 h-4 shrink-0" /> Data drift
                            </h3>
                            <p className="text-sm opacity-90">
                                District 15 transaction volume shifted vs. training window. Consider a fresh train or feature audit.
                            </p>
                        </div>
                    </div>

                    {runModalOpen && selectedRunId && modalUnified ? (
                        <ExperimentRunDetailModal
                            open={runModalOpen}
                            onClose={() => {
                                setRunModalOpen(false);
                                setAssetsZipBusy(false);
                            }}
                            runId={selectedRunId}
                            modelEnv={modelEnvForApi}
                            badges={{
                                hasMetrics: modalUnified.catalog.has_metrics,
                                minioExperiment: modalUnified.catalog.has_minio_experiment === true,
                                published: modalUnified.catalog.published === true,
                            }}
                            featureSelectionBadge={modalFeatureSelectionBadge}
                            summaryLines={modalSummaryLines}
                            configPretty={modalJsonPretty.config}
                            metricsPretty={modalJsonPretty.metrics}
                            bestParamsPretty={modalJsonPretty.bestParams}
                            detailLoading={modalDetailLoading}
                            canZipAssets={canZipAssets}
                            zipBusy={assetsZipBusy}
                            setZipBusy={setAssetsZipBusy}
                            onNotice={setNotice}
                        />
                    ) : null}

                </div>
            </main>
        </RequireAuth>
    );
}
