#![cfg_attr(
    all(target_os = "windows", not(debug_assertions)),
    windows_subsystem = "windows"
)]

use std::env;
#[cfg(unix)]
use std::ffi::CStr;
use std::fs;
use std::io::ErrorKind;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;

use notify::{RecommendedWatcher, RecursiveMode, Watcher};
use serde::{Deserialize, Serialize};
use tauri::plugin::PermissionState;
use tauri::{AppHandle, Emitter, Manager, WindowEvent};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_updater::UpdaterExt;
use url::Url;

const UPDATER_PUBLIC_KEY: &str = match option_env!("AGENT_MANAGER_UPDATER_PUBLIC_KEY") {
    Some(value) => value,
    None => "",
};
const BUILD_VERSION: &str = match option_env!("AGENT_MANAGER_RELEASE_VERSION") {
    Some(value) => value,
    None => "dev",
};
const UI_STATE_SIGNAL_NAME: &str = "ui-state-revision.json";
mod aidr_manager;
mod background;
mod system_collector;
mod runtime_watch;
#[cfg(target_os = "windows")]
mod windows_shell;

#[tauri::command]
async fn aidr_system_targets(action: String, selection: Option<serde_json::Value>, custom: Option<String>) -> Result<serde_json::Value, String> {
    let home = client_homes().into_iter().next().ok_or("aidr_desktop_home_invalid")?;
    let binary = client_binary().map_err(|_| "aidr_desktop_binary_missing")?;
    tauri::async_runtime::spawn_blocking(move || system_collector::targets(&home, &binary, &action, selection, custom))
        .await.map_err(|_| "aidr_system_runtime_failed".to_string())?
}

#[tauri::command]
async fn aidr_system_action(app: AppHandle, action: String) -> Result<serde_json::Value, String> {
    let home = client_homes().into_iter().next().ok_or("aidr_desktop_home_invalid")?;
    let binary = client_binary().map_err(|_| "aidr_desktop_binary_missing")?;
    let resources = if cfg!(debug_assertions) {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("resources/aidr-system")
    } else {
        app.path().resource_dir().map_err(|_| "aidr_system_component_missing")?.join("aidr-system")
    };
    tauri::async_runtime::spawn_blocking(move || system_collector::action(&home, &binary, &resources, &action))
        .await.map_err(|_| "aidr_system_runtime_failed".to_string())?
}

#[tauri::command]
fn aidr_receiver_status() -> aidr_manager::Snapshot {
    aidr_manager::snapshot()
}

#[tauri::command]
async fn aidr_collection_status() -> Result<serde_json::Value, String> {
    let home = client_homes()
        .into_iter()
        .next()
        .ok_or("aidr_desktop_home_invalid")?;
    let binary = client_binary().map_err(|_| "aidr_desktop_binary_missing")?;
    tauri::async_runtime::spawn_blocking(move || aidr_manager::collection_status(&home, &binary))
        .await
        .map_err(|_| "aidr_desktop_status_failed".to_string())?
}

#[tauri::command]
async fn aidr_plugin_action(
    app: AppHandle,
    action: String,
    agent: String,
) -> Result<serde_json::Value, String> {
    let home = client_homes()
        .into_iter()
        .next()
        .ok_or("aidr_desktop_home_invalid")?;
    let binary = client_binary().map_err(|_| "aidr_desktop_binary_missing")?;
    let source = if cfg!(debug_assertions) {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("resources/aidr-plugins")
    } else {
        app.path()
            .resource_dir()
            .map_err(|_| "aidr_plugin_package_unreadable")?
            .join("aidr-plugins")
    };
    tauri::async_runtime::spawn_blocking(move || {
        aidr_manager::action(&home, &binary, &source, &action, &agent)
    })
    .await
    .map_err(|_| "aidr_desktop_receiver_failed".to_string())?
}

#[tauri::command]
fn runtime_observation_supported() -> bool {
    cfg!(target_os = "macos")
}

#[tauri::command]
async fn start_runtime_watch(socket_path: String) -> Result<String, String> {
    if !cfg!(target_os = "macos") {
        return Err("runtime_observation_unsupported_platform".into());
    }
    let binary = client_binary().map_err(|_| "runtime_bridge_binary_missing".to_string())?;
    tauri::async_runtime::spawn_blocking(move || runtime_watch::start(socket_path.trim(), &binary))
        .await
        .map_err(|_| "runtime_bridge_worker_failed".to_string())?
}

#[tauri::command]
async fn read_runtime_watch(watch_id: String) -> Result<runtime_watch::Batch, String> {
    tauri::async_runtime::spawn_blocking(move || runtime_watch::read(&watch_id))
        .await
        .map_err(|_| "runtime_bridge_worker_failed".to_string())?
}

#[tauri::command]
async fn stop_runtime_watch(watch_id: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || runtime_watch::stop_id(&watch_id))
        .await
        .map_err(|_| "runtime_bridge_worker_failed".to_string())?
}

