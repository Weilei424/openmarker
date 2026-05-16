// OpenMarker — Phase 3: Visual workspace with Konva canvas.
// Layout: top bar | sidebar + canvas workspace | status bar.

import { useState, useCallback, useRef, useEffect } from "react";
import type { EngineStatus, PingResponse, GrainMode, AutoLayoutPlacement } from "../types/engine";
import type { Placement } from "../types/canvas";
import { useImportDxf, type ImportOutcome } from "../hooks/useImportDxf";
import { usePlacements } from "../hooks/usePlacements";
import { useAutoLayout } from "../hooks/useAutoLayout";
import { PieceList } from "../components/pieces/PieceList";
import { CanvasWorkspace } from "../components/canvas/CanvasWorkspace";
import { FabricPanel } from "../components/sidebar/FabricPanel";
import { GrainPanel } from "../components/sidebar/GrainPanel";

const ENGINE_URL = "http://127.0.0.1:8765";

export default function App() {
  const [engineStatus, setEngineStatus] = useState<EngineStatus>("unknown");
  const [statusMessage, setStatusMessage] = useState("Engine not connected");
  const [selectedPieceId, setSelectedPieceId] = useState<string | null>(null);
  const [fabricWidthMm, setFabricWidthMm] = useState<number>(1500);

  const { status: importStatus, pieces, warnings, errorMessage, handleFileSelected } = useImportDxf();
  const { placements, updatePlacement, resetPlacements, setAllPlacements } = usePlacements(pieces);

  const [grainDirectionDeg, setGrainDirectionDeg] = useState<number>(0);
  const [grainMode, setGrainMode] = useState<GrainMode>("none");
  const [fastMode, setFastMode] = useState<boolean>(false);

  const { runAutoLayout, status: autoStatus, errorMessage: autoError } = useAutoLayout();

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Reset selection when a new set of pieces is imported.
  useEffect(() => {
    setSelectedPieceId(null);
  }, [pieces]);

  const pingEngine = useCallback(async () => {
    setEngineStatus("connecting");
    setStatusMessage("Connecting to engine...");
    try {
      const res = await fetch(`${ENGINE_URL}/ping`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: PingResponse = await res.json();
      setEngineStatus("connected");
      setStatusMessage(`Engine connected — ${data.message} (v${data.version})`);
    } catch {
      setEngineStatus("error");
      setStatusMessage("Engine not reachable. Start: scripts/dev-engine.bat");
    }
  }, []);

  const onFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      // Reset input so the same file can be re-selected.
      e.target.value = "";
      // Use the returned outcome — React state is async and would be stale here.
      const outcome: ImportOutcome = await handleFileSelected(file);
      if (outcome.ok) {
        setStatusMessage(`${outcome.pieces.length} piece${outcome.pieces.length !== 1 ? "s" : ""} imported from ${file.name}`);
        // Auto-size fabric width to contain the initial single-row layout (10 mm gap between pieces).
        const totalW = outcome.pieces.reduce((sum, p) => sum + p.bbox.width + 10, 10);
        setFabricWidthMm(Math.ceil(totalW / 10) * 10);
      } else {
        setStatusMessage(`Import failed: ${outcome.errorMessage}`);
      }
    },
    [handleFileSelected]
  );

  const handleAutoLayout = useCallback(async () => {
    if (pieces.length === 0) return;
    const result = await runAutoLayout(pieces, fabricWidthMm, grainMode, grainDirectionDeg, fastMode);
    if (result) {
      const mapped: Placement[] = result.placements.map((pl: AutoLayoutPlacement) => ({
        pieceId: pl.piece_id,
        x: pl.x,
        y: pl.y,
        rotationDeg: pl.rotation_deg,
      }));
      setAllPlacements(mapped);
      setStatusMessage(
        `Auto layout: ${result.placements.length} piece${result.placements.length !== 1 ? "s" : ""} · ` +
        `Marker: ${Math.round(result.marker_length_mm)} mm · ` +
        `Utilization: ${result.utilization_pct}%`
      );
    } else {
      setStatusMessage(`Auto layout failed: ${autoError ?? "unknown error"}`);
    }
  }, [pieces, fabricWidthMm, grainMode, grainDirectionDeg, fastMode, runAutoLayout, setAllPlacements, autoError]);

  const importButtonLabel =
    importStatus === "loading" ? "Importing..." : "Import DXF";

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

          <Section title="Fabric">
            <FabricPanel fabricWidthMm={fabricWidthMm} onChange={setFabricWidthMm} />
          </Section>

          <Section title="Grain">
            <GrainPanel
              grainDirectionDeg={grainDirectionDeg}
              grainMode={grainMode}
              fastMode={fastMode}
              onGrainDirectionChange={setGrainDirectionDeg}
              onGrainModeChange={setGrainMode}
              onFastModeChange={setFastMode}
            />
          </Section>

          <Section title="Layout">
            {/* Hidden file input — triggered by the Import DXF button */}
            <input
              ref={fileInputRef}
              type="file"
              accept=".dxf"
              style={{ display: "none" }}
              onChange={onFileChange}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={importStatus === "loading"}
            >
              {importButtonLabel}
            </button>

            <button
              onClick={handleAutoLayout}
              disabled={pieces.length === 0 || autoStatus === "loading"}
              style={{ opacity: pieces.length === 0 ? 0.4 : 1 }}
            >
              {autoStatus === "loading" ? "Running..." : "Auto Layout"}
            </button>

            <button
              onClick={resetPlacements}
              disabled={pieces.length === 0}
              style={{ fontSize: 11, opacity: pieces.length === 0 ? 0.4 : 1 }}
            >
              Reset Layout
            </button>

            {importStatus === "error" && (
              <p style={styles.errorText}>{errorMessage}</p>
            )}

            {importStatus === "success" && (
              <>
                <p style={styles.successText}>{pieces.length} piece{pieces.length !== 1 ? "s" : ""} imported</p>
                <PieceList
                  pieces={pieces}
                  selectedPieceId={selectedPieceId}
                  onSelect={setSelectedPieceId}
                />
                {warnings.length > 0 && (
                  <div style={styles.warningBlock}>
                    {warnings.map((w, i) => (
                      <p key={i} style={styles.warningText}>{w}</p>
                    ))}
                  </div>
                )}
              </>
            )}

            {importStatus === "idle" && (
              <p style={styles.placeholder}>Import a DXF to begin.</p>
            )}
          </Section>
        </div>

        {/* Canvas workspace */}
        <div style={styles.canvas}>
          <CanvasWorkspace
            pieces={pieces}
            placements={placements}
            updatePlacement={updatePlacement}
            selectedPieceId={selectedPieceId}
            onSelectPiece={setSelectedPieceId}
            fabricWidthMm={fabricWidthMm}
          />
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
    overflow: "hidden",
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
  errorText: {
    color: "var(--color-error)",
    fontSize: 12,
  },
  successText: {
    color: "var(--color-success)",
    fontSize: 12,
  },
  warningBlock: {
    borderTop: "1px solid var(--color-border)",
    paddingTop: 4,
  },
  warningText: {
    color: "var(--color-warning)",
    fontSize: 11,
  },
} as const;
