use serde_json::{json, Value};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

struct Handoff {
    context: String,
    request_id: String,
    token: String,
    created: Instant,
}

static HANDOFF: OnceLock<Mutex<Option<Handoff>>> = OnceLock::new();
const TTL: Duration = Duration::from_secs(300);

fn cache() -> &'static Mutex<Option<Handoff>> {
    HANDOFF.get_or_init(|| Mutex::new(None))
}

#[tauri::command]
pub async fn manual_model_action(operation: String, payload: Value) -> Result<Value, String> {
    if operation == "clear" {
        *cache().lock().map_err(|_| "manual_model_unavailable")? = None;
        return Ok(json!({}));
    }
    let config = super::load_client_config()?;
    let context = format!("{}\n{}", config.server, config.token);
    if operation == "options" {
        return super::platform_request(json!({"version": 1, "method": "manual-model-options",
            "local_agent_id": payload["local_agent_id"], "agent_type": payload["agent_type"]})).await;
    }
    if operation != "issue" && operation != "copy" {
        return Err("manual_model_invalid_action".into());
    }
    let request_id = payload["request_id"].as_str().ok_or("manual_model_invalid_action")?.to_owned();
    // Revalidate authorization for every copy, even while a secret is cached locally.
    let mut result = super::platform_request(json!({"version": 1, "method": "manual-model-credential", "manual_model": payload})).await?;
    let plain = result.as_object_mut().and_then(|row| row.remove("token"));
    if let Some(plain) = plain.and_then(|value| value.as_str().map(str::to_owned)) {
        let created = Instant::now();
        *cache().lock().map_err(|_| "manual_model_unavailable")? = Some(Handoff {
            context: context.clone(), request_id: request_id.clone(), token: plain, created,
        });
        tauri::async_runtime::spawn(async move {
            tokio::time::sleep(TTL).await;
            if let Ok(mut handoff) = cache().lock() {
                if handoff.as_ref().map(|item| item.created) == Some(created) { *handoff = None; }
            }
        });
    }
    let mut handoff = cache().lock().map_err(|_| "manual_model_unavailable")?;
    if handoff.as_ref().is_some_and(|item| item.created.elapsed() >= TTL || item.context != context) { *handoff = None; }
    let current = handoff.as_ref().filter(|item| item.request_id == request_id && item.context == context);
    if operation == "copy" {
        // The renderer receives plaintext only for the explicit clipboard write, never in view state.
        return current.map(|item| json!({"token": item.token})).ok_or("manual_model_copy_expired".into());
    }
    result["copy_available"] = json!(current.is_some());
    Ok(result)
}
