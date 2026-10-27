"use client";

import { useCallback, useState } from "react";
import { FileDown, Loader2 } from "lucide-react";

import API_BASE from "@/lib/apiBase";

import type { AdminAlertVariant } from "@/components/admin/AdminAlertStack";

export type ExperimentReportNotice = {
    message: string;
    variant: AdminAlertVariant;
};

function bearerHeaders(base: Record<string, string>): Record<string, string> {
    if (typeof window === "undefined") return base;
    const token = localStorage.getItem("token");
    if (token) return { ...base, Authorization: `Bearer ${token}` };
    return base;
}

/**
 * Fetch failed before any HTTP response (browser hides CORS/preflight failures behind generic errors).
 * Not the same as FastAPI returning 4xx/5xx for report generation.
 */
function describeTransportFetchFailure(err: unknown): string {
    if (!(err instanceof Error)) return "Training report request failed unexpectedly";

    const raw = `${err.name}: ${err.message}`.trim();
    const msgLower = err.message.toLowerCase();

    const looksLikeNetworkLayer =
        err.name === "TypeError" &&
        (msgLower.includes("networkerror") ||
            msgLower.includes("failed to fetch") ||
            msgLower.includes("load failed") ||
            msgLower.includes("network error") ||
            msgLower === "failed to fetch");

    if (looksLikeNetworkLayer) {
        return (
            "Could not reach the API (no HTTP response). This usually means CORS, wrong URL/port, " +
            "the backend not accepting connections from this page, or an extension blocking the request — " +
            "not necessarily a training-report generation error. Check DevTools → Network. " +
            `(${raw})`
        );
    }

    return err.message || "Training report request failed unexpectedly";
}

/** FastAPI validation / HTTP ``detail`` (string or structured). */
function formatReportErrorDetail(body: unknown, status: number): string {
    if (body == null || typeof body !== "object") return `Training report failed (HTTP ${status})`;
    const d = body as { detail?: unknown };
    const detail = d.detail;
    if (detail == null) return `Training report failed (HTTP ${status})`;
    if (typeof detail === "string") return detail;
    if (typeof detail === "object" && detail !== null) {
        const o = detail as { message?: string; missing?: string[] };
        const parts: string[] = [];
        if (typeof o.message === "string") parts.push(o.message);
        if (Array.isArray(o.missing) && o.missing.length > 0) {
            parts.push(`Missing: ${o.missing.join(", ")}`);
        }
        if (parts.length > 0) return parts.join(" — ");
        try {
            return JSON.stringify(detail);
        } catch {
            return `Training report failed (HTTP ${status})`;
        }
    }
    return String(detail);
}

export type ExperimentReportDownloadButtonProps = {
    /** Experiment run folder id (`…/valuation/experiments/<runId>/`). */
    runId: string;
    /** Canonical experiment blob present under MinIO (same guard as dashboard). */
    canDownload?: boolean;
    className?: string;
    disabled?: boolean;
    label?: string;
    /** Non-null shows a banner; include variant so failures are not styled as success. */
    onNotice?: (payload: ExperimentReportNotice | null) => void;
};

/** Admin: presigned PDF download; server builds PDF from ``metrics.json`` when missing. */
export function ExperimentReportDownloadButton({
    runId,
    canDownload = true,
    className,
    disabled = false,
    label = "Download training report (PDF)",
    onNotice,
}: ExperimentReportDownloadButtonProps) {
    const [busy, setBusy] = useState(false);

    const requestReport = useCallback(async () => {
        const rid = runId.trim();
        if (!rid || !canDownload) return;

        setBusy(true);
        onNotice?.(null);
        try {
            const fetchPath = `${API_BASE}/api/admin/ml/experiment-report`;
            const res = await fetch(fetchPath, {
                method: "POST",
                headers: bearerHeaders({
                    Accept: "application/json",
                    "Content-Type": "application/json",
                }),
                cache: "no-store",
                body: JSON.stringify({ run_id: rid }),
            });

            let body: unknown = null;
            try {
                body = await res.json();
            } catch {
                body = null;
            }

            if (!res.ok) {
                const msg = formatReportErrorDetail(body, res.status);
                onNotice?.({ message: msg, variant: "error" });
                return;
            }

            const o = body as { url?: string; rebuilt?: boolean } | null;
            const url = typeof o?.url === "string" ? o.url : "";
            if (!url) {
                onNotice?.({
                    message: "Training report: response did not contain a URL",
                    variant: "error",
                });
                return;
            }

            if (o?.rebuilt) {
                onNotice?.({
                    message: "Report was generated from stored metrics/plots then opened.",
                    variant: "success",
                });
            }

            window.open(url, "_blank", "noopener,noreferrer");
        } catch (e) {
            onNotice?.({
                message: describeTransportFetchFailure(e),
                variant: "error",
            });
        } finally {
            setBusy(false);
        }
    }, [runId, canDownload, onNotice]);

    if (!runId.trim() || !canDownload) return null;

    return (
        <button
            type="button"
            disabled={disabled || busy}
            className={`inline-flex items-center gap-2 rounded-lg border border-foreground/15 bg-foreground/5 px-3 py-1.5 text-xs hover:bg-foreground/10 disabled:opacity-45 ${className ?? ""}`}
            onClick={(ev) => {
                ev.preventDefault();
                ev.stopPropagation();
                void requestReport();
            }}
        >
            {busy ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden /> : null}
            <FileDown className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>{busy ? "Opening…" : label}</span>
        </button>
    );
}