#[tauri::command]
fn get_build_version() -> &'static str {
    BUILD_VERSION
}

#[derive(Deserialize)]
struct ClientConfig {
    server: String,
    token: String,
    #[serde(default)]
    name: String,
}

#[derive(Serialize)]
struct ConnectionStatus {
    configured: bool,
    connected: bool,
    error: Option<String>,
    server: String,
    name: String,
    token_hint: String,
    service_installed: bool,
    service_running: bool,
    service_detail: String,
    local: serde_json::Value,
    inventory: serde_json::Value,
    platform: Option<serde_json::Value>,
}

#[derive(Serialize)]
struct LocalSnapshot {
    local: serde_json::Value,
    inventory: serde_json::Value,
}

#[derive(Clone, Deserialize, Serialize)]
struct LocalStateSignal {
    revision: String,
    event_type: String,
    created_at: String,
}

#[derive(Serialize)]
struct UpdateResult {
    supported: bool,
    available: bool,
    installed: bool,
    version: Option<String>,
    display_version: Option<String>,
    notes: Option<String>,
}

#[derive(Clone, Serialize)]
struct UpdateProgress {
    stage: &'static str,
    downloaded: u64,
    total: Option<u64>,
}

fn display_release_version(version: &str) -> String {
    let parts = version
        .split('.')
        .map(str::parse::<u64>)
        .collect::<Result<Vec<_>, _>>();
    let Ok(parts) = parts else {
        return version.to_string();
    };
    if parts.len() != 3 {
        return version.to_string();
    }
    let day = parts[2] / 100;
    let sequence = parts[2] % 100;
    if !(1..=31).contains(&day) || !(1..=99).contains(&sequence) {
        return version.to_string();
    }
    format!("{:02}.{:02}.{:02}.{}", parts[0], parts[1], day, sequence)
}

fn execute_client_sync(command: String, args: Vec<String>) -> Result<String, String> {
    // An alternate desktop home owns its AIDR child but must not replace the
    // per-user base service, whose launchd/systemd identity is shared.
    if command == "reconcile-service" && alternate_client_home() {
        return Ok(serde_json::json!({"restarted": false, "reason": "client_service_alternate_home", "state": {"installed": false, "running": false}}).to_string());
    }
    const ALLOWED: &[&str] = &[
        "configure",
        "connections",
        "switch-connection",
        "agent-settings",
        "set-agent-roots",
        "reset-agent-roots",
        "add-custom-agent",
        "remove-custom-agent",
        "inventory",
        "cached-inventory",
        "log-settings",
        "export-diagnostics",
        "register",
        "switch-model",
        "restore-model",
        "verify-model",
        "takeover",
        "pending",
        "scan-history",
        "refresh-scan-history",
        "refresh-pending",
        "submit-pending",
        "submit-observed",
        "request-skill-action",
        "apply-skill-action",
        "discard-pending",
        "discard-quarantine",
        "queue-quarantine",
        "available-skills",
        "skill-preview",
        "skill-versions",
        "install-skill",
        "install-skills",
        "quarantine",
        "backups",
        "restore",
        "run-once",
        "service-status",
        "prepare-update",
        "reconcile-service",
        "local-status",
        "read-notifications",
        "clear-notifications",
        "deliver-notification",
        "install-service",
    ];
    if !ALLOWED.contains(&command.as_str()) {
        return Err(format!("不支持的客户端操作: {command}"));
    }
    let output = Command::new(client_binary()?)
        .arg(command)
        .args(args)
        .output()
        .map_err(|error| format!("无法启动 Agent Manager Client: {error}"))?;
    if !output.status.success() {
        let detail = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if detail.is_empty() {
            format!("客户端操作失败: {}", output.status)
        } else {
            detail
        });
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

#[tauri::command]
async fn execute_client(command: String, args: Vec<String>) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || execute_client_sync(command, args))
        .await
        .map_err(|error| format!("客户端操作异常: {error}"))?
}

#[tauri::command]
async fn execute_client_with_progress(
    app: AppHandle,
    operation_id: String,
    command: String,
    args: Vec<String>,
) -> Result<String, String> {
    if command != "install-skills" {
        return Err(format!("不支持进度输出的客户端操作: {command}"));
    }
    tauri::async_runtime::spawn_blocking(move || {
        let mut child = Command::new(client_binary()?)
            .arg(&command)
            .args(args)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| format!("无法启动 Agent Manager Client: {error}"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "客户端进度输出不可用".to_string())?;
        let mut output = Vec::new();
        for line in BufReader::new(stdout).lines() {
            let line = line.map_err(|error| format!("读取客户端进度失败: {error}"))?;
            if line.trim().is_empty() {
                continue;
            }
            output.push(line.clone());
            if let Ok(mut payload) = serde_json::from_str::<serde_json::Value>(&line) {
                if let Some(object) = payload.as_object_mut() {
                    object.insert(
                        "operation_id".to_string(),
                        serde_json::Value::String(operation_id.clone()),
                    );
                }
                let _ = app.emit("client-operation-progress", payload);
            }
        }
        let result = child
            .wait_with_output()
            .map_err(|error| format!("等待客户端操作失败: {error}"))?;
        if !result.status.success() {
            let detail = String::from_utf8_lossy(&result.stderr).trim().to_string();
            return Err(if detail.is_empty() {
                format!("客户端操作失败: {}", result.status)
            } else {
                detail
            });
        }
        Ok(output.join("\n"))
    })
    .await
    .map_err(|error| format!("客户端操作异常: {error}"))?
}

