// Per-set colors for multi-copy auto-layout.
// 20 distinct colors. Excludes black, white, and yellow per requirement.
// Also avoids orange (#ff9800 used for selected) and bright red (#e53935 used
// for collision) so set colors don't clash with state highlights.

const SET_PALETTE = [
  "#3b82f6", // blue
  "#10b981", // emerald
  "#ec4899", // pink
  "#a855f7", // purple
  "#06b6d4", // cyan
  "#84cc16", // lime
  "#14b8a6", // teal
  "#8b5cf6", // violet
  "#22c55e", // green
  "#0ea5e9", // sky
  "#d946ef", // fuchsia
  "#6366f1", // indigo
  "#0891b2", // dark cyan
  "#65a30d", // dark lime
  "#9333ea", // dark purple
  "#0284c7", // dark sky
  "#16a34a", // dark green
  "#7c3aed", // dark violet
  "#15803d", // forest green
  "#1e40af", // dark blue
] as const;

export const SET_PALETTE_SIZE = SET_PALETTE.length;

export function colorForSet(setIndex: number): string {
  return SET_PALETTE[((setIndex % SET_PALETTE.length) + SET_PALETTE.length) % SET_PALETTE.length];
}

export function fillForSet(setIndex: number, alpha = 0.1): string {
  const c = colorForSet(setIndex);
  // c is "#RRGGBB"; build "rgba(r,g,b,a)".
  const r = parseInt(c.slice(1, 3), 16);
  const g = parseInt(c.slice(3, 5), 16);
  const b = parseInt(c.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
