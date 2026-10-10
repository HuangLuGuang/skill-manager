#include "bounded_log.h"
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define STATUS_MAGIC 0x424c4f47u
typedef struct {
  uint32_t magic;
  uint64_t written, errors;
} child_status_t;
typedef struct {
  size_t length, offset;
  unsigned char *wire;
} log_record_t;
struct bounded_log {
  int data_fd, status_fd;
  pid_t writer_pid;
  size_t capacity, max_record, head, count, slot_size;
  log_record_t *records;
  unsigned char *storage;
  uint64_t enqueued, written, dropped, errors, high_water;
  bool fatal, shutdown_timeout, child_status_seen;
  bool writer_reaped;
  int writer_status;
};

static uint64_t monotonic_ms(void) {
  struct timespec value;
  clock_gettime(CLOCK_MONOTONIC, &value);
  return (uint64_t)value.tv_sec * 1000 + (uint64_t)value.tv_nsec / 1000000;
}
static bool write_all(int fd, const void *data, size_t length) {
  const unsigned char *cursor = data;
  while (length) {
    ssize_t amount = write(fd, cursor, length);
    if (amount > 0) {
      cursor += amount;
      length -= (size_t)amount;
      continue;
    }
    if (amount < 0 && errno == EINTR)
      continue;
    return false;
  }
  return true;
}
static bool read_all(int fd, void *data, size_t length) {
  unsigned char *cursor = data;
  while (length) {
    ssize_t amount = read(fd, cursor, length);
    if (amount > 0) {
      cursor += amount;
      length -= (size_t)amount;
      continue;
    }
    if (amount < 0 && errno == EINTR)
      continue;
    return false;
  }
  return true;
}
static int read_header(int fd, uint32_t *length) {
  unsigned char *cursor = (unsigned char *)length;
  size_t remaining = sizeof(*length);
  while (remaining) {
    ssize_t amount = read(fd, cursor, remaining);
    if (amount > 0) {
      cursor += amount;
      remaining -= (size_t)amount;
      continue;
    }
    if (amount == 0)
      return remaining == sizeof(*length) ? 0 : -1;
    if (errno == EINTR)
      continue;
    return -1;
  }
  return 1;
}
static void writer_process(int input, int output, int status, size_t maximum,
                           unsigned char *buffer) {
  child_status_t result = {.magic = STATUS_MAGIC};
  for (;;) {
    uint32_t length = 0;
    int header = read_header(input, &length);
    if (header == 0)
      break;
    if (header < 0 || length == 0 || length > maximum ||
        !read_all(input, buffer, length) ||
        !write_all(output, buffer, length)) {
      result.errors++;
      break;
    }
    result.written++;
  }
  write_all(status, &result, sizeof(result));
  close(input);
  close(status);
  _exit(result.errors ? 74 : 0);
}
static void collect_status(bounded_log_t *log) {
  if (log->child_status_seen || log->status_fd < 0)
    return;
  child_status_t status = {0};
  ssize_t amount = read(log->status_fd, &status, sizeof(status));
  if (amount == sizeof(status) && status.magic == STATUS_MAGIC) {
    log->written = status.written;
    log->errors += status.errors;
    log->fatal = log->fatal || status.errors > 0;
    if (status.errors && log->enqueued > status.written) {
      log->dropped += log->enqueued - status.written;
      log->count = 0;
      log->head = 0;
    }
    log->child_status_seen = true;
  } else if (amount == 0) {
    log->errors++;
    log->fatal = true;
    close(log->status_fd);
    log->status_fd = -1;
  }
}
static void flush_nonblocking(bounded_log_t *log) {
  collect_status(log);
  while (log->count && !log->fatal) {
    log_record_t *record = &log->records[log->head];
    ssize_t amount = write(log->data_fd, record->wire + record->offset,
                           record->length - record->offset);
    if (amount > 0) {
      record->offset += (size_t)amount;
      if (record->offset == record->length) {
        record->length = record->offset = 0;
        log->head = (log->head + 1) % log->capacity;
        log->count--;
      }
      continue;
    }
    if (amount < 0 && errno == EINTR)
      continue;
    if (amount < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
      return;
    log->errors++;
    log->fatal = true;
  }
}

bounded_log_t *bounded_log_create(int fd, size_t capacity, size_t max_record) {
  if (fd < 0 || !capacity || !max_record || max_record > UINT32_MAX)
    return NULL;
  int data_pipe[2], status_pipe[2];
  if (pipe(data_pipe) != 0)
    return NULL;
  if (pipe(status_pipe) != 0) {
    close(data_pipe[0]);
    close(data_pipe[1]);
    return NULL;
  }
  bounded_log_t *log = calloc(1, sizeof(*log));
  if (!log) {
    close(data_pipe[0]);
    close(data_pipe[1]);
    close(status_pipe[0]);
    close(status_pipe[1]);
    return NULL;
  }
  log->slot_size = max_record + sizeof(uint32_t);
  log->records = calloc(capacity, sizeof(*log->records));
  log->storage = calloc(capacity, log->slot_size);
  unsigned char *child_buffer = malloc(max_record);
  if (!log->records || !log->storage || !child_buffer) {
    free(child_buffer);
    bounded_log_destroy(log);
    close(data_pipe[0]);
    close(data_pipe[1]);
    close(status_pipe[0]);
    close(status_pipe[1]);
    return NULL;
  }
  for (size_t i = 0; i < capacity; i++)
    log->records[i].wire = log->storage + i * log->slot_size;
  signal(SIGPIPE, SIG_IGN);
  pid_t child = fork();
  if (child < 0) {
    free(child_buffer);
    bounded_log_destroy(log);
    close(data_pipe[0]);
    close(data_pipe[1]);
    close(status_pipe[0]);
    close(status_pipe[1]);
    return NULL;
  }
  if (child == 0) {
    close(data_pipe[1]);
    close(status_pipe[0]);
    writer_process(data_pipe[0], fd, status_pipe[1], max_record, child_buffer);
  }
  free(child_buffer);
  close(data_pipe[0]);
  close(status_pipe[1]);
  log->data_fd = data_pipe[1];
  log->status_fd = status_pipe[0];
  log->writer_pid = child;
  log->capacity = capacity;
  log->max_record = max_record;
  int flags = fcntl(log->data_fd, F_GETFL);
  if (flags < 0 || fcntl(log->data_fd, F_SETFL, flags | O_NONBLOCK) != 0) {
    bounded_log_shutdown(log, 1000);
    bounded_log_destroy(log);
    return NULL;
  }
  flags = fcntl(log->status_fd, F_GETFL);
  if (flags < 0 || fcntl(log->status_fd, F_SETFL, flags | O_NONBLOCK) != 0) {
    bounded_log_shutdown(log, 1000);
    bounded_log_destroy(log);
    return NULL;
  }
  return log;
}
bool bounded_log_enqueue(bounded_log_t *log, const void *data, size_t length) {
  if (!log || !data || !length || length > log->max_record)
    return false;
  flush_nonblocking(log);
  if (log->fatal || log->count == log->capacity) {
    log->dropped++;
    return false;
  }
  size_t index = (log->head + log->count) % log->capacity;
  log_record_t *r = &log->records[index];
  uint32_t wire_length = (uint32_t)length;
  memcpy(r->wire, &wire_length, sizeof(wire_length));
  memcpy(r->wire + sizeof(wire_length), data, length);
  r->length = sizeof(wire_length) + length;
  r->offset = 0;
  log->count++;
  log->enqueued++;
  if (log->count > log->high_water)
    log->high_water = log->count;
  flush_nonblocking(log);
  return true;
}
bounded_log_stats_t bounded_log_stats(bounded_log_t *log) {
  if (!log)
    return (bounded_log_stats_t){0};
  flush_nonblocking(log);
  return (bounded_log_stats_t){
      .enqueued = log->enqueued,
      .written = log->written,
      .unconfirmed = log->enqueued - log->written,
      .dropped = log->dropped,
      .errors = log->errors,
      .high_water = log->high_water,
      .remaining = log->count,
      .fatal = log->fatal,
      .shutdown_timeout = log->shutdown_timeout,
  };
}
bounded_log_stats_t bounded_log_shutdown(bounded_log_t *log,
                                         uint32_t timeout_ms) {
  uint64_t deadline = monotonic_ms() + timeout_ms;
  while (log->count && !log->fatal && monotonic_ms() < deadline) {
    flush_nonblocking(log);
    struct timespec pause = {0, 10000000};
    nanosleep(&pause, NULL);
  }
  if (log->count) {
    log->shutdown_timeout = true;
    log->dropped += log->count;
    log->count = 0;
  }
  if (log->data_fd >= 0) {
    close(log->data_fd);
    log->data_fd = -1;
  }
  pid_t waited = 0;
  while ((waited = waitpid(log->writer_pid, &log->writer_status, WNOHANG)) ==
             0 &&
         monotonic_ms() < deadline) {
    struct timespec pause = {0, 10000000};
    nanosleep(&pause, NULL);
  }
  if (waited == log->writer_pid)
    log->writer_reaped = true;
  else if (waited < 0) {
    log->errors++;
    log->fatal = true;
  }
  if (!log->writer_reaped && waited == 0) {
    log->shutdown_timeout = true;
    kill(log->writer_pid, SIGKILL);
    uint64_t reap_deadline = monotonic_ms() + 500;
    while ((waited = waitpid(log->writer_pid, &log->writer_status, WNOHANG)) ==
               0 &&
           monotonic_ms() < reap_deadline) {
      struct timespec pause = {0, 10000000};
      nanosleep(&pause, NULL);
    }
    if (waited == log->writer_pid)
      log->writer_reaped = true;
    else {
      log->errors++;
      log->fatal = true;
    }
  }
  collect_status(log);
  if (!log->child_status_seen || !log->writer_reaped ||
      !WIFEXITED(log->writer_status) || WEXITSTATUS(log->writer_status) != 0) {
    if (!log->child_status_seen)
      log->errors++;
    log->fatal = true;
  }
  return bounded_log_stats(log);
}
void bounded_log_destroy(bounded_log_t *log) {
  if (!log)
    return;
  if (log->data_fd > 0)
    close(log->data_fd);
  if (log->status_fd > 0)
    close(log->status_fd);
  free(log->storage);
  free(log->records);
  free(log);
}
#ifdef BOUNDED_LOG_TESTING
void bounded_log_test_kill_writer(bounded_log_t *log) {
  kill(log->writer_pid, SIGKILL);
}
#endif
