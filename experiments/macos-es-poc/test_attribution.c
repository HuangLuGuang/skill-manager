#include "src/attribution.h"
#include <assert.h>
#include <stdio.h>
int main(void) {
    attribution_table_t *t=attribution_create(); assert(t);
    process_key_t r1={10,1}, r2={20,1}, c1={11,1}, c1x={11,2}, orphan={99,1};
    attribution_t a1=attribution_register_root(t,r1), a2=attribution_register_root(t,r2);
    assert(a1.root_id!=a2.root_id && a1.kind==ATTR_DIRECT && a2.kind==ATTR_DIRECT);
    assert(attribution_fork(t,r1,c1).root_id==a1.root_id);
    assert(attribution_exec(t,c1,c1x).root_id==a1.root_id && attribution_lookup(t,c1).kind==ATTR_UNKNOWN);
    attribution_exit(t,r1); assert(attribution_lookup(t,c1x).root_id==a1.root_id);
    assert(attribution_lookup(t,orphan).kind==ATTR_UNKNOWN);
    assert(attribution_exec(t,(process_key_t){11,1},(process_key_t){11,3}).kind==ATTR_UNKNOWN);
    attribution_exit(t,c1x); assert(attribution_lookup(t,c1x).kind==ATTR_UNKNOWN);
    attribution_t reused=attribution_register_root(t,(process_key_t){10,9}); assert(reused.root_id!=a1.root_id);
    attribution_destroy(t); puts("attribution tests passed"); return 0;
}
