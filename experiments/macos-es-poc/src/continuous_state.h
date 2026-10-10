#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

#define CONT_PATH_MAX 1024
typedef struct {
  pid_t pid;
  int pidversion;
  uint64_t start_us;
  bool valid;
} cont_identity_t;
typedef enum { CONT_FORK = 1, CONT_EXEC = 2, CONT_EXIT = 3 } cont_event_type_t;
typedef enum {
  CONT_UNKNOWN = 0,
  CONT_CONFIRMED_ROOT = 1,
  CONT_CONFIRMED_DESCENDANT = 2
} cont_kind_t;
typedef struct {
  cont_event_type_t type;
  uint32_t version;
  uint64_t seq_num;
  uint64_t global_seq_num;
  uint64_t time_unix_ns;
  uint64_t mach_time;
  bool parent_link_valid;
  bool subject_path_complete;
  bool target_path_complete;
  cont_identity_t subject;
  cont_identity_t target;
  char subject_path[CONT_PATH_MAX];
  char target_path[CONT_PATH_MAX];
} cont_event_t;
typedef struct {
  cont_kind_t kind;
  uint64_t root_id;
  cont_identity_t root;
} cont_result_t;
typedef struct continuous_state continuous_state_t;

continuous_state_t *continuous_create(const char *session_id);
void continuous_destroy(continuous_state_t *state);
bool continuous_add_catalog(continuous_state_t *state, const char *path);
bool continuous_add_candidate(continuous_state_t *state, pid_t pid,
                              uint64_t start_us, const char *path,
                              uint64_t sample_begin_mach,
                              uint64_t sample_end_mach);
cont_result_t continuous_apply(continuous_state_t *state,
                               const cont_event_t *event);
cont_result_t continuous_lookup(continuous_state_t *state,
                                cont_identity_t identity);
void continuous_degrade(continuous_state_t *state, const char *reason);
bool continuous_healthy(const continuous_state_t *state);
uint64_t continuous_epoch(const continuous_state_t *state);
uint64_t continuous_gap_count(const continuous_state_t *state);
const char *continuous_kind_name(cont_kind_t kind);
const char *continuous_last_reason(const continuous_state_t *state);
