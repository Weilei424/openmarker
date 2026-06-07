// Types for responses from the local Python engine API (http://127.0.0.1:8765)

export interface PingResponse {
  status: "ok" | "error";
  message: string;
  version: string;
}

export type EngineStatus = "unknown" | "connecting" | "connected" | "error";

export interface BoundingBox {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
  width: number;
  height: number;
}

export interface Piece {
  id: string;
  name: string;
  polygon: [number, number][];
  area: number;
  bbox: BoundingBox;
  is_valid: boolean;
  validation_notes: string[];
  grainline_direction_deg: number | null;
  // Frontend-only: which copy/set this piece belongs to (0-based). The engine
  // ignores it; it just uses `id` as an opaque token.
  setIndex?: number;
}

export interface ImportDxfResponse {
  pieces: Piece[];
  piece_count: number;
  skipped_count: number;
  warnings: string[];
}

export type ImportStatus = "idle" | "loading" | "success" | "error";

// Phase 6: "none" removed. Only "single" and "bi" are valid.
export type GrainMode = "single" | "bi";

// Layout quality tier sent to POST /auto-layout. "fast" = today's warm-start;
// "better"/"best" run the GA optimizer with a short/long time budget.
export type LayoutQuality = "fast" | "better" | "best";

export interface AutoLayoutPlacement {
  piece_id: string;
  x: number;
  y: number;
  rotation_deg: number;
}

// Phase 6: /auto-layout now also returns the cache id, timestamp, and duration.
export interface AutoLayoutResponse {
  id: string;
  timestamp: string;            // YYYYMMDDHHMMSS
  duration_ms: number;
  placements: AutoLayoutPlacement[];
  marker_length_mm: number;
  utilization_pct: number;
}

export interface CachedLayoutSummary {
  id: string;
  filename: string;
  timestamp: string;
  grain_mode: GrainMode;
  copies: number;
  fabric_width_mm: number;
  marker_length_mm: number;
  utilization_pct: number;
  duration_ms: number;
}

export interface CachedLayout extends CachedLayoutSummary {
  placements: AutoLayoutPlacement[];
}
