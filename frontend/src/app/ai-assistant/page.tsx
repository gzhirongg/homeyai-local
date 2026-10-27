"use client";

import { useState, useRef, useEffect } from "react";
import Navbar from "@/components/Navbar";
import { useAuth } from "@/context/AuthContext";
import { useRouter } from "next/navigation";
import { Send, Bot, User, Loader2, TrendingUp, MessageSquare } from "lucide-react";

import API_BASE from "@/lib/apiBase";
import { subscriptionAwareHeaders } from "@/lib/subscriptionPreview";

type Message = {
    role: "user" | "assistant";
    content: string;
    sources?: string[];
    confidence?: number | null;
};

export default function AIAssistantPage() {
    const { user, isLoading, isPremiumExperience } = useAuth();
    const router = useRouter();
    const [messages, setMessages] = useState<Message[]>([
        {
            role: "assistant",
            content: "Hi! I'm HomeyAI, your property market assistant. I can help you understand market trends, price predictions, rental yields, and location insights. What would you like to know?",
            confidence: 1.0
        }
    ]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (isLoading) return;
        if (!user) {
            router.push("/login?next=/ai-assistant");
            return;
        }
        if (!isPremiumExperience) {
            router.push("/dashboard");
            return;
        }
    }, [user, isLoading, router, isPremiumExperience]);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!input.trim() || loading) return;

        const userMessage: Message = {
            role: "user",
            content: input.trim()
        };

        setMessages(prev => [...prev, userMessage]);
        setInput("");
        setLoading(true);

        try {
            const token = localStorage.getItem("token");
            const response = await fetch(`${API_BASE}/api/ai/chat`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...subscriptionAwareHeaders(token),
                },
                body: JSON.stringify({
                    message: userMessage.content,
                    conversation_history: messages
                }),
            });

            if (!response.ok) {
                throw new Error("Failed to get response");
            }

            const data = await response.json();
            
            const assistantMessage: Message = {
                role: "assistant",
                content: data.response,
                sources: data.sources,
                confidence: data.confidence
            };

            setMessages(prev => [...prev, assistantMessage]);
        } catch (error) {
            console.error("Chat error:", error);
            setMessages(prev => [...prev, {
                role: "assistant",
                content: "Sorry, I encountered an error. Please try again.",
                confidence: 0
            }]);
        } finally {
            setLoading(false);
        }
    };

    const suggestedQuestions = [
        "What's the current market trend?",
        "Which town has the best investment potential?",
        "How does MRT proximity affect prices?",
        "What are typical rental yields?"
    ];

    if (isLoading || !user || !isPremiumExperience) {
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

    return (
        <main className="min-h-screen bg-slate-50 pb-20">
            <Navbar />
            
            <div className="max-w-4xl mx-auto pt-32 px-4">
                <div className="mb-8 text-center">
                    <h1 className="text-4xl font-extrabold mb-4 tracking-tight flex items-center justify-center gap-3">
                        <Bot className="w-10 h-10 text-accent" />
                        AI Market Assistant
                    </h1>
                    <p className="text-foreground/50 text-lg">
                        Ask me anything about Singapore&apos;s property market
                    </p>
                </div>

                {/* Chat Container */}
                <div className="glass rounded-3xl p-6 shadow-xl mb-6">
                    {/* Messages */}
                    <div className="space-y-4 mb-6 max-h-[500px] overflow-y-auto">
                        {messages.map((message, idx) => (
                            <div
                                key={idx}
                                className={`flex gap-3 ${message.role === "user" ? "flex-row-reverse" : ""}`}
                            >
                                <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                                    message.role === "user" 
                                        ? "bg-secondary text-white" 
                                        : "bg-accent text-white"
                                }`}>
                                    {message.role === "user" ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                                </div>
                                <div className={`flex-1 max-w-[80%] ${message.role === "user" ? "text-right" : ""}`}>
                                    <div className={`inline-block p-4 rounded-2xl ${
                                        message.role === "user"
                                            ? "bg-accent text-white rounded-tr-sm"
                                            : "bg-foreground/5 rounded-tl-sm"
                                    }`}>
                                        <p className="text-sm">{message.content}</p>
                                    </div>
                                    {message.sources && message.sources.length > 0 && (
                                        <div className="mt-2 flex flex-wrap gap-2">
                                            {message.sources.map((source, i) => (
                                                <span
                                                    key={i}
                                                    className="text-xs px-2 py-1 bg-accent/10 text-accent rounded-full"
                                                >
                                                    {source}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                    {message.confidence != null && message.confidence < 1 && (
                                        <p className="text-xs text-foreground/40 mt-1">
                                            Confidence: {Math.round(message.confidence * 100)}%
                                        </p>
                                    )}
                                </div>
                            </div>
                        ))}
                        {loading && (
                            <div className="flex gap-3">
                                <div className="w-8 h-8 rounded-full bg-accent text-white flex items-center justify-center">
                                    <Bot className="w-4 h-4" />
                                </div>
                                <div className="bg-foreground/5 p-4 rounded-2xl rounded-tl-sm">
                                    <Loader2 className="w-5 h-5 animate-spin text-accent" />
                                </div>
                            </div>
                        )}
                        <div ref={messagesEndRef} />
                    </div>

                    {/* Suggested Questions */}
                    {messages.length < 3 && (
                        <div className="mb-4">
                            <p className="text-xs text-foreground/50 mb-2 flex items-center gap-2">
                                <MessageSquare className="w-3 h-3" />
                                Try asking:
                            </p>
                            <div className="flex flex-wrap gap-2">
                                {suggestedQuestions.map((question, idx) => (
                                    <button
                                        key={idx}
                                        onClick={() => setInput(question)}
                                        className="text-xs px-3 py-2 bg-foreground/5 hover:bg-accent/10 text-foreground rounded-full transition-colors"
                                    >
                                        {question}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Input Form */}
                    <form onSubmit={handleSubmit} className="flex gap-3">
                        <input
                            type="text"
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            placeholder="Ask about market trends, prices, locations..."
                            className="flex-1 bg-background border border-foreground/10 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-accent"
                            disabled={loading}
                        />
                        <button
                            type="submit"
                            disabled={loading || !input.trim()}
                            className="px-6 py-3 bg-accent text-white rounded-xl font-bold hover:shadow-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                        >
                            {!loading ? (
                                <>
                                    <Send className="w-4 h-4" />
                                    Send
                                </>
                            ) : (
                                <Loader2 className="w-4 h-4 animate-spin" />
                            )}
                        </button>
                    </form>
                </div>

                {/* Info Card */}
                <div className="glass rounded-3xl p-6 shadow-xl bg-accent/5 border border-accent/20">
                    <h3 className="font-bold flex items-center gap-2 mb-2">
                        <TrendingUp className="w-5 h-5 text-accent" />
                        Premium Feature
                    </h3>
                    <p className="text-sm text-foreground/60">
                        This AI assistant uses advanced language models to provide insights about Singapore&apos;s property market.
                        Always verify with professional advice before making investment decisions.
                    </p>
                </div>
            </div>
        </main>
    );
}
