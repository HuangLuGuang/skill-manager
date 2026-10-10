#include "bounded_log.h"
#include "continuous_state.h"
#import <EndpointSecurity/EndpointSecurity.h>
#import <Foundation/Foundation.h>
#import <bsm/libbsm.h>
#import <fcntl.h>
#import <libproc.h>
#import <mach/mach_time.h>
#import <os/lock.h>
#import <signal.h>
#import <stdatomic.h>
#import <stdio.h>
#import <string.h>
#import <sys/stat.h>
#import <unistd.h>

#ifndef EVENT_CAPACITY
#define EVENT_CAPACITY 8192
#endif
#define LOG_CAPACITY 1024
#define LOG_RECORD_MAX 16384
#define MAX_CATALOG 32
typedef struct {
  cont_event_t items[EVENT_CAPACITY];
  size_t head, count;
  os_unfair_lock lock;
} event_ring_t;
static event_ring_t g_ring = {.lock = OS_UNFAIR_LOCK_INIT};
static _Atomic uint64_t g_overflow;
static _Atomic uint64_t g_received;
static _Atomic uint64_t g_event_enqueued;
static _Atomic uint64_t g_processed;
static _Atomic uint64_t g_event_discarded;
static _Atomic uint64_t g_ring_high_water;
static volatile sig_atomic_t g_stop;
static void stop_handler(int signal_number) {
  (void)signal_number;
  g_stop = 1;
}
static bool file_path(const es_file_t *f, char out[CONT_PATH_MAX]) {
  es_string_token_t t = f->path;
  size_t n = t.length < CONT_PATH_MAX - 1 ? t.length : CONT_PATH_MAX - 1;
  if (n && t.data)
    memcpy(out, t.data, n);
  out[n] = '\0';
  return !f->path_truncated && t.length < CONT_PATH_MAX;
}
static bool token_equal(audit_token_t a, audit_token_t b) {
  return memcmp(&a, &b, sizeof(a)) == 0;
}
static cont_identity_t identity(const es_process_t *p, uint32_t version) {
  if (version < 3)
    return (cont_identity_t){0};
  return (cont_identity_t){audit_token_to_pid(p->audit_token),
                           audit_token_to_pidversion(p->audit_token),
                           (uint64_t)p->start_time.tv_sec * 1000000 +
                               (uint64_t)p->start_time.tv_usec,
                           true};
}
static uint64_t unix_ns(struct timespec t) {
  return (uint64_t)t.tv_sec * 1000000000 + (uint64_t)t.tv_nsec;
}
static void enqueue(cont_event_t e) {
  atomic_fetch_add(&g_received, 1);
  os_unfair_lock_lock(&g_ring.lock);
  if (g_ring.count == EVENT_CAPACITY)
    atomic_fetch_add(&g_overflow, 1);
  else {
    size_t i = (g_ring.head + g_ring.count) % EVENT_CAPACITY;
    g_ring.items[i] = e;
    g_ring.count++;
    atomic_fetch_add(&g_event_enqueued, 1);
    uint64_t high = atomic_load(&g_ring_high_water);
    if (g_ring.count > high)
      atomic_store(&g_ring_high_water, g_ring.count);
  }
  os_unfair_lock_unlock(&g_ring.lock);
}
static bool dequeue(cont_event_t *out) {
  bool ok = false;
  os_unfair_lock_lock(&g_ring.lock);
  if (g_ring.count) {
    *out = g_ring.items[g_ring.head];
    g_ring.head = (g_ring.head + 1) % EVENT_CAPACITY;
    g_ring.count--;
    ok = true;
  }
  os_unfair_lock_unlock(&g_ring.lock);
  return ok;
}
static size_t queued_count(void) {
  os_unfair_lock_lock(&g_ring.lock);
  size_t count = g_ring.count;
  os_unfair_lock_unlock(&g_ring.lock);
  return count;
}
static size_t discard_queued_events(void) {
  os_unfair_lock_lock(&g_ring.lock);
  size_t discarded = g_ring.count;
  g_ring.head = 0;
  g_ring.count = 0;
  os_unfair_lock_unlock(&g_ring.lock);
  atomic_fetch_add(&g_event_discarded, discarded);
  return discarded;
}
static void capture(const es_message_t *m) {
  cont_event_t e = {.version = m->version,
                    .seq_num = m->version >= 2 ? m->seq_num : 0,
                    .global_seq_num = m->version >= 4 ? m->global_seq_num : 0,
                    .time_unix_ns = unix_ns(m->time),
                    .mach_time = m->mach_time,
                    .parent_link_valid = true};
  e.subject = identity(m->process, m->version);
  e.subject_path_complete = file_path(m->process->executable, e.subject_path);
  if (m->event_type == ES_EVENT_TYPE_NOTIFY_FORK) {
    e.type = CONT_FORK;
    e.target = identity(m->event.fork.child, m->version);
    e.target_path_complete =
        file_path(m->event.fork.child->executable, e.target_path);
    e.parent_link_valid =
        m->version >= 4 && token_equal(m->event.fork.child->parent_audit_token,
                                       m->process->audit_token);
  } else if (m->event_type == ES_EVENT_TYPE_NOTIFY_EXEC) {
    e.type = CONT_EXEC;
    e.target = identity(m->event.exec.target, m->version);
    e.target_path_complete =
        file_path(m->event.exec.target->executable, e.target_path);
  } else if (m->event_type == ES_EVENT_TYPE_NOTIFY_EXIT)
    e.type = CONT_EXIT;
  else
    return;
  enqueue(e);
}
static bool catalog_match(char catalog[MAX_CATALOG][PATH_MAX], size_t count,
                          const char *path) {
  for (size_t i = 0; i < count; i++)
    if (strcmp(catalog[i], path) == 0)
      return true;
  return false;
}
typedef struct {
  size_t added, read_failures, changed;
  bool unavailable, truncated;
} snapshot_stats_t;
static snapshot_stats_t snapshot(continuous_state_t *s,
                                 char catalog[MAX_CATALOG][PATH_MAX],
                                 size_t catalog_count, uint64_t *begin,
                                 uint64_t *end) {
  snapshot_stats_t stats = {0};
  *begin = mach_absolute_time();
  int needed = proc_listallpids(NULL, 0);
  if (needed <= 0) {
    *end = mach_absolute_time();
    stats.unavailable = true;
    return stats;
  }
  int cap = needed + 32;
  if (cap > 4096)
    cap = 4096;
  pid_t *pids = calloc((size_t)cap, sizeof(pid_t));
  if (!pids) {
    stats.unavailable = true;
    *end = mach_absolute_time();
    return stats;
  }
  int found = proc_listallpids(pids, cap * (int)sizeof(pid_t));
  if (found <= 0)
    stats.unavailable = true;
  if (found >= cap)
    stats.truncated = true;
  for (int i = 0; i < found && i < cap; i++) {
    struct proc_bsdinfo a = {0}, b = {0};
    char pa[PROC_PIDPATHINFO_MAXSIZE] = {0}, pb[PROC_PIDPATHINFO_MAXSIZE] = {0};
    pid_t pid = pids[i];
    if (pid <= 0)
      continue;
    if (proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &a, sizeof(a)) != sizeof(a) ||
        a.pbi_pid != (uint32_t)pid || proc_pidpath(pid, pa, sizeof(pa)) <= 0 ||
        proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &b, sizeof(b)) != sizeof(b) ||
        b.pbi_pid != (uint32_t)pid || proc_pidpath(pid, pb, sizeof(pb)) <= 0) {
      stats.read_failures++;
      continue;
    }
    if (a.pbi_start_tvsec != b.pbi_start_tvsec ||
        a.pbi_start_tvusec != b.pbi_start_tvusec || a.pbi_ppid != b.pbi_ppid ||
        strcmp(pa, pb) != 0) {
      stats.changed++;
      continue;
    }
    if (catalog_match(catalog, catalog_count, pa)) {
      uint64_t finish = mach_absolute_time();
      uint64_t start =
          (uint64_t)a.pbi_start_tvsec * 1000000 + a.pbi_start_tvusec;
      if (continuous_add_candidate(s, pid, start, pa, *begin, finish))
        stats.added++;
    }
  }
  free(pids);
  *end = mach_absolute_time();
  return stats;
}
static NSDictionary *identity_json(cont_identity_t i, const char *p,
                                   bool complete) {
  return @{
    @"pid" : @(i.pid),
    @"pidversion" : @(i.pidversion),
    @"start_time_us" : @(i.start_us),
    @"valid" : @(i.valid),
    @"path" : [NSString stringWithUTF8String:p ?: ""] ?: @"",
    @"path_complete" : @(complete)
  };
}
static bool emit(bounded_log_t *log, NSDictionary *object) {
  NSData *data = [NSJSONSerialization dataWithJSONObject:object
                                                 options:0
                                                   error:nil];
  if (!data || data.length + 1 > LOG_RECORD_MAX)
    return false;
  unsigned char record[LOG_RECORD_MAX];
  memcpy(record, data.bytes, data.length);
  record[data.length] = '\n';
  return bounded_log_enqueue(log, record, data.length + 1);
}
static bool log_event(bounded_log_t *log, NSString *session,
                      const cont_event_t *e, cont_result_t r,
                      continuous_state_t *s, bool replay) {
  @autoreleasepool {
    return emit(
        log, @{
          @"event" : @"continuous_attribution",
          @"monitor_session" : session,
          @"source" : @"es_notify",
          @"replay" : @(replay),
          @"event_type" : @(e->type),
          @"message_version" : @(e->version),
          @"seq_num" : @(e->seq_num),
          @"global_seq_num" : @(e->global_seq_num),
          @"mach_time" : @(e->mach_time),
          @"time_unix_ns" : @(e->time_unix_ns),
          @"subject" : identity_json(e->subject, e->subject_path,
                                     e->subject_path_complete),
          @"target" :
              identity_json(e->target, e->target_path, e->target_path_complete),
          @"parent_link_valid" : @(e->parent_link_valid),
          @"attribution" :
              [NSString stringWithUTF8String:continuous_kind_name(r.kind)],
          @"root_id" : @(r.root_id),
          @"root_identity" : identity_json(r.root, "", true),
          @"coverage" : continuous_healthy(s) ? @"complete" : @"degraded",
          @"coverage_epoch" : @(continuous_epoch(s)),
          @"session_semantics" : @"unknown",
          @"tool_semantics" : @"unknown"
        });
  }
}
int main(int argc, char **argv) {
  @autoreleasepool {
    if (argc < 6 || strcmp(argv[1], "--ready") ||
        strcmp(argv[3], "--duration")) {
      fprintf(stderr,
              "usage: %s --ready PATH --duration SECONDS "
              "[--health-interval SECONDS] CATALOG_PATH...\n",
              argv[0]);
      return 64;
    }
    char *duration_end = NULL;
    long duration_value = strtol(argv[4], &duration_end, 10);
    if (!duration_end || *duration_end != '\0' || duration_value < 1 ||
        duration_value > 86400)
      return 64;
    int duration = (int)duration_value;
    int catalog_start = 5;
    int health_interval = 0;
    if (argc >= 7 && !strcmp(argv[5], "--health-interval")) {
      char *health_end = NULL;
      long health_value = strtol(argv[6], &health_end, 10);
      if (!health_end || *health_end != '\0' || health_value < 1 ||
          health_value > 60)
        return 64;
      health_interval = (int)health_value;
      catalog_start = 7;
    }
    if (argc <= catalog_start || argc - catalog_start > MAX_CATALOG)
      return 64;
    char catalog[MAX_CATALOG][PATH_MAX] = {{0}};
    size_t catalog_count = 0;
    for (int i = catalog_start; i < argc; i++) {
      if (!realpath(argv[i], catalog[catalog_count])) {
        perror("catalog realpath");
        return 66;
      }
      catalog_count++;
    }
    NSString *uuid = [NSUUID UUID].UUIDString;
    const char *session = uuid.UTF8String;
    continuous_state_t *s = continuous_create(session);
    if (!s)
      return 70;
    for (size_t i = 0; i < catalog_count; i++)
      if (!continuous_add_catalog(s, catalog[i])) {
        fprintf(stderr, "catalog rejected\n");
        continuous_destroy(s);
        return 65;
      }
    bounded_log_t *log =
        bounded_log_create(STDOUT_FILENO, LOG_CAPACITY, LOG_RECORD_MAX);
    if (!log) {
      fprintf(stderr, "bounded log initialization failed\n");
      continuous_destroy(s);
      return 70;
    }
    signal(SIGINT, stop_handler);
    signal(SIGTERM, stop_handler);
    signal(SIGPIPE, SIG_IGN);
    es_client_t *client = NULL;
    es_new_client_result_t created =
        es_new_client(&client, ^(es_client_t *c, const es_message_t *m) {
          (void)c;
          capture(m);
        });
    if (created != ES_NEW_CLIENT_RESULT_SUCCESS) {
      fprintf(stderr, "es_new_client failed: %d\n", created);
      bounded_log_shutdown(log, 1000);
      bounded_log_destroy(log);
      continuous_destroy(s);
      return 77;
    }
    es_event_type_t events[] = {ES_EVENT_TYPE_NOTIFY_FORK,
                                ES_EVENT_TYPE_NOTIFY_EXEC,
                                ES_EVENT_TYPE_NOTIFY_EXIT};
    if (es_subscribe(client, events, 3) != ES_RETURN_SUCCESS) {
      es_delete_client(client);
      bounded_log_shutdown(log, 1000);
      bounded_log_destroy(log);
      continuous_destroy(s);
      return 78;
    }
    int ready = open(argv[2], O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (ready < 0) {
      perror("ready");
      es_delete_client(client);
      bounded_log_shutdown(log, 1000);
      bounded_log_destroy(log);
      continuous_destroy(s);
      return 73;
    }
    close(ready);
#ifdef CONTINUOUS_FAULT_BUILD
    for (uint32_t waited_ms = 0; waited_ms < FAULT_HOLD_MS;
         waited_ms += 10) {
#ifdef FAULT_WAIT_OVERFLOW
      if (atomic_load(&g_overflow) > 0)
        break;
#else
      if (queued_count() > 0)
        break;
#endif
      usleep(10000);
    }
#endif
    uint64_t begin = 0, end = 0;
    snapshot_stats_t stats = snapshot(s, catalog, catalog_count, &begin, &end);
    NSString *snapshotCoverage = (stats.unavailable || stats.truncated ||
                                  stats.read_failures || stats.changed)
                                     ? @"partial"
                                     : @"complete";
    bool log_failed = !emit(
        log, @{
          @"event" : @"snapshot_window",
          @"monitor_session" : uuid,
          @"begin_mach" : @(begin),
          @"end_mach" : @(end),
          @"candidate_end_semantics" :
              @"each candidate is eligible only after its "
              @"individual final libproc read",
          @"candidates" : @(stats.added),
          @"read_failures" : @(stats.read_failures),
          @"changed" : @(stats.changed),
          @"unavailable" : @(stats.unavailable),
          @"truncated" : @(stats.truncated),
          @"snapshot_coverage" : snapshotCoverage,
          @"buffer_capacity" : @(EVENT_CAPACITY)
#ifdef CONTINUOUS_FAULT_BUILD
              ,
          @"test_only" : @YES,
          @"test_mode" : @FAULT_MODE,
          @"hold_ms" : @(FAULT_HOLD_MS)
#endif
        });
    if (log_failed)
      continuous_degrade(s, "log_output_failure");
    uint64_t overflow_seen = 0;
    struct timespec started;
    clock_gettime(CLOCK_MONOTONIC, &started);
    time_t next_health = started.tv_sec;
    size_t replay_remaining = queued_count();
    while (!g_stop) {
      struct timespec now;
      clock_gettime(CLOCK_MONOTONIC, &now);
      if (now.tv_sec - started.tv_sec >= duration)
        break;
      uint64_t ov = atomic_load(&g_overflow);
      if (ov != overflow_seen) {
        continuous_degrade(s, "event_buffer_overflow");
        discard_queued_events();
        replay_remaining = 0;
        overflow_seen = ov;
      }
      bounded_log_stats_t live_log_stats = bounded_log_stats(log);
      if ((live_log_stats.fatal || live_log_stats.dropped ||
           live_log_stats.errors) &&
          !log_failed) {
        continuous_degrade(s, "log_output_failure");
        log_failed = true;
      }
      if (health_interval && now.tv_sec >= next_health) {
        @autoreleasepool {
          bounded_log_stats_t health_log = bounded_log_stats(log);
          if (!emit(log, @{
              @"event" : @"observer_health",
              @"monitor_session" : uuid,
              @"coverage" : continuous_healthy(s) ? @"complete" : @"degraded",
              @"coverage_epoch" : @(continuous_epoch(s)),
              @"reason" : [NSString stringWithUTF8String:continuous_last_reason(s)],
              @"snapshot_coverage" : snapshotCoverage,
              @"received" : @(atomic_load(&g_received)),
              @"processed" : @(atomic_load(&g_processed)),
              @"overflow" : @(atomic_load(&g_overflow)),
              @"event_remaining" : @(queued_count()),
              @"log_dropped" : @(health_log.dropped),
              @"log_errors" : @(health_log.errors),
              @"unix_ns" : @(unix_ns((struct timespec){.tv_sec = time(NULL)}))
              }) &&
              !log_failed) {
            continuous_degrade(s, "log_output_failure");
            log_failed = true;
          }
        }
        next_health = now.tv_sec + health_interval;
      }
      cont_event_t e;
      size_t drained = 0;
      while (drained < 512 && dequeue(&e)) {
        cont_result_t r = continuous_apply(s, &e);
        bool replay = replay_remaining > 0;
        if (!log_event(log, uuid, &e, r, s, replay) && !log_failed) {
          continuous_degrade(s, "log_output_failure");
          log_failed = true;
        }
        atomic_fetch_add(&g_processed, 1);
        if (replay)
          replay_remaining--;
        drained++;
        if (g_stop)
          break;
      }
      if (!drained)
        usleep(20000);
    }
    es_unsubscribe_all(client);
    es_delete_client(client);
    uint64_t ov = atomic_load(&g_overflow);
    if (ov != overflow_seen) {
      continuous_degrade(s, "event_buffer_overflow");
      discard_queued_events();
    }
    overflow_seen = ov;
    cont_event_t e;
    size_t final = 0;
    while (final < EVENT_CAPACITY && dequeue(&e)) {
      cont_result_t r = continuous_apply(s, &e);
      if (!log_event(log, uuid, &e, r, s, false) && !log_failed) {
        continuous_degrade(s, "log_output_failure");
        log_failed = true;
      }
      atomic_fetch_add(&g_processed, 1);
      final++;
    }
    ov = atomic_load(&g_overflow);
    if (ov != overflow_seen) {
      continuous_degrade(s, "event_buffer_overflow");
      overflow_seen = ov;
    }
    bounded_log_stats_t log_stats = bounded_log_shutdown(log, 2000);
    if ((log_stats.dropped || log_stats.errors || log_stats.shutdown_timeout) &&
        !log_failed) {
      continuous_degrade(s, "log_output_failure");
      log_failed = true;
    }
    fprintf(
        stderr,
        "SUMMARY monitor_session=%s coverage=%s snapshot_coverage=%s "
        "epoch=%llu gaps=%llu overflow=%llu reason=%s received=%llu "
        "enqueued=%llu processed=%llu event_discarded=%llu "
        "ring_high_water=%llu "
        "event_remaining=%zu log_enqueued=%llu log_written=%llu "
        "log_unconfirmed=%llu log_dropped=%llu log_errors=%llu "
        "log_high_water=%llu "
        "log_remaining=%llu log_shutdown_timeout=%s\n",
        session, continuous_healthy(s) ? "complete" : "degraded",
        snapshotCoverage.UTF8String, (unsigned long long)continuous_epoch(s),
        (unsigned long long)continuous_gap_count(s),
        (unsigned long long)atomic_load(&g_overflow), continuous_last_reason(s),
        (unsigned long long)atomic_load(&g_received),
        (unsigned long long)atomic_load(&g_event_enqueued),
        (unsigned long long)atomic_load(&g_processed),
        (unsigned long long)atomic_load(&g_event_discarded),
        (unsigned long long)atomic_load(&g_ring_high_water), queued_count(),
        (unsigned long long)log_stats.enqueued,
        (unsigned long long)log_stats.written,
        (unsigned long long)log_stats.unconfirmed,
        (unsigned long long)log_stats.dropped,
        (unsigned long long)log_stats.errors,
        (unsigned long long)log_stats.high_water,
        (unsigned long long)log_stats.remaining,
        log_stats.shutdown_timeout ? "true" : "false");
    bool successful = continuous_healthy(s) && !log_stats.unconfirmed &&
                      !log_stats.dropped &&
                      !log_stats.errors && !log_stats.shutdown_timeout &&
                      atomic_load(&g_overflow) == 0 && queued_count() == 0;
    bounded_log_destroy(log);
    continuous_destroy(s);
    return successful ? 0 : 74;
  }
}
