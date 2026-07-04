/// M1.2 — receive the frame-probe result from the webview, persist it, and
/// (when SPIKE_AUTOEXIT=1) quit so the spike can run unattended.
#[tauri::command]
fn report_spike(result: String) -> Result<(), String> {
    let path = std::env::var("SPIKE_RESULT_PATH")
        .unwrap_or_else(|_| "M1-spike-result.json".to_string());
    std::fs::write(&path, &result).map_err(|e| e.to_string())?;
    println!("SPIKE_RESULT written to {path}\n{result}");
    if std::env::var("SPIKE_AUTOEXIT").as_deref() == Ok("1") {
        // give the println a moment to flush, then exit cleanly
        std::thread::spawn(|| {
            std::thread::sleep(std::time::Duration::from_millis(500));
            std::process::exit(0);
        });
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![report_spike])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