#[tauri::command]
fn show_system_notification(app: AppHandle, title: String, body: String) -> Result<(), String> {
    let notifications = app.notification();
    if matches!(
        notifications
            .permission_state()
            .map_err(|error| error.to_string())?,
        PermissionState::Prompt | PermissionState::PromptWithRationale
    ) {
        notifications
            .request_permission()
            .map_err(|error| error.to_string())?;
    }
    if notifications
        .permission_state()
        .map_err(|error| error.to_string())?
        != PermissionState::Granted
    {
        return Err(
            "系统通知权限未开启，请在系统设置中允许智能体生命周期管理系统客户端发送通知"
                .to_string(),
        );
    }
    notifications
        .builder()
        .title(title)
        .body(body)
        .show()
        .map_err(|error| error.to_string())
}

#[tauri::command]
async fn select_skill_directory() -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(|| {
        Ok(rfd::FileDialog::new()
            .set_title("选择 Agent 的 Skill 目录")
            .pick_folder()
            .map(|path| path.to_string_lossy().into_owned()))
    })
    .await
    .map_err(|error| format!("目录选择器异常: {error}"))?
}

fn reveal_path_sync(path: &Path) -> Result<(), String> {
    if !path.is_absolute() {
        return Err("folder_open_absolute_required".to_string());
    }
    if !path.exists() {
        return Err(format!("folder_open_path_missing: {}", path.display()));
    }
    #[cfg(target_os = "macos")]
    let status = if path.is_dir() {
        Command::new("open").arg(path).status()
    } else {
        Command::new("open").arg("-R").arg(path).status()
    };
    #[cfg(target_os = "windows")]
    return windows_shell::reveal(path);
    #[cfg(target_os = "linux")]
    let status = Command::new("xdg-open")
        .arg(if path.is_dir() {
            path
        } else {
            path.parent().unwrap_or(path)
        })
        .status();
    #[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
    return Err("folder_open_unsupported".to_string());
    #[cfg(any(target_os = "macos", target_os = "linux"))]
    match status {
        Ok(value) if value.success() => Ok(()),
        Ok(value) => Err(format!("folder_open_shell_failed: {value}")),
        Err(error) => Err(format!("folder_open_launch_failed: {error}")),
    }
}

#[tauri::command]
async fn reveal_path(path: String) -> Result<(), String> {
    let diagnostic_path = path.clone();
    let started = std::time::Instant::now();
    let result =
        tauri::async_runtime::spawn_blocking(move || reveal_path_sync(&PathBuf::from(path)))
            .await
            .map_err(|error| format!("folder_open_worker_failed: {error}"))
            .and_then(|result| result);
    let error = result.as_ref().err().cloned().unwrap_or_default();
    let record = serde_json::json!({
        "event": "path_open_finished", "path": diagnostic_path,
        "outcome": if result.is_ok() { "accepted" } else { "failed" },
        "error_code": error.split(':').next().unwrap_or_default(),
        "message": error, "duration_ms": started.elapsed().as_millis(),
        "version": BUILD_VERSION, "count": 1,
    });
    // Diagnostic failures must not change the Shell operation's result.
    tauri::async_runtime::spawn(async move {
        let _ = record_desktop_diagnostic(record).await;
    });
    result
}

#[tauri::command]
async fn open_client_location(kind: String) -> Result<(), String> {
    let path = tauri::async_runtime::spawn_blocking(move || {
        let home = system_home().ok_or_else(|| "无法确定当前用户目录".to_string())?;
        let path = match kind.as_str() {
            "logs" => home.join(".agent-manager").join("logs"),
            "data" => home.join(".river-security").join("agent-manager"),
            _ => return Err("不支持的客户端目录类型".to_string()),
        };
        fs::create_dir_all(&path).map_err(|error| format!("无法创建客户端目录: {error}"))?;
        Ok(path)
    })
    .await
    .map_err(|error| format!("folder_open_worker_failed: {error}"))??;
    reveal_path(path.to_string_lossy().into_owned()).await
}

#[tauri::command]
async fn export_diagnostics(days: u32) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let result = execute_client_sync(
            "export-diagnostics".to_string(),
            vec!["--days".to_string(), days.to_string()],
        )?;
        let value: serde_json::Value =
            serde_json::from_str(&result).map_err(|_| "diagnostics_invalid_result".to_string())?;
        value
            .get("path")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .ok_or_else(|| "diagnostics_invalid_result".to_string())
    })
    .await
    .map_err(|error| format!("diagnostics_export_failed: {error}"))?
}

