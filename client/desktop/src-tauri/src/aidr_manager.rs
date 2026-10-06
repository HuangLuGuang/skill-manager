//! Owns only this application's receiver. Neither pages nor foreground timers
//! supervise collection. The existing Go store remains the queue/ACK authority.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs::{self, File, OpenOptions};
use std::hash::{Hash, Hasher};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant, SystemTime};

static MANAGER: OnceLock<Mutex<Supervisor>> = OnceLock::new();
static SHUTTING_DOWN: AtomicBool = AtomicBool::new(false);
static ACTION: Mutex<()> = Mutex::new(());
#[derive(Clone, serde::Deserialize)]
struct RetryPolicy {
    mode: String,
    retries: u32,
    max_interval_seconds: u64,
}
impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            mode: "fixed".into(),
            retries: 2,
            max_interval_seconds: 300,
        }
    }
}
impl RetryPolicy {
    fn from_plan(plan: &Value) -> Self {
        serde_json::from_value::<Self>(plan["runtime_policy"]["target"]["retry"].clone())
            .ok()
            .filter(|p| {
                ["none", "fixed", "continuous"].contains(&p.mode.as_str())
                    && p.retries <= 20
                    && (10..=3600).contains(&p.max_interval_seconds)
            })
            .unwrap_or_default()
    }
    fn permits(&self, attempts: u32) -> bool {
        attempts == 0
            || (self.mode == "continuous" && attempts < 21)
            || (self.mode == "fixed" && attempts <= self.retries)
    }
    fn delay(&self, attempts: u32, seed: u64) -> Duration {
        // Capped exponential delay plus bounded jitter. Counts saturate, so a
        // long outage cannot overflow the exponent or grow retained state.
        let base = 2u64
            .saturating_pow(attempts.min(12))
            .min(self.max_interval_seconds);
        Duration::from_millis(
            (base * 1000 + seed % (base * 200 + 1)).min(self.max_interval_seconds * 1000),
        )
    }
}

#[derive(Clone, Serialize)]
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
// A single bounded record, separate from the event queue. It contains only
// stable codes and a configuration fingerprint, never credentials or payloads.
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RetryState {
    version: u32,
    configuration: String,
    queue: String,
    device: String,
    attempts: u32,
    suspended: bool,
    active: bool,
    code: String,
    next_retry_at_ms: u64,
    last_failure: Option<String>,
    last_failure_at_ms: Option<u64>,
}
fn unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u64::MAX as u128) as u64
}
fn read_retry_state(path: &Path) -> Result<Option<RetryState>, String> {
    #[cfg(unix)]
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    options.custom_flags(libc::O_NOFOLLOW);
    let file = match options.open(path) {
        Ok(file) => file,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err("aidr_desktop_retry_state_invalid".into()),
    };
    let meta = file
        .metadata()
        .map_err(|_| "aidr_desktop_retry_state_invalid")?;
    #[cfg(unix)]
    if meta.mode() & 0o077 != 0 || meta.uid() != unsafe { libc::geteuid() } {
        return Err("aidr_desktop_retry_state_invalid".into());
    }
    if !meta.is_file() || meta.len() > 4096 {
        return Err("aidr_desktop_retry_state_invalid".into());
    }
    let mut bytes = Vec::new();
    file.take(4097)
        .read_to_end(&mut bytes)
        .map_err(|_| "aidr_desktop_retry_state_invalid")?;
    let state: RetryState =
        serde_json::from_slice(&bytes).map_err(|_| "aidr_desktop_retry_state_invalid")?;
    if state.version != 1
        || state.configuration.len() != 16
        || state.queue.len() > 2048
        || state.device.len() > 128
        || stable_error(&state.code) != state.code
        || state
            .last_failure
            .as_ref()
            .is_some_and(|code| stable_error(code) != *code)
    {
        return Err("aidr_desktop_retry_state_invalid".into());
    }
    Ok(Some(state))
}
fn write_retry_state(path: &Path, bytes: &[u8]) -> Result<(), String> {
    #[cfg(unix)]
    use std::os::unix::fs::OpenOptionsExt;
    let temp = path.with_extension(format!("{}-write", std::process::id()));
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
    let mut created = false;
    let result = (|| -> std::io::Result<()> {
        let mut file = options.open(&temp)?;
        created = true;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temp, path)?;
        File::open(path.parent().unwrap())?.sync_all()
    })();
    if created {
        let _ = fs::remove_file(&temp);
    }
    result.map_err(|_| "aidr_desktop_retry_state_unwritable".into())
}
struct Supervisor {
    home: PathBuf,
    binary: PathBuf,
    child: Option<Child>,
    lock: Option<File>,
    fingerprint: u64,
    running_fingerprint: u64,
    plan: Option<Result<Value, String>>,
    attempts: u32,
    next_start: Instant,
    started_at: SystemTime,
    health_observation: HealthObservation,
    error: Arc<Mutex<String>>,
    snapshot: Snapshot,
    socket: Option<(PathBuf, fs::Metadata)>,
    socket_birth: Option<mpsc::Receiver<Value>>,
    retry_suspended: bool,
    state_lock: Option<File>,
    retry_state: Option<RetryState>,
    saved_retry_state: Vec<u8>,
    next_retry_at_ms: u64,
}

#[derive(Default)]
struct HealthObservation {
    last_check: Option<SystemTime>,
    resume_until: Option<Instant>,
}
impl HealthObservation {
    fn resume_pending(&mut self, wall: SystemTime, monotonic: Instant) -> bool {
        // A suspended supervisor cannot observe whether the child is healthy.
        // Give it one bounded reporting window after scheduling resumes, while
        // withholding telemetry until an actually fresh report is available.
        if self.last_check.is_some_and(|previous| {
            wall.duration_since(previous)
                .map_or(true, |gap| gap > Duration::from_secs(15))
        }) {
            self.resume_until = Some(monotonic + Duration::from_secs(15));
        }
        self.last_check = Some(wall);
        self.resume_until.is_some_and(|until| monotonic < until)
    }
    fn fresh(&mut self) {
        self.resume_until = None;
    }
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
fn fingerprint(home: &Path) -> u64 {
    let mut hash = std::collections::hash_map::DefaultHasher::new();
    for name in ["config.json", "aidr/preferences.json"] {
        if let Ok(file) = File::open(home.join(".agent-manager").join(name)) {
            let mut bytes = Vec::new();
            let _ = file.take(65537).read_to_end(&mut bytes);
            bytes.hash(&mut hash);
        }
    }
    hash.finish()
}

#[cfg(unix)]
fn take_lock(path: &Path) -> Result<File, String> {
    use std::os::fd::AsRawFd;
    use std::os::unix::fs::OpenOptionsExt;
    let file = OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|_| "aidr_desktop_lock_invalid")?;
    if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        return Err("aidr_desktop_receiver_conflict".into());
    }
    Ok(file)
}
#[cfg(not(unix))]
fn take_lock(_path: &Path) -> Result<File, String> {
    Err("aidr_desktop_platform_unsupported".into())
}

