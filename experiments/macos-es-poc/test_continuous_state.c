#include "src/continuous_state.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static cont_identity_t id(int p, int v, uint64_t s) {
  return (cont_identity_t){p, v, s, true};
}
static cont_event_t ev(cont_event_type_t t, uint64_t q, uint64_t g,
                       cont_identity_t a, cont_identity_t b, const char *ap,
                       const char *bp) {
  cont_event_t e = {.type = t,
                    .version = 4,
                    .seq_num = q,
                    .global_seq_num = g,
                    .time_unix_ns = 1,
                    .mach_time = g * 10,
                    .parent_link_valid = true,
                    .subject_path_complete = true,
                    .target_path_complete = true,
                    .subject = a,
                    .target = b};
  strlcpy(e.subject_path, ap, sizeof(e.subject_path));
  strlcpy(e.target_path, bp, sizeof(e.target_path));
  return e;
}
int main(void) {
  continuous_state_t *s = continuous_create("session-a");
  assert(s);
  assert(continuous_add_catalog(s, "/agent"));
  cont_identity_t root = id(10, 1, 100), child = id(11, 1, 110),
                  childx = id(11, 2, 110), grand = id(12, 1, 120);
  assert(continuous_add_candidate(s, 10, 100, "/agent", 1, 5));
  cont_event_t f = ev(CONT_FORK, 1, 1, root, child, "/agent", "/bin/sh");
  assert(continuous_apply(s, &f).kind == CONT_CONFIRMED_DESCENDANT);
  assert(continuous_lookup(s, root).kind == CONT_CONFIRMED_ROOT);
  cont_event_t x = ev(CONT_EXEC, 1, 2, child, childx, "/bin/sh", "/bin/zsh");
  assert(continuous_apply(s, &x).kind == CONT_CONFIRMED_DESCENDANT);
  assert(continuous_lookup(s, child).kind == CONT_UNKNOWN);
  cont_event_t e =
      ev(CONT_EXIT, 1, 3, root, (cont_identity_t){0}, "/agent", "");
  continuous_apply(s, &e);
  assert(continuous_lookup(s, childx).kind == CONT_CONFIRMED_DESCENDANT);
  cont_event_t f2 = ev(CONT_FORK, 2, 4, childx, grand, "/bin/zsh", "/bin/sh");
  assert(continuous_apply(s, &f2).kind == CONT_CONFIRMED_DESCENDANT);
  cont_event_t gap =
      ev(CONT_EXIT, 2, 6, grand, (cont_identity_t){0}, "/bin/sh", "");
  assert(continuous_apply(s, &gap).kind == CONT_UNKNOWN);
  assert(!continuous_healthy(s));
  assert(continuous_lookup(s, childx).kind == CONT_UNKNOWN);
  assert(continuous_add_candidate(s, 10, 100, "/agent", 61, 65));
  cont_event_t reused =
      ev(CONT_FORK, 3, 7, id(10, 9, 100), id(13, 1, 130), "/agent", "/bin/sh");
  assert(continuous_apply(s, &reused).kind == CONT_CONFIRMED_DESCENDANT);
  cont_event_t duplicate =
      ev(CONT_EXIT, 3, 7, id(13, 1, 130), (cont_identity_t){0}, "", "");
  assert(continuous_apply(s, &duplicate).kind == CONT_UNKNOWN);
  continuous_destroy(s);
  s = continuous_create("session-b");
  continuous_add_catalog(s, "/agent");
  cont_event_t direct =
      ev(CONT_EXEC, 1, 1, id(20, 1, 200), id(20, 2, 200), "/bin/sh", "/agent");
  assert(continuous_apply(s, &direct).kind == CONT_CONFIRMED_ROOT);
  cont_event_t away =
      ev(CONT_EXEC, 2, 2, id(20, 2, 200), id(20, 3, 200), "/agent", "/bin/sh");
  assert(continuous_apply(s, &away).kind == CONT_CONFIRMED_DESCENDANT);
  cont_event_t old =
      ev(CONT_FORK, 1, 3, id(20, 2, 200), id(21, 1, 210), "/agent", "/bin/sh");
  assert(continuous_apply(s, &old).kind == CONT_UNKNOWN);
  cont_event_t missing =
      ev(CONT_EXEC, 3, 4, id(30, 1, 300), id(30, 2, 300), "/bin/sh", "/agent");
  missing.version = 3;
  assert(continuous_apply(s, &missing).kind == CONT_UNKNOWN);
  continuous_destroy(s);
  s = continuous_create("zero-seq");
  continuous_add_catalog(s, "/agent");
  cont_event_t zero =
      ev(CONT_EXEC, 0, 0, id(40, 1, 400), id(40, 2, 400), "/bin/sh", "/agent");
  assert(continuous_apply(s, &zero).kind == CONT_CONFIRMED_ROOT);
  cont_event_t badlink =
      ev(CONT_FORK, 0, 1, id(40, 2, 400), id(41, 1, 410), "/agent", "/bin/sh");
  badlink.parent_link_valid = false;
  assert(continuous_apply(s, &badlink).kind == CONT_UNKNOWN);
  assert(!continuous_healthy(s));
  continuous_destroy(s);
  s = continuous_create("ordering");
  continuous_add_catalog(s, "/agent");
  cont_event_t high = ev(CONT_EXEC, 100, 100, id(50, 1, 500), id(50, 2, 500),
                         "/bin/sh", "/agent");
  assert(continuous_apply(s, &high).kind == CONT_CONFIRMED_ROOT);
  cont_event_t low = ev(CONT_EXEC, 80, 80, id(51, 1, 510), id(51, 2, 510),
                        "/bin/sh", "/agent");
  assert(continuous_apply(s, &low).kind == CONT_UNKNOWN);
  cont_event_t low2 = ev(CONT_EXEC, 81, 81, id(52, 1, 520), id(52, 2, 520),
                         "/bin/sh", "/agent");
  assert(continuous_apply(s, &low2).kind == CONT_UNKNOWN);
  continuous_destroy(s);
  s = continuous_create("window");
  continuous_add_catalog(s, "/agent");
  continuous_add_candidate(s, 60, 600, "/agent", 100, 200);
  cont_event_t early =
      ev(CONT_FORK, 1, 1, id(60, 1, 600), id(61, 1, 610), "/agent", "/bin/sh");
  early.mach_time = 150;
  assert(continuous_apply(s, &early).kind == CONT_UNKNOWN);
  continuous_destroy(s);
  s = continuous_create("exit");
  continuous_add_catalog(s, "/agent");
  continuous_add_candidate(s, 70, 700, "/agent", 1, 5);
  cont_event_t promote =
      ev(CONT_FORK, 1, 1, id(70, 1, 700), id(71, 1, 710), "/agent", "/bin/sh");
  assert(continuous_apply(s, &promote).kind == CONT_CONFIRMED_DESCENDANT);
  cont_event_t quit =
      ev(CONT_EXIT, 1, 2, id(70, 1, 700), (cont_identity_t){0}, "", "");
  continuous_apply(s, &quit);
  cont_event_t stale =
      ev(CONT_FORK, 2, 3, id(70, 1, 700), id(72, 1, 720), "/agent", "/bin/sh");
  assert(continuous_apply(s, &stale).kind == CONT_UNKNOWN);
  continuous_degrade(s, "event_buffer_overflow");
  assert(continuous_lookup(s, id(71, 1, 710)).kind == CONT_UNKNOWN);
  continuous_destroy(s);
  s = continuous_create("candidate-exit");
  continuous_add_catalog(s, "/agent");
  continuous_add_candidate(s, 80, 800, "/agent", 1, 5);
  cont_event_t cx =
      ev(CONT_EXIT, 1, 1, id(80, 1, 800), (cont_identity_t){0}, "/agent", "");
  continuous_apply(s, &cx);
  cont_event_t cf =
      ev(CONT_FORK, 1, 2, id(80, 1, 800), id(81, 1, 810), "/agent", "/bin/sh");
  assert(continuous_apply(s, &cf).kind == CONT_UNKNOWN);
  continuous_destroy(s);
  s = continuous_create("new-session");
  assert(continuous_lookup(s, id(71, 1, 710)).kind == CONT_UNKNOWN);
  continuous_destroy(s);

  s = continuous_create("forward-gap-recovery");
  continuous_add_catalog(s, "/agent");
  cont_event_t first =
      ev(CONT_EXEC, 1, 1, id(90, 1, 900), id(90, 2, 900), "/bin/sh", "/agent");
  assert(continuous_apply(s, &first).kind == CONT_CONFIRMED_ROOT);
  cont_event_t forward =
      ev(CONT_EXEC, 3, 3, id(91, 1, 910), id(91, 2, 910), "/bin/sh", "/agent");
  assert(continuous_apply(s, &forward).kind == CONT_UNKNOWN);
  cont_event_t recovered =
      ev(CONT_EXEC, 4, 4, id(92, 1, 920), id(92, 2, 920), "/bin/sh", "/agent");
  assert(continuous_apply(s, &recovered).kind == CONT_CONFIRMED_ROOT);
  continuous_destroy(s);

  s = continuous_create("candidate-exec-invalidation");
  continuous_add_catalog(s, "/agent");
  continuous_add_candidate(s, 100, 1000, "/agent", 1, 5);
  cont_event_t unknown_exec = ev(CONT_EXEC, 1, 1, id(100, 1, 1000),
                                 id(100, 2, 1000), "/agent", "/bin/sh");
  assert(continuous_apply(s, &unknown_exec).kind == CONT_UNKNOWN);
  cont_event_t old_fork = ev(CONT_FORK, 1, 2, id(100, 1, 1000),
                             id(101, 1, 1010), "/agent", "/bin/sh");
  assert(continuous_apply(s, &old_fork).kind == CONT_UNKNOWN);
  cont_event_t truncated = ev(CONT_EXEC, 2, 3, id(102, 1, 1020),
                              id(102, 2, 1020), "/bin/sh", "/agent");
  truncated.target_path_complete = false;
  assert(continuous_apply(s, &truncated).kind == CONT_UNKNOWN);
  assert(!continuous_healthy(s));
  continuous_destroy(s);
  s = continuous_create("identity-reuse");
  continuous_add_catalog(s, "/agent");
  cont_event_t establish = ev(CONT_EXEC, 0, 0, id(200, 1, 2000),
                              id(200, 2, 2000), "/bin/sh", "/agent");
  assert(continuous_apply(s, &establish).kind == CONT_CONFIRMED_ROOT);
  cont_event_t wrong_version = ev(CONT_FORK, 0, 1, id(200, 3, 2000),
                                  id(201, 1, 2010), "/agent", "/agent");
  assert(continuous_apply(s, &wrong_version).kind == CONT_UNKNOWN);
  cont_event_t wrong_start = ev(CONT_FORK, 1, 2, id(200, 2, 2001),
                                id(202, 1, 2020), "/agent", "/agent");
  assert(continuous_apply(s, &wrong_start).kind == CONT_UNKNOWN);
  cont_event_t missing_identity = ev(CONT_FORK, 2, 3, id(200, 2, 2000),
                                     id(203, 1, 2030), "/agent", "/agent");
  missing_identity.target.valid = false;
  assert(continuous_apply(s, &missing_identity).kind == CONT_UNKNOWN);
  assert(continuous_lookup(s, id(200, 2, 2000)).kind == CONT_UNKNOWN);
  continuous_destroy(s);

  s = continuous_create("capacity-invalidation");
  continuous_add_catalog(s, "/agent");
  for (int i = 0; i < 4096; i++) {
    cont_event_t fill = ev(CONT_EXEC, i, i, id(i + 10, 1, i + 100),
                           id(i + 10, 2, i + 100), "/bin/sh", "/agent");
    assert(continuous_apply(s, &fill).kind == CONT_CONFIRMED_ROOT);
  }
  continuous_add_candidate(s, 10000, 10000, "/agent", 1, 5);
  cont_event_t full = ev(CONT_FORK, 0, 4096, id(10000, 1, 10000),
                         id(10001, 1, 10001), "/agent", "/agent");
  assert(continuous_apply(s, &full).kind == CONT_UNKNOWN);
  assert(!continuous_healthy(s));
  assert(continuous_lookup(s, id(10001, 1, 10001)).kind == CONT_UNKNOWN);
  continuous_destroy(s);
  puts("continuous state tests passed");
  return 0;
}