#[tauri::command]
async fn record_desktop_diagnostic(record: serde_json::Value) -> Result<(), String> {
    let body = serde_json::to_vec(&record).map_err(|_| "diagnostics_invalid_record".to_string())?;
    if body.len() > 16384 {
        return Err("diagnostics_record_too_large".to_string());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let mut child = Command::new(client_binary()?)
            .arg("record-desktop-diagnostic")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| error.to_string())?;
        let written = child
            .stdin
            .take()
            .ok_or_else(|| "diagnostics_invalid_record".to_string())?
            .write_all(&body);
        let result = child
            .wait_with_output()
            .map_err(|error| error.to_string())?;
        written.map_err(|error| error.to_string())?;
        if !result.status.success() {
            return Err(String::from_utf8_lossy(&result.stderr).trim().to_string());
        }
        Ok(())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn get_client_history(
    filters: std::collections::HashMap<String, String>,
) -> Result<serde_json::Value, String> {
    let config = try_load_client_config()?.ok_or("client_not_configured")?;
    let inventory: serde_json::Value = serde_json::from_str(&execute_client_sync(
        "cached-inventory".to_string(),
        Vec::new(),
    )?)
    .map_err(|_| "client_inventory_unavailable")?;
    let id = inventory
        .get("client_id")
        .and_then(|value| value.as_str())
        .ok_or("client_inventory_unavailable")?;
    let response = reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .build()
        .map_err(|_| "client_history_unavailable")?
        .get(format!(
            "{}/api/v1/clients/{}/history",
            config.server.trim_end_matches('/'),
            id
        ))
        .query(&filters)
        .bearer_auth(&config.token)
        .send()
        .await
        .map_err(|_| "client_history_unavailable")?;
    if !response.status().is_success() {
        return Err(format!(
            "client_history_http_{}",
            response.status().as_u16()
        ));
    }
    response
        .json()
        .await
        .map_err(|_| "client_history_unavailable".to_string())
}

#[tauri::command]
async fn get_connection_status() -> Result<ConnectionStatus, String> {
    let Some(config) = try_load_client_config()? else {
        return Ok(ConnectionStatus {
            configured: false,
            connected: false,
            error: None,
            server: String::new(),
            name: String::new(),
            token_hint: String::new(),
            service_installed: false,
            service_running: false,
            service_detail: String::new(),
            local: serde_json::json!({}),
            inventory: serde_json::json!({"agents": []}),
            platform: None,
        });
    };
    let service: serde_json::Value = serde_json::from_str(&execute_client_sync(
        "service-status".to_string(),
        Vec::new(),
    )?)
    .map_err(|error| format!("无法读取后台服务状态: {error}"))?;
    let local: serde_json::Value = serde_json::from_str(&execute_client_sync(
        "local-status".to_string(),
        Vec::new(),
    )?)
    .map_err(|error| format!("无法读取本地治理状态: {error}"))?;
    let inventory_output = execute_client_sync("cached-inventory".to_string(), Vec::new())
        .or_else(|_| execute_client_sync("inventory".to_string(), Vec::new()))?;
    let inventory: serde_json::Value = serde_json::from_str(&inventory_output)
        .map_err(|error| format!("无法读取本机 Agent 信息: {error}"))?;
    let client_id = inventory
        .get("client_id")
        .and_then(|value| value.as_str())
        .ok_or_else(|| "本机客户端 ID 无效".to_string())?;
    let url = format!(
        "{}/api/v1/clients/{}/status",
        config.server.trim_end_matches('/'),
        client_id
    );
    let response = reqwest::Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .map_err(|error| format!("无法初始化连接检查: {error}"))?
        .get(url)
        .bearer_auth(&config.token)
        .send()
        .await;
    let mut result = ConnectionStatus {
        configured: true,
        connected: false,
        error: None,
        server: config.server,
        name: config.name,
        token_hint: mask_token(&config.token),
        service_installed: service
            .get("installed")
            .and_then(|value| value.as_bool())
            .unwrap_or(false),
        service_running: service
            .get("running")
            .and_then(|value| value.as_bool())
            .unwrap_or(false),
        service_detail: service
            .get("detail")
            .and_then(|value| value.as_str())
            .unwrap_or("")
            .to_string(),
        local,
        inventory,
        platform: None,
    };
    let response = match response {
        Ok(response) => response,
        Err(error) => {
            result.error = Some(format!("无法连接 Agent Manager: {error}"));
            return Ok(result);
        }
    };
    if !response.status().is_success() {
        let status = response.status();
        let detail = response.text().await.unwrap_or_default();
        result.error = Some(format!("Agent Manager 返回 {status}: {detail}"));
        return Ok(result);
    }
    result.platform = Some(
        response
            .json()
            .await
            .map_err(|error| format!("平台状态响应格式错误: {error}"))?,
    );
    result.connected = true;
    Ok(result)
}

#[tauri::command]
async fn refresh_model_catalog(
    local_agent_id: String,
    agent_type: String,
    managed_agent_id: Option<String>,
) -> Result<serde_json::Value, String> {
    let config = try_load_client_config()?.ok_or("client_not_configured")?;
    let inventory: serde_json::Value = serde_json::from_str(&execute_client_sync(
        "cached-inventory".to_string(),
        Vec::new(),
    )?)
    .map_err(|_| "client_inventory_unavailable")?;
    let client_id = inventory
        .get("client_id")
        .and_then(|value| value.as_str())
        .ok_or("client_inventory_unavailable")?;
    let response = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|_| "model_catalog_refresh_unavailable")?
        .post(format!(
            "{}/api/v1/clients/{}/model-catalog/refresh",
            config.server.trim_end_matches('/'),
            client_id
        ))
        .bearer_auth(&config.token)
        .json(&serde_json::json!({
            "local_agent_id": local_agent_id,
            "agent_type": agent_type,
            "managed_agent_id": managed_agent_id.unwrap_or_default(),
        }))
        .send()
        .await
        .map_err(|_| "model_catalog_refresh_unavailable")?;
    if !response.status().is_success() {
        let status = response.status();
        let detail = response.text().await.unwrap_or_default();
        return Err(format!(
            "model_catalog_refresh_http_{}: {}",
            status.as_u16(),
            detail
        ));
    }
    response
        .json()
        .await
        .map_err(|_| "model_catalog_refresh_invalid_response".to_string())
}

