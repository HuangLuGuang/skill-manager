#include "src/bounded_log.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static void fill_pipe(int fd) {
  int flags = fcntl(fd, F_GETFL);
  assert(flags >= 0 && fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0);
  char block[4096] = {0};
  while (write(fd, block, sizeof(block)) > 0) {
  }
  assert(errno == EAGAIN || errno == EWOULDBLOCK);
}

int main(void) {
  signal(SIGPIPE, SIG_IGN);
  int normal[2];
  assert(pipe(normal) == 0);
  bounded_log_t *log = bounded_log_create(normal[1], 4, 64);
  assert(log && bounded_log_enqueue(log, "one\n", 4));
  bounded_log_stats_t stats = bounded_log_shutdown(log, 1000);
  assert(stats.written == 1 && stats.dropped == 0 && stats.errors == 0);
  char output[16] = {0};
  assert(read(normal[0], output, sizeof(output)) == 4);
  assert(strcmp(output, "one\n") == 0);
  bounded_log_destroy(log);
  close(normal[0]);
  close(normal[1]);

  int slow[2];
  assert(pipe(slow) == 0);
  fill_pipe(slow[1]);
  int slow_flags = fcntl(slow[1], F_GETFL);
  assert(slow_flags >= 0 &&
         fcntl(slow[1], F_SETFL, slow_flags & ~O_NONBLOCK) == 0);
  log = bounded_log_create(slow[1], 2, 16384);
  assert(log);
  char large[16384] = {0};
  bool rejected = false;
  for (int i = 0; i < 100; i++)
    if (!bounded_log_enqueue(log, large, sizeof(large))) {
      rejected = true;
      break;
    }
  assert(rejected);
  stats = bounded_log_shutdown(log, 100);
  assert(stats.shutdown_timeout && stats.dropped >= 1 && stats.remaining == 0);
  bounded_log_destroy(log);
  close(slow[0]);
  close(slow[1]);

  int broken[2];
  assert(pipe(broken) == 0);
  close(broken[0]);
  log = bounded_log_create(broken[1], 2, 64);
  assert(log);
  assert(bounded_log_enqueue(log, "broken\n", 7));
  usleep(100000);
  stats = bounded_log_shutdown(log, 1000);
  assert(stats.fatal && stats.errors == 1 && stats.dropped >= 1);
  bounded_log_destroy(log);
  close(broken[1]);

  int sink = open("/dev/null", O_WRONLY);
  assert(sink >= 0);
  log = bounded_log_create(sink, 2, 64);
  assert(log);
  assert(bounded_log_enqueue(log, "unconfirmed\n", 12));
  bounded_log_test_kill_writer(log);
  usleep(50000);
  stats = bounded_log_stats(log);
  assert(stats.fatal && stats.errors >= 1 && stats.unconfirmed == 1);
  stats = bounded_log_shutdown(log, 1000);
  assert(stats.fatal && stats.errors >= 1);
  bounded_log_destroy(log);
  close(sink);
  puts("bounded log tests passed");
  return 0;
}
