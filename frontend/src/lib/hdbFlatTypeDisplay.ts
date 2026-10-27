/**
 * Labels for flat types from ``hdb_property_information`` catalogue (matches backend order).
 */

const CATALOG_FLAT_ORDER: readonly string[] = [
    "1 ROOM",
    "2 ROOM",
    "3 ROOM",
    "4 ROOM",
    "5 ROOM",
    "EXECUTIVE",
    "MULTI-GENERATION",
    "STUDIO APARTMENT",
];

const ORDER_INDEX = new Map(
    CATALOG_FLAT_ORDER.map((t, i) => [t, i])
);

/** Sort key for catalogue-driven flat-type lists / tags */
export function compareFlatTypesCatalogueOrder(a: string, b: string): number {
    const ua = a.trim().toUpperCase();
    const ub = b.trim().toUpperCase();
    const ia = ORDER_INDEX.has(ua) ? ORDER_INDEX.get(ua)! : 999;
    const ib = ORDER_INDEX.has(ub) ? ORDER_INDEX.get(ub)! : 999;
    if (ia !== ib) return ia - ib;
    return ua.localeCompare(ub);
}

/** e.g. ``3 ROOM`` → ``3-Room`` */
export function formatFlatTypeCatalogueShort(flatType: string): string {
    const t = flatType.trim();
    const um = /^(\d)\s+ROOM$/i.exec(t);
    if (um) return `${um[1]}-Room`;

    switch (t.toUpperCase()) {
        case "EXECUTIVE":
            return "Executive";
        case "MULTI-GENERATION":
            return "Multi-Generation";
        case "STUDIO APARTMENT":
            return "Studio Apartment";
        default:
            return t || "—";
    }
}

/** e.g. ``3 ROOM``, 26 → ``3-Room (26)`` when units > 0 */
export function formatFlatTypeWithUnits(
    flatType: string,
    unitsSold: number
): string {
    const core = formatFlatTypeCatalogueShort(flatType);
    if (
        typeof unitsSold === "number" &&
        Number.isFinite(unitsSold) &&
        unitsSold > 0
    ) {
        return `${core} (${unitsSold})`;
    }
    return core;
}