#[tauri::command]
async fn get_local_snapshot() -> Result<LocalSnapshot, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let local = serde_json::from_str(&execute_client_sync(
            "local-status".to_string(),
            Vec::new(),
        )?)
        .map_err(|error| format!("无法读取本地治理状态: {error}"))?;
        let inventory = serde_json::from_str(&execute_client_sync(
            "cached-inventory".to_string(),
            Vec::new(),
        )?)
        .map_err(|error| format!("无法读取本机 Agent 信息: {error}"))?;
        Ok(LocalSnapshot { local, inventory })
    })
    .await
    .map_err(|error| format!("读取本地状态异常: {error}"))?
}

#[tauri::command]
async fn check_client_update(
    app: AppHandle,
    install: bool,
    channel: Option<String>,
) -> Result<UpdateResult, String> {
    if BUILD_VERSION == "dev" {
        return Ok(UpdateResult {
            supported: false,
            available: false,
            installed: false,
            version: None,
            display_version: None,
            notes: Some(
                "开发版本不参与在线更新检查；正式发布版本会检查并安装已签名更新。".to_string(),
            ),
        });
    }
    if UPDATER_PUBLIC_KEY.trim().is_empty() {
        return Err("当前安装包未配置更新签名公钥，请使用正式发布版本".to_string());
    }
    let config = load_client_config()?;
    let channel = channel.unwrap_or_else(|| "stable".to_string());
    if !matches!(channel.as_str(), "stable" | "preview") {
        return Err("无效的客户端更新通道".to_string());
    }
    let endpoint = Url::parse(&format!(
        "{}/api/v1/clients/updates/{{{{target}}}}/{{{{arch}}}}/{{{{current_version}}}}?channel={channel}",
        config.server.trim_end_matches('/'),
    ))
    .map_err(|error| format!("Agent Manager 地址无效: {error}"))?;
    let updater = app
        .updater_builder()
        .endpoints(vec![endpoint])
        .map_err(|error| format!("更新地址配置失败: {error}"))?
        .header("Authorization", format!("Bearer {}", config.token))
        .map_err(|error| format!("更新凭证配置失败: {error}"))?
        .pubkey(UPDATER_PUBLIC_KEY)
        .build()
        .map_err(|error| format!("更新器初始化失败: {error}"))?;
    let Some(update) = updater
        .check()
        .await
        .map_err(|error| format!("检查更新失败: {error}"))?
    else {
        return Ok(UpdateResult {
            supported: true,
            available: false,
            installed: false,
            version: None,
            display_version: None,
            notes: None,
        });
    };
    let display_version = display_release_version(&update.version);
    let result = UpdateResult {
        supported: true,
        available: true,
        installed: install,
        version: Some(update.version.clone()),
        display_version: Some(display_version),
        notes: update.body.clone(),
    };
    if install {
        app.emit(
            "client-update-progress",
            UpdateProgress {
                stage: "preparing",
                downloaded: 0,
                total: None,
            },
        )
        .map_err(|error| format!("更新进度通知失败: {error}"))?;
        execute_client_sync("prepare-update".to_string(), vec![])
            .map_err(|error| format!("暂停后台服务失败: {error}"))?;
        let progress_app = app.clone();
        let finish_app = app.clone();
        let mut downloaded = 0_u64;
        let install_result = update
            .download_and_install(
                move |chunk_length, content_length| {
                    downloaded += chunk_length as u64;
                    let _ = progress_app.emit(
                        "client-update-progress",
                        UpdateProgress {
                            stage: "downloading",
                            downloaded,
                            total: content_length,
                        },
                    );
                },
                move || {
                    let _ = finish_app.emit(
                        "client-update-progress",
                        UpdateProgress {
                            stage: "installing",
                            downloaded: 0,
                            total: None,
                        },
                    );
                },
            )
            .await;
        if let Err(error) = install_result {
            let _ = execute_client_sync("reconcile-service".to_string(), vec![]);
            return Err(format!("安装更新失败，原后台服务已恢复: {error}"));
        }
        let _ = app.emit(
            "client-update-progress",
            UpdateProgress {
                stage: "restarting",
                downloaded: 0,
                total: None,
            },
        );
        aidr_manager::shutdown();
        app.restart();
    }
    Ok(result)
}

