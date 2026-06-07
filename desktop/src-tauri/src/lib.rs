// OpenMarker — Tauri application entry point.
// Dynamic window size — 70% of monitor logical height bumped 15% larger, 4:3 aspect ratio.

use tauri::{Manager, LogicalSize, Size};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                if let Err(err) = size_and_show(&window) {
                    eprintln!("[OpenMarker] window sizing failed: {err}");
                    let _ = window.set_size(Size::Logical(LogicalSize { width: 1472.0, height: 920.0 }));
                    let _ = window.center();
                    let _ = window.show();
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn size_and_show(window: &tauri::WebviewWindow) -> Result<(), Box<dyn std::error::Error>> {
    // current_monitor returns the monitor under the cursor at startup.
    let monitor = window
        .current_monitor()?
        .ok_or("no monitor detected")?;

    let scale = monitor.scale_factor();
    let physical = monitor.size();
    let logical_w = physical.width as f64 / scale;
    let logical_h = physical.height as f64 / scale;

    // 70% of monitor height as the base, bumped 15% larger (-> 80.5%). Width
    // tracks at 4:3, so the whole window grows 15% in each dimension.
    let mut height = logical_h * 0.7 * 1.15;
    let mut width = height * 4.0 / 3.0;

    // If the 4:3 width would exceed the monitor, clamp to 95% of monitor width
    // and recompute height from that.
    let max_width = logical_w * 0.95;
    if width > max_width {
        width = max_width;
        height = width * 3.0 / 4.0;
    }

    window.set_size(Size::Logical(LogicalSize { width, height }))?;
    window.center()?;
    window.show()?;
    Ok(())
}
