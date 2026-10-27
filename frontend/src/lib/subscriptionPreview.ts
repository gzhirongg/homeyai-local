/** Must match backend `ADMIN_SUBSCRIPTION_PREVIEW_HEADER` in `main.py`. */
export const ADMIN_SUBSCRIPTION_PREVIEW_HEADER = "X-Homey-Preview-Role";

const STORAGE_KEY = "homeyai_admin_preview_subscription";

export type AdminPreviewSubscription = "free" | "premium";

export function getStoredAdminPreviewSubscription(): AdminPreviewSubscription | null {
    if (typeof window === "undefined") return null;
    const v = sessionStorage.getItem(STORAGE_KEY);
    if (v === "free" || v === "premium") return v;
    return null;
}

export function setStoredAdminPreviewSubscription(value: AdminPreviewSubscription | null): void {
    if (typeof window === "undefined") return;
    if (value) sessionStorage.setItem(STORAGE_KEY, value);
    else sessionStorage.removeItem(STORAGE_KEY);
}

function isAdminFromStorage(): boolean {
    if (typeof window === "undefined") return false;
    try {
        const raw = localStorage.getItem("user");
        if (!raw) return false;
        const u = JSON.parse(raw) as { role?: string };
        return u.role === "admin";
    } catch {
        return false;
    }
}

/**
 * Auth headers for API calls. When the stored user is admin and a preview tier is set,
 * sends `X-Homey-Preview-Role` so the backend can apply premium gates without DB writes.
 */
export function subscriptionAwareHeaders(
    token?: string | null,
    extra?: Record<string, string>
): Record<string, string> {
    const h: Record<string, string> = { ...(extra || {}) };
    if (token) h.Authorization = `Bearer ${token}`;
    if (isAdminFromStorage()) {
        const preview = getStoredAdminPreviewSubscription();
        if (preview) h[ADMIN_SUBSCRIPTION_PREVIEW_HEADER] = preview;
    }
    return h;
}
