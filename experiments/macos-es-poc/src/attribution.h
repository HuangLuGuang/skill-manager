#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <sys/types.h>

typedef struct { pid_t pid; int version; } process_key_t;
typedef enum { ATTR_UNKNOWN = 0, ATTR_DIRECT = 1, ATTR_INHERITED = 2 } attribution_kind_t;
typedef struct { attribution_kind_t kind; uint64_t root_id; process_key_t root; } attribution_t;
typedef struct attribution_table attribution_table_t;

attribution_table_t *attribution_create(void);
void attribution_destroy(attribution_table_t *table);
attribution_t attribution_register_root(attribution_table_t *table, process_key_t key);
attribution_t attribution_fork(attribution_table_t *table, process_key_t parent, process_key_t child);
attribution_t attribution_exec(attribution_table_t *table, process_key_t before, process_key_t after);
void attribution_exit(attribution_table_t *table, process_key_t key);
attribution_t attribution_lookup(attribution_table_t *table, process_key_t key);
const char *attribution_name(attribution_kind_t kind);
