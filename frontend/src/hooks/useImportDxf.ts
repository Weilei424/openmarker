// Hook that handles the DXF import HTTP call, keeping fetch logic out of App.tsx.

import { useState, useCallback } from "react";
import type { ImportDxfResponse, ImportStatus, Piece } from "../types/engine";

const ENGINE_URL = "http://127.0.0.1:8765";

interface UseImportDxfResult {
  status: ImportStatus;
  pieces: Piece[];
  warnings: string[];
  errorMessage: string;
  handleFileSelected: (file: File) => Promise<void>;
}

export function useImportDxf(): UseImportDxfResult {
  const [status, setStatus] = useState<ImportStatus>("idle");
  const [pieces, setPieces] = useState<Piece[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [errorMessage, setErrorMessage] = useState("");

  const handleFileSelected = useCallback(async (file: File) => {
    setStatus("loading");
    setPieces([]);
    setWarnings([]);
    setErrorMessage("");

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${ENGINE_URL}/import-dxf`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        setStatus("error");
        setErrorMessage(err.detail ?? `HTTP ${res.status}`);
        return;
      }

      const data: ImportDxfResponse = await res.json();
      setPieces(data.pieces);
      setWarnings(data.warnings);
      setStatus("success");
    } catch {
      setStatus("error");
      setErrorMessage("Engine not reachable. Start: scripts/dev-engine.bat");
    }
  }, []);

  return { status, pieces, warnings, errorMessage, handleFileSelected };
}
