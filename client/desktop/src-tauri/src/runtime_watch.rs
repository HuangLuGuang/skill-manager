#[path = "runtime_state.rs"]
mod runtime_state;
use std::io::{BufRead, BufReader, Read};
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;

const MAX_RECORD: usize = 128 * 1024;
static CURRENT: OnceLock<Mutex<Option<Arc<Session>>>> = OnceLock::new();
static OPERATIONS: Mutex<()> = Mutex::new(());
static NEXT_ID: AtomicU64 = AtomicU64::new(1);
static CLOSING: AtomicBool = AtomicBool::new(false);
static ACTIVE: AtomicBool = AtomicBool::new(false);

#[derive(Default)]
struct Buffer {
    state: runtime_state::State,
    stopped: bool,
    exit_code: Option<i32>,
    error_code: Option<String>,
}

impl Buffer {
    fn batch(&mut self, id: &str) -> Batch {
        Batch {
            watch_id: id.into(),
            snapshot: self.state.snapshot(),
            stopped: self.stopped,
            exit_code: self.exit_code,
            error_code: self.error_code.clone(),
        }
    }
}

struct Session {
    id: String,
    cancel: AtomicBool,
    buffer: Mutex<Buffer>,
    done: Mutex<bool>,
    finished: Condvar,
}

#[derive(Serialize)]
pub struct Batch {
    watch_id: String,
    snapshot: String,
    stopped: bool,
    exit_code: Option<i32>,
    error_code: Option<String>,
}

fn current() -> &'static Mutex<Option<Arc<Session>>> {
    CURRENT.get_or_init(|| Mutex::new(None))
}

fn fail(session: &Session, code: &str) {
    if let Ok(mut buffer) = session.buffer.lock() {
        buffer.state.fail(code);
        buffer.error_code = Some(code.into());
    }
    session.cancel.store(true, Ordering::Release);
}

fn read_records(reader: impl Read, session: &Session) {
    let mut reader = BufReader::new(reader);
    let mut last_diagnostic = Instant::now();
    loop {
        let mut bytes = Vec::new();
        let read = (&mut reader)
            .take((MAX_RECORD + 1) as u64)
            .read_until(b'\n', &mut bytes);
        match read {
            Ok(0) => break,
            Ok(_) if bytes.len() <= MAX_RECORD && bytes.last() == Some(&b'\n') => {}
            _ => {
                fail(session, "runtime_bridge_invalid_record");
                break;
            }
        }
        let value = serde_json::from_slice::<serde_json::Value>(&bytes).ok();
        let valid = value.as_ref().is_some_and(|v| {
            v.get("protocol").and_then(|v| v.as_u64()) == Some(1)
                && matches!(
                    v.get("type").and_then(|v| v.as_str()),
                    Some("client_status" | "server_frame")
                )
        });
        if !valid {
            fail(session, "runtime_bridge_invalid_record");
            break;
        }
        let Ok(record) = String::from_utf8(bytes) else {
            fail(session, "runtime_bridge_invalid_record");
            break;
        };
        let Ok(mut buffer) = session.buffer.lock() else {
            break;
        };
        buffer.state.push(record, value.unwrap());
        if last_diagnostic.elapsed() >= Duration::from_secs(60) {
            eprintln!(
                "{}",
                serde_json::json!({"event":"runtime_watch_counters", "metrics":buffer.state.diagnostics()})
            );
            last_diagnostic = Instant::now();
        }
    }
    if let Ok(buffer) = session.buffer.lock() {
        eprintln!(
            "{}",
            serde_json::json!({"event":"runtime_watch_finished", "metrics":buffer.state.diagnostics()})
        );
    }
}

// Retain only recognized codes, never raw stderr paths or an unbounded log.
fn read_output_error(mut reader: impl Read) -> Option<&'static str> {
    let mut tail = Vec::new();
    let mut block = [0; 256];
    let mut code = None;
    while let Ok(n) = reader.read(&mut block) {
        if n == 0 {
            break;
        }
        tail.extend_from_slice(&block[..n]);
        for candidate in [
            "runtime_observation_output_failure",
            "runtime_observation_output_backpressure_timeout",
        ] {
            if tail
                .windows(candidate.len())
                .any(|part| part == candidate.as_bytes())
                && code != Some("runtime_observation_output_backpressure_timeout")
            {
                code = Some(candidate);
            }
        }
        if tail.len() > 128 {
            tail.drain(..tail.len() - 128);
        }
    }
    code
}

