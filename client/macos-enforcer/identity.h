#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define AIDR_PROCESS_CAPACITY 4096
typedef struct { uint32_t token[8]; uint64_t start_us; bool valid; } aidr_identity;
typedef struct { aidr_identity process, root; unsigned kind, scope; } aidr_attribution;
typedef struct aidr_processes aidr_processes;

// One table belongs to exactly one boot and sensor lifetime. Callers include
// both identifiers in persisted records and reject commands for other lifetimes.
aidr_processes *aidr_processes_create(void);
void aidr_processes_destroy(aidr_processes *s);
bool aidr_identity_equal(aidr_identity a, aidr_identity b);
aidr_attribution aidr_process_lookup(aidr_processes *s, aidr_identity key);
aidr_attribution aidr_process_fork(aidr_processes *s, aidr_identity parent, aidr_identity child);
aidr_attribution aidr_process_exec(aidr_processes *s, aidr_identity before, aidr_identity after, unsigned registered_scope);
void aidr_process_remap_scopes(aidr_processes *s, const unsigned mapping[32]);
void aidr_process_exit(aidr_processes *s, aidr_identity key);
void aidr_process_gap(aidr_processes *s);
uint64_t aidr_process_gaps(aidr_processes *s);
size_t aidr_process_count(aidr_processes *s);
