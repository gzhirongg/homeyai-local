"use client";

import { useState, useEffect, useCallback, useRef, useLayoutEffect } from "react";
import DatePicker from "react-datepicker";
import { CalendarDays } from "lucide-react";
import "react-datepicker/dist/react-datepicker.css";

const CALENDAR_PANEL_W = 280;

/** First calendar day of the month for `d` (local time). */
function startOfLocalMonth(d: Date): Date {
    return new Date(d.getFullYear(), d.getMonth(), 1);
}

function formatYm(d: Date): string {
    const y = d.getFullYear();
    const m = d.getMonth() + 1;
    return `${y}-${String(m).padStart(2, "0")}`;
}

function ymToDate(ym: string): Date | null {
    if (!ym || !/^\d{4}-\d{2}$/.test(ym)) return null;
    const y = parseInt(ym.slice(0, 4), 10);
    const mo = parseInt(ym.slice(5, 7), 10);
    if (mo < 1 || mo > 12 || Number.isNaN(y)) return null;
    const d = new Date(y, mo - 1, 1);
    return d.getFullYear() === y && d.getMonth() === mo - 1 ? d : null;
}

function clipYm(ym: string, minYm?: string, maxYm?: string): string {
    if (!ym) return "";
    let v = ym;
    if (minYm && v < minYm) v = minYm;
    if (maxYm && v > maxYm) v = maxYm;
    return v;
}

/**
 * Parse free text to YYYY-MM.
 * Accepts YYYY-MM, YYYY/MM, YYYY.MM; a lone YYYY expands to Jan (from) or Dec (to).
 */
function parseFreeText(
    raw: string,
    role: "from" | "to",
): { ok: true; ym: string } | { ok: false } {
    const t = raw.trim();
    if (!t) return { ok: true, ym: "" };
    const m1 = t.match(/^(\d{4})[-/.](\d{1,2})$/);
    if (m1) {
        const y = m1[1];
        const mo = parseInt(m1[2], 10);
        if (mo >= 1 && mo <= 12) return { ok: true, ym: `${y}-${String(mo).padStart(2, "0")}` };
        return { ok: false };
    }
    const m2 = t.match(/^(\d{4})$/);
    if (m2) {
        const y = m2[1];
        return { ok: true, ym: role === "from" ? `${y}-01` : `${y}-12` };
    }
    return { ok: false };
}

/** Month shown in the inline picker: prefer valid draft, else committed value. */
function pickerDateFromState(
    textDraft: string,
    valueYm: string,
    role: "from" | "to",
    minYm?: string,
    maxYm?: string,
): Date | null {
    const trimmed = textDraft.trim();
    if (trimmed) {
        const p = parseFreeText(trimmed, role);
        if (p.ok && p.ym) {
            const clipped = clipYm(p.ym, minYm, maxYm);
            return ymToDate(clipped);
        }
    }
    return ymToDate(valueYm);
}

interface MonthYearComboProps {
    subLabel: string;
    valueYm: string;
    onCommit: (ym: string) => void;
    minYm?: string;
    maxYm?: string;
    role: "from" | "to";
    placeholder: string;
}

