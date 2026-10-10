//! Native state reduction. Display history eviction never invalidates attribution.
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::{BTreeMap, VecDeque};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

const HISTORY_COUNT: usize = 200;
const HISTORY_BYTES: usize = 1024 * 1024;
const PROCESS_COUNT: usize = 500;
const PROCESS_BYTES: usize = 4 * 1024 * 1024;

#[derive(Clone, Serialize)]
pub struct Evidence {
    raw: String,
    at: u64,
    r#type: String,
}

pub struct State {
    processes: BTreeMap<String, (Value, usize)>,
    history: VecDeque<Evidence>,
    history_bytes: usize,
    process_bytes: usize,
    session: String,
    epoch: Option<u64>,
    transport: String,
    health: String,
    coverage: String,
    reason: String,
    client_gap: String,
    updated: u64,
    started: Instant,
    received: u64,
    applied: u64,
    evicted: u64,
    overflows: u64,
    process_peak: usize,
    history_peak: usize,
    snapshots: u64,
    apply_us: u64,
}
impl Default for State {
    fn default() -> Self {
        Self {
            processes: BTreeMap::new(),
            history: VecDeque::new(),
            history_bytes: 0,
            process_bytes: 0,
            session: String::new(),
            epoch: None,
            transport: "offline".into(),
            health: "unknown".into(),
            coverage: "unknown".into(),
            reason: String::new(),
            client_gap: String::new(),
            updated: 0,
            started: Instant::now(),
            received: 0,
            applied: 0,
            evicted: 0,
            overflows: 0,
            process_peak: 0,
            history_peak: 0,
            snapshots: 0,
            apply_us: 0,
        }
    }
}
fn text(v: &Value, k: &str) -> String {
    v[k].as_str().unwrap_or_default().into()
}
fn identity(v: &Value) -> Option<String> {
    if v["valid"] != true || v["pid"].as_u64()? == 0 {
        return None;
    }
    Some(format!(
        "{}:{}:{}",
        v["pid"].as_u64()?,
        v["pidversion"].as_u64()?,
        v["start_time_us"].as_u64()?
    ))
}
impl State {
    // Diagnostic counters contain no process identities, paths or raw events.
    pub fn diagnostics(&self) -> Value {
        json!({"received":self.received,"applied":self.applied,
            "elapsed_ms":self.started.elapsed().as_millis() as u64,
            "history_evicted":self.evicted,"state_overflows":self.overflows,
            "process_peak":self.process_peak,"history_bytes":self.history_bytes,
            "history_bytes_peak":self.history_peak,"process_bytes":self.process_bytes,
            "pending_records":0,"snapshots":self.snapshots,"apply_us":self.apply_us})
    }
    fn clear_processes(&mut self) {
        self.processes.clear();
        self.process_bytes = 0;
    }
    fn reset(&mut self) {
        self.clear_processes();
        self.history.clear();
        self.history_bytes = 0;
        self.session.clear();
        self.epoch = None;
        self.client_gap.clear();
        self.reason.clear();
        self.transport = "offline".into();
        self.health = "unknown".into();
        self.coverage = "unknown".into();
    }
    pub fn fail(&mut self, code: &str) {
        self.clear_processes();
        self.client_gap = code.into();
    }
    fn remove(&mut self, key: &str) {
        if let Some((_, size)) = self.processes.remove(key) {
            self.process_bytes -= size;
        }
    }
    pub fn push(&mut self, raw: String, record: Value) {
        let begin = Instant::now();
        self.received += 1;
        let frame = &record["frame"];
        let session = text(frame, "monitor_session");
        if record["reset"] == true
            || (!session.is_empty() && !self.session.is_empty() && self.session != session)
        {
            self.reset();
        }
        if !session.is_empty() {
            self.session = session;
        }
        for source in [&record, frame] {
            if source["transport"].is_string() {
                self.transport = text(source, "transport");
            }
            if source["observer_health"].is_string() {
                self.health = text(source, "observer_health");
            }
        }
        if self.health == "healthy"
            && ["observer_health_timeout", "helper_disconnected"].contains(&self.reason.as_str())
        {
            self.reason.clear();
        }
        let payload = &frame["payload"];
        for source in [&record, frame, payload] {
            if source["coverage"].is_string() {
                self.coverage = text(source, "coverage");
            }
            let reason = text(source, "reason");
            if !reason.is_empty()
                && ![
                    "observer_heartbeat",
                    "observer_health_state_changed",
                    "late_join_no_history",
                    "new_transport_connection",
                ]
                .contains(&reason.as_str())
            {
                self.reason = reason;
            }
        }
        if let Some(epoch) = payload["coverage_epoch"].as_u64() {
            if self.epoch.is_some_and(|old| old != epoch) {
                self.clear_processes();
                self.reason = "coverage_gap".into();
            }
            self.epoch = Some(epoch);
        }
        if payload["event"] == "continuous_attribution" {
            let event = payload["event_type"].as_u64();
            if matches!(event, Some(2 | 3)) {
                if let Some(key) = identity(&payload["subject"]) {
                    self.remove(&key);
                }
            }
            if matches!(event, Some(1 | 2)) {
                let target = &payload["target"];
                if let Some(key) = identity(target) {
                    let stale: Vec<_> = self
                        .processes
                        .iter()
                        .filter(|(_, (v, _))| v["identity"]["pid"] == target["pid"])
                        .map(|(k, _)| k.clone())
                        .collect();
                    for key in stale {
                        self.remove(&key);
                    }
                    let item = json!({"identity":target,"root":payload["root_identity"],"attribution":payload["attribution"]});
                    let size = item.to_string().len();
                    if self.processes.len() >= PROCESS_COUNT
                        || self.process_bytes + size > PROCESS_BYTES
                    {
                        self.overflows += 1;
                        self.fail("runtime_state_capacity");
                    }
                    if size <= PROCESS_BYTES {
                        self.process_bytes += size;
                        self.processes.insert(key, (item, size));
                        self.process_peak = self.process_peak.max(self.processes.len());
                    }
                } else {
                    self.fail("runtime_state_invalid_identity");
                }
            }
        }
        if ["stale", "offline"].contains(&self.health.as_str()) {
            self.clear_processes();
            self.reason = if self.health == "stale" {
                "observer_health_timeout"
            } else {
                "helper_disconnected"
            }
            .into();
        }
        self.updated = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64;
        let kind = [
            text(payload, "event"),
            text(frame, "type"),
            text(&record, "type"),
        ]
        .into_iter()
        .find(|s| !s.is_empty())
        .unwrap_or_default();
        self.history_bytes += raw.len();
        self.history.push_front(Evidence {
            raw,
            at: self.updated,
            r#type: kind,
        });
        while self.history.len() > HISTORY_COUNT || self.history_bytes > HISTORY_BYTES {
            self.history_bytes -= self.history.pop_back().unwrap().raw.len();
            self.evicted += 1;
        }
        self.history_peak = self.history_peak.max(self.history_bytes);
        self.applied += 1;
        self.apply_us += begin.elapsed().as_micros() as u64;
    }
    pub fn snapshot(&mut self) -> String {
        self.snapshots += 1;
        // Serialize as text across IPC: WebKit must not round uint64 identities.
        json!({"processes":self.processes.values().map(|(v,_)|v).collect::<Vec<_>>(),
            "evidence":self.history,"transport":self.transport,"health":self.health,
            "coverage":if self.client_gap.is_empty() { &self.coverage } else { "degraded" },
            "sensor_coverage":self.coverage,"client_gap":self.client_gap,
            "reason":if self.client_gap.is_empty() { &self.reason } else { &self.client_gap },
            "monitor_session":self.session,"coverage_epoch":self.epoch,"updated":self.updated,
            "metrics":{"received":self.received,"applied":self.applied,"elapsed_ms":self.started.elapsed().as_millis() as u64,
                "history_evicted":self.evicted,"state_overflows":self.overflows,"process_peak":self.process_peak,
                "history_bytes":self.history_bytes,"history_bytes_peak":self.history_peak,"process_bytes":self.process_bytes,
                "pending_records":0,"snapshots":self.snapshots,"apply_us":self.apply_us}
        }).to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn id(pid: u64, version: u64) -> Value {
        json!({"valid":true,"pid":pid,"pidversion":version,"start_time_us":u64::MAX,"path":"/bin/sleep"})
    }
    fn event(kind: u64, subject: Value, target: Value) -> Value {
        json!({"protocol":1,"type":"server_frame","frame":{"monitor_session":"one","transport":"connected","observer_health":"healthy","coverage":"complete","payload":{
            "event":"continuous_attribution","event_type":kind,"subject":subject,"target":target,"root_identity":id(1,1),"attribution":"es_confirmed_descendant","coverage_epoch":0}}})
    }
    fn push(state: &mut State, v: Value) {
        state.push(v.to_string(), v);
    }
    fn snap(state: &mut State) -> Value {
        serde_json::from_str(&state.snapshot()).unwrap()
    }
    #[test]
    fn diagnostics_keep_counters_without_process_or_source_content() {
        let mut state = State::default();
        let mut value = event(1, id(1, 1), id(42, 1));
        value["frame"]["monitor_session"] = json!("private-source-name");
        value["frame"]["payload"]["target"]["path"] = json!("/private/not-for-diagnostics");
        push(&mut state, value);
        let counters = state.diagnostics();
        assert_eq!(counters["received"], 1);
        assert_eq!(counters["applied"], 1);
        assert_eq!(counters["process_peak"], 1);
        assert!(counters.as_object().unwrap().values().all(Value::is_number));
        let body = counters.to_string();
        assert!(!body.contains("private-source-name"));
        assert!(!body.contains("not-for-diagnostics"));
        assert_eq!(counters["snapshots"], 0);
    }
    #[test]
    fn burst_and_no_page_reads_preserve_state_and_evict_only_history() {
        let mut state = State::default();
        push(&mut state, event(1, id(1, 1), id(42, 1)));
        let start = Instant::now();
        for version in 2..=10_001 {
            push(&mut state, event(2, id(42, version - 1), id(42, version)));
        }
        let v = snap(&mut state);
        assert_eq!(v["metrics"]["applied"], 10_001);
        assert_eq!(v["metrics"]["state_overflows"], 0);
        assert_eq!(v["coverage"], "complete");
        assert_eq!(v["processes"].as_array().unwrap().len(), 1);
        assert_eq!(v["processes"][0]["identity"]["pidversion"], 10_001);
        assert_eq!(
            v["processes"][0]["identity"]["start_time_us"].as_u64(),
            Some(u64::MAX)
        );
        assert!(v["metrics"]["history_bytes"].as_u64().unwrap() <= HISTORY_BYTES as u64);
        println!(
            "burst elapsed_ms={} metrics={}",
            start.elapsed().as_millis(),
            v["metrics"]
        );
        push(&mut state, event(3, id(42, 10_001), Value::Null));
        assert!(snap(&mut state)["processes"].as_array().unwrap().is_empty());
    }
    #[test]
    fn capacity_gap_is_sticky_until_explicit_reset() {
        let mut state = State::default();
        for pid in 1..=501 {
            push(&mut state, event(1, id(1, 1), id(pid, 1)));
        }
        push(
            &mut state,
            json!({"frame":{"observer_health":"healthy","coverage":"complete","reason":"observer_heartbeat"}}),
        );
        let v = snap(&mut state);
        assert_eq!(v["coverage"], "degraded");
        assert_eq!(v["sensor_coverage"], "complete");
        assert_eq!(v["client_gap"], "runtime_state_capacity");
        assert_eq!(v["metrics"]["state_overflows"], 1);
        assert!(state.processes.len() <= PROCESS_COUNT);
        assert!(state.process_bytes <= PROCESS_BYTES);
        push(&mut state, json!({"reset":true,"transport":"connecting"}));
        assert_eq!(snap(&mut state)["client_gap"], "");
        assert!(state.processes.is_empty());
    }
    #[test]
    fn pid_reuse_old_exit_does_not_remove_new_identity() {
        let mut state = State::default();
        push(&mut state, event(1, id(1, 1), id(42, 1)));
        push(&mut state, event(2, id(42, 1), id(42, 2)));
        push(&mut state, event(3, id(42, 1), Value::Null));
        assert_eq!(state.processes.len(), 1);
        push(&mut state, event(3, id(42, 2), Value::Null));
        assert!(state.processes.is_empty());
    }
    #[test]
    fn session_epoch_and_health_clear_old_state() {
        let mut state = State::default();
        push(&mut state, event(1, id(1, 1), id(42, 1)));
        push(&mut state, json!({"frame":{"monitor_session":"two"}}));
        assert!(state.processes.is_empty());
        push(&mut state, event(1, id(1, 1), id(42, 1)));
        push(
            &mut state,
            json!({"frame":{"coverage":"degraded","payload":{"coverage_epoch":1,"reason":"global_gap"}}}),
        );
        assert!(state.processes.is_empty());
        assert_eq!(snap(&mut state)["sensor_coverage"], "degraded");
        push(&mut state, event(1, id(1, 1), id(42, 1)));
        push(&mut state, json!({"observer_health":"stale"}));
        assert!(state.processes.is_empty());
    }
    #[test]
    fn raw_history_is_exact_and_byte_bounded() {
        let mut state = State::default();
        let v = json!({"protocol":1,"type":"client_status","payload":"中".repeat(30_000),"number":u64::MAX});
        let raw = v.to_string();
        for _ in 0..300 {
            state.push(raw.clone(), v.clone());
        }
        assert_eq!(state.history[0].raw, raw);
        assert!(state.history_bytes <= HISTORY_BYTES);
        assert_eq!(snap(&mut state)["client_gap"], "");
    }
}
