/** Stored ``training_matrix_audit.feature_selection_policy`` values from metrics.json */

export type StoredFeatureSelectionPolicy = "advisory_only" | "apply_recommended_drops" | string;

export type FeatureSelectionPolicyView = {
    policy: StoredFeatureSelectionPolicy | null;
    columnsRemovedCount: number | null;
};

function readAudit(metrics: Record<string, unknown> | null | undefined): Record<string, unknown> | null {
    const a = metrics?.training_matrix_audit;
    return a && typeof a === "object" ? (a as Record<string, unknown>) : null;
}

export function policyFromMetrics(metrics: Record<string, unknown> | null | undefined): StoredFeatureSelectionPolicy | null {
    const audit = readAudit(metrics);
    const raw = audit?.feature_selection_policy;
    if (raw === undefined || raw === null) return null;
    const s = String(raw).trim();
    return s ? (s as StoredFeatureSelectionPolicy) : null;
}

export function columnsRemovedCountFromMetrics(metrics: Record<string, unknown> | null | undefined): number | null {
    const audit = readAudit(metrics);
    const fs = audit?.feature_selection;
    if (!fs || typeof fs !== "object") return null;
    const removed = (fs as Record<string, unknown>).columns_removed;
    if (!Array.isArray(removed)) return null;
    return removed.length;
}

/** Short UI label aligned with backend ``format_feature_selection_policy_short``. */
export function formatFeatureSelectionPolicyShort(policy: string | null): string {
    if (policy === null) return "Not recorded";
    if (policy === "apply_recommended_drops") return "Drops applied";
    if (policy === "advisory_only") return "Advisory only";
    return policy;
}

export function featureSelectionPolicyFromExperimentRow(row: {
    feature_selection_policy?: string | null;
    feature_selection_columns_removed_count?: number | null;
}): FeatureSelectionPolicyView {
    const pol = row.feature_selection_policy != null ? String(row.feature_selection_policy).trim() : "";
    const n = row.feature_selection_columns_removed_count;
    return {
        policy: pol ? (pol as StoredFeatureSelectionPolicy) : null,
        columnsRemovedCount: typeof n === "number" && Number.isFinite(n) ? n : null,
    };
}

export function featureSelectionPolicyFromCatalogRow(row: {
    feature_selection_policy?: string | null;
    feature_selection_columns_removed_count?: number | null;
    metrics?: Record<string, unknown> | null;
}): FeatureSelectionPolicyView {
    const slim = featureSelectionPolicyFromExperimentRow(row);
    if (slim.policy !== null) return slim;
    return {
        policy: policyFromMetrics(row.metrics ?? undefined),
        columnsRemovedCount: columnsRemovedCountFromMetrics(row.metrics ?? undefined),
    };
}

export function unifiedFeatureSelectionPolicy(args: {
    leaderboard?: {
        feature_selection_policy?: string | null;
        feature_selection_columns_removed_count?: number | null;
    } | null;
    catalog: {
        feature_selection_policy?: string | null;
        feature_selection_columns_removed_count?: number | null;
        metrics?: Record<string, unknown> | null;
    };
    detailMetrics?: Record<string, unknown> | null;
}): FeatureSelectionPolicyView {
    const lb = args.leaderboard;
    const fromLb =
        lb && lb.feature_selection_policy != null && String(lb.feature_selection_policy).trim()
            ? featureSelectionPolicyFromExperimentRow(lb)
            : null;
    const fromCat = featureSelectionPolicyFromCatalogRow(args.catalog);
    const pol =
        (fromLb?.policy ? fromLb.policy : null) ??
        fromCat.policy ??
        policyFromMetrics(args.detailMetrics ?? undefined);
    const nDetail = columnsRemovedCountFromMetrics(args.detailMetrics ?? undefined);
    const nSlim = fromLb?.columnsRemovedCount ?? fromCat.columnsRemovedCount ?? null;
    const columnsRemovedCount = nDetail !== null ? nDetail : nSlim;
    return { policy: pol, columnsRemovedCount };
}
