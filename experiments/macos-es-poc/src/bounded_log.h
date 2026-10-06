#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct bounded_log bounded_log_t;
typedef struct {
  uint64_t enqueued, written, unconfirmed, dropped, errors, high_water,
      remaining;
  bool fatal, shutdown_timeout;
} bounded_log_stats_t;

bounded_log_t *bounded_log_create(int fd, size_t capacity, size_t max_record);
bool bounded_log_enqueue(bounded_log_t *log, const void *data, size_t length);
bounded_log_stats_t bounded_log_stats(bounded_log_t *log);
bounded_log_stats_t bounded_log_shutdown(bounded_log_t *log,
                                         uint32_t timeout_ms);
void bounded_log_destroy(bounded_log_t *log);
#ifdef BOUNDED_LOG_TESTING
void bounded_log_test_kill_writer(bounded_log_t *log);
#endif
