"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { X, Loader2 } from "lucide-react";
import HighlightedText from "@/components/HighlightedText";
import { usePropertyAutocomplete } from "@/hooks/usePropertyAutocomplete";
import {
    FULL_POSTAL_LEN,
    lookupProperty,
    postalHighlightForQuery,
    routeSearchQuery,
    type PropertyLookupResult,
    type PropertySearchHit,
} from "@/lib/propertySearch";

export type { FlatOption, PropertyLookupResult, PropertySearchHit } from "@/lib/propertySearch";
export { normalizePropertyLookup } from "@/lib/propertySearch";

export type PropertySearchSelectionPresentation = "tag" | "hidden" | "search";

type LookupModeProps = {
    mode?: "lookup";
    selection: PropertyLookupResult | null;
    onSelectionChange: (value: PropertyLookupResult | null) => void;
    initialPostal?: string;
    commit?: never;
    onCommitChange?: never;
};

type CommitModeProps = {
    mode: "commit";
    commit: PropertySearchHit | null;
    onCommitChange: (value: PropertySearchHit | null) => void;
    selection?: never;
    onSelectionChange?: never;
    initialPostal?: never;
};

type SharedProps = {
    className?: string;
    inputClassName?: string;
    selectionPresentation?: PropertySearchSelectionPresentation;
};

type Props = SharedProps & (LookupModeProps | CommitModeProps);

