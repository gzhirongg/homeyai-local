"use client";

import { useState, useRef, useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X, Send, Bot, Loader2, MessageSquare } from "lucide-react";
import ChatMessageBubble, { type ChatMsg } from "./ChatMessageBubble";
import type { ChatBlock } from "./ChatChart";

import API_BASE from "@/lib/apiBase";
import { subscriptionAwareHeaders } from "@/lib/subscriptionPreview";

interface ChatDrawerProps {
    open: boolean;
    onClose?: () => void;
    analyticsContext?: Record<string, any> | null;
    inline?: boolean;
}

export default function ChatDrawer({ open, onClose, analyticsContext, inline }: ChatDrawerProps) {
    const [messages, setMessages] = useState<ChatMsg[]>([]);
    const [input, setInput] = useState("");
    const [isStreaming, setIsStreaming] = useState(false);
    const [conversationId, setConversationId] = useState<number | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    useEffect(() => {
        if (open) inputRef.current?.focus();
    }, [open]);

    const sendMessage = async (text?: string) => {
        const content = text || input.trim();
        if (!content || isStreaming) return;

        const userMsg: ChatMsg = { role: "user", content };
        const updated = [...messages, userMsg];
        setMessages(updated);
        setInput("");
        setIsStreaming(true);

        const apiMessages = updated.map(m => ({ role: m.role, content: m.content }));
        const token = localStorage.getItem("token");

        try {
            const res = await fetch(`${API_BASE}/api/chat`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...subscriptionAwareHeaders(token),
                },
                body: JSON.stringify({
                    messages: apiMessages,
                    conversation_id: conversationId,
                    context: analyticsContext || undefined,
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
                        if (block.conversation_id && !conversationId) {
                            setConversationId(block.conversation_id);
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
        } catch (e) {
            console.error("Chat error:", e);
            setMessages(prev => [...prev, { role: "assistant", content: "Sorry, something went wrong." }]);
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

    const innerContent = (
        <>
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-foreground/10">
                <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-accent to-secondary flex items-center justify-center">
                        <Bot className="w-5 h-5 text-white" />
                    </div>
                    <div>
                        <h3 className="font-bold text-sm">HomeyAI Chat</h3>
                        {analyticsContext && (
                            <p className="text-[10px] text-accent font-medium">Context-aware mode</p>
                        )}
                    </div>
                </div>
                {!inline && onClose && (
                    <button onClick={onClose} className="p-2 rounded-xl hover:bg-foreground/5 transition-colors">
                        <X className="w-5 h-5 text-foreground/50" />
                    </button>
                )}
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
                {messages.length === 0 && (
                    <div className="flex flex-col items-center justify-center h-full text-center">
                        <MessageSquare className="w-10 h-10 text-foreground/10 mb-3" />
                        <p className="text-sm font-medium text-foreground/40 mb-1">Ask about the data</p>
                        <p className="text-xs text-foreground/30">
                            {analyticsContext
                                ? "I have context from your current analytics view."
                                : "Ask me anything about Singapore HDB resale market."}
                        </p>
                    </div>
                )}
                {messages.map((msg, idx) => (
                    <ChatMessageBubble key={idx} msg={msg} />
                ))}

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
            <div className="p-4 border-t border-foreground/10">
                <div className="glass rounded-2xl shadow-lg border-foreground/10 p-2 flex items-end gap-2">
                    <textarea
                        ref={inputRef}
                        value={input}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder="Ask about HDB resale trends..."
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
            </div>
        </>
    );

    if (inline) {
        if (!open) return null;
        return (
            <div className="w-full h-[600px] glass rounded-3xl shadow-xl flex flex-col overflow-hidden border border-white/20">
                {innerContent}
            </div>
        );
    }

    return (
        <AnimatePresence>
            {open && (
                <>
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
                        onClick={onClose}
                    />
                    <motion.div
                        initial={{ x: "100%" }}
                        animate={{ x: 0 }}
                        exit={{ x: "100%" }}
                        transition={{ type: "spring", damping: 25, stiffness: 300 }}
                        className="fixed right-0 top-0 bottom-0 z-50 w-full max-w-lg bg-slate-50 shadow-2xl flex flex-col"
                    >
                        {innerContent}
                    </motion.div>
                </>
            )}
        </AnimatePresence>
    );
}
