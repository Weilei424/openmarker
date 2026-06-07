// OpenMarker — Phase 6: cached-tabs workflow with bottom metrics panel.
// Layout: topbar | preview-panel | (sidebar + (tabs / canvas)) | bottom-panel | statusbar.

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import type { EngineStatus, PingResponse, GrainMode, Piece, LayoutQuality } from "../types/engine";
import { useImportDxf, type ImportOutcome } from "../hooks/useImportDxf";
import { usePlacements } from "../hooks/usePlacements";
import { useAutoLayout } from "../hooks/useAutoLayout";
import { useLayoutCache } from "../hooks/useLayoutCache";
import { PreviewPanel } from "../components/PreviewPanel";
import { MenuBar } from "../components/MenuBar";
import { CachedLayoutTabs } from "../components/CachedLayoutTabs";
import { BottomPanel, formatDuration } from "../components/BottomPanel";
import { CanvasWorkspace } from "../components/canvas/CanvasWorkspace";
import { FabricPanel } from "../components/sidebar/FabricPanel";
import { GrainPanel } from "../components/sidebar/GrainPanel";
import { QualityPanel } from "../components/sidebar/QualityPanel";

const FABRIC_GRAIN_DEG = 90;
const ENGINE_URL = "http://127.0.0.1:8765";

