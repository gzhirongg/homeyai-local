"use client";

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

export function SimpleLineChart({ data }: { data: any[] }) {
    return (
        <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(0,0,0,0.05)" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 12, opacity: 0.5 }} />
                <YAxis hide />
                <Tooltip />
                <Line type="monotone" dataKey="value" stroke="var(--color-accent)" strokeWidth={3} dot={false} />
            </LineChart>
        </ResponsiveContainer>
    )
}
