//! Observes the shared receiver in the managed daemon. Desktop lifetime only
//! controls the UI; collection and recovery belong to the background service.
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant};

static MANAGER: OnceLock<(PathBuf, PathBuf)> = OnceLock::new();
static SHUTTING_DOWN: AtomicBool = AtomicBool::new(false);
static ACTION: Mutex<()> = Mutex::new(());
#[derive(Clone, Deserialize, Serialize)]
pub struct Snapshot {
    pub code: String,
    pub enabled: bool,
    pub attempts: u32,
    pub managed_task: String,
    pub telemetry: Value,
    pub receiver_diagnostic: Value,
    pub retry_count: u32,
    pub retry_mode: String,
    pub retry_suspended: bool,
    pub next_retry_seconds: Option<u64>,
    pub policy: Value,
    pub last_failure: Option<String>,
    pub last_failure_at_ms: Option<u64>,
}
pub fn run_cli(binary: &Path, home: &Path, args: &[String]) -> Result<Value, String> {
    let result = Command::new(binary)
        .arg("aidr-desktop")
        .arg("--home")
        .arg(home)
        .args(args)
        .output()
        .map_err(|_| "aidr_desktop_binary_missing")?;
    if !result.status.success() {
        return Err(stable_error(&String::from_utf8_lossy(&result.stderr)));
    }
    if result.stdout.len() > 65536 {
        return Err("aidr_desktop_status_invalid".into());
    }
    serde_json::from_slice(&result.stdout).map_err(|_| "aidr_desktop_status_invalid".into())
}
fn stable_error(text: &str) -> String {
    text.split_whitespace()
        .find(|part| {
            part.starts_with("aidr_")
                && part.len() < 100
                && part
                    .chars()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
        })
        .unwrap_or("aidr_desktop_receiver_failed")
        .to_string()
}
pub fn init(home: PathBuf, binary: PathBuf) {
    let _ = MANAGER.set((home, binary));
}

pub fn collection_status(home: &Path, binary: &Path) -> Result<Value, String> {
    run_cli(binary, home, &["--action".into(), "channels-status".into()])
}

pub fn snapshot() -> Snapshot {
    let result = MANAGER
        .get()
        .ok_or_else(|| "aidr_desktop_not_configured".to_string())
        .and_then(|(home, binary)| {
            run_cli(binary, home, &["--action".into(), "receiver-status".into()])
        })
        .and_then(|value| {
            serde_json::from_value(value).map_err(|_| "aidr_desktop_status_invalid".to_string())
        });
    result.unwrap_or_else(|code| Snapshot {
        code,
        enabled: false,
        attempts: 0,
        managed_task: "0".into(),
        telemetry: Value::Null,
        receiver_diagnostic: Value::Null,
        retry_count: 0,
        retry_mode: "fixed".into(),
        retry_suspended: false,
        next_retry_seconds: None,
        policy: Value::Null,
        last_failure: None,
        last_failure_at_ms: None,
    })
}

pub fn action(
    home: &Path,
    binary: &Path,
    source: &Path,
    action: &str,
    agent: &str,
) -> Result<Value, String> {
    let _guard = ACTION.lock().unwrap();
    if SHUTTING_DOWN.load(Ordering::Acquire) {
        return Err("aidr_desktop_stopped".into());
    }
    if action == "authorize" || action == "remove-managed" {
        return authorize_managed(home, binary, action, agent);
    }
    if ![
        "inspect",
        "connect",
        "enroll",
        "disconnect",
        "upgrade",
        "enable",
        "disable",
        "retry",
        "retry-logs",
        "system-check",
    ]
    .contains(&action)
    {
        return Err("aidr_desktop_action_invalid".into());
    }
    run_cli(
        binary,
        home,
        &[
            "--action".into(),
            action.into(),
            "--agent".into(),
            agent.into(),
            "--source-dir".into(),
            source.to_string_lossy().into_owned(),
        ],
    )
}

#[cfg(target_os = "macos")]
fn authorize_managed(
    home: &Path,
    binary: &Path,
    action: &str,
    agent: &str,
) -> Result<Value, String> {
    let before = run_cli(binary, home, &["--action".into(), "status".into()])?;
    let version = before
        .pointer("/runtime_policy/version")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned();
    let result = authorize_managed_attempt(home, binary, action, agent);
    if let Err(code) = &result {
        if action == "authorize"
            && [
                "aidr_managed_authorization_cancelled",
                "aidr_managed_authorization_failed",
                "aidr_managed_authorization_interrupted",
            ]
            .contains(&code.as_str())
        {
            // Local diagnostic evidence is bound to the pre-prompt revision.
            // A newer target or device binding rejects this late result.
            run_cli(
                binary,
                home,
                &[
                    "--action".into(),
                    "authorization-result".into(),
                    "--policy-version".into(),
                    version,
                    "--result-code".into(),
                    code.clone(),
                ],
            )?;
        }
    }
    result
}

