"use client";

import { useState, useEffect } from "react";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Loader2,
  RefreshCcw,
  Activity,
  BarChart2,
  Landmark,
  Sparkles,
  Info,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";

import API_BASE from "@/lib/apiBase";
import { subscriptionAwareHeaders } from "@/lib/subscriptionPreview";
import { useAuth } from "@/context/AuthContext";

// ─────────────────────────────────────────────────────────────────────────────
// Types — aligned with the backend response shape.
// When the real backend is ready, swap `MarketSentimentData` accordingly.
// ─────────────────────────────────────────────────────────────────────────────

export type RsiLabel = "Overheated" | "Neutral" | "Undervalued";
export type VolumeLabel = "High Conviction" | "Normal Activity" | "Low Conviction";
export type RateLabel = "Tightening" | "Stable" | "Easing";

export interface MarketSentimentData {
  rsi_value: number;       // 0–100 normalised (drives gauge arc)
  rsi_raw: number | null;  // Actual HDB RPI index number e.g. 187.4
  rsi_qoq_pct: number;    // Quarter-on-quarter % change
  rsi_label: RsiLabel;

  /** Monthly transaction count */
  txn_volume: number;
  txn_volume_label: VolumeLabel;
  /** How many std devs above/below the 6-month mean */
  txn_volume_z: number;

  /** SORA/MAS rate, e.g. 3.72 */
  interest_rate: number | null;
  /** Positive = rising (tightening), negative = falling (easing) */
  interest_rate_delta: number;
  interest_rate_label: RateLabel | null;

  /** One-sentence synthesis from the backend (or computed on frontend) */
  composite_insight: string;