export default function App() {
  const [engineStatus, setEngineStatus] = useState<EngineStatus>("unknown");
  const [statusMessage, setStatusMessage] = useState("Engine not connected");
  const [selectedPieceId, setSelectedPieceId] = useState<string | null>(null);
  const [fabricWidthMm, setFabricWidthMm] = useState<number>(1500);
  const [currentFileName, setCurrentFileName] = useState<string | null>(null);

  const { status: importStatus, pieces, warnings, errorMessage, handleFileSelected } = useImportDxf();

  const [grainMode, setGrainMode] = useState<GrainMode>("single");
  const [showGrainline, setShowGrainline] = useState<boolean>(true);
  const [copiesInput, setCopiesInput] = useState<string>("");
  const [disableNfpCache, setDisableNfpCache] = useState<boolean>(false);
  const [effort, setEffort] = useState<number>(1);
  const [quality, setQuality] = useState<LayoutQuality>("fast");
  const [elapsedMs, setElapsedMs] = useState<number>(0);
  const [maxCacheEntries, setMaxCacheEntries] = useState<number>(5);
  // TEMP(phase6-bench): include effort in dedup key so the same settings at
  // different effort levels create separate cache tabs for benchmarking.
  const [includeEffortInKey, setIncludeEffortInKey] = useState<boolean>(false);

  const { runAutoLayout, abort: abortAutoLayout, status: autoStatus, errorMessage: autoError } = useAutoLayout();
  const { entries, activeId, activeEntry, setActiveId, closeTab, refresh: refreshCache, clearAll: clearCache } = useLayoutCache();

  const copies = useMemo(() => {
    const trimmed = copiesInput.trim();
    if (trimmed === "") return 1;
    const v = parseInt(trimmed, 10);
    if (!Number.isFinite(v) || v < 1) return 1;
    return Math.min(20, Math.floor(v));
  }, [copiesInput]);

  // Form-state expansion: used as the input to the next Auto Layout call.
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

  // Snapshot expansion: derived from the ACTIVE cached entry's `copies`, not
  // the sidebar. Keeps the canvas frozen while the user edits sidebar values
  // for the next run. Falls back to `expandedPieces` only when no tab is active
  // (so the canvas can still show the empty-fabric backdrop with current width).
  const snapshotPieces = useMemo<Piece[]>(() => {
    if (!activeEntry || pieces.length === 0) return [];
    const out: Piece[] = [];
    for (let setIdx = 0; setIdx < activeEntry.copies; setIdx++) {
      for (const p of pieces) {
        out.push({ ...p, id: `${p.id}__c${setIdx}`, setIndex: setIdx });
      }
    }
    return out;
  }, [pieces, activeEntry?.copies]);

  const { placements } = usePlacements(snapshotPieces, activeEntry?.placements ?? null);

  // Canvas fabric width is the active tab's snapshot when one is active,
  // otherwise the sidebar's current value (for the empty-fabric backdrop).
  const canvasFabricWidthMm = activeEntry?.fabric_width_mm ?? fabricWidthMm;

  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setSelectedPieceId(null);
  }, [pieces]);

  // Reflect the current file in the OS window title (Tauri only; harmless in plain Vite dev).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { getCurrentWindow } = await import("@tauri-apps/api/window");
        if (cancelled) return;
        const title = currentFileName
          ? `OpenMarker — Working on ${currentFileName}`
          : "OpenMarker";
        await getCurrentWindow().setTitle(title);
      } catch {
        // Not running in Tauri (e.g. `npm run dev` standalone) — ignore.
      }
    })();
    return () => { cancelled = true; };
  }, [currentFileName]);

  // Live elapsed timer while an auto-layout runs (mainly for the multi-minute
  // Better/Best tiers). Resets to 0 when not loading.
  useEffect(() => {
    if (autoStatus !== "loading") {
      setElapsedMs(0);
      return;
    }
    const startedAt = Date.now();
    setElapsedMs(0);
    const id = setInterval(() => setElapsedMs(Date.now() - startedAt), 1000);
    return () => clearInterval(id);
  }, [autoStatus]);

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
      e.target.value = "";

      // New import = fresh slate. Drop cached tabs and reset sidebar form
      // before we even know whether the import succeeds — the user's
      // mental model is "I'm starting over."
      await clearCache();
      setFabricWidthMm(1500);
      setGrainMode("single");
      setShowGrainline(true);
      setCopiesInput("");

      const outcome: ImportOutcome = await handleFileSelected(file);
      if (outcome.ok) {
        setStatusMessage(`${outcome.pieces.length} piece${outcome.pieces.length !== 1 ? "s" : ""} imported from ${file.name}`);
        setCurrentFileName(file.name);
      } else {
        setStatusMessage(`Import failed: ${outcome.errorMessage}`);
      }
    },
    [handleFileSelected, clearCache]
  );

  const handleAutoLayout = useCallback(async () => {
    if (expandedPieces.length === 0 || !currentFileName) return;
    const canonical = String(copies);
    if (copiesInput.trim() !== canonical) {
      setCopiesInput(canonical);
    }
    const outcome = await runAutoLayout(
      currentFileName, expandedPieces, fabricWidthMm, grainMode, FABRIC_GRAIN_DEG, copies, disableNfpCache, effort, maxCacheEntries, includeEffortInKey, quality,
    );
    if (outcome.ok) {
      await refreshCache();
      setActiveId(outcome.data.id);
      if (outcome.data.stopped) {
        setStatusMessage(
          `Stopped — showing best result so far · ` +
          `Marker: ${Math.round(outcome.data.marker_length_mm)} mm · ` +
          `Utilization: ${outcome.data.utilization_pct}%`
        );
      } else {
        setStatusMessage(
          `Auto layout: ${outcome.data.placements.length} piece${outcome.data.placements.length !== 1 ? "s" : ""} · ` +
          `Marker: ${Math.round(outcome.data.marker_length_mm)} mm · ` +
          `Utilization: ${outcome.data.utilization_pct}%`
        );
      }
    } else if (outcome.aborted) {
      setStatusMessage("Auto layout stopped.");
    } else {
      setStatusMessage(`Auto layout failed: ${outcome.errorMessage}`);
    }
  }, [expandedPieces, currentFileName, fabricWidthMm, grainMode, copies, copiesInput, disableNfpCache, effort, maxCacheEntries, includeEffortInKey, quality, runAutoLayout, refreshCache, setActiveId]);

  const importButtonLabel = importStatus === "loading" ? "Importing..." : "Import DXF";

  return (
    <div style={styles.root}>
      <MenuBar />

      <PreviewPanel
        pieces={pieces}
        selectedPieceId={selectedPieceId}
        onSelect={setSelectedPieceId}
      />

      <div style={styles.body}>
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
              showGrainline={showGrainline}
              onGrainModeChange={setGrainMode}
              onShowGrainlineChange={setShowGrainline}
            />
          </Section>

          <Section title="Settings">
            <label style={styles.settingRowVertical}>
              <span style={styles.settingLabel}>Copies (1–20)</span>
              <input
                type="number"
                min={1}
                max={20}
                value={copiesInput}
                placeholder="1"
                onChange={(e) => setCopiesInput(e.target.value)}
                style={styles.numberInputTall}
              />
            </label>
          </Section>

          <Section title="Advanced">
            <label style={styles.settingRow}>
              <span style={styles.settingLabel}>Cached results (5–20)</span>
              <input
                type="number"
                min={5}
                max={20}
                value={maxCacheEntries}
                onChange={(e) => {
                  const v = parseInt(e.target.value, 10);
                  if (Number.isFinite(v)) setMaxCacheEntries(Math.max(5, Math.min(20, v)));
                }}
                style={styles.numberInputSmall}
              />
            </label>

            <label style={styles.advancedCheckRow}>
              <input
                type="checkbox"
                checked={disableNfpCache}
                onChange={(e) => setDisableNfpCache(e.target.checked)}
              />
              <span style={{ fontSize: 12 }}>Disable NFP cache</span>
            </label>
            <p style={styles.advancedHint}>For benchmarking. Layout result is identical either way; only speed changes.</p>

            {/* TEMP(phase6-bench): cache key includes effort for benchmarking */}
            <label style={styles.advancedCheckRow}>
              <input
                type="checkbox"
                checked={includeEffortInKey}
                onChange={(e) => setIncludeEffortInKey(e.target.checked)}
              />
              <span style={{ fontSize: 12 }}>[TEMP] Include effort in cache key</span>
            </label>
            <p style={styles.advancedHint}>For benchmarking: same settings at different effort levels create separate tabs.</p>

            {/* Parallel effort applies to the Fast tier only. Better/Best force
                all-but-one core for more GA islands, so the radio is disabled then. */}
            <div style={{ marginTop: 8, opacity: quality !== "fast" ? 0.5 : 1 }}>
              <div style={styles.settingLabel}>Parallel effort</div>
              {[
                { value: 1, label: "Eco (serial)" },
                { value: 2, label: "Low (2 cores)" },
                { value: 3, label: "Balanced (1/2 cores)" },
                { value: 4, label: "High (all but one)" },
                { value: 5, label: "Max (all cores)" },
              ].map((opt) => (
                <label key={opt.value} style={styles.advancedRadioRow}>
                  <input
                    type="radio"
                    name="effort"
                    checked={effort === opt.value}
                    disabled={quality !== "fast"}
                    onChange={() => setEffort(opt.value)}
                  />
                  <span style={{ fontSize: 12 }}>{opt.label}</span>
                </label>
              ))}
              <p style={styles.advancedHint}>
                {quality !== "fast"
                  ? "Better/Best use all but one core; this applies to Fast only."
                  : "Cancellation may not interrupt parallel runs immediately."}
              </p>
            </div>
          </Section>

          <Section title="Layout quality">
            <QualityPanel quality={quality} onChange={setQuality} />
          </Section>

          <Section title="Layout">
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

            {autoStatus === "loading" && (
              <>
                <p style={styles.advancedHint}>
                  {`Optimizing (${quality})… ${formatDuration(elapsedMs)} elapsed`}
                </p>
                <div className="progress-indeterminate" />
              </>
            )}

            {autoStatus === "error" && autoError && (
              <p style={styles.errorText}>{autoError}</p>
            )}

            {importStatus === "error" && (
              <p style={styles.errorText}>{errorMessage}</p>
            )}

            {importStatus === "success" && warnings.length > 0 && (
              <div style={styles.warningBlock}>
                {warnings.map((w, i) => (
                  <p key={i} style={styles.warningText}>{w}</p>
                ))}
              </div>
            )}

            {importStatus === "idle" && (
              <p style={styles.placeholder}>Import a DXF to begin.</p>
            )}
          </Section>
        </div>

        {/* Canvas column: tabs strip above the canvas (sharing the canvas's left edge). */}
        <div style={styles.canvasColumn}>
          <CachedLayoutTabs
            entries={entries}
            activeId={activeId}
            onActivate={setActiveId}
            onClose={closeTab}
          />
          <div style={styles.canvas}>
            <CanvasWorkspace
              pieces={snapshotPieces.length > 0 ? snapshotPieces : expandedPieces}
              placements={placements}
              selectedPieceId={selectedPieceId}
              onSelectPiece={setSelectedPieceId}
              fabricWidthMm={canvasFabricWidthMm}
              showGrainline={showGrainline}
              markerLengthMm={activeEntry?.marker_length_mm ?? 0}
            />
          </div>
        </div>
      </div>

      <BottomPanel
        markerLengthMm={activeEntry?.marker_length_mm ?? null}
        utilizationPct={activeEntry?.utilization_pct ?? null}
        durationMs={activeEntry?.duration_ms ?? null}
      />

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
  body: { flex: 1, display: "flex", overflow: "hidden" },
  sidebar: {
    width: "var(--sidebar-width)",
    borderRight: "1px solid var(--color-border)",
    background: "var(--color-surface)",
    display: "flex",
    flexDirection: "column" as const,
    flexShrink: 0,
    overflowY: "auto" as const,
  },
  canvasColumn: {
    flex: 1,
    display: "flex",
    flexDirection: "column" as const,
    overflow: "hidden",
  },
  canvas: { flex: 1, overflow: "hidden" },
  section: { borderBottom: "1px solid var(--color-border)" },
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
  statusDot: { display: "flex", alignItems: "center", gap: 6, fontSize: 12 },
  dot: { width: 8, height: 8, borderRadius: "50%", display: "inline-block" },
  placeholder: { color: "var(--color-text-muted)", fontSize: 12 },
  errorText: { color: "var(--color-error)", fontSize: 12 },
  successText: { color: "var(--color-success)", fontSize: 12 },
  warningBlock: { borderTop: "1px solid var(--color-border)", paddingTop: 4 },
  warningText: { color: "var(--color-warning)", fontSize: 11 },
  settingRowVertical: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 6,
    fontSize: 12,
  },
  settingRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between" as const,
    gap: 8,
    fontSize: 12,
  },
  numberInputSmall: {
    width: 60,
    padding: "4px 6px",
    background: "var(--color-surface)",
    color: "var(--color-text)",
    border: "1px solid var(--color-border)",
    borderRadius: 3,
    fontSize: 12,
    textAlign: "right" as const,
  },
  settingLabel: { color: "var(--color-text-muted)" },
  numberInputTall: {
    width: 80,
    height: 44,
    padding: "4px 8px",
    background: "var(--color-surface)",
    color: "var(--color-text)",
    border: "1px solid var(--color-border)",
    borderRadius: 3,
    fontSize: 18,
    textAlign: "right" as const,
  },
  advancedCheckRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    cursor: "pointer",
    fontSize: 12,
  },
  advancedRadioRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginTop: 4,
    cursor: "pointer",
  },
  advancedHint: {
    fontSize: 10,
    color: "var(--color-text-muted)",
    fontStyle: "italic" as const,
    marginTop: 4,
    marginBottom: 0,
  },
} as const;
