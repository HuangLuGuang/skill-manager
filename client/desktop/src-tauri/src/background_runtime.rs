use serde::Deserialize;
use serde_json::Value;
use std::{
    collections::HashMap,
    sync::Mutex,
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager, State};

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Preferences {
    system_notifications: bool,
    notification_level: String,
    auto_check_updates: bool,
    update_channel: String,
    templates: HashMap<String, Copy>,
    labels: HashMap<String, String>,
    agents: HashMap<String, String>,
    update_title: String,
    update_body: String,
    #[serde(default)]
    notified_version: String,
}

#[derive(Clone, Deserialize)]
pub struct Copy {
    title: String,
    message: String,
}

#[derive(Default)]
pub struct Runtime {
    preferences: Mutex<Option<Preferences>>,
    wake: Mutex<Option<std::sync::mpsc::SyncSender<()>>>,
    notified_version: Mutex<String>,
}

pub fn notified_version(app: &AppHandle) -> String {
    app.state::<Runtime>()
        .notified_version
        .lock()
        .unwrap()
        .clone()
}
pub fn wake(app: &AppHandle) {
    if let Some(sender) = app.state::<Runtime>().wake.lock().unwrap().as_ref() {
        let _ = sender.try_send(());
    }
}

#[tauri::command]
pub fn sync_background_runtime(
    app: AppHandle,
    state: State<'_, Runtime>,
    preferences: Preferences,
) {
    *state.preferences.lock().unwrap() = Some(preferences);
    wake(&app);
}

fn rank(value: &str) -> u8 {
    match value {
        "critical" => 2,
        "warning" => 1,
        _ => 0,
    }
}

fn fill(template: &str, agent: &str, skill: &str) -> String {
    let mut result = String::new();
    let mut remaining = template;
    while !remaining.is_empty() {
        if let Some(tail) = remaining.strip_prefix("{agent}") {
            result.push_str(agent);
            remaining = tail;
        } else if let Some(tail) = remaining.strip_prefix("{skill}") {
            result.push_str(skill);
            remaining = tail;
        } else {
            let ch = remaining.chars().next().unwrap();
            result.push(ch);
            remaining = &remaining[ch.len_utf8()..];
        }
    }
    result
}

