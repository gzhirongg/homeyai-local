"use client";

import { Bot, User } from "lucide-react";
import ChatChart, { type ChatBlock } from "./ChatChart";

export interface ChatMsg {
    id?: number;
    role: "user" | "assistant";
    content: string;
    blocks?: ChatBlock[];
}

export default function ChatMessageBubble({ msg }: { msg: ChatMsg }) {
    return (
        <div className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            {msg.role === "assistant" && (
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent to-secondary flex items-center justify-center shrink-0 mt-0.5">
                    <Bot className="w-4 h-4 text-white" />
                </div>
            )}
            <div className={`max-w-[80%] ${msg.role === "user" ? "order-first" : ""}`}>
                <div
                    className={`rounded-2xl px-4 py-3 ${
                        msg.role === "user"
                            ? "bg-accent text-white rounded-br-md"
                            : "glass border-foreground/5 rounded-bl-md"
                    }`}
                >
                    {msg.blocks?.map((block, bi) => {
                        if (block.type === "chart") {
                            return <ChatChart key={bi} block={block} />;
                        }
                        if (block.type === "tool_call") {
                            return (
                                <div key={bi} className="my-2 px-3 py-1.5 rounded-lg bg-foreground/5 text-[10px] font-mono text-foreground/40">
                                    ↗ Called <span className="font-bold text-accent">{block.name}</span>
                                </div>
                            );
                        }
                        return null;
                    })}
                    {msg.content && (
                        <div className="text-sm leading-relaxed whitespace-pre-wrap">
                            {msg.content.split(/(\*\*[^*]+\*\*)/).map((part, pi) => {
                                if (part.startsWith("**") && part.endsWith("**")) {
                                    return <strong key={pi}>{part.slice(2, -2)}</strong>;
                                }
                                return <span key={pi}>{part}</span>;
                            })}
                        </div>
                    )}
                </div>
            </div>
            {msg.role === "user" && (
                <div className="w-8 h-8 rounded-lg bg-foreground/10 flex items-center justify-center shrink-0 mt-0.5">
                    <User className="w-4 h-4 text-foreground/60" />
                </div>
            )}
        </div>
    );
}
