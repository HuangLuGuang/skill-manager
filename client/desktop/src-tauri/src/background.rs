use std::sync::Mutex;

use serde::Deserialize;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, State, Wry};

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

pub fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

pub fn close_to_background(window: &tauri::WebviewWindow) {
    // Before the webview initializes the tray, keep a taskbar entry on Windows/Linux.
    let result = if !cfg!(target_os = "macos") && window.app_handle().tray_by_id(TRAY_ID).is_none() {
        window.minimize()
    } else {
        window.hide()
    };
    if let Err(error) = result {
        eprintln!("could not move client window to background: {error}");
    }
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

    let open = MenuItem::with_id(app, "client-background-open", labels.open, true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "client-background-quit", labels.quit, true, None::<&str>)?;
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