#[cfg(target_os = "macos")]
fn authorize_managed_attempt(
    home: &Path,
    binary: &Path,
    action: &str,
    agent: &str,
) -> Result<Value, String> {
    if !["claude", "codex"].contains(&agent) {
        return Err("aidr_plugin_host_unsupported".into());
    }
    if action == "authorize" {
        run_cli(
            binary,
            home,
            &[
                "--action".into(),
                "authorize-plan".into(),
                "--agent".into(),
                agent.into(),
            ],
        )?;
    }
    if !cfg!(debug_assertions) {
        let current = std::env::current_exe().map_err(|_| "aidr_managed_package_invalid")?;
        let bundle = current
            .parent()
            .and_then(Path::parent)
            .and_then(Path::parent)
            .ok_or("aidr_managed_package_invalid")?;
        let executable = fs::canonicalize(binary).map_err(|_| "aidr_managed_package_invalid")?;
        let bundle = fs::canonicalize(bundle).map_err(|_| "aidr_managed_package_invalid")?;
        if bundle.extension().and_then(|v| v.to_str()) != Some("app")
            || !executable.starts_with(&bundle)
        {
            return Err("aidr_managed_package_invalid".into());
        }
        if !Command::new("/usr/bin/codesign")
            .args(["--verify", "--deep", "--strict"])
            .arg(&bundle)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_ok_and(|s| s.success())
        {
            return Err("aidr_managed_package_invalid".into());
        }
    }
    // Native system authorization handles the password. The privileged action
    // and paths are fixed; tasks cannot supply shell text or executable URLs.
    let command = format!(
        "{} aidr-managed-install --agent {} --action {}",
        shell_quote(&binary.to_string_lossy()),
        agent,
        if action == "authorize" {
            "install"
        } else {
            "remove"
        }
    );
    let script = format!(
        "do shell script {} with administrator privileges",
        applescript_quote(&command)
    );
    let mut process = Command::new("/usr/bin/osascript")
        .arg("-e")
        .arg(script)
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|_| "aidr_managed_authorization_failed")?;
    let stderr = process.stderr.take().unwrap();
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let mut bytes = Vec::new();
        let _ = stderr.take(4096).read_to_end(&mut bytes);
        let _ = sender.send(bytes);
    });
    let deadline = Instant::now() + Duration::from_secs(120);
    let status = loop {
        if SHUTTING_DOWN.load(Ordering::Acquire) || Instant::now() >= deadline {
            let _ = process.kill();
            let _ = process.wait();
            return Err("aidr_managed_authorization_interrupted".into());
        }
        match process.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => thread::sleep(Duration::from_millis(50)),
            Err(_) => {
                let _ = process.kill();
                let _ = process.wait();
                return Err("aidr_managed_authorization_failed".into());
            }
        }
    };
    if !status.success() {
        let bytes = receiver
            .recv_timeout(Duration::from_secs(1))
            .unwrap_or_default();
        let detail = String::from_utf8_lossy(&bytes);
        if detail.contains("(-128)") {
            return Err("aidr_managed_authorization_cancelled".into());
        }
        let code = stable_error(&detail);
        return Err(if code == "aidr_desktop_receiver_failed" {
            "aidr_managed_authorization_failed".into()
        } else {
            code
        });
    }
    if action == "remove-managed" {
        return run_cli(
            binary,
            home,
            &[
                "--action".into(),
                "managed-removed".into(),
                "--agent".into(),
                agent.into(),
            ],
        );
    }
    run_cli(
        binary,
        home,
        &[
            "--action".into(),
            "apply-managed".into(),
            "--agent".into(),
            agent.into(),
        ],
    )
}
#[cfg(not(target_os = "macos"))]
fn authorize_managed(
    _home: &Path,
    _binary: &Path,
    _action: &str,
    _agent: &str,
) -> Result<Value, String> {
    Err("aidr_managed_platform_unsupported".into())
}
fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\"'\"'"))
}
fn applescript_quote(value: &str) -> String {
    format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\""))
}
pub fn shutdown() {
    SHUTTING_DOWN.store(true, Ordering::Release);
    let _guard = ACTION.lock().unwrap();
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn authorization_quotes_keep_paths_outside_shell_syntax() {
        assert_eq!(
            shell_quote("/Apps/Client's App/bin"),
            "'/Apps/Client'\"'\"'s App/bin'"
        );
        assert_eq!(
            applescript_quote("do \"x\" \\ path"),
            "\"do \\\"x\\\" \\\\ path\""
        );
    }
    #[test]
    fn errors_do_not_return_raw_credentials() {
        assert_eq!(
            stable_error("error: aidr_hook_socket_exists secret-value"),
            "aidr_hook_socket_exists"
        );
        assert_eq!(
            stable_error("HTTP secret-value"),
            "aidr_desktop_receiver_failed"
        );
    }
}
