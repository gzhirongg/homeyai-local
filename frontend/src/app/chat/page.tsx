"use client";

import Navbar from "@/components/Navbar";
import RequireAuth from "@/components/RequireAuth";
import ChatMessageBubble, { type ChatMsg } from "@/components/ChatMessageBubble";
import type { ChatBlock } from "@/components/ChatChart";
import { motion, AnimatePresence } from "framer-motion";
import {
    Send, Bot, Loader2, MessageSquare, ChevronRight,
    Plus, Trash2, FileText, PanelLeftClose, PanelLeftOpen,
} from "lucide-react";
import { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";

import API_BASE from "@/lib/apiBase";
import { subscriptionAwareHeaders } from "@/lib/subscriptionPreview";
import { useAuth } from "@/context/AuthContext";

interface Conversation {
    id: number;
    title: string;
    report_id: number | null;
    preview: string;
    created_at: string | null;
    updated_at: string | null;
}

interface Report {
    id: number;
    title: string;
    created_at: string | null;
}

const EXAMPLE_PROMPTS = [
    { persona: "Lifestyle Commuter", prompt: "What is the price trend of 4-room flats in Clementi over the last 10 years?", icon: "🏙️" },
    { persona: "Kiasu Parent", prompt: "Compare resale prices of 5-room flats in Bedok vs Tampines", icon: "🎓" },
    { persona: "Yield Hunter", prompt: "Which town has the highest average PSF for 3-room flats?", icon: "📈" },
    { persona: "Upgrader", prompt: "Show me the price trend of executive flats in Punggol", icon: "🏠" },
];

export default function ChatPage() {
    const { adminPreviewSubscription } = useAuth();
    const [conversations, setConversations] = useState<Conversation[]>([]);
    const [activeConvoId, setActiveConvoId] = useState<number | null>(null);
    const [messages, setMessages] = useState<ChatMsg[]>([]);
    const [input, setInput] = useState("");
    const [isStreaming, setIsStreaming] = useState(false);
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [reports, setReports] = useState<Report[]>([]);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
    const authHeaders = subscriptionAwareHeaders(token);

    const loadConversations = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/api/conversations`, { headers: authHeaders as Record<string, string> });
            if (res.ok) setConversations(await res.json());
        } catch (e) { console.error("Failed to load conversations:", e); }
    }, [token, adminPreviewSubscription]);

    const loadReports = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/api/reports`, { headers: authHeaders as Record<string, string> });
            if (res.ok) setReports(await res.json());
        } catch (e) { console.error("Failed to load reports:", e); }
    }, [token, adminPreviewSubscription]);

    useEffect(() => {
        loadConversations();
        loadReports();
    }, [loadConversations, loadReports]);

    const loadConversation = async (id: number) => {
        setActiveConvoId(id);
        try {
            const res = await fetch(`${API_BASE}/api/conversations/${id}`, { headers: authHeaders as Record<string, string> });
            if (res.ok) {
                const data = await res.json();
                setMessages(
                    data.messages.map((m: any) => ({
                        id: m.id,
                        role: m.role,
                        content: m.content || "",
                        blocks: m.blocks || undefined,
                    }))
                );
            }
        } catch (e) { console.error("Failed to load conversation:", e); }
    };

    const startNewChat = () => {
        setActiveConvoId(null);
        setMessages([]);
        inputRef.current?.focus();
    };

    const deleteConversation = async (id: number) => {
        try {
            const res = await fetch(`${API_BASE}/api/conversations/${id}`, { method: "DELETE", headers: authHeaders as Record<string, string> });
            if (res.ok) {
                setConversations(prev => prev.filter(c => c.id !== id));
                if (activeConvoId === id) startNewChat();
            }
        } catch (e) { console.error("Delete failed:", e); }
    };

    const sendMessage = async (text?: string) => {
        const content = text || input.trim();
        if (!content || isStreaming) return;

        const userMsg: ChatMsg = { role: "user", content };
        const updated = [...messages, userMsg];
        setMessages(updated);
        setInput("");
        setIsStreaming(true);

        const apiMessages = updated.map(m => ({ role: m.role, content: m.content }));

        try {
            const res = await fetch(`${API_BASE}/api/chat`, {
                method: "POST",
                headers: { "Content-Type": "application/json", ...subscriptionAwareHeaders(token) },
                body: JSON.stringify({
                    messages: apiMessages,
                    conversation_id: activeConvoId,
                }),
            });

            if (!res.ok || !res.body) throw new Error("Chat request failed");

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            const blocks: ChatBlock[] = [];
            let textContent = "";

            setMessages(prev => [...prev, { role: "assistant", content: "", blocks: [] }]);

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop() || "";

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    try {
                        const block: ChatBlock = JSON.parse(line.slice(6));
                        if (block.type === "done") continue;

                        if (block.conversation_id && !activeConvoId) {
                            setActiveConvoId(block.conversation_id);
                        }

                        blocks.push(block);
                        if (block.type === "text") textContent += block.content || "";

                        setMessages(prev => {
                            const copy = [...prev];
                            copy[copy.length - 1] = { role: "assistant", content: textContent, blocks: [...blocks] };
                            return copy;
                        });
                    } catch { /* skip malformed */ }
                }
            }

            loadConversations();
        } catch (e) {
            console.error("Chat error:", e);
            setMessages(prev => [...prev, { role: "assistant", content: "Sorry, something went wrong. Please try again." }]);
        } finally {
            setIsStreaming(false);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    return (
        <RequireAuth>
            <main className="min-h-screen bg-slate-50 flex flex-col">
                <Navbar />
                <div className="flex-1 flex pt-16">
                    {/* Sidebar */}
                    <AnimatePresence>
                        {sidebarOpen && (
                            <motion.aside
                                initial={{ width: 0, opacity: 0 }}
                                animate={{ width: 320, opacity: 1 }}
                                exit={{ width: 0, opacity: 0 }}
                                transition={{ duration: 0.2 }}
                                className="border-r border-foreground/10 bg-white/50 backdrop-blur-md flex flex-col overflow-hidden shrink-0"
                            >
                                <div className="p-4 border-b border-foreground/10">
                                    <button
                                        onClick={startNewChat}
                                        className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-bold bg-accent text-white hover:bg-accent/90 transition-all"
                                    >
                                        <Plus className="w-4 h-4" /> New Chat
                                    </button>
                                </div>

                                <div className="flex-1 overflow-y-auto">
                                    {/* Conversations */}
                                    <div className="p-3">
                                        <h4 className="text-[10px] font-bold text-foreground/40 uppercase tracking-wider px-2 mb-2">Conversations</h4>
                                        {conversations.length === 0 ? (
                                            <p className="text-xs text-foreground/30 px-2 py-4">No conversations yet</p>
                                        ) : (
                                            <div className="space-y-1">
                                                {conversations.map(c => (
                                                    <button
                                                        key={c.id}
                                                        onClick={() => loadConversation(c.id)}
                                                        className={`w-full text-left px-3 py-2.5 rounded-xl text-sm transition-all group flex items-start justify-between gap-2 ${
                                                            activeConvoId === c.id
                                                                ? "bg-accent/10 text-accent font-bold"
                                                                : "hover:bg-foreground/5 text-foreground/70"
                                                        }`}
                                                    >
                                                        <div className="flex-1 min-w-0">
                                                            <p className="truncate font-medium text-xs">{c.title}</p>
                                                            {c.preview && <p className="truncate text-[10px] text-foreground/40 mt-0.5">{c.preview}</p>}
                                                        </div>
                                                        <button
                                                            onClick={e => { e.stopPropagation(); deleteConversation(c.id); }}
                                                            className="p-1 rounded-lg text-foreground/20 hover:text-red-500 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-all shrink-0"
                                                        >
                                                            <Trash2 className="w-3 h-3" />
                                                        </button>
                                                    </button>
                                                ))}
                                            </div>
                                        )}
                                    </div>

                                    {/* Reports */}
                                    <div className="p-3 border-t border-foreground/10">
                                        <h4 className="text-[10px] font-bold text-foreground/40 uppercase tracking-wider px-2 mb-2">Saved Reports</h4>
                                        {reports.length === 0 ? (
                                            <p className="text-xs text-foreground/30 px-2 py-4">No reports saved yet</p>
                                        ) : (
                                            <div className="space-y-1">
                                                {reports.map(r => (
                                                    <Link
                                                        key={r.id}
                                                        href={`/reports/${r.id}`}
                                                        className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs hover:bg-foreground/5 transition-all text-foreground/60 hover:text-accent"
                                                    >
                                                        <FileText className="w-3.5 h-3.5 shrink-0" />
                                                        <span className="truncate">{r.title}</span>
                                                    </Link>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </motion.aside>
                        )}
                    </AnimatePresence>

                    {/* Main Chat Area */}
                    <div className="flex-1 flex flex-col max-w-4xl mx-auto w-full px-4">
                        {/* Sidebar toggle */}
                        <div className="py-3">
                            <button
                                onClick={() => setSidebarOpen(!sidebarOpen)}
                                className="p-2 rounded-xl hover:bg-foreground/5 transition-colors text-foreground/40 hover:text-foreground/60"
                            >
                                {sidebarOpen ? <PanelLeftClose className="w-5 h-5" /> : <PanelLeftOpen className="w-5 h-5" />}
                            </button>
                        </div>

                        {/* Messages */}
                        <div className="flex-1 overflow-y-auto py-2 space-y-6">
                            {messages.length === 0 && (
                                <div className="flex flex-col items-center justify-center h-full min-h-[60vh]">
                                    <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-accent to-secondary flex items-center justify-center mb-6">
                                        <Bot className="w-8 h-8 text-white" />
                                    </div>
                                    <h2 className="text-2xl font-extrabold mb-2">HomeyAI Chat</h2>
                                    <p className="text-sm text-foreground/50 mb-8 text-center max-w-md">
                                        Ask me anything about Singapore&apos;s HDB resale market.
                                        I can query real transaction data and show you charts.
                                    </p>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-lg">
                                        {EXAMPLE_PROMPTS.map((ex, i) => (
                                            <button
                                                key={i}
                                                onClick={() => sendMessage(ex.prompt)}
                                                className="glass rounded-xl p-4 text-left hover:shadow-md hover:border-accent/20 transition-all group border border-foreground/5"
                                            >
                                                <div className="flex items-center gap-2 mb-1.5">
                                                    <span className="text-lg">{ex.icon}</span>
                                                    <span className="text-[10px] font-bold text-foreground/40 uppercase tracking-wider">{ex.persona}</span>
                                                </div>
                                                <p className="text-xs font-medium text-foreground/70 group-hover:text-accent transition-colors leading-relaxed">
                                                    {ex.prompt}
                                                </p>
                                                <ChevronRight className="w-3 h-3 text-foreground/20 mt-2 group-hover:text-accent transition-colors" />
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}

                            <AnimatePresence>
                                {messages.map((msg, idx) => (
                                    <motion.div key={idx} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
                                        <ChatMessageBubble msg={msg} />
                                    </motion.div>
                                ))}
                            </AnimatePresence>

                            {isStreaming && messages[messages.length - 1]?.role !== "assistant" && (
                                <div className="flex gap-3">
                                    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent to-secondary flex items-center justify-center">
                                        <Bot className="w-4 h-4 text-white" />
                                    </div>
                                    <div className="glass rounded-2xl rounded-bl-md px-4 py-3 border-foreground/5">
                                        <div className="flex items-center gap-2 text-sm text-foreground/50">
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                            Analyzing...
                                        </div>
                                    </div>
                                </div>
                            )}

                            <div ref={messagesEndRef} />
                        </div>

                        {/* Input */}
                        <div className="sticky bottom-0 pb-4 pt-2 bg-gradient-to-t from-slate-50 via-slate-50/95 to-transparent">
                            <div className="glass rounded-2xl shadow-lg border-foreground/10 p-2 flex items-end gap-2">
                                <textarea
                                    ref={inputRef}
                                    value={input}
                                    onChange={e => setInput(e.target.value)}
                                    onKeyDown={handleKeyDown}
                                    placeholder="Ask about HDB resale trends, prices, districts..."
                                    rows={1}
                                    className="flex-1 bg-transparent px-3 py-2.5 text-sm resize-none focus:outline-none max-h-32"
                                    style={{ minHeight: "40px" }}
                                />
                                <button
                                    onClick={() => sendMessage()}
                                    disabled={!input.trim() || isStreaming}
                                    className="p-2.5 rounded-xl bg-accent text-white hover:bg-accent/90 transition-all disabled:opacity-30 shrink-0"
                                >
                                    <Send className="w-4 h-4" />
                                </button>
                            </div>
                            <p className="text-center text-[10px] text-foreground/30 mt-2">
                                HomeyAI uses real HDB resale data. AI responses may vary.
                            </p>
                        </div>
                    </div>
                </div>
            </main>
        </RequireAuth>
    );
}