fn same_file(a: &fs::Metadata, b: &fs::Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        a.ino() == b.ino() && a.dev() == b.dev()
    }
    #[cfg(not(unix))]
    {
        let _ = (a, b);
        false
    }
}
impl Supervisor {
    fn retry_failure(&mut self, code: String, retry: &RetryPolicy) {
        self.snapshot.code = code.clone();
        self.snapshot.last_failure = Some(code.clone());
        self.snapshot.last_failure_at_ms = Some(unix_ms());
        self.retry_suspended = correction_required(&code);
        let delay = retry.delay(self.attempts, unix_ms());
        self.next_start = Instant::now() + delay;
        self.next_retry_at_ms = unix_ms().saturating_add(delay.as_millis() as u64);
    }
    fn prepare_failure(&mut self, code: String, retry: &RetryPolicy) {
        let configuration_busy = code == "aidr_desktop_action_busy";
        self.retry_failure(code, retry);
        // Platform installation can hold the mutation lock during startup.
        // Retry this contention within the configured budget; other preparation
        // failures still require correction before opening the event store.
        self.retry_suspended = !configuration_busy;
        self.lock = None;
    }
    fn load_retry_state(&mut self, plan: &Value, retry: &RetryPolicy) -> Result<(), String> {
        let root = plan["paths"]["root"]
            .as_str()
            .ok_or("aidr_desktop_status_invalid")?;
        // prepare validates the private root and owns its creation. A status
        // read alone never creates a second receiver or removes old sockets.
        if !Path::new(root).exists() {
            run_cli(
                &self.binary,
                &self.home,
                &["--action".into(), "prepare".into()],
            )?;
        }
        if self.state_lock.is_none() {
            self.state_lock = Some(take_lock(&Path::new(root).join("supervisor.lock"))?);
        }
        let mut state = RetryState {
            version: 1,
            configuration: format!("{:016x}", self.running_fingerprint),
            queue: plan["paths"]["state"].as_str().unwrap_or("").into(),
            device: plan["paths"]["device"].as_str().unwrap_or("").into(),
            attempts: 0,
            suspended: false,
            active: false,
            code: "aidr_desktop_stopped".into(),
            next_retry_at_ms: 0,
            last_failure: None,
            last_failure_at_ms: None,
        };
        if let Some(previous) = read_retry_state(&Path::new(root).join("receiver-supervisor.json"))?
        {
            if previous.configuration == state.configuration
                && previous.queue == state.queue
                && previous.device == state.device
            {
                state = previous;
                self.attempts = state.attempts;
                self.retry_suspended = state.suspended && state.code != "aidr_desktop_action_busy";
                self.snapshot.code = state.code.clone();
                self.snapshot.last_failure = state.last_failure.clone();
                self.snapshot.last_failure_at_ms = state.last_failure_at_ms;
                let wait = state
                    .next_retry_at_ms
                    .saturating_sub(unix_ms())
                    .min(retry.max_interval_seconds * 1000);
                self.next_start = Instant::now() + Duration::from_millis(wait);
                self.next_retry_at_ms = unix_ms().saturating_add(wait);
                if state.active {
                    self.retry_failure("aidr_desktop_receiver_interrupted".into(), retry);
                }
            }
        }
        self.retry_state = Some(state);
        self.saved_retry_state.clear();
        Ok(())
    }
    fn persist_retry_state(&mut self) {
        let Some(state) = self.retry_state.as_mut() else {
            return;
        };
        state.attempts = self.attempts;
        state.suspended = self.retry_suspended;
        state.active = self.child.is_some();
        state.code = self.snapshot.code.clone();
        state.next_retry_at_ms = self.next_retry_at_ms;
        state.last_failure = self.snapshot.last_failure.clone();
        state.last_failure_at_ms = self.snapshot.last_failure_at_ms;
        let bytes = serde_json::to_vec(state).unwrap();
        if bytes == self.saved_retry_state {
            return;
        }
        if let Err(code) = write_retry_state(
            &self
                .home
                .join(".agent-manager/aidr/receiver-supervisor.json"),
            &bytes,
        ) {
            self.stop();
            self.snapshot.code = code;
            self.retry_suspended = true;
        } else {
            self.saved_retry_state = bytes;
        }
    }
    fn quit(&mut self) {
        let healthy = self.snapshot.code == "aidr_desktop_running" && self.child.is_some();
        let previous = self.snapshot.code.clone();
        self.stop();
        if healthy {
            // A deliberate healthy application exit is not a receiver failure.
            // Preserve the last failure, but grant a new initial launch.
            self.attempts = 0;
            self.retry_suspended = false;
            self.next_retry_at_ms = 0;
        } else {
            self.snapshot.code = previous;
        }
        self.persist_retry_state();
        self.state_lock = None;
    }
    fn capture_socket_birth(&mut self, socket: &Path, wait: Duration) {
        let Some(channel) = &self.socket_birth else {
            return;
        };
        if let Ok(proof) = channel.recv_timeout(wait) {
            self.socket_birth = None;
            if let Ok(meta) = fs::symlink_metadata(socket) {
                #[cfg(unix)]
                {
                    use std::os::unix::fs::{FileTypeExt, MetadataExt};
                    if proof["kind"] == "aidr_receiver_socket"
                        && proof["device"].as_str().and_then(|v| v.parse::<u64>().ok())
                            == Some(meta.dev())
                        && proof["inode"].as_str().and_then(|v| v.parse::<u64>().ok())
                            == Some(meta.ino())
                        && meta.file_type().is_socket()
                    {
                        self.socket = Some((socket.to_path_buf(), meta));
                    }
                }
            }
        }
    }
    fn stop(&mut self) {
        if let Some(mut child) = self.child.take() {
            // PID is taken exclusively from our unreaped Child, never from a
            // socket, old status record or another client's process listing.
            #[cfg(unix)]
            unsafe {
                libc::kill(child.id() as i32, libc::SIGTERM);
            }
            #[cfg(not(unix))]
            {
                let _ = child.kill();
            }
            let deadline = Instant::now() + Duration::from_secs(8);
            loop {
                match child.try_wait() {
                    Ok(Some(_)) => break,
                    _ if Instant::now() >= deadline => {
                        let _ = child.kill();
                        let _ = child.wait();
                        break;
                    }
                    _ => thread::sleep(Duration::from_millis(50)),
                }
            }
        }
        let path = self.home.join(".agent-manager/aidr/hook.sock");
        self.capture_socket_birth(&path, Duration::from_millis(200));
        self.socket_birth = None;
        self.clean_owned_socket();
        self.lock = None;
        self.snapshot.telemetry = Value::Null;
        self.snapshot.code = "aidr_desktop_stopped".into();
    }
    fn clean_owned_socket(&mut self) {
        if let Some((path, original)) = self.socket.take() {
            if fs::symlink_metadata(&path).is_ok_and(|now| same_file(&now, &original)) {
                let _ = fs::remove_file(path);
            }
        }
    }
    fn tick(&mut self) {
        self.tick_inner();
        self.snapshot.attempts = self.attempts;
        self.snapshot.retry_count = self.attempts.saturating_sub(1);
        let retry = self
            .plan
            .as_ref()
            .and_then(|p| p.as_ref().ok())
            .map(RetryPolicy::from_plan)
            .unwrap_or_default();
        self.snapshot.retry_suspended =
            self.retry_suspended || (self.child.is_none() && !retry.permits(self.attempts));
        self.snapshot.next_retry_seconds = if self.child.is_none()
            && self.snapshot.enabled
            && !self.snapshot.retry_suspended
            && self.attempts > 0
        {
            Some(
                self.next_retry_at_ms
                    .saturating_sub(unix_ms())
                    .div_ceil(1000),
            )
        } else {
            None
        };
        self.persist_retry_state();
    }
    fn tick_inner(&mut self) {
        let fp = fingerprint(&self.home);
        if fp != self.fingerprint {
            self.fingerprint = fp;
            self.plan = None;
        }
        let plan = match self
            .plan
            .get_or_insert_with(|| {
                run_cli(
                    &self.binary,
                    &self.home,
                    &["--action".into(), "status".into()],
                )
            })
            .clone()
        {
            Ok(p) => p,
            Err(code) => {
                self.stop();
                self.snapshot.enabled = false;
                self.snapshot.code = code;
                return;
            }
        };
        // Host observations and application timestamps refresh the displayed
        // plan without restarting a healthy receiver. Only its configuration,
        // binding, credentials and retry target affect the process lifecycle.
        let mut running = std::collections::hash_map::DefaultHasher::new();
        if let Ok(file) = File::open(self.home.join(".agent-manager/config.json")) {
            let mut bytes = Vec::new();
            let _ = file.take(65537).read_to_end(&mut bytes);
            bytes.hash(&mut running);
        }
        if !plan["receiver_required"].is_boolean() {
            plan["enabled"].to_string().hash(&mut running);
        }
        plan["paths"].to_string().hash(&mut running);
        plan["runtime_policy"]["target"]["retry"]
            .to_string()
            .hash(&mut running);
        let running_fp = running.finish();
        let retry = RetryPolicy::from_plan(&plan);
        if running_fp != self.running_fingerprint {
            self.stop();
            self.running_fingerprint = running_fp;
            self.attempts = 0;
            self.snapshot.attempts = 0;
            self.retry_suspended = false;
            self.next_start = Instant::now();
            self.next_retry_at_ms = 0;
            self.retry_state = None;
            self.snapshot.last_failure = None;
            self.snapshot.last_failure_at_ms = None;
            if plan["paths"]["root"].is_string() {
                if let Err(code) = self.load_retry_state(&plan, &retry) {
                    self.snapshot.enabled = false;
                    self.snapshot.code = code;
                    self.retry_suspended = true;
                    return;
                }
            }
        }
        self.snapshot.enabled = plan["enabled"].as_bool() == Some(true);
        self.snapshot.policy = plan["runtime_policy"].clone();
        self.snapshot.retry_mode = retry.mode.clone();
        self.snapshot.managed_task = plan["managed_task"].as_str().unwrap_or("0").into();
        if !receiver_required(&plan) {
            self.stop();
            self.snapshot.code = "aidr_desktop_disabled".into();
            if let Err(code) = write_stopped_observation(&self.home, &plan) {
                self.snapshot.code = code;
            }
            return;
        }
        let Some(root) = plan["paths"]["root"].as_str().map(PathBuf::from) else {
            self.snapshot.code = "aidr_desktop_status_invalid".into();
            return;
        };
        let socket = PathBuf::from(plan["paths"]["socket"].as_str().unwrap_or(""));
        self.capture_socket_birth(&socket, Duration::ZERO);
        if let Some(child) = self.child.as_mut() {
            if child.try_wait().ok().flatten().is_some() {
                self.child = None;
                self.capture_socket_birth(&socket, Duration::from_millis(200));
                self.socket_birth = None;
                self.clean_owned_socket();
                self.lock = None;
                self.snapshot.telemetry = Value::Null;
                let code = self.error.lock().unwrap().clone();
                self.retry_failure(code, &retry);
            }
        }
        if self.child.is_none() {
            if self.retry_suspended || !retry.permits(self.attempts) {
                return;
            }
            if Instant::now() < self.next_start {
                return;
            }
            self.attempts = self.attempts.saturating_add(1);
            self.snapshot.attempts = self.attempts;
            // An existing socket is a visible migration/conflict condition. It
            // is never adopted or removed based on PID or failed health probes.
            if fs::symlink_metadata(&socket).is_ok() {
                self.retry_failure("aidr_desktop_receiver_conflict".into(), &retry);
                self.retry_suspended = true;
                return;
            }
            self.lock = match take_lock(&root.join("desktop.lock")) {
                Ok(lock) => Some(lock),
                Err(code) => {
                    self.retry_failure(code, &retry);
                    self.retry_suspended = true;
                    return;
                }
            };
            if let Err(code) = run_cli(
                &self.binary,
                &self.home,
                &["--action".into(), "prepare".into()],
            ) {
                self.prepare_failure(code, &retry);
                return;
            }
            *self.error.lock().unwrap() = "aidr_desktop_receiver_failed".into();
            // Persist the reserved attempt before launching. A crash in the
            // spawn window must not grant an extra retry after restarting.
            self.persist_retry_state();
            if self.retry_suspended {
                return;
            }
            match Command::new(&self.binary)
                .arg("aidr-hook-serve")
                .arg("--managed-home")
                .arg(&self.home)
                .arg("--parent-stdin")
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
            {
                Ok(mut child) => {
                    if let Some(stdout) = child.stdout.take() {
                        let (sender, receiver) = mpsc::channel();
                        self.socket_birth = Some(receiver);
                        thread::spawn(move || {
                            let mut reader = BufReader::new(stdout.take(4096));
                            let mut line = String::new();
                            if reader.read_line(&mut line).is_ok() {
                                if let Ok(proof) = serde_json::from_str::<Value>(&line) {
                                    let _ = sender.send(proof);
                                }
                            }
                            let _ = std::io::copy(&mut reader, &mut std::io::sink());
                        });
                    }
                    if let Some(stderr) = child.stderr.take() {
                        let error = self.error.clone();
                        thread::spawn(move || {
                            // Retain only a stable code. Never retain command output,
                            // raw config, HTTP headers or credentials.
                            for line in BufReader::new(stderr.take(4096))
                                .lines()
                                .map_while(Result::ok)
                            {
                                *error.lock().unwrap() = stable_error(&line);
                            }
                        });
                    }
                    self.child = Some(child);
                    self.started_at = SystemTime::now();
                    self.snapshot.code = "aidr_desktop_starting".into();
                    self.next_retry_at_ms = 0;
                }
                Err(_) => {
                    self.lock = None;
                    self.retry_failure("aidr_desktop_binary_missing".into(), &retry);
                    self.retry_suspended = true;
                    return;
                }
            }
        }
        let status = Path::new(plan["paths"]["status"].as_str().unwrap_or(""));
        let resume_pending = self
            .health_observation
            .resume_pending(SystemTime::now(), Instant::now());
        let fresh = fs::metadata(status)
            .ok()
            .and_then(|m| m.modified().ok())
            .is_some_and(|modified| {
                modified >= self.started_at
                    && modified.elapsed().unwrap_or(Duration::MAX) < Duration::from_secs(15)
            });
        if fresh {
            self.health_observation.fresh();
            self.snapshot.code = "aidr_desktop_status_invalid".into();
            self.snapshot.telemetry = Value::Null;
            if let Ok(file) = File::open(status) {
                let mut bytes = Vec::new();
                let _ = file.take(65537).read_to_end(&mut bytes);
                if bytes.len() <= 65536 {
                    if let Ok(value) = serde_json::from_slice::<Value>(&bytes) {
                        if valid_telemetry(&value, &plan["paths"]["device"]) {
                            self.snapshot.telemetry = value;
                            self.snapshot.code = "aidr_desktop_running".into();
                            if !self.snapshot.enabled && plan["receiver_required"].is_boolean() {
                                if self.snapshot.telemetry["state"]["runtime_collection_enabled"]
                                    == false
                                {
                                    if self.snapshot.telemetry["state"]["pending_upload_records"]
                                        .as_u64()
                                        == Some(0)
                                    {
                                        self.stop();
                                        self.snapshot.code = "aidr_desktop_disabled".into();
                                        if let Err(code) =
                                            write_stopped_observation(&self.home, &plan)
                                        {
                                            self.snapshot.code = code;
                                        }
                                        self.plan = None;
                                        return;
                                    }
                                    self.snapshot.code = "aidr_desktop_draining".into();
                                }
                            }
                        }
                    }
                }
            }
            self.capture_socket_birth(&socket, Duration::ZERO);
        } else if self.child.is_some() && resume_pending {
            self.snapshot.code = "aidr_desktop_health_rechecking".into();
            self.snapshot.telemetry = Value::Null;
        } else if self.child.is_some()
            && self.started_at.elapsed().unwrap_or_default() > Duration::from_secs(10)
        {
            self.snapshot.code = "aidr_desktop_health_stale".into();
            self.snapshot.telemetry = Value::Null;
            // An unresponsive owned process is reaped before any retry. Keep
            // the actual failure visible throughout the backoff.
            self.stop();
            self.retry_failure("aidr_desktop_health_stale".into(), &retry);
        }
    }
}
fn correction_required(code: &str) -> bool {
    [
        "aidr_upload_auth_rejected",
        "aidr_desktop_managed_binding_changed",
        "aidr_store_binding_mismatch",
        "aidr_hook_socket_exists",
        "aidr_store_busy",
        "aidr_plugin_version_unverified",
        "aidr_desktop_managed_authorization_required",
        "aidr_desktop_receiver_conflict",
        "aidr_desktop_retry_state_invalid",
        "aidr_desktop_retry_state_unwritable",
    ]
    .contains(&code)
}
fn write_stopped_observation(home: &Path, plan: &Value) -> Result<(), String> {
    let Some(version) = plan["runtime_policy"]["version"].as_str() else {
        return Ok(());
    };
    if plan["enabled"].as_bool() != Some(false) || !plan["receiver_required"].is_boolean() {
        return Ok(());
    }
    let path = home.join(".agent-manager/aidr/hook-collection-status.json");
    if fs::metadata(&path)
        .ok()
        .and_then(|m| m.modified().ok())
        .is_some_and(|t| t.elapsed().unwrap_or(Duration::MAX) < Duration::from_secs(5))
    {
        return Ok(());
    }
    let observation = json!({"version":1,"client_id":plan["paths"]["device"],"queue":plan["paths"]["state"],"policy_version":version,"observed_at_ms":unix_ms().to_string(),"enabled":false,"code":"aidr_desktop_disabled"});
    write_retry_state(&path, &serde_json::to_vec(&observation).unwrap())
        .map_err(|_| "aidr_desktop_status_failed".into())
}
fn receiver_required(plan: &Value) -> bool {
    plan["enabled"].as_bool() == Some(true) || plan["receiver_required"].as_bool() == Some(true)
}
fn valid_telemetry(value: &Value, device: &Value) -> bool {
    value.is_object()
        && value["state"]["client_id"].is_string()
        && &value["state"]["client_id"] == device
        && value["state"]["stream_id"].is_string()
        && value["state"]["receiver_instance"].is_string()
        && value["state"]["queued_records"].is_u64()
}
pub fn init(home: PathBuf, binary: PathBuf) {
    let _ = MANAGER.set(Mutex::new(Supervisor {
        home,
        binary,
        child: None,
        lock: None,
        fingerprint: 0,
        running_fingerprint: 0,
        plan: None,
        attempts: 0,
        next_start: Instant::now(),
        started_at: SystemTime::now(),
        health_observation: HealthObservation::default(),
        error: Arc::new(Mutex::new(String::new())),
        socket: None,
        socket_birth: None,
        retry_suspended: false,
        state_lock: None,
        retry_state: None,
        saved_retry_state: Vec::new(),
        next_retry_at_ms: 0,
        snapshot: Snapshot {
            code: "aidr_desktop_disabled".into(),
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
        },
    }));
    thread::spawn(|| {
        while !SHUTTING_DOWN.load(Ordering::Acquire) {
            if let Some(m) = MANAGER.get() {
                m.lock().unwrap().tick();
            }
            thread::sleep(Duration::from_secs(1));
        }
    });
}
pub fn collection_status(home: &Path, binary: &Path) -> Result<Value, String> {
    run_cli(binary, home, &["--action".into(), "channels-status".into()])
}

