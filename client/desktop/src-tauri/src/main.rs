use std::env;
#[cfg(unix)]
use std::ffi::CStr;
use std::fs;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use tauri::plugin::PermissionState;
use tauri::{AppHandle, Emitter};
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
    const ALLOWED: &[&str] = &[
        "configure",
        "agent-settings",
        "set-agent-roots",
        "reset-agent-roots",
        "add-custom-agent",
        "remove-custom-agent",
        "inventory",
        "cached-inventory",
        "register",
        "takeover",
        "pending",
        "refresh-pending",
        "submit-pending",
        "queue-quarantine",
        "available-skills",
        "skill-preview",
        "skill-versions",
        "install-skill",
        "quarantine",
        "backups",
        "restore",
        "run-once",
        "pause-governance",
        "resume-governance",
        "service-status",
        "prepare-update",
        "reconcile-service",
        "local-status",
        "read-notifications",
        "clear-notifications",
        "deliver-notification",
        "install-service",
        "uninstall-service",
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
        return Err("只能打开绝对路径".to_string());
    }
    if !path.exists() {
        return Err(format!("路径不存在或已被移动: {}", path.display()));
    }
    #[cfg(target_os = "macos")]
    let status = if path.is_dir() {
        Command::new("open").arg(path).status()
    } else {
        Command::new("open").arg("-R").arg(path).status()
    };
    #[cfg(target_os = "windows")]
    let status = if path.is_dir() {
        Command::new("explorer").arg(path).status()
    } else {
        Command::new("explorer")
            .arg(format!("/select,{}", path.display()))
            .status()
    };
    #[cfg(target_os = "linux")]
    let status = Command::new("xdg-open")
        .arg(if path.is_dir() {
            path
        } else {
            path.parent().unwrap_or(path)
        })
        .status();
    #[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
    return Err("当前系统暂不支持打开文件夹".to_string());
    #[cfg(any(target_os = "macos", target_os = "windows", target_os = "linux"))]
    match status {
        Ok(value) if value.success() => Ok(()),
        Ok(value) => Err(format!("系统文件管理器返回失败状态: {value}")),
        Err(error) => Err(format!("无法打开系统文件管理器: {error}")),
    }
}

#[tauri::command]
async fn reveal_path(path: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || reveal_path_sync(&PathBuf::from(path)))
        .await
        .map_err(|error| format!("打开文件夹操作异常: {error}"))?
}

#[tauri::command]
async fn open_client_location(kind: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        let home = system_home().ok_or_else(|| "无法确定当前用户目录".to_string())?;
        let path = match kind.as_str() {
            "logs" => home.join(".agent-manager").join("logs"),
            "data" => home.join(".river-security").join("agent-manager"),
            _ => return Err("不支持的客户端目录类型".to_string()),
        };
        fs::create_dir_all(&path).map_err(|error| format!("无法创建客户端目录: {error}"))?;
        reveal_path_sync(&path)
    })
    .await
    .map_err(|error| format!("打开客户端目录异常: {error}"))?
}

#[tauri::command]
async fn export_diagnostics(content: String) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        if content.len() > 1024 * 1024 {
            return Err("诊断报告内容超过 1 MB 限制".to_string());
        }
        serde_json::from_str::<serde_json::Value>(&content)
            .map_err(|error| format!("诊断报告格式无效: {error}"))?;
        let home = system_home().ok_or_else(|| "无法确定当前用户目录".to_string())?;
        let output_dir = home.join("Downloads");
        fs::create_dir_all(&output_dir).map_err(|error| format!("无法创建下载目录: {error}"))?;
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| format!("系统时间无效: {error}"))?
            .as_secs();
        let path = output_dir.join(format!("agent-manager-client-diagnostics-{timestamp}.json"));
        fs::write(&path, content).map_err(|error| format!("无法写入诊断报告: {error}"))?;
        Ok(path.to_string_lossy().into_owned())
    })
    .await
    .map_err(|error| format!("导出诊断报告异常: {error}"))?
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
        app.restart();
    }
    Ok(result)
}

fn load_client_config() -> Result<ClientConfig, String> {
    try_load_client_config()?.ok_or_else(|| "请先连接 Agent Manager".to_string())
}

fn try_load_client_config() -> Result<Option<ClientConfig>, String> {
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
    let mut body = None;
    for home in homes {
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
        .setup(|app| {
            #[cfg(target_os = "macos")]
            if let Err(error) = notify_rust::set_application(&app.config().identifier) {
                eprintln!("could not register macOS notification identity: {error}");
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
            execute_client,
            select_skill_directory,
            reveal_path,
            open_client_location,
            export_diagnostics,
            get_connection_status,
            show_system_notification,
            check_client_update,
            get_build_version
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Agent Manager Client desktop");
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::{client_binary, display_release_version, mask_token, system_home};

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
}
