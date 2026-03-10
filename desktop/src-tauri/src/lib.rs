// OpenMarker — Tauri application entry point.
// Phase 1: plain shell. Engine communication happens over HTTP (localhost:8765).

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
