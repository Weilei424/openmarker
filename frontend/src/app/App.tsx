// OpenMarker - Phase 1: app shell with engine connectivity check.
// Layout: top bar | sidebar + canvas workspace | status bar.

import { useState, useCallback } from "react";
import type { EngineStatus, PingResponse } from "../types/engine";

const ENGINE_URL = "http://127.0.0.1:8765";

export default function App() {
  const [engineStatus, setEngineStatus] = useState<EngineStatus>("unknown");
  const [statusMessage, setStatusMessage] = useState("Engine not connected");

  const pingEngine = useCallback(async () => {
    setEngineStatus("connecting");
    setStatusMessage("Connecting to engine...");
    try {
      const res = await fetch(`${ENGINE_URL}/ping`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: PingResponse = await res.json();
      setEngineStatus("connected");
      setStatusMessage(`Engine connected — ${data.message} (v${data.version})`);
    } catch (err) {
      setEngineStatus("error");
      setStatusMessage("Engine not reachable. Start: python engine/api/main.py");
    }
  }, []);

  return (
    <div style={styles.root}>
      {/* Top bar */}
      <div style={styles.topBar}>
        <span style={styles.appTitle}>OpenMarker</span>
      </div>

      {/* Body: sidebar + workspace */}
      <div style={styles.body}>
        {/* Sidebar */}
        <div style={styles.sidebar}>
          <Section title="Engine">
            <button onClick={pingEngine} disabled={engineStatus === "connecting"}>
              {engineStatus === "connecting" ? "Connecting..." : "Ping Engine"}
            </button>
            <StatusDot status={engineStatus} />
          </Section>

          <Section title="Layout">
            <p style={styles.placeholder}>Import a DXF to begin.</p>
          </Section>
        </div>

        {/* Canvas workspace placeholder */}
        <div style={styles.canvas}>
          <p style={styles.canvasPlaceholder}>Workspace — Phase 3</p>
        </div>
      </div>

      {/* Status bar */}
      <div style={styles.statusBar}>
        <span>{statusMessage}</span>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={styles.section}>
      <div style={styles.sectionTitle}>{title}</div>
      <div style={styles.sectionBody}>{children}</div>
    </div>
  );
}

function StatusDot({ status }: { status: EngineStatus }) {
  const colors: Record<EngineStatus, string> = {
    unknown: "var(--color-text-muted)",
    connecting: "var(--color-warning)",
    connected: "var(--color-success)",
    error: "var(--color-error)",
  };
  const labels: Record<EngineStatus, string> = {
    unknown: "Not checked",
    connecting: "Connecting",
    connected: "Connected",
    error: "Error",
  };
  return (
    <div style={styles.statusDot}>
      <span style={{ ...styles.dot, background: colors[status] }} />
      <span style={{ color: colors[status] }}>{labels[status]}</span>
    </div>
  );
}

const styles = {
  root: {
    display: "flex",
    flexDirection: "column" as const,
    height: "100vh",
    background: "var(--color-bg)",
  },
  topBar: {
    height: "var(--topbar-height)",
    background: "var(--color-surface)",
    borderBottom: "1px solid var(--color-border)",
    display: "flex",
    alignItems: "center",
    padding: "0 16px",
    flexShrink: 0,
  },
  appTitle: {
    fontWeight: 600,
    fontSize: 14,
    letterSpacing: "0.02em",
    color: "var(--color-text)",
  },
  body: {
    flex: 1,
    display: "flex",
    overflow: "hidden",
  },
  sidebar: {
    width: "var(--sidebar-width)",
    borderRight: "1px solid var(--color-border)",
    background: "var(--color-surface)",
    display: "flex",
    flexDirection: "column" as const,
    flexShrink: 0,
    overflowY: "auto" as const,
  },
  section: {
    borderBottom: "1px solid var(--color-border)",
  },
  sectionTitle: {
    padding: "8px 12px",
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase" as const,
    letterSpacing: "0.05em",
    color: "var(--color-text-muted)",
  },
  sectionBody: {
    padding: "8px 12px 12px",
    display: "flex",
    flexDirection: "column" as const,
    gap: 8,
  },
  canvas: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "#111",
  },
  canvasPlaceholder: {
    color: "var(--color-text-muted)",
    fontSize: 13,
  },
  statusBar: {
    height: "var(--statusbar-height)",
    background: "var(--color-surface)",
    borderTop: "1px solid var(--color-border)",
    display: "flex",
    alignItems: "center",
    padding: "0 12px",
    fontSize: 12,
    color: "var(--color-text-muted)",
    flexShrink: 0,
  },
  statusDot: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    fontSize: 12,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: "50%",
    display: "inline-block",
  },
  placeholder: {
    color: "var(--color-text-muted)",
    fontSize: 12,
  },
} as const;
