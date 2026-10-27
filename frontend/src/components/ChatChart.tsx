"use client";

import {
    LineChart, Line, BarChart, Bar, AreaChart, Area,
    XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";

export interface ChatBlock {
    type: "text" | "chart" | "tool_call" | "done";
    content?: string;
    chart_type?: string;
    title?: string;
    data?: any[];
    x_key?: string;
    y_key?: string;
    y_label?: string;
    name?: string;
    arguments?: any;
    conversation_id?: number;
}

export default function ChatChart({ block }: { block: ChatBlock }) {
    const data = block.data || [];
    const xKey = block.x_key || "period";
    const yKey = block.y_key || "avg_price";

    if (data.length === 0) return null;

    return (
        <div className="my-3 p-4 rounded-xl bg-white/60 border border-foreground/5">
            {block.title && <p className="text-xs font-bold text-foreground/60 mb-3">{block.title}</p>}
            <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                    {block.chart_type === "bar" ? (
                        <BarChart data={data}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(0,0,0,0.05)" />
                            <XAxis dataKey={xKey} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                            <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10 }} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
                            <Tooltip contentStyle={{ borderRadius: "12px", border: "1px solid rgba(0,0,0,0.05)" }} formatter={(v: any) => [`S$${Number(v).toLocaleString()}`, block.y_label || yKey]} />
                            <Bar dataKey={yKey} fill="var(--color-accent)" radius={[4, 4, 0, 0]} />
                        </BarChart>
                    ) : block.chart_type === "area" ? (
                        <AreaChart data={data}>
                            <defs>
                                <linearGradient id="chatAreaGrad" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor="var(--color-accent)" stopOpacity={0.3} />
                                    <stop offset="95%" stopColor="var(--color-accent)" stopOpacity={0} />
                                </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(0,0,0,0.05)" />
                            <XAxis dataKey={xKey} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                            <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10 }} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
                            <Tooltip contentStyle={{ borderRadius: "12px", border: "1px solid rgba(0,0,0,0.05)" }} formatter={(v: any) => [`S$${Number(v).toLocaleString()}`, block.y_label || yKey]} />
                            <Area type="monotone" dataKey={yKey} stroke="var(--color-accent)" strokeWidth={2} fillOpacity={1} fill="url(#chatAreaGrad)" />
                        </AreaChart>
                    ) : (
                        <LineChart data={data}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(0,0,0,0.05)" />
                            <XAxis dataKey={xKey} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                            <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10 }} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
                            <Tooltip contentStyle={{ borderRadius: "12px", border: "1px solid rgba(0,0,0,0.05)" }} formatter={(v: any) => [`S$${Number(v).toLocaleString()}`, block.y_label || yKey]} />
                            <Line type="monotone" dataKey={yKey} stroke="var(--color-accent)" strokeWidth={2.5} dot={false} />
                        </LineChart>
                    )}
                </ResponsiveContainer>
            </div>
        </div>
    );
}