fn load_client_config() -> Result<ClientConfig, String> {
    try_load_client_config()?.ok_or_else(|| "请先连接 Agent Manager".to_string())
}

fn client_homes() -> Vec<PathBuf> {
    let mut homes = Vec::new();
    if let Ok(home) = env::var("AGENT_MANAGER_CLIENT_HOME") {
        if !home.trim().is_empty() {
            homes.push(PathBuf::from(home));
        }
    } else {
        if let Some(home) = system_home() {
            homes.push(home);
        }
        homes.extend(
            [env::var("HOME").ok(), env::var("USERPROFILE").ok()]
                .into_iter()
                .flatten()
                .map(PathBuf::from),
        );
        if cfg!(target_os = "macos") {
            if let Ok(user) = env::var("USER") {
                homes.push(Path::new("/Users").join(user));
            }
        }
    }
    homes.dedup();
    homes
}
fn alternate_client_home() -> bool {
    different_client_home(
        env::var_os("AGENT_MANAGER_CLIENT_HOME")
            .filter(|value| !value.is_empty())
            .map(PathBuf::from),
        system_home(),
    )
}
fn different_client_home(override_home: Option<PathBuf>, normal_home: Option<PathBuf>) -> bool {
    let Some(override_home) = override_home else {
        return false;
    };
    let Some(normal_home) = normal_home else {
        return true;
    };
    let normalize = |path: PathBuf| path.canonicalize().unwrap_or(path);
    normalize(override_home) != normalize(normal_home)
}

fn client_runtime_root() -> Option<PathBuf> {
    let homes = client_homes();
    homes
        .iter()
        .find(|home| home.join(".agent-manager").join("config.json").is_file())
        .or_else(|| homes.first())
        .map(|home| home.join(".agent-manager"))
}

fn is_ui_state_signal_path(path: &Path) -> bool {
    path.file_name()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value == UI_STATE_SIGNAL_NAME)
}

fn start_local_state_watcher(app: AppHandle) {
    thread::spawn(move || {
        let Some(runtime_root) = client_runtime_root() else {
            eprintln!("could not determine Agent Manager Client runtime directory");
            return;
        };
        if let Err(error) = fs::create_dir_all(&runtime_root) {
            eprintln!("could not prepare Agent Manager Client event directory: {error}");
            return;
        }
        let signal_path = runtime_root.join(UI_STATE_SIGNAL_NAME);
        let mut last_revision = String::new();
        let mut watcher: RecommendedWatcher =
            match notify::recommended_watcher(move |result: notify::Result<notify::Event>| {
                let Ok(event) = result else {
                    return;
                };
                if !event.paths.iter().any(|path| is_ui_state_signal_path(path)) {
                    return;
                }
                let Ok(body) = fs::read(&signal_path) else {
                    return;
                };
                let Ok(signal) = serde_json::from_slice::<LocalStateSignal>(&body) else {
                    return;
                };
                if signal.revision.is_empty() || signal.revision == last_revision {
                    return;
                }
                last_revision = signal.revision.clone();
                let _ = app.emit("client-local-state-changed", signal);
            }) {
                Ok(watcher) => watcher,
                Err(error) => {
                    eprintln!("could not create Agent Manager Client event watcher: {error}");
                    return;
                }
            };
        if let Err(error) = watcher.watch(&runtime_root, RecursiveMode::NonRecursive) {
            eprintln!("could not watch Agent Manager Client events: {error}");
            return;
        }
        loop {
            thread::park();
        }
    });
}

fn try_load_client_config() -> Result<Option<ClientConfig>, String> {
    let mut body = None;
    for home in client_homes() {
        let path = home.join(".agent-manager").join("config.json");
        match fs::read(&path) {
            Ok(value) => {
                body = Some(value);
                break;
            }
            Err(error) if error.kind() == ErrorKind::NotFound => continue,
            Err(error) => return Err(format!("无法读取客户端配置: {error}")),
        }
    }
    let Some(body) = body else {
        return Ok(None);
    };
    let config: ClientConfig =
        serde_json::from_slice(&body).map_err(|error| format!("客户端配置格式错误: {error}"))?;
    if config.server.trim().is_empty() || config.token.trim().is_empty() {
        return Err("尚未配置 Agent Manager 地址或客户端接入凭证".to_string());
    }
    Ok(Some(config))
}

