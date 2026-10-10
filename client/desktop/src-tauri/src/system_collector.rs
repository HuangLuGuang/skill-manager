//! Privilege stays in the standalone collector. The desktop invokes only a
//! fixed installation command through macOS's administrator authorization UI.
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use std::io::Read;
use serde_json::{json, Value};

static ACTION: Mutex<()> = Mutex::new(());

fn cli(binary: &Path, args: &[&str]) -> Result<Value, String> {
    let output = Command::new(binary).arg("aidr-system").args(args).output()
        .map_err(|_| "aidr_system_cli_failed".to_string())?;
    if !output.status.success() {
        let error = String::from_utf8_lossy(&output.stderr);
        let code = error.lines().flat_map(|s| s.split_whitespace()).find(|s|
            (s.starts_with("aidr_") || s.starts_with("aidr.")) && s.len() < 140);
        return Err(code.unwrap_or("aidr_system_cli_failed").to_string());
    }
    serde_json::from_slice(&output.stdout).map_err(|_| "aidr_system_response_invalid".into())
}

fn shell_quote(value: &str) -> String { format!("'{}'", value.replace('\'', "'\\''")) }

pub fn targets(home: &Path, binary: &Path, action: &str, selection: Option<Value>, custom: Option<String>) -> Result<Value, String> {
    if !cfg!(target_os = "macos") { return Err("aidr_system_unsupported".into()); }
    if !matches!(action, "targets" | "discover" | "select" | "add-program") { return Err("aidr_system_request_invalid".into()); }
    let _guard = ACTION.try_lock().map_err(|_| "aidr_system_busy".to_string())?;
    let selection = selection.unwrap_or(Value::Null).to_string();
    let custom = custom.unwrap_or_default();
    cli(binary, &["--action", action, "--home", &home.to_string_lossy(), "--selection", &selection, "--custom", &custom])
}
fn apple_quote(value: &str) -> String { format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\"")) }

pub fn action(home: &Path, binary: &Path, resources: &Path, action: &str) -> Result<Value, String> {
    if !cfg!(target_os = "macos") { return Err("aidr_system_unsupported".into()); }
    if action == "status" { return cli(binary, &["--action", "status"]); }
    if action == "settings" {
        Command::new("/usr/bin/open").arg("x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")
            .status().map_err(|_| "aidr_system_settings_failed".to_string())?;
        return Ok(json!({}));
    }
    if action == "reveal" {
        Command::new("/usr/bin/open").args(["-R", "/Library/Application Support/AgentManagerRuntime/system/bin/aidr-enforcer"])
            .status().map_err(|_| "aidr_system_settings_failed".to_string())?;
        return Ok(json!({}));
    }
    let _guard = ACTION.try_lock().map_err(|_| "aidr_system_busy".to_string())?;
    if action == "stop" { return cli(binary, &["--action", "stop"]); }
    if action != "start" { return Err("aidr_system_request_invalid".into()); }
    let current = cli(binary, &["--action", "status"])?;
    if matches!(current["state"].as_str(), Some("collecting" | "starting" | "draining" | "degraded")) { return Ok(current); }
    let native = resources.join("aidr-enforcer");
    let prepared = cli(binary, &["--action", "prepare", "--home", &home.to_string_lossy(), "--native", &native.to_string_lossy()])?;
    let request = prepared["request"].as_str().ok_or("aidr_system_response_invalid")?;
    let result = authorize(binary, request);
    let _ = std::fs::remove_file(request);
    result
}

fn authorize(binary: &Path, request: &str) -> Result<Value, String> {
    #[cfg(unix)] let uid = unsafe { libc::getuid() };
    #[cfg(not(unix))] let uid = 0;
    let command = format!("{} aidr-system --action install-start --uid {} --request {}",
        shell_quote(&binary.to_string_lossy()), uid, shell_quote(request));
    let script = format!("do shell script {} with administrator privileges", apple_quote(&command));
    let mut child = Command::new("/usr/bin/osascript").args(["-e", &script])
        .stdout(Stdio::piped()).stderr(Stdio::piped()).spawn().map_err(|_| "aidr_system_authorization_failed".to_string())?;
    let stdout = child.stdout.take().ok_or("aidr_system_authorization_failed")?;
    let stderr = child.stderr.take().ok_or("aidr_system_authorization_failed")?;
    let reader = |stream: Box<dyn Read + Send>| std::thread::spawn(move || {let mut data=Vec::new();let _=stream.take(1 << 20).read_to_end(&mut data);data});
    let out = reader(Box::new(stdout)); let err = reader(Box::new(stderr));
    let until = Instant::now() + Duration::from_secs(150);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < until => std::thread::sleep(Duration::from_millis(100)),
            _ => { let _=child.kill(); let _=child.wait(); return Err("aidr_system_authorization_timeout".into()); }
        }
    };
    let output = out.join().unwrap_or_default();
    let error = String::from_utf8_lossy(&err.join().unwrap_or_default()).into_owned();
    if !status.success() {
        if error.contains("(-128)") { return Err("aidr_system_authorization_cancelled".into()); }
        if let Some(code) = error.split_whitespace().find(|s| s.starts_with("aidr_") && s.len()<140) {
            return Err(code.trim_end_matches(|c: char| !c.is_ascii_alphanumeric() && c!='_').into());
        }
        return Err("aidr_system_authorization_failed".into());
    }
    serde_json::from_slice(&output).map_err(|_| "aidr_system_response_invalid".into())
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn authorization_quotes_paths_as_data() {
        assert_eq!(shell_quote("a'b$(whoami)"), "'a'\\''b$(whoami)'");
        assert_eq!(apple_quote("a\\\"b"), "\"a\\\\\\\"b\"");
    }
    #[test] fn concurrent_mutation_is_rejected_before_authorization() {
        let _guard = ACTION.lock().unwrap();
        let unused = Path::new("/unused");
        if cfg!(target_os = "macos") {
            for command in ["start", "stop"] {
                assert_eq!(action(unused, unused, unused, command).unwrap_err(), "aidr_system_busy");
            }
        }
    }
}