export default function PropertySearchInput(props: Props) {
    const {
        className = "",
        inputClassName = "",
        selectionPresentation = "tag",
    } = props;

    const mode = props.mode ?? "lookup";
    const isCommitMode = mode === "commit";

    const selection = !isCommitMode ? props.selection : null;
    const onSelectionChange = !isCommitMode ? props.onSelectionChange : undefined;
    const initialPostal = !isCommitMode ? props.initialPostal : undefined;
    const commit = isCommitMode ? props.commit : null;
    const onCommitChange = isCommitMode ? props.onCommitChange : undefined;

    const listboxId = useId();
    const [query, setQuery] = useState("");
    const [open, setOpen] = useState(false);
    const [lookupLoading, setLookupLoading] = useState(false);
    const rootRef = useRef<HTMLDivElement>(null);
    const triedInitial = useRef(false);
    const prevInitialPostal = useRef(initialPostal);
    const onSelectionChangeRef = useRef(onSelectionChange);
    const prevPresentation = useRef(selectionPresentation);

    onSelectionChangeRef.current = onSelectionChange;

    const searchEnabled =
        isCommitMode
            ? !commit
            : !selection || selectionPresentation === "search";

    const {
        hits,
        loading,
        noResults,
        activeIndex,
        setActiveIndex,
        listRef,
        handleListKeyDown,
        resetList,
    } = usePropertyAutocomplete({ query, enabled: searchEnabled });

    const searchRoute = routeSearchQuery(query);
    const postalHighlight = postalHighlightForQuery(query, searchRoute);

    useEffect(() => {
        if (prevInitialPostal.current !== initialPostal) {
            triedInitial.current = false;
            prevInitialPostal.current = initialPostal;
        }
    }, [initialPostal]);

    useEffect(() => {
        if (
            selectionPresentation === "search" &&
            prevPresentation.current !== "search" &&
            selection
        ) {
            setQuery("");
            setOpen(false);
            resetList();
        }
        prevPresentation.current = selectionPresentation;
    }, [selectionPresentation, selection, resetList]);

    useEffect(() => {
        const onDoc = (e: MouseEvent) => {
            if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
                setOpen(false);
            }
        };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, []);

    useEffect(() => {
        if (isCommitMode || triedInitial.current) return;
        if (selection) {
            triedInitial.current = true;
            return;
        }
        const pc = (initialPostal || "").replace(/\D/g, "");
        if (pc.length !== FULL_POSTAL_LEN) {
            triedInitial.current = true;
            return;
        }
        triedInitial.current = true;
        setLookupLoading(true);
        lookupProperty(pc)
            .then((r) => {
                onSelectionChangeRef.current?.(r);
            })
            .catch(() => {
                onSelectionChangeRef.current?.(null);
            })
            .finally(() => setLookupLoading(false));
    }, [initialPostal, selection, isCommitMode]);

    const pickHit = useCallback(
        async (hit: PropertySearchHit) => {
            const pc = (hit.postal_code || "").replace(/\D/g, "");
            if (pc.length !== FULL_POSTAL_LEN) return;

            setOpen(false);
            setQuery("");
            resetList();

            if (isCommitMode) {
                onCommitChange?.(hit);
                return;
            }

            setLookupLoading(true);
            try {
                const detail = await lookupProperty(pc);
                onSelectionChange?.(detail);
            } catch {
                onSelectionChange?.(null);
            } finally {
                setLookupLoading(false);
            }
        },
        [isCommitMode, onCommitChange, onSelectionChange, resetList]
    );

    const clear = () => {
        setQuery("");
        resetList();
        setOpen(false);
        if (isCommitMode) {
            onCommitChange?.(null);
        } else {
            onSelectionChange?.(null);
        }
    };

    const onInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (
            handleListKeyDown(e, {
                open: open && hits.length > 0,
                setOpen,
                pickHit: (h) => void pickHit(h),
            })
        ) {
            return;
        }
    };

    const showDropdown = open && (loading || hits.length > 0 || noResults);
    const activeDescendantId =
        activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined;

    const searchField = (
        <div ref={rootRef} className={`relative ${className}`}>
            <div className="flex items-center gap-2">
                <input
                    type="text"
                    autoComplete="off"
                    role="combobox"
                    aria-expanded={showDropdown}
                    aria-controls={listboxId}
                    aria-activedescendant={activeDescendantId}
                    placeholder="Search by address or 6-digit postal code…"
                    className={`flex-1 min-w-0 bg-transparent border border-foreground/10 rounded-xl px-4 py-3 outline-none focus:ring-2 focus:ring-accent ${inputClassName}`}
                    value={query}
                    onChange={(e) => {
                        setQuery(e.target.value);
                        setOpen(true);
                    }}
                    onFocus={() => setOpen(true)}
                    onKeyDown={onInputKeyDown}
                    disabled={lookupLoading}
                />
                {loading || lookupLoading ? (
                    <Loader2 className="w-5 h-5 animate-spin text-accent shrink-0" />
                ) : null}
            </div>
            {showDropdown && (
                <div
                    ref={listRef}
                    id={listboxId}
                    role="listbox"
                    className="absolute z-50 left-0 right-0 mt-1 max-h-60 overflow-auto rounded-xl border border-foreground/10 bg-background shadow-lg text-left text-sm"
                >
                    {noResults && query.trim().length >= 2 && !loading && (
                        <div className="px-4 py-3 text-foreground/60" role="status">
                            No records found
                        </div>
                    )}
                    {hits.map((h, i) => (
                        <button
                            key={`${h.postal_code}-${i}`}
                            id={`${listboxId}-option-${i}`}
                            data-hit-index={i}
                            type="button"
                            role="option"
                            aria-selected={i === activeIndex}
                            className={`w-full text-left px-4 py-2.5 border-b border-foreground/5 last:border-0 transition-colors ${
                                i === activeIndex
                                    ? "bg-accent/15"
                                    : "hover:bg-accent/10"
                            }`}
                            onMouseEnter={() => setActiveIndex(i)}
                            onClick={() => void pickHit(h)}
                        >
                            <div className="font-medium truncate">
                                <HighlightedText
                                    text={h.name || "(No label)"}
                                    highlight={query}
                                />
                            </div>
                            {h.postal_code ? (
                                <div className="text-xs text-foreground/50 font-mono">
                                    <HighlightedText
                                        text={h.postal_code}
                                        highlight={postalHighlight}
                                    />
                                </div>
                            ) : null}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );

    const hasSelection = isCommitMode ? !!commit : !!selection;

    if (!isCommitMode && selection && selectionPresentation === "hidden") {
        return null;
    }

    if (!hasSelection || (!isCommitMode && selectionPresentation === "search")) {
        return searchField;
    }

    const tagLabel = isCommitMode
        ? commit!.name
        : selection!.address_label;
    const tagPostal = isCommitMode
        ? commit!.postal_code
        : selection!.postal_code;

    return (
        <div className={`flex items-center gap-2 flex-wrap ${className}`}>
            <button
                type="button"
                onClick={clear}
                className="flex items-center gap-2 px-3 py-2 rounded-xl bg-accent/10 border border-accent/30 text-sm font-medium max-w-full hover:bg-accent/15 transition-colors text-left"
                title="Click to change address"
            >
                <span className="truncate">{tagLabel}</span>
                <span className="text-foreground/50 whitespace-nowrap">
                    · {tagPostal}
                </span>
                <span
                    aria-label="Clear property"
                    className="p-0.5 rounded bg-accent/20 shrink-0"
                >
                    <X className="w-4 h-4" />
                </span>
            </button>
            {lookupLoading ? (
                <Loader2 className="w-4 h-4 animate-spin text-accent" />
            ) : null}
        </div>
    );
}