#[cfg(unix)]
fn system_home() -> Option<PathBuf> {
    let passwd = unsafe { libc::getpwuid(libc::getuid()) };
    if passwd.is_null() {
        return None;
    }
    let value = unsafe { CStr::from_ptr((*passwd).pw_dir) };
    Some(PathBuf::from(value.to_string_lossy().into_owned()))
}

#[cfg(not(unix))]
fn system_home() -> Option<PathBuf> {
    None
}

fn mask_token(token: &str) -> String {
    let chars: Vec<char> = token.chars().collect();
    if chars.len() <= 9 {
        return "****".to_string();
    }
    format!(
        "{}****{}",
        chars[..5].iter().collect::<String>(),
        chars[chars.len() - 4..].iter().collect::<String>()
    )
}

fn client_binary() -> Result<PathBuf, String> {
    #[cfg(debug_assertions)]
    if let Ok(value) = env::var("AGENT_MANAGER_CLIENT_BINARY") {
        let path = PathBuf::from(value);
        if path.is_file() {
            return Ok(path);
        }
    }
    if cfg!(debug_assertions) {
        let bin_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("bin");
        if let Ok(entries) = fs::read_dir(bin_dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path
                    .file_name()
                    .and_then(|value| value.to_str())
                    .is_some_and(|value| value.starts_with("agent-manager-client-"))
                {
                    return Ok(path);
                }
            }
        }
    }
    if let Ok(current) = env::current_exe() {
        let name = if cfg!(windows) {
            "agent-manager-client.exe"
        } else {
            "agent-manager-client"
        };
        let candidates = [
            current.parent().map(|path| path.join(name)),
            current
                .parent()
                .and_then(Path::parent)
                .map(|path| path.join("Resources").join(name)),
        ];
        for candidate in candidates.into_iter().flatten() {
            if candidate.is_file() {
                return Ok(candidate);
            }
        }
    }
    Err("未找到 Agent Manager Client 后台程序，请重新安装客户端".to_string())
}

fn main() {
    tauri::Builder::default()
        .manage(background::BackgroundMenu::default())
        .setup(|app| {
            #[cfg(target_os = "macos")]
            if let Err(error) = notify_rust::set_application(&app.config().identifier) {
                eprintln!("could not register macOS notification identity: {error}");
            }
            start_local_state_watcher(app.handle().clone());
            if let (Some(home), Ok(binary)) = (client_homes().into_iter().next(), client_binary()) {
                aidr_manager::init(home, binary);
            }
            if let Some(window) = app.get_webview_window("main") {
                let closing_window = window.clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        background::close_to_background(&closing_window);
                    }
                });
            }
            Ok(())
        })
        .plugin(tauri_plugin_notification::init())
        .plugin(
            tauri_plugin_updater::Builder::new()
                .pubkey(UPDATER_PUBLIC_KEY)
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            background::sync_background_menu,
            execute_client,
            aidr_receiver_status,
            aidr_collection_status,
            aidr_system_action,
            aidr_system_targets,
            aidr_plugin_action,
            execute_client_with_progress,
            runtime_observation_supported,
            start_runtime_watch,
            read_runtime_watch,
            stop_runtime_watch,
            select_skill_directory,
            reveal_path,
            open_client_location,
            export_diagnostics,
            record_desktop_diagnostic,
            get_connection_status,
            refresh_model_catalog,
            get_local_snapshot,
            get_client_history,
            show_system_notification,
            check_client_update,
            get_build_version
        ])
        .build(tauri::generate_context!())
        .expect("failed to build Agent Manager Client desktop")
        .run(|app, event| {
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen { .. } = event {
                background::show_main_window(app);
            }
            // Native macOS Quit can go directly through applicationWillTerminate
            // to Exit, without ExitRequested. Cleanup is idempotent and must
            // finish before that native callback returns.
            if let tauri::RunEvent::Exit = event {
                aidr_manager::shutdown();
                runtime_watch::begin_shutdown();
                let _ = runtime_watch::shutdown();
            }
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                aidr_manager::shutdown();
                if runtime_watch::begin_shutdown() {
                    api.prevent_exit();
                    let app = app.clone();
                    thread::spawn(move || {
                        if runtime_watch::shutdown().is_ok() {
                            app.exit(0);
                        }
                    });
                } else if runtime_watch::active() {
                    api.prevent_exit();
                }
            }
        });
}

