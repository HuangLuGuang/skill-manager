#include "continuous_state.h"
#include <stdlib.h>
#include <string.h>

#define CONT_CAPACITY 4096
#define CATALOG_CAPACITY 32
typedef struct {
  bool used;
  cont_identity_t id;
  cont_result_t result;
} process_slot_t;
typedef struct {
  bool used;
  pid_t pid;
  uint64_t start_us;
  uint64_t begin_mach, end_mach;
  char path[CONT_PATH_MAX];
} candidate_t;
struct continuous_state {
  char session_id[64];
  char catalog[CATALOG_CAPACITY][CONT_PATH_MAX];
  size_t catalog_count;
  candidate_t candidates[CONT_CAPACITY];
  process_slot_t processes[CONT_CAPACITY];
  uint64_t next_root, last_global, last_by_type[4], epoch, gaps;
  bool healthy, seen_global, seen_type[4];
  char last_reason[64];
};
static bool id_equal(cont_identity_t a, cont_identity_t b) {
  return a.valid && b.valid && a.pid == b.pid && a.pidversion == b.pidversion &&
         a.start_us == b.start_us;
}
static cont_result_t unknown(void) { return (cont_result_t){0}; }
static process_slot_t *find(continuous_state_t *s, cont_identity_t id) {
  for (size_t i = 0; i < CONT_CAPACITY; i++)
    if (s->processes[i].used && id_equal(s->processes[i].id, id))
      return &s->processes[i];
  return NULL;
}
static process_slot_t *vacant(continuous_state_t *s) {
  for (size_t i = 0; i < CONT_CAPACITY; i++)
    if (!s->processes[i].used)
      return &s->processes[i];
  return NULL;
}
static cont_result_t put(continuous_state_t *s, cont_identity_t id,
                         cont_result_t r) {
  process_slot_t *p = find(s, id);
  if (!p)
    p = vacant(s);
  if (!p) {
    continuous_degrade(s, "process_capacity");
    return unknown();
  }
  *p = (process_slot_t){true, id, r};
  return r;
}
static void remove_id(continuous_state_t *s, cont_identity_t id) {
  process_slot_t *p = find(s, id);
  if (p)
    p->used = false;
}
static bool catalog_match(continuous_state_t *s, const char *path) {
  for (size_t i = 0; i < s->catalog_count; i++)
    if (strcmp(s->catalog[i], path) == 0)
      return true;
  return false;
}
static candidate_t *candidate(continuous_state_t *s, cont_identity_t id,
                              const char *path, uint64_t event_mach) {
  for (size_t i = 0; i < CONT_CAPACITY; i++)
    if (s->candidates[i].used && s->candidates[i].pid == id.pid &&
        s->candidates[i].start_us == id.start_us &&
        event_mach > s->candidates[i].end_mach &&
        strcmp(s->candidates[i].path, path) == 0)
      return &s->candidates[i];
  return NULL;
}
static void remove_candidates(continuous_state_t *s, cont_identity_t id) {
  for (size_t i = 0; i < CONT_CAPACITY; i++)
    if (s->candidates[i].used && s->candidates[i].pid == id.pid &&
        s->candidates[i].start_us == id.start_us)
      s->candidates[i].used = false;
}
continuous_state_t *continuous_create(const char *session_id) {
  continuous_state_t *s = calloc(1, sizeof(*s));
  if (s) {
    s->healthy = true;
    s->next_root = 1;
    strlcpy(s->session_id, session_id, sizeof(s->session_id));
  }
  return s;
}
void continuous_destroy(continuous_state_t *s) { free(s); }
bool continuous_add_catalog(continuous_state_t *s, const char *path) {
  if (s->catalog_count >= CATALOG_CAPACITY || strlen(path) >= CONT_PATH_MAX)
    return false;
  strlcpy(s->catalog[s->catalog_count++], path, CONT_PATH_MAX);
  return true;
}
bool continuous_add_candidate(continuous_state_t *s, pid_t pid, uint64_t start,
                              const char *path, uint64_t begin, uint64_t end) {
  if (!catalog_match(s, path) || begin > end)
    return false;
  for (size_t i = 0; i < CONT_CAPACITY; i++)
    if (!s->candidates[i].used) {
      s->candidates[i] = (candidate_t){.used = true,
                                       .pid = pid,
                                       .start_us = start,
                                       .begin_mach = begin,
                                       .end_mach = end};
      strlcpy(s->candidates[i].path, path, CONT_PATH_MAX);
      return true;
    }
  continuous_degrade(s, "candidate_capacity");
  return false;
}
void continuous_degrade(continuous_state_t *s, const char *reason) {
  s->healthy = false;
  s->epoch++;
  s->gaps++;
  strlcpy(s->last_reason, reason, sizeof(s->last_reason));
  memset(s->processes, 0, sizeof(s->processes));
  memset(s->candidates, 0, sizeof(s->candidates));
}
static bool sequence_ok(continuous_state_t *s, const cont_event_t *e) {
  if (e->version < 4 || e->type < 1 || e->type > 3) {
    continuous_degrade(s, "missing_v4_sequence");
    return false;
  }
  if (s->seen_global && e->global_seq_num != s->last_global + 1) {
    bool forward = e->global_seq_num > s->last_global;
    continuous_degrade(s, forward ? "global_gap"
                                  : "global_duplicate_or_out_of_order");
    if (forward) {
      s->last_global = e->global_seq_num;
      s->last_by_type[e->type] = e->seq_num;
      s->seen_type[e->type] = true;
    }
    return false;
  }
  if (s->seen_type[e->type] && e->seq_num != s->last_by_type[e->type] + 1) {
    bool forward = e->seq_num > s->last_by_type[e->type];
    continuous_degrade(s,
                       forward ? "type_gap" : "type_duplicate_or_out_of_order");
    s->last_global = e->global_seq_num;
    s->seen_global = true;
    if (forward)
      s->last_by_type[e->type] = e->seq_num;
    return false;
  }
  s->last_global = e->global_seq_num;
  s->seen_global = true;
  s->last_by_type[e->type] = e->seq_num;
  s->seen_type[e->type] = true;
  return true;
}
cont_result_t continuous_apply(continuous_state_t *s, const cont_event_t *e) {
  if (!sequence_ok(s, e))
    return unknown();
  if (!e->subject.valid || (e->type != CONT_EXIT && !e->target.valid) ||
      (e->type == CONT_FORK && !e->parent_link_valid)) {
    continuous_degrade(s, "missing_or_invalid_identity_link");
    return unknown();
  }
  if (!e->subject_path_complete ||
      (e->type != CONT_EXIT && !e->target_path_complete)) {
    continuous_degrade(s, "truncated_executable_path");
    return unknown();
  }
  if (e->type == CONT_EXIT) {
    cont_result_t r = continuous_lookup(s, e->subject);
    remove_id(s, e->subject);
    remove_candidates(s, e->subject);
    return r;
  }
  if (e->type == CONT_EXEC) {
    cont_result_t before = continuous_lookup(s, e->subject);
    remove_id(s, e->subject);
    remove_candidates(s, e->subject);
    if (before.kind != CONT_UNKNOWN) {
      before.kind = CONT_CONFIRMED_DESCENDANT;
      return put(s, e->target, before);
    }
    if (catalog_match(s, e->target_path)) {
      cont_result_t r = {CONT_CONFIRMED_ROOT, s->next_root++, e->target};
      return put(s, e->target, r);
    }
    return unknown();
  }
  cont_result_t parent = continuous_lookup(s, e->subject);
  candidate_t *c = NULL;
  if (parent.kind == CONT_UNKNOWN &&
      (c = candidate(s, e->subject, e->subject_path, e->mach_time))) {
    parent = (cont_result_t){CONT_CONFIRMED_ROOT, s->next_root++, e->subject};
    c->used = false;
    parent = put(s, e->subject, parent);
  }
  if (parent.kind != CONT_UNKNOWN) {
    cont_result_t child = parent;
    child.kind = CONT_CONFIRMED_DESCENDANT;
    return put(s, e->target, child);
  }
  return unknown();
}
cont_result_t continuous_lookup(continuous_state_t *s, cont_identity_t id) {
  process_slot_t *p = find(s, id);
  return p ? p->result : unknown();
}
bool continuous_healthy(const continuous_state_t *s) { return s->healthy; }
uint64_t continuous_epoch(const continuous_state_t *s) { return s->epoch; }
uint64_t continuous_gap_count(const continuous_state_t *s) { return s->gaps; }
const char *continuous_kind_name(cont_kind_t k) {
  return k == CONT_CONFIRMED_ROOT         ? "es_confirmed_root"
         : k == CONT_CONFIRMED_DESCENDANT ? "es_confirmed_descendant"
                                          : "unknown";
}
const char *continuous_last_reason(const continuous_state_t *s) {
  return s->last_reason;
}