function MonthYearCombo({
    subLabel,
    valueYm,
    onCommit,
    minYm,
    maxYm,
    role,
    placeholder,
}: MonthYearComboProps) {
    const [textDraft, setTextDraft] = useState(valueYm);
    const [invalid, setInvalid] = useState(false);
    const [calendarOpen, setCalendarOpen] = useState(false);
    const [panelPos, setPanelPos] = useState<{ top: number; left: number } | null>(null);
    const rootRef = useRef<HTMLDivElement>(null);
    const inputRowRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setTextDraft(valueYm);
        setInvalid(false);
    }, [valueYm]);

    const placePanel = useCallback(() => {
        const el = inputRowRef.current;
        if (!el) return;
        const r = el.getBoundingClientRect();
        const left = Math.min(
            Math.max(8, r.right - CALENDAR_PANEL_W),
            window.innerWidth - CALENDAR_PANEL_W - 8,
        );
        const top = r.bottom + 4;
        setPanelPos({ top, left });
    }, []);

    useLayoutEffect(() => {
        if (!calendarOpen) {
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setPanelPos(null);
            return;
        }
        placePanel();
        window.addEventListener("resize", placePanel);
        window.addEventListener("scroll", placePanel, true);
        return () => {
            window.removeEventListener("resize", placePanel);
            window.removeEventListener("scroll", placePanel, true);
        };
    }, [calendarOpen, placePanel]);

    useEffect(() => {
        if (!calendarOpen) return;
        const onDoc = (e: MouseEvent) => {
            if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
                setCalendarOpen(false);
            }
        };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, [calendarOpen]);

    const tryCommit = useCallback(() => {
        const trimmed = textDraft.trim();
        if (!trimmed) {
            setInvalid(false);
            onCommit("");
            setTextDraft("");
            return;
        }
        const parsed = parseFreeText(textDraft, role);
        if (!parsed.ok) {
            setInvalid(true);
            return;
        }
        const clipped = clipYm(parsed.ym, minYm, maxYm);
        setInvalid(false);
        onCommit(clipped);
        setTextDraft(clipped);
    }, [textDraft, role, minYm, maxYm, onCommit]);

    const minDate = minYm ? ymToDate(minYm) ?? undefined : undefined;
    const maxDate = maxYm ? ymToDate(maxYm) ?? undefined : undefined;
    const pickerSelected = pickerDateFromState(textDraft, valueYm, role, minYm, maxYm);

    const onCalendarChange = (date: Date | null) => {
        if (!date) return;
        const ym = formatYm(startOfLocalMonth(date));
        const clipped = clipYm(ym, minYm, maxYm);
        setInvalid(false);
        setTextDraft(clipped);
        onCommit(clipped);
        setCalendarOpen(false);
    };

    return (
        <div ref={rootRef} className="relative space-y-1">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide block">
                {subLabel}
            </span>
            <div
                ref={inputRowRef}
                className={`flex rounded-xl border bg-white overflow-hidden transition-shadow ${
                    invalid
                        ? "border-red-500 ring-1 ring-red-500/40"
                        : "border-slate-200 focus-within:ring-2 focus-within:ring-accent/50"
                }`}
            >
                <input
                    id={`ym-combo-${role}`}
                    type="text"
                    inputMode="numeric"
                    autoComplete="off"
                    placeholder={placeholder}
                    value={textDraft}
                    onChange={(e) => {
                        setTextDraft(e.target.value);
                        setInvalid(false);
                    }}
                    onBlur={(e) => {
                        if (rootRef.current?.contains(e.relatedTarget as Node)) return;
                        tryCommit();
                    }}
                    onKeyDown={(e) => {
                        if (e.key === "Enter") {
                            e.preventDefault();
                            tryCommit();
                        }
                    }}
                    className="flex-1 min-w-0 px-3 py-2 text-sm font-mono text-slate-700 placeholder:text-slate-400 bg-transparent focus:outline-none"
                    aria-invalid={invalid}
                    aria-describedby={invalid ? `ym-err-${role}` : undefined}
                />
                <button
                    type="button"
                    aria-expanded={calendarOpen}
                    aria-label={`${subLabel} month picker`}
                    onClick={() => setCalendarOpen((o) => !o)}
                    className="shrink-0 flex items-center justify-center px-3 border-l border-slate-200 text-accent hover:bg-slate-50 transition-colors"
                >
                    <CalendarDays className="w-4 h-4" aria-hidden />
                </button>
            </div>
            {invalid && (
                <p id={`ym-err-${role}`} className="text-xs text-red-500 font-medium" role="alert">
                    invalid date
                </p>
            )}
            {calendarOpen && panelPos && (
                <div
                    className="fixed z-[2050] rounded-xl border border-slate-200 bg-white shadow-lg overflow-hidden analytics-datepicker-inline-wrap"
                    style={{
                        top: panelPos.top,
                        left: panelPos.left,
                        width: CALENDAR_PANEL_W,
                    }}
                >
                    <DatePicker
                        inline
                        selected={pickerSelected}
                        onChange={onCalendarChange}
                        showMonthYearPicker
                        dateFormat="MMM yyyy"
                        minDate={minDate}
                        maxDate={maxDate}
                        openToDate={pickerSelected ?? minDate ?? maxDate ?? new Date()}
                        calendarClassName="analytics-datepicker-calendar analytics-datepicker-calendar--inline"
                    />
                </div>
            )}
        </div>
    );
}

export interface AnalyticsDateRangeProps {
    dateFrom: string;
    dateTo: string;
    onDatesChange: (next: { date_from: string; date_to: string }) => void;
    minYm?: string;
    maxYm?: string;
}

/**
 * Month/year: one text field + adjacent calendar ([react-datepicker](https://github.com/Hacker0x01/react-datepicker) inline).
 * API values are transaction months (YYYY-MM).
 */
export default function AnalyticsDateRange({
    dateFrom,
    dateTo,
    onDatesChange,
    minYm,
    maxYm,
}: AnalyticsDateRangeProps) {
    const handleFrom = useCallback(
        (ym: string) => {
            const from = clipYm(ym, minYm, maxYm);
            let to = dateTo;
            if (from && to && from > to) to = from;
            onDatesChange({ date_from: from, date_to: to });
        },
        [dateTo, minYm, maxYm, onDatesChange],
    );

    const handleTo = useCallback(
        (ym: string) => {
            const to = clipYm(ym, minYm, maxYm);
            let from = dateFrom;
            if (from && to && from > to) from = to;
            onDatesChange({ date_from: from, date_to: to });
        },
        [dateFrom, minYm, maxYm, onDatesChange],
    );

    return (
        <div className="space-y-4">
            <MonthYearCombo
                subLabel="From"
                valueYm={dateFrom}
                onCommit={handleFrom}
                minYm={minYm}
                maxYm={maxYm}
                role="from"
                placeholder="YYYY-MM or YYYY"
            />
            <MonthYearCombo
                subLabel="To"
                valueYm={dateTo}
                onCommit={handleTo}
                minYm={minYm}
                maxYm={maxYm}
                role="to"
                placeholder="YYYY-MM or YYYY"
            />
        </div>
    );
}