#[cfg(test)]
mod tests {
    #[test]
    fn reveal_path_rejects_invalid_targets_before_launch() {
        assert_eq!(
            super::reveal_path_sync(Path::new("relative-skill")),
            Err("folder_open_absolute_required".into())
        );
        let missing = std::env::temp_dir().join(format!(
            "agent-manager-missing-skill-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        assert!(super::reveal_path_sync(&missing)
            .unwrap_err()
            .starts_with("folder_open_path_missing:"));
    }

    #[test]
    fn alternate_home_does_not_own_global_base_service() {
        let normal = Some(PathBuf::from("/Users/customer"));
        assert!(!different_client_home(None, normal.clone()));
        assert!(!different_client_home(normal.clone(), normal.clone()));
        assert!(different_client_home(
            Some(PathBuf::from("/private/customer-profile")),
            normal
        ));
        assert!(different_client_home(
            Some(PathBuf::from("/private/customer-profile")),
            None
        ));
    }
    use std::path::{Path, PathBuf};
    use std::sync::mpsc;
    use std::time::{Duration, SystemTime, UNIX_EPOCH};

    use super::{
        client_binary, different_client_home, display_release_version, is_ui_state_signal_path,
        mask_token, system_home,
    };
    use notify::{RecursiveMode, Watcher};

    #[test]
    fn native_watcher_observes_atomic_ui_state_signal() {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "agent-manager-ui-event-{}-{unique}",
            std::process::id()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let target = root.join("ui-state-revision.json");
        let temporary = root.join(".ui-state-revision.tmp");
        let (sender, receiver) = mpsc::channel();
        let mut watcher =
            notify::recommended_watcher(move |result: notify::Result<notify::Event>| {
                let _ = sender.send(result);
            })
            .unwrap();
        watcher.watch(&root, RecursiveMode::NonRecursive).unwrap();
        std::fs::write(&temporary, br#"{"revision":"1"}"#).unwrap();
        std::fs::rename(&temporary, &target).unwrap();

        let deadline = std::time::Instant::now() + Duration::from_secs(3);
        let mut observed = false;
        while std::time::Instant::now() < deadline {
            let remaining = deadline.saturating_duration_since(std::time::Instant::now());
            match receiver.recv_timeout(remaining) {
                Ok(Ok(event)) if event.paths.iter().any(|path| is_ui_state_signal_path(path)) => {
                    observed = true;
                    break;
                }
                Ok(_) => continue,
                Err(_) => break,
            }
        }
        drop(watcher);
        let _ = std::fs::remove_dir_all(&root);
        assert!(observed, "native watcher missed the atomic UI state signal");
    }

    #[test]
    fn formats_encoded_daily_release_version() {
        assert_eq!(display_release_version("26.7.2802"), "26.07.28.2");
        assert_eq!(display_release_version("26.7.2901"), "26.07.29.1");
    }

    #[test]
    fn preserves_legacy_or_unexpected_versions() {
        assert_eq!(display_release_version("26.7.28"), "26.7.28");
        assert_eq!(display_release_version("0.2.0"), "0.2.0");
        assert_eq!(display_release_version("dev"), "dev");
    }

    #[test]
    fn token_is_never_returned_in_full() {
        assert_eq!(mask_token("amat_123456789"), "amat_****6789");
        assert_eq!(mask_token("short"), "****");
    }

    #[test]
    fn debug_build_uses_prepared_sidecar() {
        let path = client_binary().expect("prepared sidecar");
        assert_eq!(
            path.parent()
                .and_then(Path::file_name)
                .and_then(|value| value.to_str()),
            Some("bin")
        );
    }

    #[cfg(unix)]
    #[test]
    fn system_home_is_absolute() {
        assert!(system_home().expect("system home").is_absolute());
    }

    #[test]
    #[ignore = "requires an isolated AGENT_MANAGER_CLIENT_HOME and compiled AGENT_MANAGER_CLIENT_BINARY"]
    fn diagnostics_export_uses_real_sidecar() {
        let home = std::env::var("AGENT_MANAGER_CLIENT_HOME").expect("isolated test home");
        assert!(std::env::var("AGENT_MANAGER_CLIENT_BINARY").is_ok());
        let settings =
            super::execute_client_sync("log-settings".into(), vec!["--days".into(), "1".into()])
                .expect("save retention");
        let settings: serde_json::Value = serde_json::from_str(&settings).unwrap();
        assert_eq!(settings["retention_days"], 1);
        tauri::async_runtime::block_on(super::record_desktop_diagnostic(serde_json::json!({
            "event": "script_error", "message": "native export test", "version": "integration-test", "count": 1,
        }))).expect("write native diagnostic");
        let exported = tauri::async_runtime::block_on(super::export_diagnostics(1))
            .expect("export diagnostics");
        assert!(Path::new(&exported).starts_with(Path::new(&home).join("Downloads")));
        let bytes = std::fs::read(exported).expect("read actual ZIP");
        assert!(bytes.starts_with(b"PK\x03\x04"));
        let invalid = tauri::async_runtime::block_on(super::export_diagnostics(30));
        assert!(invalid.unwrap_err().contains("diagnostics_invalid_range"));
    }
}