fn notification(item: &Value, preferences: &Preferences) -> (String, String) {
    let field = |key: &str| item[key].as_str().unwrap_or("");
    let event = field("event_type");
    let agent = preferences
        .agents
        .get(field("agent_type"))
        .map(String::as_str)
        .unwrap_or(field("agent_type"));
    let Some(copy) = preferences.templates.get(event) else {
        return (field("title").to_string(), field("message").to_string());
    };
    let title = copy.title.clone();
    if matches!(
        event,
        "skill_governance_detected" | "skill_governance_action"
    ) {
        let mut parts = vec![agent.to_string(), field("skill_name").to_string()];
        for (key, kind) in [
            ("trigger", "trigger"),
            ("action", "action"),
            ("status", "actionStatus"),
        ] {
            if let Some(value) = item["details"][key].as_str().filter(|v| !v.is_empty()) {
                parts.push(
                    preferences
                        .labels
                        .get(&format!("ui.agentManagement.{kind}.{value}"))
                        .cloned()
                        .unwrap_or(value.to_string()),
                );
            }
        }
        for key in ["error_code", "path"] {
            if let Some(value) = item["details"][key].as_str().filter(|v| !v.is_empty()) {
                parts.push(
                    preferences
                        .labels
                        .get(&format!("ui.agentManagement.error.{value}"))
                        .cloned()
                        .unwrap_or(value.to_string()),
                );
            }
        }
        return (
            title,
            parts
                .into_iter()
                .filter(|v| !v.is_empty())
                .collect::<Vec<_>>()
                .join(" · "),
        );
    }
    (title, fill(&copy.message, agent, field("skill_name")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_notification_uses_translated_resources_and_preserves_evidence() {
        for title in ["Skill 处置结果", "Skill Remediation Result"] {
            let preferences: Preferences = serde_json::from_value(serde_json::json!({
                "systemNotifications": true, "notificationLevel": "warning",
                "autoCheckUpdates": false, "updateChannel": "stable",
                "templates": {"skill_governance_action": {"title": title, "message": ""}},
                "labels": {"ui.agentManagement.action.quarantine": "Quarantine"},
                "agents": {"codex": "Codex"}, "updateTitle": "", "updateBody": ""
            }))
            .unwrap();
            let item = serde_json::json!({
                "event_type": "skill_governance_action", "agent_type": "codex", "skill_name": "原始 Skill",
                "details": {"action": "quarantine", "path": "/private/原始文件"}
            });
            let (actual_title, body) = notification(&item, &preferences);
            assert_eq!(actual_title, title);
            assert_eq!(body, "Codex · 原始 Skill · Quarantine · /private/原始文件");
        }
    }

    #[test]
    fn template_substitution_does_not_reinterpret_user_input() {
        assert_eq!(
            fill("{agent} 的 Skill {skill}", "{skill}", "原始{agent}"),
            "{skill} 的 Skill 原始{agent}"
        );
        assert!(rank("critical") > rank("warning"));
        assert!(rank("warning") > rank("info"));
    }
}

pub fn start(app: AppHandle) {
    let (sender, receiver) = std::sync::mpsc::sync_channel(1);
    *app.state::<Runtime>().wake.lock().unwrap() = Some(sender);
    std::thread::spawn(move || {
        let mut last_update: Option<Instant> = None;
        let mut notified_version = String::new();
        loop {
            let _ = receiver.recv_timeout(Duration::from_secs(30));
            let Some(preferences) = app.state::<Runtime>().preferences.lock().unwrap().clone()
            else {
                continue;
            };
            let snapshot = tauri::async_runtime::block_on(super::get_local_snapshot(None));
            if let Ok(snapshot) = snapshot {
                for item in snapshot.local["notifications"]
                    .as_array()
                    .into_iter()
                    .flatten()
                {
                    if item["delivered_at"].as_str().is_some_and(|v| !v.is_empty()) {
                        continue;
                    }
                    let Some(id) = item["id"].as_i64() else {
                        continue;
                    };
                    if preferences.system_notifications
                        && rank(item["severity"].as_str().unwrap_or(""))
                            >= rank(&preferences.notification_level)
                    {
                        let (title, body) = notification(item, &preferences);
                        if let Err(error) =
                            super::show_system_notification(app.clone(), title, body)
                        {
                            let _ = app.emit("client-notification-error", error);
                            continue;
                        }
                    }
                    match super::execute_client_sync(
                        "deliver-notification".into(),
                        vec!["--id".into(), id.to_string()],
                    ) {
                        Ok(_) => {
                            let _ = app.emit("client-notification-error", "");
                        }
                        Err(error) => {
                            let _ = app.emit("client-notification-error", error);
                        }
                    }
                }
            }
            if app.get_webview_window("main").is_none()
                && preferences.auto_check_updates
                && last_update.is_none_or(|at| at.elapsed() >= Duration::from_secs(6 * 60 * 60))
            {
                last_update = Some(Instant::now());
                if let Ok(result) = tauri::async_runtime::block_on(super::check_client_update(
                    app.clone(),
                    false,
                    Some(preferences.update_channel.clone()),
                )) {
                    if result.available {
                        let version = result.version.unwrap_or_default();
                        if !version.is_empty()
                            && version != notified_version
                            && version != preferences.notified_version
                            && super::show_system_notification(
                                app.clone(),
                                preferences.update_title.replace("{version}", &version),
                                preferences.update_body.clone(),
                            )
                            .is_ok()
                        {
                            notified_version = version;
                            *app.state::<Runtime>().notified_version.lock().unwrap() =
                                notified_version.clone();
                        }
                    }
                }
            }
        }
    });
}
