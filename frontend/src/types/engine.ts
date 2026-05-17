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
}

export interface ImportDxfResponse {
  pieces: Piece[];
  piece_count: number;
  skipped_count: number;
  warnings: string[];
}

export type ImportStatus = "idle" | "loading" | "success" | "error";

export type GrainMode = "none" | "single" | "bi";

export interface AutoLayoutPlacement {
  piece_id: string;
  x: number;
  y: number;
  rotation_deg: number;
}

export interface AutoLayoutResponse {
  placements: AutoLayoutPlacement[];
  marker_length_mm: number;
  utilization_pct: number;
}
