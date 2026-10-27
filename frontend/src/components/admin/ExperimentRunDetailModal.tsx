"use client";

import { useCallback, useEffect } from "react";
import { FileArchive, Loader2, X } from "lucide-react";

import API_BASE from "@/lib/apiBase";
import {
    ExperimentReportDownloadButton,
    type ExperimentReportNotice,
} from "@/components/admin/ExperimentReportDownloadButton";

function bearerHeaders(base: Record<string, string>): Record<string, string> {
    if (typeof window === "undefined") return base;
    const token = localStorage.getItem("token");
    if (token) return { ...base, Authorization: `Bearer ${token}` };
    return base;
}

function formatZipErrorDetail(detail: unknown): string {
    if (detail == null) return "Request failed";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
        return detail
            .map((d) => {
                if (d && typeof d === "object" && "msg" in d) {
                    const o = d as { msg?: string };
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

export type ExperimentFeatureSelectionBadge = {
    policyLabel: string;
    variant: "apply" | "advisory" | "unknown";
};

export type ExperimentRunDetailModalProps = {
    open: boolean;
    onClose: () => void;
    runId: string;
    modelEnv: string;
    badges: {
        hasMetrics: boolean;
        minioExperiment: boolean;
        published: boolean;
    };
    /** Pre-fit variance/MI/correlation policy recorded on the run (from metrics.training_matrix_audit). */
    featureSelectionBadge?: ExperimentFeatureSelectionBadge | null;
    summaryLines: { label: string; value: string }[];
    configPretty: string | null;
    metricsPretty: string | null;
    bestParamsPretty: string | null;
    detailLoading: boolean;
    canZipAssets: boolean;
    zipBusy: boolean;
    setZipBusy: (v: boolean) => void;
    onNotice: (payload: ExperimentReportNotice | null) => void;
};

export function ExperimentRunDetailModal({
    open,
    onClose,
    runId,
    modelEnv,
    badges,
    featureSelectionBadge = null,
    summaryLines,
    configPretty,
    metricsPretty,
    bestParamsPretty,
    detailLoading,
    canZipAssets,
    zipBusy,
    setZipBusy,
    onNotice,
}: ExperimentRunDetailModalProps) {
    useEffect(() => {
        if (!open) return;
        const onKey = (ev: KeyboardEvent) => {
            if (ev.key === "Escape") onClose();
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [open, onClose]);

    const downloadAssetsZip = useCallback(async () => {
        const rid = runId.trim();
        if (!rid || zipBusy) return;
        setZipBusy(true);
        onNotice(null);
        try {
            const envSeg = modelEnv.trim();
            const body: { run_id: string; env?: string } = { run_id: rid };
            if (envSeg && envSeg !== "…") body.env = envSeg;

            const res = await fetch(`${API_BASE}/api/admin/ml/experiment-run-assets-zip`, {
                method: "POST",
                headers: bearerHeaders({
                    Accept: "application/zip",
                    "Content-Type": "application/json",
                }),
                body: JSON.stringify(body),
            });

            if (!res.ok) {
                let detail: unknown;
                try {
                    detail = (await res.json()) as { detail?: unknown };
                    detail = detail && typeof detail === "object" && "detail" in detail ? (detail as { detail: unknown }).detail : detail;
                } catch {
                    detail = null;
                }
                onNotice({
                    message: `Asset bundle failed: ${formatZipErrorDetail(detail)} (HTTP ${res.status})`,
                    variant: "error",
                });
                return;
            }

            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `${rid}_assets.zip`;
            a.click();
            URL.revokeObjectURL(url);
            onNotice({ message: "Asset bundle download started.", variant: "success" });
        } catch (e) {
            onNotice({
                message: e instanceof Error ? e.message : "Asset bundle request failed",
                variant: "error",
            });
        } finally {
            setZipBusy(false);
        }
    }, [runId, modelEnv, zipBusy, setZipBusy, onNotice]);

    if (!open) return null;

    const rid = runId.trim();

    return (
        <div
            className="fixed inset-0 z-[10250] overflow-y-auto overscroll-contain bg-black/50 backdrop-blur-sm"
            role="dialog"
            aria-modal="true"
            aria-labelledby="experiment-run-detail-title"
            onClick={onClose}
        >
            <div className="min-h-[100dvh] flex items-center justify-center p-4 py-6 sm:p-6 sm:py-10">
                <div
                    className="bg-white rounded-2xl shadow-2xl border border-foreground/10 w-full max-w-2xl max-h-[min(82dvh,calc(100dvh-5rem))] overflow-hidden flex flex-col my-auto"
                    onClick={(e) => e.stopPropagation()}
                >
                <div className="p-5 border-b border-foreground/10 flex items-start gap-3 shrink-0">
                    <div className="min-w-0 flex-1">
                        <h2 id="experiment-run-detail-title" className="text-lg font-bold font-mono break-all">
                            {rid}
                        </h2>
                        <div className="flex flex-wrap gap-2 mt-2">
                            {badges.minioExperiment ? (
                                <span className="text-[11px] font-bold px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-800 border border-emerald-500/30">
                                    MinIO experiment
                                </span>
                            ) : (
                                <span className="text-[11px] font-bold px-2 py-0.5 rounded-md bg-foreground/10 text-foreground/55 border border-foreground/15">
                                    No experiment prefix
                                </span>
                            )}
                            {badges.published ? (
                                <span className="text-[11px] font-bold px-2 py-0.5 rounded-md bg-violet-500/15 text-violet-900 border border-violet-500/30">
                                    Published
                                </span>
                            ) : null}
                            <span
                                className={`text-[11px] font-bold px-2 py-0.5 rounded-md border ${
                                    badges.hasMetrics
                                        ? "bg-emerald-500/15 text-emerald-800 border-emerald-500/30"
                                        : "bg-foreground/10 text-foreground/50 border-foreground/15"
                                }`}
                            >
                                Metrics {badges.hasMetrics ? "yes" : "no"}
                            </span>
                            {featureSelectionBadge ? (
                                <span
                                    className={`text-[11px] font-bold px-2 py-0.5 rounded-md border ${
                                        featureSelectionBadge.variant === "apply"
                                            ? "bg-emerald-500/15 text-emerald-900 border-emerald-500/35"
                                            : featureSelectionBadge.variant === "advisory"
                                              ? "bg-slate-500/10 text-slate-700 border-slate-400/25"
                                              : "bg-foreground/10 text-foreground/50 border-foreground/15"
                                    }`}
                                    title="feature_selection_policy from metrics.training_matrix_audit"
                                >
                                    Feature selection: {featureSelectionBadge.policyLabel}
                                </span>
                            ) : null}
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="shrink-0 p-2 rounded-lg text-foreground/50 hover:text-foreground hover:bg-foreground/10"
                        aria-label="Close"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="p-5 overflow-y-auto flex-1 space-y-5 min-h-0">
                    <div className="flex flex-wrap gap-2 items-center">
                        <ExperimentReportDownloadButton
                            runId={rid}
                            canDownload={badges.minioExperiment}
                            label="View training report (PDF)"
                            onNotice={onNotice}
                        />
                        <button
                            type="button"
                            disabled={!canZipAssets || zipBusy}
                            title={
                                !canZipAssets
                                    ? "No MinIO experiment or published artifact folder expected for this row"
                                    : undefined
                            }
                            className="inline-flex items-center gap-2 rounded-lg border border-foreground/15 bg-foreground/5 px-3 py-1.5 text-xs hover:bg-foreground/10 disabled:opacity-45 disabled:cursor-not-allowed"
                            onClick={() => void downloadAssetsZip()}
                        >
                            {zipBusy ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden /> : null}
                            <FileArchive className="h-3.5 w-3.5 shrink-0" aria-hidden />
                            <span>{zipBusy ? "Zipping…" : "Download all assets (zip)"}</span>
                        </button>
                    </div>
                    <p className="text-[10px] text-foreground/45">
                        Opens the PDF in a new tab when available; otherwise the server builds it from{" "}
                        <code className="bg-foreground/10 px-0.5 rounded">metrics.json</code> and plots. The zip bundles every
                        object under this run in MinIO (model, metrics, training data, plots, report, etc.). Large runs may take a
                        while.
                    </p>

                    <div>
                        <p className="text-xs font-bold uppercase tracking-wider text-foreground/40 mb-2">Summary</p>
                        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-sm">
                            {summaryLines.map(({ label, value }) => (
                                <div key={label} className="flex justify-between gap-2 border-b border-foreground/5 pb-1">
                                    <dt className="text-foreground/50 shrink-0">{label}</dt>
                                    <dd className="font-mono text-[11px] text-right text-foreground/85 break-all">{value}</dd>
                                </div>
                            ))}
                        </dl>
                    </div>

                    <JsonBlock title="config.json" loading={detailLoading} content={configPretty} />
                    <JsonBlock title="metrics.json" loading={detailLoading} content={metricsPretty} />
                    <JsonBlock title="best_params.json" loading={detailLoading} content={bestParamsPretty} />
                </div>

                <div className="p-4 border-t border-foreground/10 flex justify-end shrink-0 bg-foreground/[0.02]">
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-xl border border-foreground/15 bg-white px-4 py-2 text-sm font-semibold text-foreground/80 hover:bg-foreground/[0.04]"
                    >
                        Close
                    </button>
                </div>
                </div>
            </div>
        </div>
    );
}

function JsonBlock({
    title,
    loading,
    content,
}: {
    title: string;
    loading: boolean;
    content: string | null;
}) {
    return (
        <div>
            <p className="text-xs font-bold uppercase tracking-wider text-foreground/40 mb-2">{title}</p>
            {loading ? (
                <p className="text-xs text-foreground/45">Loading…</p>
            ) : content ? (
                <pre className="text-[11px] font-mono bg-foreground/[0.04] border border-foreground/10 rounded-xl p-3 max-h-56 overflow-auto whitespace-pre-wrap break-all">
                    {content}
                </pre>
            ) : (
                <p className="text-xs text-foreground/45">Not available for this run (no MinIO detail or empty file).</p>
            )}
        </div>
    );
}
