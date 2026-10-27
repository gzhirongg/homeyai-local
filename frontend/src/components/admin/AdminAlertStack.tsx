"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { motion } from "framer-motion";
import { AlertCircle, AlertTriangle, Check, CircleCheck, Copy, X } from "lucide-react";

export type AdminAlertVariant = "success" | "error" | "warning";

export type AdminAlertItem = {
    id: string;
    variant: AdminAlertVariant;
    message: string;
    /** Auto-dismiss after ms (typically success only). */
    autoDismissMs?: number;
    actions?: ReactNode;
};

function variantClasses(v: AdminAlertVariant): {
    wrap: string;
    icon: typeof AlertCircle;
    iconClass: string;
} {
    switch (v) {
        case "success":
            return {
                wrap: "border-emerald-500/35 bg-emerald-500/10 text-emerald-950 backdrop-blur-sm",
                icon: CircleCheck,
                iconClass: "text-emerald-600",
            };
        case "warning":
            return {
                wrap: "border-amber-500/35 bg-amber-500/10 text-amber-950 backdrop-blur-sm",
                icon: AlertTriangle,
                iconClass: "text-amber-700",
            };
        default:
            return {
                wrap: "border-red-500/35 bg-red-500/10 text-red-950 backdrop-blur-sm",
                icon: AlertCircle,
                iconClass: "text-red-600",
            };
    }
}

function AlertRow({
    alert,
    onDismiss,
}: {
    alert: AdminAlertItem;
    onDismiss: (id: string) => void;
}) {
    const [copied, setCopied] = useState(false);
    /** False triggers slide-out + opacity exit before parent removes alert from state. */
    const [visible, setVisible] = useState(true);
    const exitDismissedRef = useRef(false);
    const cfg = variantClasses(alert.variant);
    const Icon = cfg.icon;

    useEffect(() => {
        if (!alert.autoDismissMs) return undefined;
        const t = window.setTimeout(() => setVisible(false), alert.autoDismissMs);
        return () => window.clearTimeout(t);
    }, [alert.autoDismissMs, alert.id]);

    const copyMessage = () => {
        void navigator.clipboard.writeText(alert.message).then(
            () => {
                setCopied(true);
                window.setTimeout(() => setCopied(false), 2000);
            },
            () => {},
        );
    };

    const requestClose = () => setVisible(false);

    return (
        <motion.div
            role="alert"
            initial={{ opacity: 0, x: 56 }}
            animate={
                visible
                    ? { opacity: 1, x: 0 }
                    : { opacity: 0, x: 72 }
            }
            transition={{
                opacity: { duration: 0.28, ease: [0.22, 1, 0.36, 1] },
                x: { duration: 0.32, ease: [0.22, 1, 0.36, 1] },
            }}
            onAnimationComplete={() => {
                if (visible) return;
                if (exitDismissedRef.current) return;
                exitDismissedRef.current = true;
                onDismiss(alert.id);
            }}
            className={`rounded-xl border px-3 py-2.5 shadow-lg flex gap-3 w-full max-w-sm ${cfg.wrap}`}
        >
            <Icon className={`w-5 h-5 shrink-0 mt-0.5 ${cfg.iconClass}`} aria-hidden />
            <div className="min-w-0 flex-1 text-sm leading-snug">
                {/* Body click copies the full message (same as Copy control). */}
                <button
                    type="button"
                    className="text-left w-full font-medium whitespace-pre-wrap hover:opacity-90 rounded-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:ring-current/40"
                    onClick={copyMessage}
                    title="Click to copy message"
                >
                    {alert.message}
                </button>
                {alert.actions ? <div className="mt-2 flex flex-wrap gap-2">{alert.actions}</div> : null}
            </div>
            <div className="flex flex-col gap-1 shrink-0 items-end">
                <button
                    type="button"
                    className="p-1 rounded-md hover:bg-black/5 text-current"
                    onClick={copyMessage}
                    aria-label={copied ? "Copied" : "Copy message"}
                    title="Copy"
                >
                    {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                </button>
                <button
                    type="button"
                    className="p-1 rounded-md hover:bg-black/5 text-current"
                    onClick={requestClose}
                    aria-label="Dismiss"
                >
                    <X className="w-4 h-4" />
                </button>
            </div>
        </motion.div>
    );
}

export function AdminAlertStack({
    alerts,
    onDismiss,
}: {
    alerts: AdminAlertItem[];
    onDismiss: (id: string) => void;
}) {
    if (alerts.length === 0) return null;
    return (
        <div
            className="fixed top-24 right-4 z-[100] flex flex-col items-end gap-2 pointer-events-none max-w-[min(22rem,calc(100vw-2rem))]"
            aria-live="polite"
        >
            {alerts.map((a) => (
                <div key={a.id} className="pointer-events-auto w-full flex justify-end">
                    <AlertRow alert={a} onDismiss={onDismiss} />
                </div>
            ))}
        </div>
    );
}