fn run(session: Arc<Session>, mut child: std::process::Child) {
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();
    let reader_session = session.clone();
    let reader = thread::spawn(move || read_records(stdout, &reader_session));
    let errors = thread::spawn(move || read_output_error(stderr));
    let mut termination_sent = false;
    let exit_code = loop {
        if session.cancel.load(Ordering::Acquire) && !termination_sent {
            let _ = child.kill();
            termination_sent = true;
        }
        match child.try_wait() {
            Ok(Some(status)) => break status.code(),
            Ok(None) => thread::sleep(Duration::from_millis(25)),
            Err(_) => {
                fail(&session, "runtime_bridge_wait_failed");
                let _ = child.kill();
                break None;
            }
        }
    };
    // The known CLI starts no children; its exit closes both pipe writers.
    let deadline = Instant::now() + Duration::from_secs(1);
    while (!reader.is_finished() || !errors.is_finished()) && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(10));
    }
    if !reader.is_finished() || !errors.is_finished() {
        fail(&session, "runtime_bridge_reader_timeout");
    }
    let output_error = if errors.is_finished() {
        errors.join().ok().flatten()
    } else {
        None
    };
    if let Ok(mut buffer) = session.buffer.lock() {
        buffer.stopped = true;
        buffer.exit_code = exit_code;
        if let Some(code) = output_error {
            buffer.state.fail(code);
            buffer.error_code = Some(code.into());
        }
        if exit_code != Some(0) && !termination_sent && buffer.error_code.is_none() {
            buffer.state.fail("runtime_bridge_process_failed");
            buffer.error_code = Some("runtime_bridge_process_failed".into());
        }
    }
    ACTIVE.store(false, Ordering::Release);
    if let Ok(mut done) = session.done.lock() {
        *done = true;
        session.finished.notify_all();
    }
}

fn stop(session: &Session) -> Result<(), String> {
    session.cancel.store(true, Ordering::Release);
    let done = session
        .done
        .lock()
        .map_err(|_| "runtime_bridge_state_unavailable")?;
    let (done, _) = session
        .finished
        .wait_timeout_while(done, Duration::from_secs(3), |done| !*done)
        .map_err(|_| "runtime_bridge_state_unavailable")?;
    if !*done {
        return Err("runtime_bridge_stop_timeout".into());
    }
    Ok(())
}