  last_updated: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function rsiConfig(label: RsiLabel | undefined) {
  switch (label) {
    case "Overheated":
      return {
        color: "text-red-500",
        bg: "bg-red-500",
        track: "bg-red-100",
        badge: "bg-red-500/10 text-red-600 border-red-200",
        glow: "shadow-red-500/20",
      };
    case "Undervalued":
      return {
        color: "text-emerald-500",
        bg: "bg-emerald-500",
        track: "bg-emerald-100",
        badge: "bg-emerald-500/10 text-emerald-600 border-emerald-200",
        glow: "shadow-emerald-500/20",
      };
    default:
      return {
        color: "text-amber-500",
        bg: "bg-amber-500",
        track: "bg-amber-100",
        badge: "bg-amber-500/10 text-amber-600 border-amber-200",
        glow: "shadow-amber-500/20",
      };
  }
}

function volumeConfig(label: VolumeLabel | undefined) {
  switch (label) {
    case "High Conviction":
      return {
        color: "text-emerald-500",
        badge: "bg-emerald-500/10 text-emerald-600 border-emerald-200",
        icon: <ArrowUpRight className="w-4 h-4" />,
      };
    case "Low Conviction":
      return {
        color: "text-slate-400",
        badge: "bg-slate-100 text-slate-600 border-slate-200",
        icon: <ArrowDownRight className="w-4 h-4" />,
      };
    default:
      return {
        color: "text-amber-500",
        badge: "bg-amber-500/10 text-amber-600 border-amber-200",
        icon: <Minus className="w-4 h-4" />,
      };
  }
}

function rateConfig(label: RateLabel | undefined) {
  switch (label) {
    case "Tightening":
      return {
        color: "text-red-500",
        badge: "bg-red-500/10 text-red-600 border-red-200",
        icon: <TrendingUp className="w-4 h-4" />,
      };
    case "Easing":
      return {
        color: "text-emerald-500",
        badge: "bg-emerald-500/10 text-emerald-600 border-emerald-200",
        icon: <TrendingDown className="w-4 h-4" />,
      };
    default:
      return {
        color: "text-amber-500",
        badge: "bg-amber-500/10 text-amber-600 border-amber-200",
        icon: <Minus className="w-4 h-4" />,
      };
  }
}

/** A premium horizontal indicator bar for the RPI index.
 *  Replaces the semi-circle to prevent text clashing and improve readability. */
function RsiIndicator({
  value, label, rawIndex, qoqPct,
}: {
  value: number;
  label: RsiLabel;
  rawIndex: number | null;
  qoqPct: number;
}) {
  const cfg = rsiConfig(label);
  const qoqSign = qoqPct >= 0 ? "+" : "";

  return (
    <div className="w-full flex flex-col items-center gap-6 py-4">
      {/* Big Number Section */}
      <div className="flex flex-col items-center">
        <div className="flex items-baseline gap-2">
          <span className={`text-6xl font-black tracking-tighter ${cfg.color}`}>
            {rawIndex != null ? rawIndex.toFixed(1) : value.toFixed(0)}
          </span>
          <span className="text-sm font-bold text-foreground/30 uppercase tracking-widest">RPI</span>
        </div>
        {rawIndex != null && (
          <span className={`text-sm font-bold mt-1 flex items-center gap-1 ${cfg.color}`}>
            {qoqPct >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
            {qoqSign}{qoqPct.toFixed(2)}% vs. last quarter
          </span>
        )}
      </div>

      {/* The Multi-Segment Bar */}
      <div className="w-full relative px-2">
        <div className="h-3 w-full flex rounded-full overflow-hidden bg-foreground/5 p-0.5 border border-foreground/5">
          <div className="h-full w-[40%] bg-emerald-500/30 border-r border-background/20" title="Undervalued (<40)" />
          <div className="h-full w-[30%] bg-amber-500/30 border-r border-background/20" title="Neutral (40-70)" />
          <div className="h-full w-[30%] bg-red-500/30" title="Overheated (>70)" />
        </div>

        {/* Current Position Pointer */}
        <div
          className="absolute top-[-4px] transition-all duration-1000 ease-out flex flex-col items-center"
          style={{ left: `${value}%`, transform: "translateX(-50%)" }}
        >
          <div className={`w-4 h-4 rounded-full border-2 border-background shadow-lg ${cfg.color.replace("text-", "bg-")}`} />
          <div className={`w-0.5 h-4 mt-1 ${cfg.color.replace("text-", "bg-")}`} />
        </div>

        {/* Labels under the bar */}
        <div className="flex justify-between mt-3 text-[10px] font-bold text-foreground/30 uppercase tracking-tighter">
          <span>Undervalued</span>
          <span>Neutral</span>
          <span>Overheated</span>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-cards
// ─────────────────────────────────────────────────────────────────────────────

function RsiCard({ data }: { data: MarketSentimentData }) {
  const cfg = rsiConfig(data.rsi_label);

  return (
    <div className="glass rounded-3xl p-7 shadow-xl flex flex-col gap-5 border border-foreground/5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-11 h-11 shrink-0 rounded-2xl flex items-center justify-center bg-foreground/5">
          <Activity className={`w-5 h-5 ${cfg.color}`} />
        </div>
        <div>
          <h3 className="font-bold text-base leading-tight">HDB Resale Price Index (RPI)</h3>
          <p className="text-xs text-foreground/40 mt-0.5">Official HDB quarterly benchmark</p>
        </div>
      </div>

      {/* Badge + Indicator */}
      <div className="flex flex-col items-center gap-3">
        <span className={`text-xs font-bold px-3 py-1 rounded-full border ${cfg.badge}`}>
          {data.rsi_label}
        </span>
        <RsiIndicator
          value={data.rsi_value}
          label={data.rsi_label}
          rawIndex={data.rsi_raw ?? null}
          qoqPct={data.rsi_qoq_pct ?? 0}
        />
      </div>


      {/* Description */}
      <p className="text-sm text-foreground/55 leading-relaxed">
        {data.rsi_label === "Overheated"
          ? "The RPI has climbed well above its long-run baseline, meaning resale flat prices are at elevated levels relative to historical norms. Sellers are in a stronger negotiating position and buyers should budget for above-average valuations."
          : data.rsi_label === "Undervalued"
          ? "The RPI is tracking below its long-run trend, indicating resale prices have softened from recent peaks. Buyers may find more room to negotiate and better value compared to the last few years."
          : "The RPI is in line with its long-run trend. Resale prices are neither inflated nor depressed relative to history — a relatively balanced environment for both buyers and sellers."}
      </p>
    </div>
  );
}

function VolumeCard({ data }: { data: MarketSentimentData }) {
  const cfg = volumeConfig(data.txn_volume_label);
  const zSign = data.txn_volume_z >= 0 ? "+" : "";
  return (
    <div className="glass rounded-3xl p-7 shadow-xl flex flex-col gap-5 border border-foreground/5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-11 h-11 rounded-2xl flex items-center justify-center bg-foreground/5">
          <BarChart2 className={`w-5 h-5 ${cfg.color}`} />
        </div>
        <div>
          <h3 className="font-bold text-base leading-tight">Transaction Volume</h3>
          <p className="text-xs text-foreground/40 mt-0.5">Market liquidity signal</p>
        </div>
      </div>

      {/* Big number */}
      <div className="flex flex-col items-center py-2 gap-2">
        <span className={`flex items-center gap-1 text-xs font-bold px-3 py-1 rounded-full border ${cfg.badge}`}>
          {cfg.icon}
          {data.txn_volume_label}
        </span>
        <span className={`text-6xl font-black tracking-tight ${cfg.color}`}>
          {data.txn_volume.toLocaleString()}
        </span>
        <span className="text-sm text-foreground/40">transactions this month</span>
        <span className={`text-sm font-semibold ${cfg.color}`}>
          {zSign}{data.txn_volume_z.toFixed(1)}σ vs. 6-month mean
        </span>
      </div>

      {/* Visual bar */}
      <div>
        <div className="flex justify-between text-xs text-foreground/40 mb-1.5">
          <span>Low</span>
          <span>6-month mean</span>
          <span>High</span>
        </div>
        <div className="relative h-3 bg-foreground/10 rounded-full overflow-hidden">
          {/* Mean marker */}
          <div className="absolute top-0 bottom-0 w-0.5 bg-foreground/30 left-1/2" />
          {/* Fill — clamp between 5% and 95% for display */}
          <div
            className={`h-full rounded-full transition-all duration-1000 ${
              data.txn_volume_label === "High Conviction"
                ? "bg-emerald-500"
                : data.txn_volume_label === "Low Conviction"
                ? "bg-slate-400"
                : "bg-amber-500"
            }`}
            style={{
              width: `${Math.min(95, Math.max(5, 50 + data.txn_volume_z * 20))}%`,
            }}
          />
        </div>
      </div>

      {/* Description */}
      <p className="text-sm text-foreground/55 leading-relaxed">
        {data.txn_volume_label === "High Conviction"
          ? "Elevated transaction volumes validate current price levels — buyers and sellers are actively transacting, reducing the risk that prices reflect thin or speculative trading."
          : data.txn_volume_label === "Low Conviction"
          ? "Below-average activity signals market uncertainty. Price levels may not be well-supported, and wide bid-ask spreads can make fair valuation harder."
          : "Transaction volumes are in line with seasonal norms. Market pricing is likely representative of genuine supply-demand conditions."}
      </p>
    </div>
  );
}

function RateCard({ data }: { data: MarketSentimentData }) {
  const cfg = rateConfig(data.interest_rate_label ?? undefined);
  const deltaSign = data.interest_rate_delta >= 0 ? "+" : "";
  return (
    <div className="glass rounded-3xl p-7 shadow-xl flex flex-col gap-5 border border-foreground/5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-11 h-11 shrink-0 rounded-2xl flex items-center justify-center bg-foreground/5">
          <Landmark className={`w-5 h-5 ${cfg.color}`} />
        </div>
        <div className="min-w-0">
          <h3 className="font-bold text-base leading-tight">Interest Rates (SORA)</h3>
          <p className="text-xs text-foreground/40 mt-0.5">Affordability pressure</p>
        </div>
      </div>

      {/* Big number */}
      <div className="flex flex-col items-center py-2 gap-2">
        <span className={`flex items-center gap-1 text-xs font-bold px-3 py-1 rounded-full border ${cfg.badge}`}>
          {cfg.icon}
          {data.interest_rate_label ?? "Unavailable"}
        </span>
        {data.interest_rate != null ? (
          <>
            <span className={`text-6xl font-black tracking-tight ${cfg.color}`}>
              {data.interest_rate.toFixed(2)}%
            </span>
            <span className="text-sm text-foreground/40">current benchmark rate</span>
            <span className={`text-sm font-semibold ${cfg.color}`}>
              {deltaSign}{data.interest_rate_delta.toFixed(2)}% vs. prior month
            </span>
          </>
        ) : (
          <>
            <span className="text-4xl font-black tracking-tight text-foreground/20">—</span>
            <span className="text-sm text-foreground/40 text-center px-4">
              Interest-rate data is unavailable. This signal is excluded from the summary.
            </span>
          </>
        )}
      </div>


      {/* Direction badge row */}
      <div className="grid grid-cols-2 gap-3 text-center text-xs">
        <div className={`rounded-xl py-3 px-2 ${data.interest_rate_label === "Tightening" ? "bg-red-500/10 text-red-600 font-bold" : "bg-foreground/5 text-foreground/40"}`}>
          <TrendingUp className="w-4 h-4 mx-auto mb-1" />
          Tightening<br />(Rising Rates)
        </div>
        <div className={`rounded-xl py-3 px-2 ${data.interest_rate_label === "Easing" ? "bg-emerald-500/10 text-emerald-600 font-bold" : "bg-foreground/5 text-foreground/40"}`}>
          <TrendingDown className="w-4 h-4 mx-auto mb-1" />
          Easing<br />(Falling Rates)
        </div>
      </div>

      {/* Description */}
      <p className="text-sm text-foreground/55 leading-relaxed">
        {data.interest_rate == null ? "Rate direction cannot be assessed without published rate data." : data.interest_rate_label === "Tightening"
          ? "Rising rates increase monthly mortgage repayments, reducing how much buyers can borrow. This compresses purchasing power and can cool demand over time."
          : data.interest_rate_label === "Easing"
          ? "Falling rates lower monthly mortgage repayments, expanding purchasing power. More buyers can qualify for larger loans, which typically supports property prices."
          : "Rates are holding steady, keeping affordability conditions broadly stable. Buyers can plan with greater certainty on monthly repayment costs."}
      </p>
    </div>
  );
}

function CompositeCard({ insight, lastUpdated }: { insight: string; lastUpdated: string }) {
  return (
    <div className="glass rounded-3xl p-8 shadow-xl border border-accent/20 bg-gradient-to-br from-accent/5 to-secondary/5">
      <div className="flex items-center gap-3 mb-5">
        <div className="w-11 h-11 rounded-2xl bg-accent/10 flex items-center justify-center">
          <Sparkles className="w-5 h-5 text-accent" />
        </div>
        <div>
          <h3 className="font-bold text-base">Composite Market Synthesis</h3>
          <p className="text-xs text-foreground/40">Rule-based summary of available market data</p>
        </div>
      </div>

      <blockquote className="text-base font-medium text-foreground/80 leading-relaxed border-l-4 border-accent/40 pl-5 italic">
        &ldquo;{insight}&rdquo;
      </blockquote>

      <div className="flex items-center justify-between mt-6 pt-4 border-t border-foreground/5 text-xs text-foreground/40">
        <span className="flex items-center gap-1.5">
          <Info className="w-3.5 h-3.5" />
          Not financial advice. Consult a licensed property agent.
        </span>
        <span>Updated: {new Date(lastUpdated).toLocaleString("en-SG", { dateStyle: "medium", timeStyle: "short" })}</span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Panel (exported — used by both the page and embedded contexts)
// ─────────────────────────────────────────────────────────────────────────────

export type MarketSentimentPanelVariant = "page" | "embedded";

interface MarketSentimentPanelProps {
  variant?: MarketSentimentPanelVariant;
}

export default function MarketSentimentPanel({ variant = "page" }: MarketSentimentPanelProps) {
  const { adminPreviewSubscription } = useAuth();
  const [data, setData] = useState<MarketSentimentData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(false);

  const fetchData = async () => {
    setError(false);
    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
      const response = await fetch(`${API_BASE}/api/market/sentiment`, {
        headers: subscriptionAwareHeaders(token),
      });
      if (!response.ok) throw new Error("API error");
      const json = await response.json();
      if (typeof json.rsi_value !== "number") throw new Error("Incomplete market data");
      setData(json as MarketSentimentData);
    } catch {
      setError(true);
      setData(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  useEffect(() => {
    fetchData();
  }, [adminPreviewSubscription]);

  const isPage = variant === "page";

  return (
    <div className={isPage ? "max-w-6xl mx-auto pt-32 px-4 pb-20 sm:px-6 lg:px-8" : "w-full"}>
      {/* Header row */}
      <div className={`flex items-start justify-between gap-4 ${isPage ? "mb-10" : "mb-6"}`}>
        {isPage ? (
          <div>
            <span className="text-accent font-bold uppercase tracking-widest text-xs">Premium Feature</span>
            <h1 className="text-4xl font-extrabold tracking-tight mt-2 flex items-center gap-3">
              <TrendingUp className="w-9 h-9 text-accent" />
              Market Sentiment
            </h1>
            <p className="text-foreground/50 mt-2 max-w-xl">
              Three real-market signals — RSI, transaction liquidity, and interest rate direction — synthesised into one clear market view.
            </p>
          </div>
        ) : (
          <p className="text-sm text-foreground/55 max-w-xl">
            RSI · Transaction Volume · Interest Rates — synthesised into one market view.
          </p>
        )}

        <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshing || loading}
          className="shrink-0 p-3 rounded-xl border border-foreground/10 hover:bg-foreground/5 transition-all disabled:opacity-40"
          title="Refresh"
        >
          <RefreshCcw className={`w-5 h-5 ${refreshing ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* Body */}
      {loading ? (
        <div className="glass rounded-3xl p-16 shadow-xl text-center">
          <Loader2 className="w-12 h-12 animate-spin mx-auto text-accent mb-4" />
          <p className="text-lg font-semibold">Analysing market signals…</p>
          <p className="text-sm text-foreground/40 mt-1">RSI · Liquidity · Interest Rates</p>
        </div>
      ) : data ? (
        <div className="space-y-6">
          {/* Composite synthesis — pinned at the top */}
          <CompositeCard insight={data.composite_insight} lastUpdated={data.last_updated} />

          {/* Three signal cards */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <RsiCard data={data} />
            <VolumeCard data={data} />
            <RateCard data={data} />
          </div>

          {/* Methodology footnote */}
          <div className="glass rounded-2xl px-6 py-5 border border-foreground/5 flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between text-sm text-foreground/50">
            <span className="flex items-center gap-2">
              <Info className="w-4 h-4 shrink-0" />
              Signals use HDB resale data and available MAS rates. The summary follows fixed rules; it is not news or social-media sentiment.
            </span>
            <span className="shrink-0 font-medium text-foreground/40">
              Data: HDB · MAS SORA
            </span>
          </div>
        </div>
      ) : (
        <div className="glass rounded-3xl p-16 shadow-xl text-center">
          <p className="text-lg font-semibold text-red-500 mb-4">{error ? "Market data is unavailable. No sample values are substituted." : "No market data"}</p>
          <button
            type="button"
            onClick={handleRefresh}
            className="px-6 py-3 bg-accent text-white rounded-xl font-bold hover:shadow-lg transition-all"
          >
            Try Again
          </button>
        </div>
      )}
    </div>
  );
}
