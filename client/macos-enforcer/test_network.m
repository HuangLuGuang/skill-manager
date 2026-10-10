// Real local sockets driven by an independent test process, without ES privileges.
#define main aidr_network_native_main
#import "enforcer.m"
#undef main
#include <assert.h>
#include <arpa/inet.h>
#include <libproc.h>
#include <mach/mach.h>
#include <sys/socket.h>
#include <unistd.h>

static aidr_identity current_identity(void){
  audit_token_t token;mach_msg_type_number_t count=TASK_AUDIT_TOKEN_COUNT;
  assert(task_info(mach_task_self(),TASK_AUDIT_TOKEN,(task_info_t)&token,&count)==KERN_SUCCESS);
  struct proc_bsdinfo info;assert(proc_pidinfo(getpid(),PROC_PIDTBSDINFO,0,&info,sizeof(info))==sizeof(info));
  aidr_identity id={.start_us=info.pbi_start_tvsec*1000000+info.pbi_start_tvusec,.valid=true};
  memcpy(id.token,token.val,sizeof(id.token));return id;
}
int main(void){@autoreleasepool {
  aidr_identity id=current_identity();assert(aidr_network_identity_matches(id));
  aidr_identity reused=id;reused.token[7]++;assert(!aidr_network_identity_matches(reused));
  reused=id;reused.start_us++;assert(!aidr_network_identity_matches(reused));
  int server=socket(AF_INET,SOCK_STREAM,0);assert(server>=0);
  struct sockaddr_in addr={.sin_family=AF_INET,.sin_addr.s_addr=htonl(INADDR_LOOPBACK)};
  assert(bind(server,(void *)&addr,sizeof(addr))==0 && listen(server,4)==0);
  socklen_t length=sizeof(addr);assert(getsockname(server,(void *)&addr,&length)==0);
  int clients[2],accepted[2];for(int i=0;i<2;i++){
    clients[i]=socket(AF_INET,SOCK_STREAM,0);assert(connect(clients[i],(void *)&addr,sizeof(addr))==0);
    accepted[i]=accept(server,NULL,NULL);assert(accepted[i]>=0);
  }
  NSString *status;NSArray *records=aidr_network_snapshot(id,&status);assert([status isEqual:@"sampled"]);
  NSMutableSet *keys=[NSMutableSet set];NSUInteger matched=0;
  for(NSDictionary *row in records)if([row[@"remote_port"] intValue]==ntohs(addr.sin_port)){
    assert([row[@"state"] isEqual:@"established"] && [row[@"remote_ip"] isEqual:@"127.0.0.1"]);
    [keys addObject:row[@"key"]];matched++;
  }
  assert(matched==2 && keys.count==2);
  // Integration of real sockets with a test-only attribution table. This does
  // not exercise ES authorization or establish real Agent attribution.
  FILE *output=tmpfile();assert(output);
  boot_id=@"11111111-1111-1111-1111-111111111111";monitor_id=@"22222222-2222-2222-2222-222222222222";
  self_identity=id;processes=aidr_processes_create();mach_timebase_info(&timebase);
  policy=calloc(1,sizeof(*policy));policy->revision=1;policy->expires=time(NULL)+60;policy->root_count=1;
  strcpy(policy->roots[0].path,"/test-only-attribution");
  audit_log=bounded_log_create(fileno(output),64,65536);
  sample_network();assert([network_status isEqual:@"waiting_for_process"]);assert(atomic_load(&sequence)==0);
  aidr_process_exec(processes,id,id,1);sample_network();uint64_t first=atomic_load(&sequence);assert(first>=4);
  sample_network();assert(atomic_load(&sequence)==first);
  // An ES source gap must break continuity, even if the root is re-observed
  // before the next polling cycle.
  aidr_process_gap(processes);aidr_process_exec(processes,id,id,1);sample_network();assert(atomic_load(&sequence)==first*2);
  aidr_process_exit(processes,id);sample_network();assert(network_cache.count==0);
  bounded_log_shutdown(audit_log,1000);fflush(output);rewind(output);
  NSMutableSet *observations=[NSMutableSet set];char line[65536];
  while(fgets(line,sizeof(line),output)){
    NSDictionary *record=[NSJSONSerialization JSONObjectWithData:[NSData dataWithBytes:line length:strlen(line)] options:0 error:nil];
    assert(record[@"network"] && !record[@"network"][@"key"]);
    [observations addObject:record[@"network"][@"observation_id"]];
  }
  assert(observations.count==first*2);fclose(output);
  int udp=socket(AF_INET,SOCK_DGRAM,0);assert(connect(udp,(void *)&addr,sizeof(addr))==0);
  records=aidr_network_snapshot(id,&status);bool udp_found=false;
  for(NSDictionary *row in records)if([row[@"protocol"] isEqual:@"udp"] && [row[@"remote_port"] intValue]==ntohs(addr.sin_port)){
    assert([row[@"state"] isEqual:@"unknown"]);udp_found=true;
  }
  assert(udp_found);close(udp);
  int server6=socket(AF_INET6,SOCK_STREAM,0);struct sockaddr_in6 addr6={.sin6_family=AF_INET6,.sin6_addr=IN6ADDR_LOOPBACK_INIT};
  assert(bind(server6,(void *)&addr6,sizeof(addr6))==0 && listen(server6,1)==0);
  length=sizeof(addr6);assert(getsockname(server6,(void *)&addr6,&length)==0);
  int client6=socket(AF_INET6,SOCK_STREAM,0);assert(connect(client6,(void *)&addr6,sizeof(addr6))==0);
  int peer6=accept(server6,NULL,NULL);assert(peer6>=0);
  bool ipv6_found=false;records=aidr_network_snapshot(id,&status);
  for(NSDictionary *row in records)if([row[@"remote_port"] intValue]==ntohs(addr6.sin6_port) && [row[@"remote_ip"] isEqual:@"::1"])ipv6_found=true;
  assert(ipv6_found);close(client6);close(peer6);close(server6);
  assert(aidr_network_snapshot(reused,&status).count==0);
  // Peer FIN is observed as CLOSE_WAIT, not inferred from a disappearing fd.
  for(int i=0;i<2;i++)assert(shutdown(accepted[i],SHUT_WR)==0);
  bool close_wait=false;for(unsigned attempt=0;attempt<100 && !close_wait;attempt++){
    usleep(10000);records=aidr_network_snapshot(id,&status);
    for(NSDictionary *row in records)if([row[@"remote_port"] intValue]==ntohs(addr.sin_port) && [row[@"state"] isEqual:@"close_wait"])close_wait=true;
  }
  assert(close_wait);
  for(int i=0;i<2;i++){close(clients[i]);close(accepted[i]);}close(server);
  records=aidr_network_snapshot(id,&status);
  for(NSDictionary *row in records)assert([row[@"remote_port"] intValue]!=ntohs(addr.sin_port));
  int failed=socket(AF_INET,SOCK_STREAM,0);assert(connect(failed,(void *)&addr,sizeof(addr))<0);close(failed);
  // A transient failed connect is not reconstructible from this inventory.
  records=aidr_network_snapshot(id,&status);
  for(NSDictionary *row in records)assert(![row[@"state"] isEqual:@"failed"]);
  puts("PASS real local TCP, distinct same-peer sockets, peer FIN, disappearance and exact identity mismatch; independent test driver, not Agent traffic");
}}
