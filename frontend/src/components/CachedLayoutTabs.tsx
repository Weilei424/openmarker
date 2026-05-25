import type { CachedLayoutSummary } from "../types/engine";

interface Props {
  entries: CachedLayoutSummary[];
  activeId: string | null;
  onActivate: (id: string) => void;
  onClose: (id: string) => void;
}

/**
 * Tab strip rendered ABOVE the canvas, scoped to the canvas column
 * (left edge aligned with canvas, not with the sidebar).
 */
export function CachedLayoutTabs({ entries, activeId, onActivate, onClose }: Props) {
  if (entries.length === 0) {
    return <div style={styles.empty}>No cached layouts yet.</div>;
  }
  return (
    <div style={styles.strip}>
      {entries.map((e) => {
        const isActive = e.id === activeId;
        return (
          <div
            key={e.id}
            style={{ ...styles.tab, ...(isActive ? styles.tabActive : {}) }}
            onClick={() => onActivate(e.id)}
            role="button"
            tabIndex={0}
          >
            <span style={styles.label}>
              {e.grain_mode} · ×{e.copies} · {formatHHMMSS(e.timestamp)}
            </span>
            <button
              style={styles.closeBtn}
              onClick={(ev) => {
                ev.stopPropagation();
                onClose(e.id);
              }}
              aria-label={`Close ${e.id}`}
              title="Close tab"
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}

// "YYYYMMDDHHMMSS" → "HH:MM:SS"
function formatHHMMSS(timestamp: string): string {
  if (timestamp.length !== 14) return timestamp;
  return `${timestamp.slice(8, 10)}:${timestamp.slice(10, 12)}:${timestamp.slice(12, 14)}`;
}

const styles = {
  strip: {
    height: 32,
    background: "var(--color-surface)",
    borderBottom: "1px solid var(--color-border)",
    display: "flex",
    alignItems: "stretch",
    overflowX: "auto" as const,
    flexShrink: 0,
  },
  empty: {
    height: 32,
    background: "var(--color-surface)",
    borderBottom: "1px solid var(--color-border)",
    display: "flex",
    alignItems: "center",
    padding: "0 12px",
    fontSize: 12,
    color: "var(--color-text-muted)",
    flexShrink: 0,
  },
  tab: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "0 8px 0 12px",
    fontSize: 12,
    cursor: "pointer",
    borderRight: "1px solid var(--color-border)",
    color: "var(--color-text-muted)",
    background: "transparent",
  },
  tabActive: {
    background: "var(--color-bg)",
    color: "var(--color-text)",
    fontWeight: 600 as const,
  },
  label: {
    whiteSpace: "nowrap" as const,
  },
  closeBtn: {
    background: "transparent",
    border: "none",
    color: "inherit",
    cursor: "pointer",
    fontSize: 14,
    padding: "0 4px",
    lineHeight: 1,
  },
} as const;
