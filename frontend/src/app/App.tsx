// OpenMarker — Phase 3: Visual workspace with Konva canvas.
// Layout: top bar | sidebar + canvas workspace | status bar.

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import type { EngineStatus, PingResponse, GrainMode, AutoLayoutPlacement, Piece } from "../types/engine";
import type { Placement } from "../types/canvas";
import { useImportDxf, type ImportOutcome } from "../hooks/useImportDxf";
import { usePlacements } from "../hooks/usePlacements";
import { useAutoLayout } from "../hooks/useAutoLayout";
import { PieceList } from "../components/pieces/PieceList";
import { CanvasWorkspace } from "../components/canvas/CanvasWorkspace";
import { FabricPanel } from "../components/sidebar/FabricPanel";
import { GrainPanel } from "../components/sidebar/GrainPanel";
import { computeMarkerMetrics } from "../utils/metrics";
import { engineToFrontendPlacement } from "../utils/enginePlacement";

const FABRIC_GRAIN_DEG = 90; // Fabric grain runs top → bottom (fixed by design).

const ENGINE_URL = "http://127.0.0.1:8765";

export default function App() {
  const [engineStatus, setEngineStatus] = useState<EngineStatus>("unknown");
  const [statusMessage, setStatusMessage] = useState("Engine not connected");
  const [selectedPieceId, setSelectedPieceId] = useState<string | null>(null);
  const [fabricWidthMm, setFabricWidthMm] = useState<number>(1500);

  const { status: importStatus, pieces, warnings, errorMessage, handleFileSelected } = useImportDxf();

  const [grainMode, setGrainMode] = useState<GrainMode>("none");
  const [fastMode, setFastMode] = useState<boolean>(false);
  const [copiesInput, setCopiesInput] = useState<string>("");
  const [manualEditEnabled, setManualEditEnabled] = useState<boolean>(false);

  const { runAutoLayout, abort: abortAutoLayout, status: autoStatus, errorMessage: autoError } = useAutoLayout();

  // Effective copy count: 1 when input is empty/invalid, otherwise clamped to [1, 20].
  const copies = useMemo(() => {
    const trimmed = copiesInput.trim();
    if (trimmed === "") return 1;
    const v = parseInt(trimmed, 10);
    if (!Number.isFinite(v) || v < 1) return 1;
    return Math.min(20, Math.floor(v));
  }, [copiesInput]);

  // Expand the imported pieces by `copies` so the canvas / engine / metrics
  // operate on the multi-set layout. setIndex tags each copy for coloring.
  const expandedPieces = useMemo<Piece[]>(() => {
    if (pieces.length === 0) return [];
    const out: Piece[] = [];
    for (let setIdx = 0; setIdx < copies; setIdx++) {
      for (const p of pieces) {
        out.push({ ...p, id: `${p.id}__c${setIdx}`, setIndex: setIdx });
      }
    }
    return out;
  }, [pieces, copies]);

  const { placements, updatePlacement, resetPlacements, setAllPlacements } = usePlacements(expandedPieces);

  const metrics = useMemo(
    () => computeMarkerMetrics(placements, expandedPieces, fabricWidthMm),
    [placements, expandedPieces, fabricWidthMm]
  );

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
    if (expandedPieces.length === 0) return;
    // Normalize the copies input so the user sees the effective value
    // (empty → "1", out-of-range → clamped).
    const canonical = String(copies);
    if (copiesInput.trim() !== canonical) {
      setCopiesInput(canonical);
    }
    const outcome = await runAutoLayout(
      expandedPieces, fabricWidthMm, grainMode, FABRIC_GRAIN_DEG, fastMode,
    );
    if (outcome.ok) {
      const pieceMap = new Map(expandedPieces.map((p) => [p.id, p]));
      const mapped: Placement[] = outcome.data.placements.map((pl: AutoLayoutPlacement) =>
        engineToFrontendPlacement(pieceMap.get(pl.piece_id)!, pl.x, pl.y, pl.rotation_deg)
      );
      setAllPlacements(mapped);
      setStatusMessage(
        `Auto layout: ${outcome.data.placements.length} piece${outcome.data.placements.length !== 1 ? "s" : ""} · ` +
        `Marker: ${Math.round(outcome.data.marker_length_mm)} mm · ` +
        `Utilization: ${outcome.data.utilization_pct}%`
      );
    } else if (outcome.aborted) {
      setStatusMessage("Auto layout stopped.");
    } else {
      setStatusMessage(`Auto layout failed: ${outcome.errorMessage}`);
    }
  }, [expandedPieces, fabricWidthMm, grainMode, fastMode, runAutoLayout, setAllPlacements, copies, copiesInput]);

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
              grainMode={grainMode}
              fastMode={fastMode}
              onGrainModeChange={setGrainMode}
              onFastModeChange={setFastMode}
            />
          </Section>

          <Section title="Settings">
            <label style={styles.settingRow}>
              <span style={styles.settingLabel}>Copies (1–20)</span>
              <input
                type="number"
                min={1}
                max={20}
                value={copiesInput}
                placeholder="1"
                onChange={(e) => setCopiesInput(e.target.value)}
                style={styles.numberInput}
              />
            </label>
            <label style={styles.checkRow}>
              <input
                type="checkbox"
                checked={manualEditEnabled}
                onChange={(e) => setManualEditEnabled(e.target.checked)}
              />
              <span style={{ fontSize: 12 }}>Enable manual edit on canvas</span>
            </label>
          </Section>

          <Section title="Metrics">
            <MetricsPanel
              length={metrics.length}
              utilization={metrics.utilization}
              overflowsFabric={metrics.overflowsFabric}
              hasPlacements={placements.length > 0}
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

            {autoStatus === "loading" && (
              <button
                onClick={abortAutoLayout}
                style={{ fontSize: 12, background: "var(--color-error, #b91c1c)", color: "#fff" }}
              >
                Stop
              </button>
            )}

            <button
              onClick={resetPlacements}
              disabled={pieces.length === 0}
              style={{ fontSize: 11, opacity: pieces.length === 0 ? 0.4 : 1 }}
            >
              Reset Layout
            </button>

            {autoStatus === "error" && autoError && (
              <p style={styles.errorText}>{autoError}</p>
            )}

            {importStatus === "error" && (
              <p style={styles.errorText}>{errorMessage}</p>
            )}

            {importStatus === "success" && (
              <>
                <p style={styles.successText}>{pieces.length} piece{pieces.length !== 1 ? "s" : ""} imported</p>
                <PieceList
                  pieces={pieces}
                  selectedPieceId={selectedPieceId}
                  onSelect={(id) => setSelectedPieceId(id === selectedPieceId ? null : id)}
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
            pieces={expandedPieces}
            placements={placements}
            updatePlacement={updatePlacement}
            selectedPieceId={selectedPieceId}
            onSelectPiece={setSelectedPieceId}
            fabricWidthMm={fabricWidthMm}
            grainMode={grainMode}
            markerLengthMm={metrics.length}
            manualEditEnabled={manualEditEnabled}
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

function MetricsPanel({
  length,
  utilization,
  overflowsFabric,
  hasPlacements,
}: {
  length: number;
  utilization: number;
  overflowsFabric: boolean;
  hasPlacements: boolean;
}) {
  if (!hasPlacements) {
    return <p style={styles.placeholder}>No pieces placed.</p>;
  }
  const utilColor =
    utilization >= 75 ? "var(--color-success)" : utilization >= 50 ? "var(--color-warning)" : "var(--color-text)";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={styles.metricRow}>
        <span style={styles.metricLabel}>Marker length</span>
        <span style={styles.metricValue}>{Math.round(length)} mm</span>
      </div>
      <div style={styles.metricRow}>
        <span style={styles.metricLabel}>Utilization</span>
        <span style={{ ...styles.metricValue, color: utilColor, fontSize: 14 }}>
          {overflowsFabric ? "—" : `${utilization.toFixed(1)}%`}
        </span>
      </div>
      {!overflowsFabric && (
        <div style={styles.utilBarTrack}>
          <div style={{ ...styles.utilBarFill, width: `${Math.min(100, utilization)}%`, background: utilColor }} />
        </div>
      )}
      {overflowsFabric && (
        <p style={styles.warningText}>Pieces overflow fabric — run Auto Layout to fit.</p>
      )}
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
  metricRow: {
    display: "flex",
    justifyContent: "space-between" as const,
    alignItems: "center",
    fontSize: 12,
  },
  metricLabel: {
    color: "var(--color-text-muted)",
  },
  metricValue: {
    fontWeight: 600,
    color: "var(--color-text)",
  },
  utilBarTrack: {
    height: 4,
    background: "var(--color-border)",
    borderRadius: 2,
    overflow: "hidden" as const,
    marginTop: 2,
  },
  utilBarFill: {
    height: "100%",
    transition: "width 0.2s ease",
  },
  settingRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between" as const,
    gap: 8,
    fontSize: 12,
  },
  settingLabel: {
    color: "var(--color-text-muted)",
  },
  numberInput: {
    width: 60,
    padding: "2px 6px",
    background: "var(--color-surface)",
    color: "var(--color-text)",
    border: "1px solid var(--color-border)",
    borderRadius: 3,
    fontSize: 12,
    textAlign: "right" as const,
  },
  checkRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    cursor: "pointer",
    marginTop: 6,
  },
} as const;
