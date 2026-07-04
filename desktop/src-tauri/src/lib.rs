use std::net::TcpStream;
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Manager, RunEvent,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

/// Handle to the spawned Hermes API sidecar so it can be killed on exit.
struct Sidecar(Mutex<Option<Child>>);

const HOTKEY: &str = "ctrl+shift+v";

/// Repo root (dev layout: this crate sits at desktop/src-tauri).
fn project_root() -> std::path::PathBuf {
    std::path::PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../.."))
}

fn env_from_project(key: &str) -> Option<String> {
    // process env wins; fall back to the project .env
    if let Ok(v) = std::env::var(key) {
        return Some(v);
    }
    dotenvy::from_path_iter(project_root().join(".env"))
        .ok()?
        .flatten()
        .find(|(k, _)| k == key)
        .map(|(_, v)| v)
}

/// Front-end bootstrap config: where the Hermes API lives + its token.
/// Local-only secret handed to our own webview — never leaves the box.
#[tauri::command]
fn get_config() -> serde_json::Value {
    let port = env_from_project("HERMES_API_PORT").unwrap_or_else(|| "8100".into());
    serde_json::json!({
        "apiUrl": format!("http://127.0.0.1:{port}"),
        "wsUrl": format!("ws://127.0.0.1:{port}/ws/events"),
        "token": env_from_project("HERMES_API_TOKEN").unwrap_or_default(),
        "vaultPath": env_from_project("VAULT_PATH").unwrap_or_default(),
    })
}

/// M3.4 — read a note's markdown for the side panel. Path must resolve
/// inside the vault (no traversal out of it).
#[tauri::command]
fn read_note(path: String) -> Result<String, String> {
    let vault = std::path::PathBuf::from(
        env_from_project("VAULT_PATH").ok_or("VAULT_PATH not configured")?,
    )
    .canonicalize()
    .map_err(|e| e.to_string())?;
    let target = std::path::Path::new(&path)
        .canonicalize()
        .map_err(|e| format!("{path}: {e}"))?;
    if !target.starts_with(&vault) {
        return Err("path escapes vault".into());
    }
    std::fs::read_to_string(&target).map_err(|e| e.to_string())
}

/// M1.2 — receive the frame-probe result from the webview, persist it, and
/// (when SPIKE_AUTOEXIT=1) quit so the spike can run unattended. The probe
/// stays in the app as a startup canary for driver/glvnd regressions (M1.3).
#[tauri::command]
fn report_spike(result: String) -> Result<(), String> {
    let path = std::env::var("SPIKE_RESULT_PATH")
        .unwrap_or_else(|_| "M1-spike-result.json".to_string());
    std::fs::write(&path, &result).map_err(|e| e.to_string())?;
    println!("SPIKE_RESULT written to {path}\n{result}");
    if std::env::var("SPIKE_AUTOEXIT").as_deref() == Ok("1") {
        std::thread::spawn(|| {
            std::thread::sleep(std::time::Duration::from_millis(500));
            std::process::exit(0);
        });
    }
    Ok(())
}

/// ctrl+Q from the webview — exits through the normal path so the sidecar
/// gets reaped (RunEvent::Exit).
#[tauri::command]
fn quit_app(app: AppHandle) {
    app.exit(0);
}

/// gpu-deck — open the full mission-control tree in its own window.
#[tauri::command]
fn open_deck(app: AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window("deck") {
        w.show().and_then(|_| w.set_focus()).map_err(|e| e.to_string())?;
        return Ok(());
    }
    let url = if cfg!(debug_assertions) {
        tauri::WebviewUrl::External("http://localhost:1420/#deck".parse().unwrap())
    } else {
        tauri::WebviewUrl::App("index.html#deck".into())
    };
    tauri::WebviewWindowBuilder::new(&app, "deck", url)
        .title("VAULT · GPU DECK")
        .inner_size(860.0, 640.0)
        .build()
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// M6.3 — open the Grafana dashboard in its own webview window. Grafana
/// Cloud sends X-Frame-Options: deny (no iframes, even public dashboards);
/// a child window sidesteps that. URL comes from the project .env only —
/// the HUD webview cannot pick the destination.
#[tauri::command]
fn open_vitals(app: AppHandle) -> Result<(), String> {
    let url = env_from_project("GRAFANA_EMBED_URL")
        .filter(|u| !u.is_empty())
        .ok_or("GRAFANA_EMBED_URL not configured")?;
    if let Some(w) = app.get_webview_window("vitals") {
        w.show().and_then(|_| w.set_focus()).map_err(|e| e.to_string())?;
        return Ok(());
    }
    tauri::WebviewWindowBuilder::new(
        &app,
        "vitals",
        tauri::WebviewUrl::External(url.parse().map_err(|e| format!("{e}"))?),
    )
    .title("VAULT · GPU RESOURCE (Grafana)")
    .inner_size(1000.0, 560.0)
    .build()
    .map_err(|e| e.to_string())?;
    Ok(())
}

fn toggle_hud(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        if w.is_visible().unwrap_or(false) {
            let _ = w.hide();
        } else {
            let _ = w.show();
            let _ = w.set_focus();
        }
    }
}

