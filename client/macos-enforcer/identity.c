#include "identity.h"
#include <stdlib.h>
#include <string.h>

struct aidr_processes {
  aidr_attribution slots[AIDR_PROCESS_CAPACITY];
  uint64_t gaps;
  size_t count;
};
static aidr_attribution unknown(void) { return (aidr_attribution){0}; }
bool aidr_identity_equal(aidr_identity a, aidr_identity b) {
  return a.valid && b.valid && a.token[5] == b.token[5] &&
         a.token[7] == b.token[7] && a.start_us == b.start_us;
}
aidr_processes *aidr_processes_create(void) { return calloc(1,sizeof(aidr_processes)); }
void aidr_processes_destroy(aidr_processes *s) { free(s); }
static aidr_attribution *find(aidr_processes *s, aidr_identity key) {
  for (size_t i=0;i<AIDR_PROCESS_CAPACITY;i++)
    if (s->slots[i].kind && aidr_identity_equal(s->slots[i].process,key)) return &s->slots[i];
  return NULL;
}
aidr_attribution aidr_process_lookup(aidr_processes *s, aidr_identity key) {
  aidr_attribution *p=find(s,key); return p ? *p : unknown();
}
void aidr_process_gap(aidr_processes *s) {
  memset(s->slots,0,sizeof(s->slots));s->count=0;s->gaps++;
}
static aidr_attribution put(aidr_processes *s, aidr_attribution value) {
  if (!value.process.valid || !value.process.start_us || !value.process.token[5]) return unknown();
  aidr_attribution *p=find(s,value.process);
  if (p) { *p=value;return value; }
  for (size_t i=0;i<AIDR_PROCESS_CAPACITY;i++) if (!s->slots[i].kind) {
    s->slots[i]=value;s->count++;return value;
  }
  aidr_process_gap(s);return unknown();
}
aidr_attribution aidr_process_fork(aidr_processes *s, aidr_identity parent, aidr_identity child) {
  aidr_attribution result=aidr_process_lookup(s,parent);
  if (!result.kind) return unknown();
  result.process=child;result.kind=2;return put(s,result);
}
void aidr_process_exit(aidr_processes *s, aidr_identity key) {
  aidr_attribution *p=find(s,key);if (p) {memset(p,0,sizeof(*p));s->count--;}
}
aidr_attribution aidr_process_exec(aidr_processes *s, aidr_identity before, aidr_identity after, unsigned registered_scope) {
  aidr_attribution result=aidr_process_lookup(s,before);
  aidr_process_exit(s,before);
  if (result.kind) { result.process=after;return put(s,result); }
  if (registered_scope>0 && registered_scope<=32) return put(s,(aidr_attribution){after,after,1,registered_scope});
  return unknown();
}
void aidr_process_remap_scopes(aidr_processes *s,const unsigned mapping[32]) {
  for(size_t i=0;i<AIDR_PROCESS_CAPACITY;i++)if(s->slots[i].kind){
    unsigned scope=s->slots[i].scope;
    unsigned next=scope>0 && scope<=32?mapping[scope-1]:0;
    if(!next || next>32){memset(&s->slots[i],0,sizeof(s->slots[i]));s->count--;}
    else s->slots[i].scope=next;
  }
}
uint64_t aidr_process_gaps(aidr_processes *s) {return s->gaps;}
size_t aidr_process_count(aidr_processes *s) {return s->count;}