pub fn start(socket: &str, executable: &Path) -> Result<String, String> {
    if !cfg!(target_os = "macos") {
        return Err("runtime_observation_unsupported_platform".into());
    }
    if !Path::new(socket).is_absolute() {
        return Err("runtime_observation_socket_path_absolute".into());
    }
    let _operation = OPERATIONS
        .lock()
        .map_err(|_| "runtime_bridge_state_unavailable")?;
    if CLOSING.load(Ordering::Acquire) {
        return Err("runtime_bridge_closing".into());
    }
    let mut slot = current()
        .lock()
        .map_err(|_| "runtime_bridge_state_unavailable")?;
    if let Some(previous) = slot.as_ref() {
        stop(previous)?;
    }
    let child = Command::new(executable)
        .args([
            "runtime-watch",
            "--socket",
            socket,
            "--reconnect",
            "1s",
            "--health-timeout",
            "5s",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|_| "runtime_bridge_start_failed")?;
    let session = Arc::new(Session {
        id: format!("runtime-{}", NEXT_ID.fetch_add(1, Ordering::Relaxed)),
        cancel: AtomicBool::new(false),
        buffer: Mutex::new(Buffer::default()),
        done: Mutex::new(false),
        finished: Condvar::new(),
    });
    let id = session.id.clone();
    *slot = Some(session.clone());
    ACTIVE.store(true, Ordering::Release);
    thread::spawn(move || run(session, child));
    Ok(id)
}

pub fn read(id: &str) -> Result<Batch, String> {
    let slot = current()
        .lock()
        .map_err(|_| "runtime_bridge_state_unavailable")?;
    let session = slot
        .as_ref()
        .filter(|s| s.id == id)
        .ok_or("runtime_bridge_watch_not_found")?;
    let result = session
        .buffer
        .lock()
        .map_err(|_| "runtime_bridge_state_unavailable")?
        .batch(id);
    Ok(result)
}

pub fn stop_id(id: &str) -> Result<(), String> {
    let _operation = OPERATIONS
        .lock()
        .map_err(|_| "runtime_bridge_state_unavailable")?;
    let mut slot = current()
        .lock()
        .map_err(|_| "runtime_bridge_state_unavailable")?;
    if let Some(session) = slot.as_ref().filter(|s| s.id == id) {
        stop(session)?;
        *slot = None;
    }
    Ok(())
}

pub fn active() -> bool {
    ACTIVE.load(Ordering::Acquire)
}

pub fn begin_shutdown() -> bool {
    CLOSING
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .is_ok()
}

pub fn shutdown() -> Result<(), String> {
    let result = (|| {
        let _operation = OPERATIONS
            .lock()
            .map_err(|_| "runtime_bridge_state_unavailable")?;
        let mut slot = current()
            .lock()
            .map_err(|_| "runtime_bridge_state_unavailable")?;
        if let Some(session) = slot.as_ref() {
            stop(session)?;
        }
        *slot = None;
        Ok(())
    })();
    if result.is_err() {
        CLOSING.store(false, Ordering::Release);
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(unix)]
    #[test]
    fn partial_output_keeps_terminal_diagnostic_and_degrades() {
        let child = Command::new("/bin/sh")
            .args(["-c", "printf '{\"protocol\":1'; printf 'error: runtime_observation_output_failure: runtime_observation_output_backpressure_timeout\\n' >&2; exit 1"])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn().unwrap();
        let state = Arc::new(session());
        run(state.clone(), child);
        let mut buffer = state.buffer.lock().unwrap();
        assert!(buffer.stopped);
        assert_eq!(
            buffer.error_code.as_deref(),
            Some("runtime_observation_output_backpressure_timeout")
        );
        let snapshot: serde_json::Value = serde_json::from_str(&buffer.state.snapshot()).unwrap();
        assert_eq!(snapshot["coverage"], "degraded");
        assert!(snapshot["processes"].as_array().unwrap().is_empty());
    }

    #[test]
    fn output_diagnostics_keep_only_stable_codes_across_chunks() {
        let input = format!("{}runtime_observation_output_failure: runtime_observation_output_backpressure_timeout{}", "x".repeat(250), "secret path".repeat(10000));
        assert_eq!(
            read_output_error(input.as_bytes()),
            Some("runtime_observation_output_backpressure_timeout")
        );
        assert_eq!(
            read_output_error(b"arbitrary private diagnostic".as_slice()),
            None
        );
    }
    fn session() -> Session {
        Session {
            id: "test".into(),
            cancel: AtomicBool::new(false),
            buffer: Mutex::new(Buffer::default()),
            done: Mutex::new(false),
            finished: Condvar::new(),
        }
    }
    #[cfg(unix)]
    #[test]
    #[ignore = "30 second controlled native stream acceptance; not a GUI test"]
    fn sustained_stream_with_snapshot_pause() {
        use std::io::Write;
        use std::os::unix::net::UnixStream;
        let (mut writer, reader) = UnixStream::pair().unwrap();
        let state = Arc::new(session());
        let target = state.clone();
        let consume = thread::spawn(move || read_records(reader, &target));
        let producer = thread::spawn(move || {
            let start = Instant::now();
            for n in 1..=30_000u64 {
                let identity = |version| serde_json::json!({"valid":true,"pid":42,"pidversion":version,"start_time_us":u64::MAX,"path":"/bin/sleep"});
                let event = serde_json::json!({"protocol":1,"type":"server_frame","frame":{"monitor_session":"controlled","transport":"connected","observer_health":"healthy","coverage":"complete","payload":{
                    "event":"continuous_attribution","event_type":2,"subject":identity(n-1),"target":identity(n),"root_identity":identity(1),"attribution":"es_confirmed_descendant","coverage_epoch":0}}});
                writeln!(writer, "{}", event).unwrap();
                if n % 50 == 0 {
                    if let Some(wait) = Duration::from_millis(n).checked_sub(start.elapsed()) {
                        thread::sleep(wait);
                    }
                }
            }
        });
        let start = Instant::now();
        while start.elapsed() < Duration::from_secs(10) {
            let _ = state.buffer.lock().unwrap().batch("test");
            thread::sleep(Duration::from_millis(250));
        }
        let first = state.buffer.lock().unwrap().batch("test");
        println!(
            "snapshot_polling={}",
            serde_json::from_str::<serde_json::Value>(&first.snapshot).unwrap()["metrics"]
        );
        // No page reads at all while the remaining 20 seconds continue to arrive.
        producer.join().unwrap();
        consume.join().unwrap();
        let last = state.buffer.lock().unwrap().batch("test");
        let v: serde_json::Value = serde_json::from_str(&last.snapshot).unwrap();
        println!("snapshot_paused={}", v["metrics"]);
        assert_eq!(v["metrics"]["applied"], 30_000);
        assert_eq!(v["metrics"]["state_overflows"], 0);
        assert_eq!(v["coverage"], "complete");
        assert_eq!(v["processes"][0]["identity"]["pidversion"], 30_000);
        assert_eq!(
            v["processes"][0]["identity"]["start_time_us"].as_u64(),
            Some(u64::MAX)
        );
        assert!(!state.cancel.load(Ordering::Acquire));
    }
    #[test]
    fn paused_page_does_not_block_native_reader() {
        let state = session();
        let raw = "{\"protocol\":1,\"type\":\"client_status\",\"transport\":\"connected\"}\n";
        read_records(std::io::Cursor::new(raw.repeat(10_000)), &state);
        let batch = state.buffer.lock().unwrap().batch("test");
        let snapshot: serde_json::Value = serde_json::from_str(&batch.snapshot).unwrap();
        assert_eq!(snapshot["metrics"]["applied"], 10_000);
        assert_eq!(snapshot["metrics"]["history_evicted"], 9_800);
        assert_eq!(snapshot["client_gap"], "");
    }
    #[test]
    fn oversized_and_unterminated_lines_fail_before_unbounded_allocation() {
        for bytes in [vec![b'x'; MAX_RECORD + 2], b"{\"protocol\":1}".to_vec()] {
            let state = session();
            read_records(std::io::Cursor::new(bytes), &state);
            assert!(state.cancel.load(Ordering::Acquire));
            assert_eq!(
                state.buffer.lock().unwrap().error_code.as_deref(),
                Some("runtime_bridge_invalid_record")
            );
        }
    }
    #[cfg(unix)]
    #[test]
    fn cancellation_reaps_the_owned_process() {
        let child = Command::new("/bin/sleep")
            .arg("30")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let pid = child.id();
        let state = Arc::new(session());
        let worker_state = state.clone();
        let worker = thread::spawn(move || run(worker_state, child));
        stop(&state).unwrap();
        worker.join().unwrap();
        assert!(state.buffer.lock().unwrap().stopped);
        assert_eq!(unsafe { libc::kill(pid as i32, 0) }, -1);
        assert_eq!(
            std::io::Error::last_os_error().raw_os_error(),
            Some(libc::ESRCH)
        );
    }

    #[cfg(target_os = "macos")]
    #[test]
    #[ignore = "requires AGENT_MANAGER_CLIENT_BINARY pointing to a built client"]
    fn real_client_streams_offline_and_is_reaped() {
        let binary = std::env::var("AGENT_MANAGER_CLIENT_BINARY").unwrap();
        let id = start(
            "/nonexistent-agent-manager-runtime-test/runtime.sock",
            Path::new(&binary),
        )
        .unwrap();
        let deadline = Instant::now() + Duration::from_secs(4);
        let mut offline = false;
        while Instant::now() < deadline {
            let batch = read(&id).unwrap();
            let snapshot: serde_json::Value = serde_json::from_str(&batch.snapshot).unwrap();
            offline |= snapshot["transport"] == "offline";
            if offline {
                break;
            }
            thread::sleep(Duration::from_millis(25));
        }
        stop_id(&id).unwrap();
        assert!(offline);
        assert!(!active());
        assert!(read(&id).is_err());
        let restarted = start(
            "/nonexistent-agent-manager-runtime-test/runtime.sock",
            Path::new(&binary),
        )
        .unwrap();
        assert_ne!(id, restarted);
        // Exercise the same native shutdown path used by window close/app exit.
        assert!(begin_shutdown());
        shutdown().unwrap();
        assert!(!active());
        assert!(read(&restarted).is_err());
        CLOSING.store(false, Ordering::Release);
    }
}
