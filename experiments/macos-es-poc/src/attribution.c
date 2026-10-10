#include "attribution.h"
#include <os/lock.h>
#include <stdlib.h>
#include <string.h>

#define ATTR_CAPACITY 4096
typedef struct { bool used; process_key_t key; attribution_t value; } slot_t;
struct attribution_table { os_unfair_lock lock; uint64_t next_root; slot_t slots[ATTR_CAPACITY]; };

static bool equal(process_key_t a, process_key_t b) { return a.pid == b.pid && a.version == b.version; }
static slot_t *find(attribution_table_t *t, process_key_t key) {
    for (size_t i = 0; i < ATTR_CAPACITY; i++) if (t->slots[i].used && equal(t->slots[i].key, key)) return &t->slots[i];
    return NULL;
}
static slot_t *vacant(attribution_table_t *t) {
    for (size_t i = 0; i < ATTR_CAPACITY; i++) if (!t->slots[i].used) return &t->slots[i];
    return NULL;
}
static attribution_t unknown(void) { return (attribution_t){.kind = ATTR_UNKNOWN}; }
static attribution_t put(attribution_table_t *t, process_key_t key, attribution_t value) {
    slot_t *slot = find(t, key); if (!slot) slot = vacant(t); if (!slot) return unknown();
    *slot = (slot_t){.used = true, .key = key, .value = value}; return value;
}
attribution_table_t *attribution_create(void) { attribution_table_t *t = calloc(1, sizeof(*t)); if (t) { t->lock = OS_UNFAIR_LOCK_INIT; t->next_root = 1; } return t; }
void attribution_destroy(attribution_table_t *t) { free(t); }
attribution_t attribution_register_root(attribution_table_t *t, process_key_t key) {
    os_unfair_lock_lock(&t->lock); attribution_t a = {.kind=ATTR_DIRECT,.root_id=t->next_root++,.root=key}; a=put(t,key,a); os_unfair_lock_unlock(&t->lock); return a;
}
attribution_t attribution_fork(attribution_table_t *t, process_key_t parent, process_key_t child) {
    os_unfair_lock_lock(&t->lock); slot_t *p=find(t,parent); attribution_t a=unknown(); if(p){a=p->value;a.kind=ATTR_INHERITED;a=put(t,child,a);} os_unfair_lock_unlock(&t->lock); return a;
}
attribution_t attribution_exec(attribution_table_t *t, process_key_t before, process_key_t after) {
    os_unfair_lock_lock(&t->lock); slot_t *old=find(t,before); attribution_t a=unknown(); if(old){a=old->value;old->used=false;a=put(t,after,a);} os_unfair_lock_unlock(&t->lock); return a;
}
void attribution_exit(attribution_table_t *t, process_key_t key) { os_unfair_lock_lock(&t->lock); slot_t *s=find(t,key); if(s)s->used=false; os_unfair_lock_unlock(&t->lock); }
attribution_t attribution_lookup(attribution_table_t *t, process_key_t key) { os_unfair_lock_lock(&t->lock); slot_t *s=find(t,key); attribution_t a=s?s->value:unknown(); os_unfair_lock_unlock(&t->lock); return a; }
const char *attribution_name(attribution_kind_t k) { return k==ATTR_DIRECT?"direct":k==ATTR_INHERITED?"inherited":"unknown"; }
