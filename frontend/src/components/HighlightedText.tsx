"use client";

function escapeRegExp(s: string): string {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

type Props = {
    text: string;
    highlight: string;
    /** Highlight class for matched segments (defaults to emerald analytics style). */
    matchClassName?: string;
};

export default function HighlightedText({
    text,
    highlight,
    matchClassName = "text-emerald-600 font-black bg-emerald-50 px-0.5 rounded",
}: Props) {
    const tokens = highlight.trim().split(/\s+/).filter(Boolean);
    if (!tokens.length) return <span>{text}</span>;

    let regex: RegExp;
    try {
        regex = new RegExp(`(${tokens.map(escapeRegExp).join("|")})`, "gi");
    } catch {
        return <span>{text}</span>;
    }

    const parts = text.split(regex);
    const isMatchToken = (part: string) =>
        tokens.some((t) => part.toLowerCase() === t.toLowerCase());

    return (
        <span>
            {parts.map((part, i) =>
                isMatchToken(part) ? (
                    <span key={i} className={matchClassName}>
                        {part}
                    </span>
                ) : (
                    <span key={i}>{part}</span>
                )
            )}
        </span>
    );
}
