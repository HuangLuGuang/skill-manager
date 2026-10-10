#include "identity.h"
#include <assert.h>
#include <stdio.h>
static aidr_identity key(uint32_t pid, uint32_t version, uint64_t start) {
  aidr_identity p={.valid=true,.start_us=start};p.token[5]=pid;p.token[7]=version;return p;
}
int main(void) {
  aidr_processes *s=aidr_processes_create();assert(s);
  aidr_identity root=key(100,1,UINT64_C(18446744073709551000));
  assert(aidr_process_exec(s,(aidr_identity){0},root,true).kind==1);
  for (unsigned i=0;i<1000;i++) {
    aidr_identity child=key(200+i,2,100+i),exec=key(200+i,3,100+i);
    assert(aidr_process_fork(s,root,child).kind==2);
    assert(aidr_identity_equal(aidr_process_exec(s,child,exec,false).root,root));
    assert(aidr_process_lookup(s,child).kind==0);
  }
  aidr_process_exit(s,root);
  assert(aidr_process_count(s)==1000);
  for (unsigned i=0;i<1000;i++) {
    aidr_identity p=key(200+i,3,100+i),reused=key(200+i,4,10000+i);
    assert(aidr_process_lookup(s,p).kind==2);
    assert(aidr_process_lookup(s,reused).kind==0);
    aidr_process_exit(s,reused);assert(aidr_process_lookup(s,p).kind==2);
    aidr_process_exit(s,p);assert(aidr_process_lookup(s,p).kind==0);
  }
  assert(aidr_process_count(s)==0);
  aidr_process_exec(s,(aidr_identity){0},root,true);
  for (unsigned i=0;i<AIDR_PROCESS_CAPACITY;i++) aidr_process_fork(s,root,key(200+i,5,100+i));
  assert(aidr_process_gaps(s)==1 && aidr_process_count(s)==0);
  assert(aidr_process_lookup(s,root).kind==0);
  aidr_process_exec(s,(aidr_identity){0},root,true);
  aidr_process_gap(s);assert(aidr_process_count(s)==0 && aidr_process_gaps(s)==2);
  aidr_process_exec(s,(aidr_identity){0},root,1);
  aidr_identity child=key(101,3,42);aidr_process_fork(s,root,child);
  unsigned mapping[32]={2};aidr_process_remap_scopes(s,mapping);
  assert(aidr_process_lookup(s,child).scope==2 && aidr_process_lookup(s,root).scope==2);
  mapping[0]=0;aidr_process_remap_scopes(s,mapping);assert(aidr_process_count(s)==0);
  aidr_processes_destroy(s);puts("PASS identity transitions, 1000 descendants, parent exit, PID reuse, bounded capacity and gap invalidation");
}