pub fn snapshot() -> Snapshot {
    let (mut snapshot, details) = match MANAGER.get() {
        Some(manager) => {
            let supervisor = manager.lock().unwrap();
            (
                supervisor.snapshot.clone(),
                Some((
                    supervisor.home.clone(),
                    supervisor.binary.clone(),
                    supervisor.child.as_ref().map(Child::id),
                )),
            )
        }
        None => {
            return Snapshot {
                code: "aidr_desktop_not_configured".into(),
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
            }
        }
    };
    if let Some((home, binary, owned_pid)) = details {
        snapshot.receiver_diagnostic =
            match run_cli(&binary, &home, &["--action".into(), "diagnose".into()]) {
                Ok(mut diagnostic) => {
                    if owned_pid.map(u64::from) == diagnostic["pid"].as_u64()
                        && owned_pid.is_some()
                        && diagnostic["ownership"] == "external_verified"
                    {
                        diagnostic["ownership"] = json!("owned");
                    }
                    diagnostic
                }
                Err(code) => json!({"ownership":"unavailable", "code":code}),
            };
    }
    snapshot
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
    if action == "retry" {
        if let Some(m) = MANAGER.get() {
            let mut s = m.lock().unwrap();
            if s.snapshot.code == "aidr_desktop_retry_state_invalid" {
                return Err(s.snapshot.code.clone());
            }
            s.stop();
            s.plan = None;
            s.attempts = 0;
            s.retry_suspended = false;
            s.next_start = Instant::now();
            s.next_retry_at_ms = 0;
            s.snapshot.code = "aidr_desktop_starting".into();
            s.persist_retry_state();
            if s.retry_state.is_none() {
                s.running_fingerprint = 0;
            }
        }
        return Ok(json!({"code":"aidr_desktop_starting"}));
    }
    if ![
        "inspect",
        "connect",
        "upgrade",
        "enable",
        "disable",
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
    if let Some(m) = MANAGER.get() {
        m.lock().unwrap().quit();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn scheduling_resume_waits_for_fresh_health_without_unbounded_grace() {
        let wall = SystemTime::UNIX_EPOCH + Duration::from_secs(1000);
        let monotonic = Instant::now();
        let mut health = HealthObservation::default();
        assert!(!health.resume_pending(wall, monotonic));
        // Sleep may advance wall time while leaving monotonic time unchanged.
        let resumed = wall + Duration::from_secs(600);
        assert!(health.resume_pending(resumed, monotonic));
        for seconds in 1..15 {
            assert!(health.resume_pending(
                resumed + Duration::from_secs(seconds),
                monotonic + Duration::from_secs(seconds)
            ));
        }
        assert!(!health.resume_pending(
            resumed + Duration::from_secs(15),
            monotonic + Duration::from_secs(15)
        ));
        assert!(!health.resume_pending(
            resumed + Duration::from_secs(16),
            monotonic + Duration::from_secs(16)
        ));
    }
    #[test]
    fn fresh_health_ends_resume_window_and_clock_rollback_rechecks() {
        let wall = SystemTime::UNIX_EPOCH + Duration::from_secs(1000);
        let monotonic = Instant::now();
        let mut health = HealthObservation::default();
        assert!(!health.resume_pending(wall, monotonic));
        assert!(health.resume_pending(wall + Duration::from_secs(30), monotonic));
        health.fresh();
        assert!(!health.resume_pending(wall + Duration::from_secs(31), monotonic));
        assert!(health.resume_pending(wall, monotonic));
    }
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
    #[cfg(unix)]
    #[test]
    fn retry_state_restores_limits_backoff_and_precise_binding() {
        use std::os::unix::fs::{symlink, PermissionsExt};
        let root = std::env::temp_dir().join(format!("aidr-retry-state-{}", std::process::id()));
        let private = root.join(".agent-manager/aidr");
        fs::create_dir_all(&private).unwrap();
        fs::set_permissions(&private, fs::Permissions::from_mode(0o700)).unwrap();
        let make = || Supervisor {
            home: root.clone(),
            binary: PathBuf::from("/nonexistent"),
            child: None,
            lock: None,
            fingerprint: 0,
            running_fingerprint: 1234,
            plan: None,
            attempts: 0,
            next_start: Instant::now(),
            started_at: SystemTime::now(),
            health_observation: HealthObservation::default(),
            error: Arc::new(Mutex::new(String::new())),
            socket: None,
            socket_birth: None,
            retry_suspended: false,
            state_lock: None,
            retry_state: None,
            saved_retry_state: Vec::new(),
            next_retry_at_ms: 0,
            snapshot: Snapshot {
                code: "aidr_desktop_stopped".into(),
                enabled: true,
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
            },
        };
        let plan = json!({"paths":{"root":private,"state":"queue-one","device":"device-one"}});
        let retry = RetryPolicy::default();
        // Parallel process tests can retain a forked reference until exec.
        // Only wait after the owning supervisor has explicitly released it;
        // the simultaneous-owner rejection below remains immediate.
        let restore_after_release = |supervisor: &mut Supervisor, plan: &Value| {
            let deadline = Instant::now() + Duration::from_secs(2);
            loop {
                match supervisor.load_retry_state(plan, &retry) {
                    Ok(()) => break,
                    Err(code)
                        if code == "aidr_desktop_receiver_conflict"
                            && Instant::now() < deadline =>
                    {
                        thread::sleep(Duration::from_millis(10));
                    }
                    Err(code) => panic!("state restoration after owner release: {code}"),
                }
            }
        };
        let mut first = make();
        first.load_retry_state(&plan, &retry).unwrap();
        first.attempts = 3;
        first.retry_failure("aidr_desktop_receiver_failed".into(), &retry);
        first.persist_retry_state();
        let path = private.join("receiver-supervisor.json");
        let modified = fs::metadata(&path).unwrap().modified().unwrap();
        first.persist_retry_state();
        assert_eq!(modified, fs::metadata(&path).unwrap().modified().unwrap());
        let mut second = make();
        assert_eq!(
            second.load_retry_state(&plan, &retry).unwrap_err(),
            "aidr_desktop_receiver_conflict"
        );
        drop(first);
        restore_after_release(&mut second, &plan);
        assert_eq!(second.attempts, 3);
        assert!(!retry.permits(second.attempts));
        assert!(second.next_start > Instant::now());
        assert_eq!(
            second.snapshot.last_failure.as_deref(),
            Some("aidr_desktop_receiver_failed")
        );
        let failure_at = second.snapshot.last_failure_at_ms;
        second.quit();
        assert_eq!(second.attempts, 3);
        let mut resumed = make();
        restore_after_release(&mut resumed, &plan);
        assert_eq!(resumed.attempts, 3);
        assert_eq!(resumed.snapshot.last_failure_at_ms, failure_at);
        resumed.child = Some(Command::new("/bin/sleep").arg("30").spawn().unwrap());
        resumed.snapshot.code = "aidr_desktop_running".into();
        resumed.quit();
        let mut healthy_restart = make();
        restore_after_release(&mut healthy_restart, &plan);
        assert_eq!(healthy_restart.attempts, 0);
        assert_eq!(healthy_restart.snapshot.last_failure_at_ms, failure_at);
        healthy_restart.child = Some(Command::new("/bin/sleep").arg("30").spawn().unwrap());
        healthy_restart.attempts = 1;
        healthy_restart.snapshot.code = "aidr_desktop_running".into();
        healthy_restart.persist_retry_state();
        // Preserve an unclean record while explicitly reaping our test child.
        healthy_restart.stop();
        drop(healthy_restart);
        let mut interrupted = make();
        restore_after_release(&mut interrupted, &plan);
        assert_eq!(interrupted.attempts, 1);
        assert_eq!(
            interrupted.snapshot.code,
            "aidr_desktop_receiver_interrupted"
        );
        interrupted.quit();
        let mut rotated = make();
        rotated.running_fingerprint = 5678;
        let different = json!({"paths":{"root":private,"state":"queue-two","device":"device-two"}});
        restore_after_release(&mut rotated, &different);
        assert_eq!(rotated.attempts, 0);
        rotated.quit();
        fs::remove_file(&path).unwrap();
        let foreign = root.join("foreign");
        fs::write(&foreign, "keep this file").unwrap();
        symlink(&foreign, &path).unwrap();
        assert_eq!(
            read_retry_state(&path).err().as_deref(),
            Some("aidr_desktop_retry_state_invalid")
        );
        assert_eq!(fs::read_to_string(&foreign).unwrap(), "keep this file");
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn configurable_retry_modes_and_jitter_are_bounded() {
        let mut policy = RetryPolicy::default();
        assert!(policy.permits(0));
        assert!(policy.permits(2));
        assert!(!policy.permits(3));
        policy.mode = "none".into();
        assert!(policy.permits(0));
        assert!(!policy.permits(1));
        policy.mode = "continuous".into();
        assert!(policy.permits(20));
        assert!(!policy.permits(21));
        assert!(!policy.permits(u32::MAX));
        for attempt in [1, 2, 10, 32, u32::MAX] {
            for seed in [0, 1, u64::MAX] {
                let delay = policy.delay(attempt, seed);
                assert!(delay >= Duration::from_secs(2));
                assert!(delay <= Duration::from_secs(300));
            }
        }
        assert!(correction_required("aidr_store_busy"));
        assert!(!correction_required("aidr_desktop_receiver_failed"));
    }
    #[test]
    fn malformed_or_cross_device_telemetry_is_not_healthy() {
        let device = json!("device-one");
        assert!(!valid_telemetry(&Value::Null, &device));
        assert!(!valid_telemetry(
            &json!({"state":{"client_id":"device-two"}}),
            &device
        ));
        let value = json!({"state":{"client_id":"device-one", "stream_id":"stream", "receiver_instance":"instance", "queued_records":0}});
        assert!(valid_telemetry(&value, &device));
    }
    #[test]
    fn stopped_observation_preserves_target_identity_without_claiming_live_intake() {
        let home = std::env::temp_dir().join(format!("aidr-stopped-{}", std::process::id()));
        fs::create_dir_all(home.join(".agent-manager/aidr")).unwrap();
        let plan = json!({"enabled":false,"receiver_required":false,"runtime_policy":{"version":"1:4"},"paths":{"device":"test-device","state":"test-queue"}});
        write_stopped_observation(&home, &plan).unwrap();
        let path = home.join(".agent-manager/aidr/hook-collection-status.json");
        let value: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(value["enabled"], false);
        assert_eq!(value["client_id"], "test-device");
        assert_eq!(value["queue"], "test-queue");
        assert_eq!(value["policy_version"], "1:4");
        assert!(value["observed_at_ms"]
            .as_str()
            .unwrap()
            .parse::<u64>()
            .is_ok());
        assert!(!receiver_required(&plan));
        assert!(receiver_required(
            &json!({"enabled":false,"receiver_required":true})
        ));
        fs::remove_dir_all(home).unwrap();
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
    #[cfg(unix)]
    #[test]
    fn cached_plan_does_not_spawn_status_process_on_every_tick() {
        use std::os::unix::fs::PermissionsExt;
        let root = std::env::temp_dir().join(format!("aidr-cache-{}", std::process::id()));
        fs::create_dir_all(root.join(".agent-manager")).unwrap();
        let binary = root.join("client");
        let counter = root.join("calls");
        fs::write(&binary, format!("#!/bin/sh\nprintf 'x' >> '{}'\nprintf '%s' '{{\"enabled\":false,\"managed_task\":\"0\"}}'\n", counter.display())).unwrap();
        fs::set_permissions(&binary, fs::Permissions::from_mode(0o700)).unwrap();
        let mut s = Supervisor {
            home: root.clone(),
            binary,
            child: None,
            lock: None,
            fingerprint: 0,
            running_fingerprint: 0,
            plan: None,
            attempts: 0,
            next_start: Instant::now(),
            started_at: SystemTime::now(),
            health_observation: HealthObservation::default(),
            error: Arc::new(Mutex::new(String::new())),
            socket: None,
            socket_birth: None,
            retry_suspended: false,
            state_lock: None,
            retry_state: None,
            saved_retry_state: Vec::new(),
            next_retry_at_ms: 0,
            snapshot: Snapshot {
                code: String::new(),
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
            },
        };
        for _ in 0..120 {
            s.tick();
        }
        assert_eq!(fs::read(&counter).unwrap().len(), 1);
        fs::write(root.join(".agent-manager/config.json"), b"changed").unwrap();
        s.tick();
        assert_eq!(fs::read(&counter).unwrap().len(), 2);
        fs::remove_dir_all(root).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn preparation_contention_retries_with_budget_and_restores_prior_busy_state() {
        let root = std::env::temp_dir().join(format!("aidr-prepare-busy-{}", std::process::id()));
        fs::create_dir_all(root.join(".agent-manager/aidr")).unwrap();
        let binary = root.join("unused-client");
        let mut s = Supervisor {
            home: root.clone(),
            binary,
            child: None,
            lock: None,
            fingerprint: 0,
            running_fingerprint: 0,
            plan: None,
            attempts: 0,
            next_start: Instant::now(),
            started_at: SystemTime::now(),
            health_observation: HealthObservation::default(),
            error: Arc::new(Mutex::new(String::new())),
            socket: None,
            socket_birth: None,
            retry_suspended: false,
            state_lock: None,
            retry_state: None,
            saved_retry_state: Vec::new(),
            next_retry_at_ms: 0,
            snapshot: Snapshot {
                code: String::new(),
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
            },
        };
        let retry = RetryPolicy::default();
        s.attempts = 1;
        s.prepare_failure("aidr_desktop_action_busy".into(), &retry);
        assert!(!s.retry_suspended);
        assert_eq!(s.snapshot.code, "aidr_desktop_action_busy");
        assert!(s.next_start > Instant::now());
        assert!(retry.permits(s.attempts));
        s.attempts = 3;
        assert!(!retry.permits(s.attempts));
        assert!(!RetryPolicy {
            mode: "none".into(),
            ..retry.clone()
        }
        .permits(1));
        s.prepare_failure("aidr_desktop_config_invalid".into(), &retry);
        assert!(s.retry_suspended);

        let directory = root.join(".agent-manager/aidr");
        let previous = RetryState {
            version: 1,
            configuration: format!("{:016x}", s.running_fingerprint),
            queue: "queue-one".into(),
            device: "device-one".into(),
            attempts: 1,
            suspended: true,
            active: false,
            code: "aidr_desktop_action_busy".into(),
            next_retry_at_ms: 0,
            last_failure: Some("aidr_desktop_action_busy".into()),
            last_failure_at_ms: Some(100),
        };
        let path = directory.join("receiver-supervisor.json");
        write_retry_state(&path, &serde_json::to_vec(&previous).unwrap()).unwrap();
        s.load_retry_state(
            &json!({"paths":{"root":directory,"state":"queue-one","device":"device-one"}}),
            &retry,
        )
        .unwrap();
        assert!(!s.retry_suspended);
        assert_eq!(s.attempts, 1);
        assert_eq!(s.snapshot.last_failure_at_ms, Some(100));
        s.persist_retry_state();
        assert!(!read_retry_state(&path).unwrap().unwrap().suspended);
        drop(s);
        fs::remove_dir_all(root).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn lock_prevents_competing_desktops() {
        let p = std::env::temp_dir().join(format!("aidr-lock-{}", std::process::id()));
        let first = take_lock(&p).unwrap();
        assert!(take_lock(&p).is_err());
        drop(first);
        // Other parallel tests may briefly inherit the descriptor between
        // fork and exec; close-on-exec releases that inherited reference.
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            if take_lock(&p).is_ok() {
                break;
            }
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(10));
        }
        let _ = fs::remove_file(p);
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn real_sidecar_rotation_retry_limit_and_cleanup() {
        use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
        let root = PathBuf::from(format!("/private/tmp/aidr-rust-{}", std::process::id()));
        fs::create_dir_all(root.join(".agent-manager/aidr")).unwrap();
        fs::set_permissions(
            root.join(".agent-manager/aidr"),
            fs::Permissions::from_mode(0o700),
        )
        .unwrap();
        let config = root.join(".agent-manager/config.json");
        let save = |token: &str| {
            let value = json!({"server":"http://127.0.0.1:9","token":token});
            let mut f = OpenOptions::new()
                .create(true)
                .truncate(true)
                .write(true)
                .mode(0o600)
                .open(&config)
                .unwrap();
            use std::io::Write;
            f.write_all(value.to_string().as_bytes()).unwrap();
        };
        save("fictional-one");
        let prefs = root.join(".agent-manager/aidr/preferences.json");
        {
            use std::io::Write;
            let mut f = OpenOptions::new()
                .create(true)
                .write(true)
                .mode(0o600)
                .open(&prefs)
                .unwrap();
            f.write_all(b"{\"enabled\":true,\"hosts\":{}}").unwrap();
        }
        let binary = super::super::client_binary().unwrap();
        let mut s = Supervisor {
            home: root.clone(),
            binary,
            child: None,
            lock: None,
            fingerprint: 0,
            running_fingerprint: 0,
            plan: None,
            attempts: 0,
            next_start: Instant::now(),
            started_at: SystemTime::now(),
            health_observation: HealthObservation::default(),
            error: Arc::new(Mutex::new(String::new())),
            socket: None,
            socket_birth: None,
            retry_suspended: false,
            state_lock: None,
            retry_state: None,
            saved_retry_state: Vec::new(),
            next_retry_at_ms: 0,
            snapshot: Snapshot {
                code: String::new(),
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
            },
        };
        let prerequisites = action(&root, &s.binary, &root, "system-check", "").unwrap();
        assert_eq!(prerequisites["version"], 1);
        assert_eq!(prerequisites["es_authorization"], "unknown");
        assert_eq!(prerequisites["es_subscription"], "unknown");
        assert!(s.child.is_none());
        let ready = |s: &mut Supervisor| {
            let deadline = Instant::now() + Duration::from_secs(8);
            loop {
                s.tick();
                if s.snapshot.code == "aidr_desktop_running" {
                    break;
                }
                assert!(Instant::now() < deadline, "{}", s.snapshot.code);
                thread::sleep(Duration::from_millis(150));
            }
        };
        // Startup ownership precedes the first health report. Kill the
        // actual child in that window and require cleanup and a new launch.
        s.tick();
        let socket = root.join(".agent-manager/aidr/hook.sock");
        let deadline = Instant::now() + Duration::from_secs(15);
        while s.socket.is_none() {
            s.capture_socket_birth(&socket, Duration::from_millis(50));
            assert!(Instant::now() < deadline);
        }
        assert!(s.snapshot.telemetry.is_null());
        let early_pid = s.child.as_ref().unwrap().id();
        s.child.as_mut().unwrap().kill().unwrap();
        s.child.as_mut().unwrap().wait().unwrap();
        s.tick();
        assert!(!socket.exists());
        s.next_start = Instant::now();
        ready(&mut s);
        assert_ne!(early_pid, s.child.as_ref().unwrap().id());
        ready(&mut s);
        let pid = s.child.as_ref().unwrap().id();
        let stream = s.snapshot.telemetry["state"]["stream_id"].clone();
        // A real offline sidecar keeps one durable event while intake stops.
        // The same owned process resumes; disabling does not abandon its queue.
        let mut submit = Command::new(&s.binary)
            .args([
                "aidr-hook",
                "--agent",
                "codex",
                "--event",
                "SessionStart",
                "--socket",
            ])
            .arg(&socket)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        submit
            .stdin
            .take()
            .unwrap()
            .write_all(
                b"{\"hook_event_name\":\"SessionStart\",\"session_id\":\"controlled-drain\"}",
            )
            .unwrap();
        assert!(submit.wait().unwrap().success());
        fs::write(&prefs, b"{\"enabled\":false,\"hosts\":{}}").unwrap();
        let drain_deadline = Instant::now() + Duration::from_secs(8);
        while s.snapshot.code != "aidr_desktop_draining" {
            s.tick();
            assert!(Instant::now() < drain_deadline, "{}", s.snapshot.code);
            thread::sleep(Duration::from_millis(100));
        }
        assert_eq!(s.child.as_ref().unwrap().id(), pid);
        assert!(!s.snapshot.enabled);
        assert_eq!(s.snapshot.telemetry["state"]["pending_upload_records"], 1);
        fs::write(&prefs, b"{\"enabled\":true,\"hosts\":{}}").unwrap();
        ready(&mut s);
        assert_eq!(s.child.as_ref().unwrap().id(), pid);
        {
            struct ResumeChild(u32);
            impl Drop for ResumeChild {
                fn drop(&mut self) {
                    unsafe { libc::kill(self.0 as i32, libc::SIGCONT) };
                }
            }
            assert_eq!(unsafe { libc::kill(pid as i32, libc::SIGSTOP) }, 0);
            let _resume = ResumeChild(pid);
            let wall = SystemTime::now();
            s.started_at = wall - Duration::from_secs(60);
            s.health_observation.last_check = Some(wall - Duration::from_secs(60));
            let status = PathBuf::from(
                s.plan.as_ref().unwrap().as_ref().unwrap()["paths"]["status"]
                    .as_str()
                    .unwrap(),
            );
            File::options()
                .write(true)
                .open(status)
                .unwrap()
                .set_times(fs::FileTimes::new().set_modified(wall - Duration::from_secs(30)))
                .unwrap();
            let attempts = s.attempts;
            s.tick();
            assert_eq!(s.snapshot.code, "aidr_desktop_health_rechecking");
            assert!(s.snapshot.telemetry.is_null());
            assert_eq!(s.child.as_ref().unwrap().id(), pid);
            assert_eq!(s.attempts, attempts);
        }
        ready(&mut s);
        assert_eq!(s.child.as_ref().unwrap().id(), pid);
        s.tick();
        assert_eq!(pid, s.child.as_ref().unwrap().id());
        save("fictional-two");
        ready(&mut s);
        assert_ne!(pid, s.child.as_ref().unwrap().id());
        assert_eq!(stream, s.snapshot.telemetry["state"]["stream_id"]);
        // Losing the private desktop pipe also stops an otherwise healthy
        // receiver, including when the desktop is terminated abnormally.
        drop(s.child.as_mut().unwrap().stdin.take());
        let deadline = Instant::now() + Duration::from_secs(8);
        while s.child.as_mut().unwrap().try_wait().unwrap().is_none() {
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(25));
        }
        assert!(!socket.exists());
        save("fictional-three");
        ready(&mut s);
        assert_eq!(stream, s.snapshot.telemetry["state"]["stream_id"]);
        // Each crash is our owned child. A fourth automatic launch is forbidden.
        for attempt in 1..=3 {
            assert_eq!(s.attempts, attempt);
            s.child.as_mut().unwrap().kill().unwrap();
            thread::sleep(Duration::from_millis(100));
            s.tick();
            if attempt < 3 {
                s.next_start = Instant::now();
                ready(&mut s);
            }
        }
        assert!(s.child.is_none());
        s.next_start = Instant::now();
        s.tick();
        assert!(s.child.is_none());
        s.stop();
        assert!(!root.join(".agent-manager/aidr/hook.sock").exists());
        assert!(root.join(".agent-manager/aidr/queues").exists());
        // An external socket is evidence of a conflict, not authority to
        // remove it or signal its owner.
        let foreign = root.join(".agent-manager/aidr/hook.sock");
        let external = std::os::unix::net::UnixListener::bind(&foreign).unwrap();
        s.attempts = 0;
        s.next_start = Instant::now();
        s.tick();
        assert_eq!(s.snapshot.code, "aidr_desktop_receiver_conflict");
        assert!(s.child.is_none());
        s.stop();
        assert!(foreign.exists());
        drop(external);
        fs::remove_dir_all(root).unwrap();
    }
}
