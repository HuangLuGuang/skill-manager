use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use serde::Deserialize;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, State, Wry};

#[derive(Default)]
pub struct WindowDraft(Mutex<serde_json::Value>);

#[tauri::command]
pub fn take_window_draft(app: AppHandle, state: State<'_, WindowDraft>) -> serde_json::Value {
    let mut draft = state.0.lock().unwrap().take();
    if !draft.is_object() {
        draft = serde_json::json!({});
    }
    draft["notifiedVersion"] = super::background_runtime::notified_version(&app).into();
    draft
}

#[tauri::command]
pub fn retire_main_window(
    window: tauri::WebviewWindow,
    state: State<'_, WindowDraft>,
    draft: serde_json::Value,
) -> Result<(), String> {
    if super::runtime_watch::active() {
        return Ok(());
    }
    if window.label() != "main" || draft.to_string().len() > 256 * 1024 {
        return Err("client_window_draft_invalid".into());
    }
    *state.0.lock().unwrap() = draft;
    window.destroy().map_err(|error| error.to_string())
}

const TRAY_ID: &str = "client-background";

#[derive(Default)]
pub struct BackgroundMenu(Mutex<Option<MenuLabels>>);

struct MenuLabels {
    open: MenuItem<Wry>,
    quit: MenuItem<Wry>,
}

#[derive(Deserialize)]
pub struct Labels {
    title: String,
    open: String,
    quit: String,
}

#[derive(Default)]
pub struct MainWindowReady(AtomicBool);

fn reveal(window: &tauri::WebviewWindow) -> tauri::Result<()> {
    window.unminimize()?;
    window.show()?;
    window.set_focus()
}

#[tauri::command]
pub fn main_window_ready(window: tauri::WebviewWindow, ready: State<'_, MainWindowReady>) -> Result<(), String> {
    ready.0.store(true, Ordering::Release);
    reveal(&window).map_err(|error| error.to_string())
}

pub fn show_main_window(app: &AppHandle) {
    let ready = app.state::<MainWindowReady>();
    if app.get_webview_window("main").is_none() {
        ready.0.store(false, Ordering::Release);
        if let Some(config) = app.config().app.windows.first() {
            if let Err(error) = tauri::WebviewWindowBuilder::from_config(app, config)
                .and_then(|builder| builder.build())
            {
                eprintln!("could not recreate client window: {error}");
            }
        }
        return;
    }
    if !ready.0.load(Ordering::Acquire) {
        return;
    }
    if let Some(window) = app.get_webview_window("main") {
        let _ = reveal(&window);
    }
}

pub fn close_to_background(window: &tauri::WebviewWindow) {
    // Before the webview initializes the tray, keep a taskbar entry on Windows/Linux.
    let result = if !cfg!(target_os = "macos") && window.app_handle().tray_by_id(TRAY_ID).is_none()
    {
        window.minimize()
    } else {
        window.hide()
    };
    if let Err(error) = result {
        eprintln!("could not move client window to background: {error}");
        return;
    }
    let _ = window.emit("client-window-close-requested", ());
}

#[tauri::command]
pub fn sync_background_menu(
    app: AppHandle,
    state: State<'_, BackgroundMenu>,
    labels: Labels,
) -> Result<(), String> {
    sync_menu(&app, &state, labels).map_err(|error| error.to_string())
}

fn sync_menu(app: &AppHandle, state: &BackgroundMenu, labels: Labels) -> tauri::Result<()> {
    let mut items = state.0.lock().unwrap();
    if let Some(items) = items.as_ref() {
        items.open.set_text(labels.open)?;
        items.quit.set_text(labels.quit)?;
        if let Some(tray) = app.tray_by_id(TRAY_ID) {
            tray.set_tooltip(Some(labels.title))?;
        }
        return Ok(());
    }

    let open = MenuItem::with_id(
        app,
        "client-background-open",
        labels.open,
        true,
        None::<&str>,
    )?;
    let quit = MenuItem::with_id(
        app,
        "client-background-quit",
        labels.quit,
        true,
        None::<&str>,
    )?;
    let menu = Menu::with_items(app, &[&open, &quit])?;
    let mut tray = TrayIconBuilder::with_id(TRAY_ID)
        .menu(&menu)
        .tooltip(labels.title)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "client-background-open" => show_main_window(app),
            "client-background-quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main_window(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    *items = Some(MenuLabels { open, quit });
    Ok(())
}
