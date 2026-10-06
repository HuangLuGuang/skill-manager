#include <errno.h>
#include <unistd.h>

static int injected_output_fd = -1;
static ssize_t (*real_write_fn)(int, const void *, size_t) = write;
static ssize_t injected_write(int fd, const void *data, size_t length) {
  if (fd == injected_output_fd) {
    errno = ENOSPC;
    return -1;
  }
  return real_write_fn(fd, data, length);
}

#define write injected_write
#define BOUNDED_LOG_TESTING 1
#include "src/bounded_log.c"
#undef write

#include <assert.h>
#include <fcntl.h>
#include <stdio.h>

int main(void) {
  int sink = open("/dev/null", O_WRONLY);
  assert(sink >= 0);
  injected_output_fd = sink;
  bounded_log_t *log = bounded_log_create(sink, 4, 128);
  assert(log);
  assert(bounded_log_enqueue(log, "enospc\n", 7));
  usleep(100000);
  bounded_log_stats_t stats = bounded_log_shutdown(log, 1000);
  assert(stats.fatal);
  assert(stats.errors >= 1);
  assert(stats.written == 0);
  assert(stats.unconfirmed == 1);
  assert(stats.dropped >= 1);
  bounded_log_destroy(log);
  close(sink);
  puts("bounded log ENOSPC write seam passed");
  return 0;
}
