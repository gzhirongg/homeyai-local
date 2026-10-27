"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import API_BASE from "@/lib/apiBase";
import type { MarketSentimentData } from "@/components/MarketSentimentPanel";
import { subscriptionAwareHeaders } from "@/lib/subscriptionPreview";

function sentimentBadge(label: MarketSentimentData["rsi_label"] | undefined) {
    if (label === "Overheated")
        return { cls: "text-red-700 bg-red-50 border-red-200", dot: "bg-red-500" };
    if (label === "Undervalued")
        return {
            cls: "text-emerald-700 bg-emerald-50 border-emerald-200",
            dot: "bg-emerald-500",
        };
    return { cls: "text-amber-800 bg-amber-50 border-amber-200", dot: "bg-amber-500" };
}

type Props = {
    refreshNonce?: number;
};

export default function ValuationMarketSentiment({ refreshNonce = 0 }: Props) {
    const [sentiment, setSentiment] = useState<MarketSentimentData | null>(null);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        const loadSentiment = async () => {
            setLoading(true);
            try {
                const token =
                    typeof window !== "undefined" ? localStorage.getItem("token") : null;
                const res = await fetch(`${API_BASE}/api/market/sentiment`, {
                    headers: subscriptionAwareHeaders(token),
                });
                const json = await res.json().catch(() => null);
                if (res.ok && typeof json?.rsi_value === "number") {
                    setSentiment(json as MarketSentimentData);
                } else {
                    setSentiment(null);
                }
            } catch {
                setSentiment(null);
            } finally {
                setLoading(false);
            }
        };
        void loadSentiment();
    }, [refreshNonce]);

    if (loading) {
        return (
            <p className="text-sm text-foreground/50 flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading market signals…
            </p>
        );
    }

    if (!sentiment) {
        return (
            <p className="text-sm text-foreground/45">
                Market signal unavailable at the moment.
            </p>
        );
    }

    const badge = sentimentBadge(sentiment.rsi_label);

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
                <span
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-bold ${badge.cls}`}
                >
                    <span className={`w-1.5 h-1.5 rounded-full ${badge.dot}`} />
                    {sentiment.rsi_label}
                </span>
                <span className="text-xs text-foreground/50">
                    RSI {sentiment.rsi_value?.toFixed(1) ?? "—"}
                </span>
            </div>
            <p className="text-xs text-foreground/65 leading-relaxed">
                {sentiment.composite_insight}
            </p>
        </div>
    );
}
