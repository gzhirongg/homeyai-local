"use client";

import Navbar from "@/components/Navbar";
import MarketSentimentPanel from "@/components/MarketSentimentPanel";
import { useAuth } from "@/context/AuthContext";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function MarketSentimentPage() {
    const { user, isLoading, isPremiumExperience } = useAuth();
    const router = useRouter();

    useEffect(() => {
        if (isLoading) return;
        if (!user) {
            router.push("/login?next=/market-sentiment");
            return;
        }
        if (!isPremiumExperience) {
            router.push("/dashboard");
            return;
        }
    }, [user, isLoading, router, isPremiumExperience]);

    if (isLoading || !user) {
        return (
            <main className="min-h-screen bg-slate-50 flex items-center justify-center">
                <Navbar />
                <div className="text-center p-8">
                    <div className="w-12 h-12 border-4 border-accent border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                    <p className="text-lg font-semibold">Loading...</p>
                </div>
            </main>
        );
    }

    if (!isPremiumExperience) {
        return (
            <main className="min-h-screen bg-slate-50 flex items-center justify-center">
                <Navbar />
                <div className="text-center p-8">
                    <p className="text-lg font-semibold text-red-500">Premium Feature Required</p>
                </div>
            </main>
        );
    }

    return (
        <main className="min-h-screen bg-slate-50 pb-20">
            <Navbar />
            <MarketSentimentPanel variant="page" />
        </main>
    );
}