fn api_port() -> u16 {
    std::env::var("HERMES_API_PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(8100)
}

/// Spawn the Hermes API (uvicorn via uv) unless something already serves the
/// port. Dev-mode path resolution: the api/ dir sits two levels above this
/// crate; override with VAULT_API_DIR for packaged builds.
fn spawn_hermes_api() -> Option<Child> {
    let port = api_port();
    if TcpStream::connect(("127.0.0.1", port)).is_ok() {
        println!("[vault] Hermes API already serving on :{port}, not spawning");
        return None;
    }
    let api_dir = std::env::var("VAULT_API_DIR")
        .unwrap_or_else(|_| concat!(env!("CARGO_MANIFEST_DIR"), "/../../api").to_string());
    match Command::new("uv")
        .args([
            "run",
            "uvicorn",
            "vault_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
        ])
        .arg(port.to_string())
        .current_dir(&api_dir)
        .spawn()
    {
        Ok(child) => {
            println!("[vault] spawned Hermes API sidecar (pid {}) on :{port}", child.id());
            Some(child)
        }
        Err(e) => {
            eprintln!("[vault] FAILED to spawn Hermes API from {api_dir}: {e}");
            None
        }
    }
}

/// This box routes GL/EGL to the NVIDIA card by default — the unfavorable
/// WebKitGTK path (10fps software render, see docs/M1-decision-2026-07-03.md).
/// Pin Mesa/RADV before the webview initializes. VAULT_NO_GPU_PIN=1 disables.
#[cfg(target_os = "linux")]
fn pin_amd_gl() {
    if std::env::var_os("VAULT_NO_GPU_PIN").is_some() {
        return;
    }
    for (k, v) in [
        (
            "__EGL_VENDOR_LIBRARY_FILENAMES",
            "/usr/share/glvnd/egl_vendor.d/50_mesa.json",
        ),
        ("__GLX_VENDOR_LIBRARY_NAME", "mesa"),
        ("DRI_PRIME", "1"),
    ] {
        if std::env::var_os(k).is_none() {
            std::env::set_var(k, v);
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[cfg(target_os = "linux")]
    pin_amd_gl();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state == ShortcutState::Pressed {
                        toggle_hud(app);
                    }
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            report_spike,
            get_config,
            read_note,
            quit_app,
            open_vitals,
            open_deck
        ])
        .setup(|app| {
            // tray: toggle + quit (M0.2)
            let toggle = MenuItem::with_id(app, "toggle", "Show/Hide HUD", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit VAULT", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&toggle, &quit])?;
            TrayIconBuilder::with_id("vault-tray")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("VAULT")
                .menu(&menu)
                .on_menu_event(|app, e| match e.id.as_ref() {
                    "toggle" => toggle_hud(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            // global hotkey (Wayland compositors may withhold delivery; the
            // tray toggle is the guaranteed path)
            match app.global_shortcut().register(HOTKEY) {
                Ok(()) => println!("[vault] global hotkey registered: {HOTKEY}"),
                Err(e) => eprintln!("[vault] hotkey registration failed ({HOTKEY}): {e}"),
            }

            // Hermes API sidecar
            app.manage(Sidecar(Mutex::new(spawn_hermes_api())));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = app.try_state::<Sidecar>() {
                if let Some(mut child) = state.0.lock().unwrap().take() {
                    println!("[vault] stopping Hermes API sidecar (pid {})", child.id());
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        }
    });
}
