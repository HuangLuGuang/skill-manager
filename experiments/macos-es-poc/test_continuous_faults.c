#include "src/continuous_state.h"
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#define TEST_QUEUE_CAPACITY 4
typedef struct {
  cont_event_t events[TEST_QUEUE_CAPACITY];
  size_t count;
} test_queue_t;
static cont_identity_t identity(int pid, int version, uint64_t start) {
  return (cont_identity_t){pid, version, start, true};
}
static cont_event_t event(cont_event_type_t type, uint64_t seq, uint64_t global,
                          cont_identity_t subject, cont_identity_t target,
                          const char *subject_path, const char *target_path) {
  cont_event_t value = {.type = type,
                        .version = 4,
                        .seq_num = seq,
                        .global_seq_num = global,
                        .mach_time = 100 + global,
                        .parent_link_valid = true,
                        .subject_path_complete = true,
                        .target_path_complete = true,
                        .subject = subject,
                        .target = target};
  strlcpy(value.subject_path, subject_path, sizeof(value.subject_path));
  strlcpy(value.target_path, target_path, sizeof(value.target_path));
  return value;
}
static bool inject(test_queue_t *queue, cont_event_t value) {
  if (queue->count == TEST_QUEUE_CAPACITY)
    return false;
  queue->events[queue->count++] = value;
  return true;
}
static void report(const char *scenario, bool passed) {
  printf("{\"source\":\"test_injection\",\"scenario\":\"%s\",\"passed\":%s}\n",
         scenario, passed ? "true" : "false");
}
int main(void) {
  continuous_state_t *state = continuous_create("test-replay");
  assert(state);
  assert(continuous_add_catalog(state, "/agent"));
  assert(continuous_add_candidate(state, 10, 100, "/agent", 1, 50));
  cont_identity_t root = identity(10, 1, 100), child = identity(11, 1, 110),
                  child_exec = identity(11, 2, 110);
  test_queue_t queue = {0};
  assert(
      inject(&queue, event(CONT_FORK, 0, 0, root, child, "/agent", "/agent")));
  assert(inject(&queue, event(CONT_EXIT, 0, 1, root, (cont_identity_t){0},
                              "/agent", "")));
  assert(inject(
      &queue, event(CONT_EXEC, 0, 2, child, child_exec, "/agent", "/bin/sh")));
  assert(inject(&queue, event(CONT_EXIT, 1, 3, child_exec, (cont_identity_t){0},
                              "/bin/sh", "")));
  assert(!inject(&queue, event(CONT_EXIT, 2, 4, child_exec,
                               (cont_identity_t){0}, "/bin/sh", "")));
  continuous_degrade(state, "event_buffer_overflow");
  assert(!continuous_healthy(state));
  report("queue_overflow_clears_state", true);
  continuous_destroy(state);

  state = continuous_create("test-replay-ordered");
  continuous_add_catalog(state, "/agent");
  continuous_add_candidate(state, 10, 100, "/agent", 1, 50);
  for (size_t i = 0; i < queue.count; i++) {
    cont_result_t result = continuous_apply(state, &queue.events[i]);
    if (i == 0)
      assert(result.kind == CONT_CONFIRMED_DESCENDANT);
    if (i == 2 || i == 3)
      assert(result.root_id == 1);
  }
  report("snapshot_hold_replay_arrival_order", true);
  continuous_destroy(state);

  const char *names[] = {"gap", "duplicate", "out_of_order"};
  for (int scenario = 0; scenario < 3; scenario++) {
    state = continuous_create(names[scenario]);
    continuous_add_catalog(state, "/agent");
    cont_event_t first = event(CONT_EXEC, 100, 100, identity(20, 1, 200),
                               identity(20, 2, 200), "/bin/sh", "/agent");
    assert(continuous_apply(state, &first).kind == CONT_CONFIRMED_ROOT);
    uint64_t sequence = scenario == 0 ? 102 : scenario == 1 ? 100 : 90;
    cont_event_t fault =
        event(CONT_EXEC, sequence, sequence, identity(21, 1, 210),
              identity(21, 2, 210), "/bin/sh", "/agent");
    assert(continuous_apply(state, &fault).kind == CONT_UNKNOWN);
    assert(!continuous_healthy(state));
    assert(continuous_lookup(state, identity(20, 2, 200)).kind == CONT_UNKNOWN);
    report(names[scenario], true);
    continuous_destroy(state);
  }

  state = continuous_create("multi-exec");
  continuous_add_catalog(state, "/agent");
  cont_identity_t one = identity(30, 2, 300), two = identity(30, 3, 300),
                  three = identity(30, 4, 300);
  cont_event_t establish =
      event(CONT_EXEC, 0, 0, identity(30, 1, 300), one, "/bin/sh", "/agent");
  cont_result_t result = continuous_apply(state, &establish);
  assert(result.kind == CONT_CONFIRMED_ROOT);
  uint64_t root_id = result.root_id;
  cont_event_t exec2 = event(CONT_EXEC, 1, 1, one, two, "/agent", "/bin/sh");
  assert(continuous_apply(state, &exec2).root_id == root_id);
  cont_event_t exec3 =
      event(CONT_EXEC, 2, 2, two, three, "/bin/sh", "/bin/cat");
  assert(continuous_apply(state, &exec3).root_id == root_id);
  cont_event_t stale =
      event(CONT_FORK, 0, 3, one, identity(31, 1, 310), "/agent", "/bin/sh");
  assert(continuous_apply(state, &stale).kind == CONT_UNKNOWN);
  report("multi_exec_and_pidversion_reuse", true);
  continuous_destroy(state);

  state = continuous_create("restart");
  assert(continuous_lookup(state, three).kind == CONT_UNKNOWN);
  report("restart_isolation", true);
  continuous_destroy(state);
  puts("continuous fault harness passed");
  return 0;
}
