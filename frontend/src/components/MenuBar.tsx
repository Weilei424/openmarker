import { useState, useRef, useEffect } from "react";

interface MenuItem {
  label: string;
  // Phase 6: UI only. onClick is intentionally a no-op for now.
}

interface MenuGroup {
  label: string;
  items: MenuItem[];
}

const MENUS: MenuGroup[] = [
  { label: "File",     items: [{ label: "Open…" }, { label: "Quit" }] },
  { label: "Edit",     items: [{ label: "Undo" }, { label: "Redo" }] },
  { label: "Settings", items: [{ label: "Preferences…" }] },
  { label: "Help",     items: [{ label: "About OpenMarker" }] },
];

export function MenuBar() {
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  // Close the open menu when clicking outside the bar.
  useEffect(() => {
    if (openIdx === null) return;
    function onDocClick(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpenIdx(null);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [openIdx]);

  return (
    <div ref={ref} style={styles.bar}>
      {MENUS.map((menu, i) => {
        const open = openIdx === i;
        return (
          <div key={menu.label} style={styles.menuWrap}>
            <button
              type="button"
              style={{ ...styles.menuBtn, ...(open ? styles.menuBtnOpen : {}) }}
              onClick={() => setOpenIdx(open ? null : i)}
              onMouseEnter={() => { if (openIdx !== null) setOpenIdx(i); }}
            >
              {menu.label}
            </button>
            {open && (
              <div style={styles.dropdown} role="menu">
                {menu.items.map((item) => (
                  <div
                    key={item.label}
                    style={styles.item}
                    role="menuitem"
                    onClick={() => setOpenIdx(null)}
                  >
                    {item.label}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

const styles = {
  bar: {
    display: "flex",
    height: 28,
    background: "var(--color-surface)",
    borderBottom: "1px solid var(--color-border)",
    paddingLeft: 4,
    fontSize: 12,
    flexShrink: 0,
    position: "relative" as const,
    userSelect: "none" as const,
  },
  menuWrap: {
    position: "relative" as const,
  },
  menuBtn: {
    background: "transparent",
    border: "none",
    color: "var(--color-text)",
    padding: "0 10px",
    height: 28,
    cursor: "pointer",
    fontSize: 12,
  },
  menuBtnOpen: {
    background: "var(--color-bg)",
  },
  dropdown: {
    position: "absolute" as const,
    top: 28,
    left: 0,
    minWidth: 160,
    background: "var(--color-surface)",
    border: "1px solid var(--color-border)",
    borderTop: "none",
    boxShadow: "0 2px 6px rgba(0,0,0,0.4)",
    zIndex: 1000,
  },
  item: {
    padding: "6px 14px",
    cursor: "pointer",
    color: "var(--color-text)",
  },
} as const;
