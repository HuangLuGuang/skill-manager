#import <EndpointSecurity/EndpointSecurity.h>
#import <Foundation/Foundation.h>
#import <Security/Security.h>
#import <bsm/libbsm.h>
#import <mach/mach.h>
#import <mach/mach_time.h>
#import <os/lock.h>
#include <errno.h>
#include <fcntl.h>
#include <libproc.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <sys/sysctl.h>
#include <time.h>
#include <unistd.h>
#include "identity.h"
#include "policy.h"
#include "collection.h"
#include "network.h"
#include "../../experiments/macos-es-poc/src/bounded_log.h"

static bool collection_only;
static es_client_t *client;
static aidr_processes *processes;
static aidr_policy *policy;
static os_unfair_lock lock=OS_UNFAIR_LOCK_INIT;
static os_unfair_lock audit_lock=OS_UNFAIR_LOCK_INIT;
static bounded_log_t *audit_log;
static NSString *boot_id,*monitor_id,*device_id;
static NSData *public_key,*active_envelope;
static int state_fd=-1;
static aidr_identity self_identity;
static volatile sig_atomic_t stopping;
static _Atomic bool supervisor_disconnected;
static _Atomic uint64_t sequence,response_errors;
static uint64_t last_seq[ES_EVENT_TYPE_LAST];static bool seen_seq[ES_EVENT_TYPE_LAST];
// Bounded metadata follows the same exact process identities as attribution.
static NSMutableDictionary<NSString *, NSDictionary *> *process_details;
static mach_timebase_info_data_t timebase;
static NSString *network_status = @"starting";
static NSMutableDictionary *network_cache;
static uint64_t network_sample_ns, network_generation;
static size_t network_cursor;
typedef struct {bool used,verified;char id[37];uint64_t expires;aidr_attribution target;} response_entry;
static response_entry responses[128];

static NSString *decimal_string(uint64_t value){return [NSString stringWithFormat:@"%llu",(unsigned long long)value];}
static uint64_t unix_ns(void){struct timespec now;clock_gettime(CLOCK_REALTIME,&now);return (uint64_t)now.tv_sec*1000000000+now.tv_nsec;}
static uint64_t micros(uint64_t ticks){return (uint64_t)((__uint128_t)ticks*timebase.numer/timebase.denom/1000);}
static aidr_identity identity(const es_process_t *p,uint32_t version){
  aidr_identity id={0};if(!p || version<3)return id;
  memcpy(id.token,p->audit_token.val,sizeof(id.token));id.start_us=(uint64_t)p->start_time.tv_sec*1000000+p->start_time.tv_usec;
  id.valid=id.token[5]>0 && id.start_us>0;return id;
}
static NSDictionary *identity_json(aidr_identity p){return @{@"pid":decimal_string(p.token[5]),@"pidversion":decimal_string(p.token[7]),@"start_us":decimal_string(p.start_us)};}
static void emit(NSString *kind,aidr_attribution actor,NSDictionary *extra){
  @autoreleasepool {
    os_unfair_lock_lock(&audit_lock);
    aidr_identity id=actor.process.valid?actor.process:self_identity;
    NSMutableDictionary *event=[@{@"schema_version":@1,@"boot_id":boot_id,@"monitor_id":monitor_id,@"sequence":decimal_string(atomic_fetch_add(&sequence,1)+1),@"time_ns":decimal_string(unix_ns()),@"kind":kind,@"process":identity_json(id),@"relation":actor.kind==1?@"direct":actor.kind==2?@"inherited":@"unknown"} mutableCopy];
    if(actor.root.valid)event[@"root"]=identity_json(actor.root);
    [event addEntriesFromDictionary:extra];NSData *data=[NSJSONSerialization dataWithJSONObject:event options:NSJSONWritingSortedKeys error:nil];
    if(data){NSMutableData *line=[data mutableCopy];[line appendBytes:"\n" length:1];bounded_log_enqueue(audit_log,line.bytes,line.length);}
    os_unfair_lock_unlock(&audit_lock);
  }
}
static void health(NSString *code){
  os_unfair_lock_lock(&lock);uint64_t gaps=aidr_process_gaps(processes),revision=policy?policy->revision:0;
  if([code isEqual:@"aidr_enforcement_active"]){if(!policy)code=@"aidr_enforcement_no_policy";else if(policy->expires<=(uint64_t)time(NULL))code=@"aidr_enforcement_policy_expired";else if(gaps)code=@"aidr_enforcement_source_gap";else if(collection_only)code=@"aidr_enforcement_collection_only";}
  NSDictionary *networkHealth=@{@"source":@"libproc_snapshot",@"state":[code isEqual:@"aidr_enforcement_stopped"]?@"stopped":network_status,@"sampled_at_ns":decimal_string(network_sample_ns)};
  os_unfair_lock_unlock(&lock);
  os_unfair_lock_lock(&audit_lock);
  bounded_log_stats_t stats=bounded_log_stats(audit_log);
  os_unfair_lock_unlock(&audit_lock);
  if(stats.dropped || stats.errors || stats.fatal)code=@"aidr_enforcement_audit_gap";
  if(atomic_load(&response_errors))code=@"aidr_enforcement_response_failed";
  emit(@"health",(aidr_attribution){0},@{@"detail_schema":@1,@"reason_code":code,@"revision":decimal_string(revision),@"gaps":decimal_string(gaps+stats.dropped+stats.errors),@"network_health":networkHealth});
}
static bool token_path(es_string_token_t value,char out[1024]){
  if(!value.data || value.length<1 || value.length>=1024)return false;
  memcpy(out,value.data,value.length);out[value.length]=0;return strlen(out)==value.length;
}
static unsigned root_image(const es_process_t *p,const char *path){
  if(!policy || !(p->codesigning_flags & kSecCodeStatusValid))return 0;
  for(size_t i=0;i<policy->root_count;i++){
    aidr_root_image *r=&policy->roots[i];
    if(!strcmp(r->path,path) && p->executable->stat.st_dev==r->device && p->executable->stat.st_ino==r->inode)for(size_t h=0;h<r->hash_count;h++)if(!memcmp(r->cdhashes[h],p->cdhash,20))return (unsigned)i+1;
  }
  return 0;
}
static NSString *process_key(aidr_identity id){return [NSString stringWithFormat:@"%u:%u:%llu",id.token[5],id.token[7],(unsigned long long)id.start_us];}
static NSString *path_text(const es_file_t *file){
  if(!file || file->path_truncated || file->path.length>1023)return @"";
  return [[NSString alloc] initWithBytes:file->path.data length:file->path.length encoding:NSUTF8StringEncoding]?:@"";
}
static NSString *joined_path(const es_file_t *dir,es_string_token_t name){
  NSString *base=path_text(dir),*leaf=[[NSString alloc] initWithBytes:name.data length:name.length encoding:NSUTF8StringEncoding];
  NSString *value=base.length && leaf.length?[base stringByAppendingPathComponent:leaf]:@"";
  return [value lengthOfBytesUsingEncoding:NSUTF8StringEncoding]<=1023?value:@"";
}
static NSMutableDictionary *details_for(aidr_attribution actor){
  NSMutableDictionary *details=[process_details[process_key(actor.process)] mutableCopy]?:[NSMutableDictionary dictionary];
  if(policy && actor.scope>0 && actor.scope<=policy->root_count)details[@"root_path"]=[NSString stringWithUTF8String:policy->roots[actor.scope-1].path];
  return details;
}
static void remember(aidr_identity id,NSDictionary *details){
  if(!id.valid)return;
  if(!process_details)process_details=[NSMutableDictionary dictionary];
  if(process_details.count>=AIDR_PROCESS_CAPACITY)[process_details removeAllObjects];
  process_details[process_key(id)]=[details copy];
}
static void sample_network(void){
  @autoreleasepool {
    aidr_attribution actors[AIDR_PROCESS_CAPACITY];
    os_unfair_lock_lock(&lock);
    uint64_t revision=policy?policy->revision:0, gaps=aidr_process_gaps(processes);
    size_t count=policy && policy->expires>(uint64_t)time(NULL)?aidr_process_snapshot(processes,actors,AIDR_PROCESS_CAPACITY):0;
    os_unfair_lock_unlock(&lock);
    if(!network_cache || gaps!=network_generation)network_cache=[NSMutableDictionary dictionary];
    network_generation=gaps;
    NSMutableSet *live=[NSMutableSet set];
    for(size_t i=0;i<count;i++)[live addObject:process_key(actors[i].process)];
    for(NSString *key in [network_cache allKeys])if(![live containsObject:key])[network_cache removeObjectForKey:key];
    NSUInteger cached=0;for(NSDictionary *entries in network_cache.allValues)cached+=entries.count;
    unsigned emitted_count=0;
    NSString *status=count?@"sampled":@"waiting_for_process";
    uint64_t begin=mach_absolute_time();size_t processed=0;
    // Never hold the ES callback lock while enumerating descriptors. Bound work
    // per cycle and rotate through large policies rather than starving tails.
    for(;processed<count && processed<256 && !stopping;processed++){
      if(micros(mach_absolute_time()-begin)>200000){status=@"partial";break;}
      aidr_attribution actor=actors[(network_cursor+processed)%count];
      NSString *readStatus;NSArray *sockets=aidr_network_snapshot(actor.process,&readStatus);
      if(![readStatus isEqual:@"sampled"] && ![status isEqual:@"permission_denied"])status=readStatus;
      os_unfair_lock_lock(&lock);
      aidr_attribution current=aidr_process_lookup(processes,actor.process);
      bool valid=current.kind && current.scope==actor.scope && policy && policy->revision==revision && policy->expires>(uint64_t)time(NULL);
      NSMutableDictionary *details=valid?details_for(actor):nil;
      os_unfair_lock_unlock(&lock);
      NSString *owner=process_key(actor.process);
      if(!valid){cached-=[network_cache[owner] count];[network_cache removeObjectForKey:owner];if(![status isEqual:@"permission_denied"])status=@"partial";continue;}
      NSDictionary *old=network_cache[owner];cached-=old.count;NSMutableDictionary *next=[NSMutableDictionary dictionary];
      for(NSDictionary *socket in sockets){
        NSString *key=socket[@"key"];if(next[key])continue;
        if(cached>=8192 || emitted_count>=256){status=@"partial";break;}
        cached++;NSDictionary *prior=old[key];
        NSMutableDictionary *value=[socket mutableCopy];[value removeObjectForKey:@"key"];
        value[@"observation_id"]=prior?prior[@"value"][@"observation_id"]:NSUUID.UUID.UUIDString.lowercaseString;
        uint64_t now=unix_ns();bool changed=!prior || ![prior[@"value"] isEqual:value];
        uint64_t emitted=prior?[prior[@"emitted"] unsignedLongLongValue]:0;
        if(changed || now-emitted>=30000000000ull){
          NSMutableDictionary *extra=[details mutableCopy];
          [extra addEntriesFromDictionary:@{@"network":value,@"reason_code":@"aidr_network_snapshot",@"revision":decimal_string(revision),@"result":@"observed"}];
          emit(@"network",actor,extra);emitted=now;emitted_count++;
        }
        next[key]=@{@"value":value,@"emitted":@(emitted)};
      }
      // Missing sockets end an observation, never synthesize a close/failure.
      network_cache[owner]=next;
    }
    if(processed<count && ![status isEqual:@"permission_denied"])status=@"partial";
    network_cursor=count?(network_cursor+processed)%count:0;
    os_unfair_lock_lock(&lock);network_status=status;network_sample_ns=unix_ns();os_unfair_lock_unlock(&lock);
  }
}
static NSString *argument_prefix(es_string_token_t arg,size_t limit,size_t *length){
  *length=MIN(arg.length,limit);
  NSString *text=[[NSString alloc] initWithBytes:arg.data length:*length encoding:NSUTF8StringEncoding];
  // A UTF-8 boundary needs at most three bytes removed. An invalid byte earlier
  // in the argument is unavailable text, not a reason to rescan the whole value.
  for(unsigned trim=0;!text && *length && arg.length>limit && trim<3;trim++){
    (*length)--;text=[[NSString alloc] initWithBytes:arg.data length:*length encoding:NSUTF8StringEncoding];
  }
  return text;
}
static NSDictionary *execution_details(const es_message_t *m){
  NSMutableArray *argv=[NSMutableArray array];size_t remaining=8192;bool truncated=false;
  uint32_t count=es_exec_arg_count(&m->event.exec);
  for(uint32_t i=0;i<count;i++){
    if(i>=256){truncated=true;break;}
    es_string_token_t arg=es_exec_arg(&m->event.exec,i);size_t length;
    NSString *text=argument_prefix(arg,remaining,&length);
    if(!text){truncated=true;break;}
    [argv addObject:text];remaining-=length;
    if(length<arg.length){truncated=true;break;}
  }
  NSMutableDictionary *details=[@{@"argv":argv,@"argv_truncated":@(truncated),@"executable":path_text(m->event.exec.target->executable),@"parent_pid":decimal_string(m->event.exec.target->ppid)} mutableCopy];
  if(m->version>=3)details[@"cwd"]=path_text(m->event.exec.cwd);
  // This marker is display provenance declared by the client, never authority.
  const char *marker="AGENT_MANAGER_ACTIVITY=client_probe";
  for(uint32_t i=0;i<es_exec_env_count(&m->event.exec);i++){
    es_string_token_t env=es_exec_env(&m->event.exec,i);
    if(env.length==strlen(marker) && !memcmp(env.data,marker,env.length)){details[@"activity_origin"]=@"client_probe";break;}
  }
  return details;
}
static void exit_details(NSMutableDictionary *details,int stat,uint64_t start_us,uint64_t now_ns){
  if(WIFEXITED(stat))details[@"exit_code"]=@(WEXITSTATUS(stat));
  else if(WIFSIGNALED(stat))details[@"exit_signal"]=@(WTERMSIG(stat));
  if(now_ns/1000>=start_us)details[@"duration_ms"]=decimal_string((now_ns/1000-start_us)/1000);
}
static void handle(es_client_t *c,const es_message_t *m){
  @autoreleasepool {
    uint64_t begin=mach_absolute_time();aidr_identity subject=identity(m->process,m->version);
    es_event_type_t type=m->event_type;
    if(type>=ES_EVENT_TYPE_LAST)return;
    char path[1024]={0};aidr_attribution actor={.process=subject};uint64_t revision=0;bool gap=false;
    os_unfair_lock_lock(&lock);
    if(m->version>=2){if(seen_seq[type] && m->seq_num!=last_seq[type]+1){aidr_process_gap(processes);[process_details removeAllObjects];gap=true;}seen_seq[type]=true;last_seq[type]=m->seq_num;}
    else {aidr_process_gap(processes);[process_details removeAllObjects];gap=true;}
    if(policy)revision=policy->revision;
    // The ES message authenticates an already-running root on its first observed
    // operation. No PID-only snapshot or guessed ancestry is introduced.
    aidr_attribution observed={0};
    if(!aidr_process_lookup(processes,subject).kind){
      NSString *image=path_text(m->process->executable);unsigned scope=image.length?root_image(m->process,image.UTF8String):0;
      if(scope){observed=aidr_process_exec(processes,subject,subject,scope);observed.process=subject;
        remember(subject,@{@"executable":image,@"parent_pid":decimal_string(m->process->ppid)});}
    }
    if(type==ES_EVENT_TYPE_AUTH_OPEN){
      actor=aidr_process_lookup(processes,subject);actor.process=subject;
      NSMutableDictionary *auth_details=details_for(actor);
      const es_file_t *file=m->event.open.file;bool complete=token_path(file->path,path) && !file->path_truncated;
      bool denied=false,matched=false,expired=policy && policy->expires<=(uint64_t)time(NULL);char rule[65]={0};
      if(policy)for(size_t i=0;i<policy->rule_count;i++){
        aidr_rule *r=&policy->rules[i];bool object=file->stat.st_dev==r->device && file->stat.st_ino==r->inode;
        if(!object && (!complete || strcmp(path,r->path)))continue;
        bool deny=expired?policy->expired_deny:(r->agent_only && !actor.kind)?policy->unknown_deny:r->deny;
        if(!matched || deny)strlcpy(rule,r->id,sizeof(rule));matched=true;denied|=deny;
      }
      os_unfair_lock_unlock(&lock);
      es_respond_result_t result=es_respond_flags_result(c,m,denied?0:UINT32_MAX,false);
      uint64_t end=mach_absolute_time();if(result!=ES_RESPOND_RESULT_SUCCESS)atomic_fetch_add(&response_errors,1);
      if(observed.kind)emit(@"process",observed,@{@"transition":@"observed",@"path":path_text(m->process->executable),@"revision":decimal_string(revision),@"reason_code":@"aidr_process_observed"});
      if(matched || result!=ES_RESPOND_RESULT_SUCCESS){[auth_details addEntriesFromDictionary:@{@"path":[NSString stringWithUTF8String:path]?:@"",@"revision":decimal_string(revision),@"rule_id":[NSString stringWithUTF8String:rule],@"decision":denied?@"deny":@"allow",@"result":result==ES_RESPOND_RESULT_SUCCESS?@"responded":@"failed",@"reason_code":expired?@"aidr_enforcement_policy_expired":!actor.kind?@"aidr_enforcement_unknown_actor":@"aidr_enforcement_rule_match",@"latency_us":decimal_string(micros(end-begin)),@"deadline_remaining_us":decimal_string(end<m->deadline?micros(m->deadline-end):0)}];emit(@"authorization",actor,auth_details);}
    }else if(type==ES_EVENT_TYPE_NOTIFY_FORK || type==ES_EVENT_TYPE_NOTIFY_EXEC || type==ES_EVENT_TYPE_NOTIFY_EXIT){
      NSString *transition;response_entry completed[128];size_t completed_count=0;bool root_candidate=false;
      NSMutableDictionary *details;
      if(type==ES_EVENT_TYPE_NOTIFY_FORK){
        aidr_identity child=identity(m->event.fork.child,m->version);
        actor=aidr_process_fork(processes,subject,child);actor.process=child;
        token_path(m->event.fork.child->executable->path,path);transition=@"fork";
        details=[process_details[process_key(subject)] mutableCopy]?:[NSMutableDictionary dictionary];
        details[@"parent"]=identity_json(subject);details[@"parent_pid"]=decimal_string(subject.token[5]);
        if(actor.kind)remember(child,details);
      }else if(type==ES_EVENT_TYPE_NOTIFY_EXEC){
        const es_process_t *target=m->event.exec.target;bool complete=token_path(target->executable->path,path) && !target->executable->path_truncated;
        if(policy && complete)for(size_t i=0;i<policy->root_count;i++)if(!strcmp(policy->roots[i].path,path))root_candidate=true;
        actor=aidr_process_exec(processes,subject,identity(target,m->version),complete?root_image(target,path):0);actor.process=identity(target,m->version);transition=@"exec";
        details=actor.kind || root_candidate?[execution_details(m) mutableCopy]:[NSMutableDictionary dictionary];NSDictionary *prior=process_details[process_key(subject)];
        if(prior[@"parent"])details[@"parent"]=prior[@"parent"];
        if(prior[@"activity_origin"])details[@"activity_origin"]=prior[@"activity_origin"];
        [process_details removeObjectForKey:process_key(subject)];
        if(actor.kind)remember(actor.process,details);
      }else{
        actor=aidr_process_lookup(processes,subject);actor.process=subject;
        token_path(m->process->executable->path,path);transition=@"exit";
        details=details_for(actor);exit_details(details,m->event.exit.stat,subject.start_us,unix_ns());
        aidr_process_exit(processes,subject);[process_details removeObjectForKey:process_key(subject)];
        for(size_t i=0;i<128;i++)if(responses[i].used && !responses[i].verified && aidr_identity_equal(responses[i].target.process,subject)){responses[i].verified=true;completed[completed_count++]=responses[i];}
      }
      if(policy && actor.scope>0 && actor.scope<=policy->root_count)details[@"root_path"]=[NSString stringWithUTF8String:policy->roots[actor.scope-1].path];
      os_unfair_lock_unlock(&lock);
      if(observed.kind)emit(@"process",observed,@{@"transition":@"observed",@"path":path_text(m->process->executable),@"revision":decimal_string(revision),@"reason_code":@"aidr_process_observed"});
      [details addEntriesFromDictionary:@{@"transition":transition,@"path":[NSString stringWithUTF8String:path]?:@"",@"revision":decimal_string(revision),@"reason_code":actor.kind?[@"aidr_process_" stringByAppendingString:transition]:@"aidr_enforcement_root_identity_mismatch"}];
      if(actor.kind || root_candidate)emit(@"process",actor,details);
      for(size_t i=0;i<completed_count;i++)emit(@"response",completed[i].target,@{@"command_id":[NSString stringWithUTF8String:completed[i].id],@"result":@"verified",@"reason_code":@"aidr_response_exit_observed"});
    }else{
      actor=aidr_process_lookup(processes,subject);actor.process=subject;
      NSMutableDictionary *details=details_for(actor);NSString *operation=nil,*source=@"",*destination=nil;
      bool allowed=m->action_type==ES_ACTION_TYPE_NOTIFY && (m->action.notify.result_type!=ES_RESULT_TYPE_AUTH || m->action.notify.result.auth==ES_AUTH_RESULT_ALLOW);
      if(type==ES_EVENT_TYPE_NOTIFY_CREATE && allowed){operation=@"create";const es_event_create_t *e=&m->event.create;
        source=e->destination_type==ES_DESTINATION_TYPE_EXISTING_FILE?path_text(e->destination.existing_file):joined_path(e->destination.new_path.dir,e->destination.new_path.filename);
      }else if(type==ES_EVENT_TYPE_NOTIFY_CLOSE && m->event.close.modified){operation=@"modify";source=path_text(m->event.close.target);
      }else if(type==ES_EVENT_TYPE_NOTIFY_RENAME && allowed){operation=@"rename";const es_event_rename_t *e=&m->event.rename;source=path_text(e->source);
        destination=e->destination_type==ES_DESTINATION_TYPE_EXISTING_FILE?path_text(e->destination.existing_file):joined_path(e->destination.new_path.dir,e->destination.new_path.filename);
      }else if(type==ES_EVENT_TYPE_NOTIFY_UNLINK && allowed){operation=@"delete";source=path_text(m->event.unlink.target);}
      os_unfair_lock_unlock(&lock);
      if(observed.kind)emit(@"process",observed,@{@"transition":@"observed",@"path":path_text(m->process->executable),@"revision":decimal_string(revision),@"reason_code":@"aidr_process_observed"});
      if(actor.kind && operation){
        [details addEntriesFromDictionary:@{@"operation":operation,@"path":source,@"revision":decimal_string(revision),@"reason_code":[@"aidr_file_" stringByAppendingString:operation],@"result":@"observed"}];
        if(destination)details[@"destination_path"]=destination;
        if(!source.length || (destination && !destination.length))details[@"paths_truncated"]=@YES;
        emit(@"file",actor,details);
      }
    }
    if(gap)health(@"aidr_enforcement_source_gap");
  }
}

static NSData *read_private(const char *name){
  int fd=openat(state_fd,name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return nil;
  struct stat st;bool valid=fstat(fd,&st)==0 && S_ISREG(st.st_mode) && st.st_uid==0 && !(st.st_mode&077) && st.st_size<=65536;
  NSMutableData *data=[NSMutableData data];char buffer[4096];ssize_t n;
  if(valid)while((n=read(fd,buffer,sizeof(buffer)))>0){[data appendBytes:buffer length:n];if(data.length>65536){valid=false;break;}}
  close(fd);return valid?data:nil;
}
static bool persist(NSData *data){
  // An incomplete temporary file is never activated; keep the old snapshot.
  int fd=openat(state_fd,"policy.next",O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW|O_CLOEXEC,0600);if(fd<0)return false;
  struct stat st;bool ok=fstat(fd,&st)==0 && S_ISREG(st.st_mode) && st.st_uid==0 && st.st_nlink==1 && !(st.st_mode&077);
  size_t written=0;while(ok && written<data.length){ssize_t n=write(fd,(const char *)data.bytes+written,data.length-written);if(n<=0){ok=false;break;}written+=(size_t)n;}
  if(ok)ok=fsync(fd)==0;close(fd);
  if(ok)ok=renameat(state_fd,"policy.next",state_fd,aidr_collection_cache(collection_only))==0 && fsync(state_fd)==0;
  return ok;
}
static bool apply(NSData *data,bool restore){
  NSString *reason;NSDictionary *value=aidr_verify_envelope(data,public_key,&reason);aidr_policy *next=calloc(1,sizeof(*next));
  bool ok=next && value && (collection_only?aidr_compile_attribution(value,device_id,restore,next,&reason):aidr_compile_policy(value,device_id,restore,next,&reason));
  if(ok){os_unfair_lock_lock(&lock);uint64_t old=policy?policy->revision:0;NSData *previous=active_envelope;os_unfair_lock_unlock(&lock);
    if(next->revision<old || (next->revision==old && !aidr_equal_envelopes(previous,data))){ok=false;reason=@"aidr_enforcement_revision_conflict";}
    else if(next->revision==old){free(next);return true;}
    else if(!restore && !persist(data)){ok=false;reason=@"aidr_enforcement_policy_persist_failed";}
  }
  if(ok){os_unfair_lock_lock(&lock);aidr_policy *old=policy;unsigned mapping[32]={0};
    if(old)for(size_t i=0;i<old->root_count;i++)for(size_t j=0;j<next->root_count;j++)if(!strcmp(old->roots[i].path,next->roots[j].path) && old->roots[i].device==next->roots[j].device && old->roots[i].inode==next->roots[j].inode && old->roots[i].hash_count==next->roots[j].hash_count && !memcmp(old->roots[i].cdhashes,next->roots[j].cdhashes,old->roots[i].hash_count*20))mapping[i]=(unsigned)j+1;
    aidr_process_remap_scopes(processes,mapping);policy=next;active_envelope=[data copy];os_unfair_lock_unlock(&lock);free(old);
    if(!restore)emit(@"policy",(aidr_attribution){0},@{@"revision":decimal_string(next->revision),@"result":@"applied",@"reason_code":collection_only?@"aidr_enforcement_attribution_applied":@"aidr_enforcement_policy_applied"});
  }else{free(next);health(reason?:@"aidr_enforcement_policy_invalid");}
  return ok;
}
static bool parse_identity(NSDictionary *raw,aidr_identity *p){
  if(![raw isKindOfClass:NSDictionary.class] || raw.count!=3)return false;
  uint64_t pid,version,start;if(!aidr_decimal(raw[@"pid"],&pid)||!aidr_decimal(raw[@"pidversion"],&version)||!aidr_decimal(raw[@"start_us"],&start)||pid<2||pid>INT_MAX||version>UINT32_MAX||!start)return false;
  *p=(aidr_identity){.start_us=start,.valid=true};p->token[5]=(uint32_t)pid;p->token[7]=(uint32_t)version;return true;
}
static void command(NSData *data){
  if(collection_only){health(@"aidr_enforcement_collection_control_rejected");return;}
  NSString *reason;NSDictionary *value=aidr_verify_envelope(data,public_key,&reason);uint64_t issued,expires;aidr_identity target;
  NSString *ident=value[@"command_id"];
  if(!value || value.count!=9 || ![value[@"schema"] isEqual:@1] || ![value[@"device"] isEqual:device_id] || ![value[@"action"] isEqual:@"terminate"] || ![value[@"boot_id"] isEqual:boot_id] || ![value[@"monitor_id"] isEqual:monitor_id] || ![ident isKindOfClass:NSString.class] || ident.length!=36 || ![[NSUUID alloc] initWithUUIDString:ident] || !aidr_decimal(value[@"issued_at"],&issued) || !aidr_decimal(value[@"expires_at"],&expires) || expires<=issued || expires-issued>120 || issued>(uint64_t)time(NULL)+60 || expires<=(uint64_t)time(NULL) || !parse_identity(value[@"process"],&target)){
    health(@"aidr_enforcement_command_invalid");return;
  }
  os_unfair_lock_lock(&lock);aidr_attribution actor=aidr_process_lookup(processes,target);actor.process=target;
  response_entry *slot=NULL;bool duplicate=false;
  for(size_t i=0;i<128;i++)if(responses[i].used && !strcmp(responses[i].id,ident.UTF8String)){slot=&responses[i];duplicate=true;break;}
  if(duplicate){bool verified=slot->verified,same=aidr_identity_equal(slot->target.process,target);if(same)actor=slot->target;os_unfair_lock_unlock(&lock);emit(@"response",actor,@{@"command_id":ident,@"result":!same?@"rejected":verified?@"verified":@"executed",@"reason_code":!same?@"aidr_response_command_conflict":verified?@"aidr_response_exit_observed":@"aidr_response_duplicate"});return;}
  for(size_t i=0;i<128;i++)if(!responses[i].used || responses[i].expires<(uint64_t)time(NULL)){slot=&responses[i];break;}
  if(!actor.kind || !slot || target.token[5]==(uint32_t)getpid()){os_unfair_lock_unlock(&lock);emit(@"response",actor,@{@"command_id":ident,@"result":@"rejected",@"reason_code":!slot?@"aidr_response_capacity":@"aidr_response_identity_unknown"});return;}
  // Retrieve the actual token from the ES table, never construct a token from a
  // remote PID. The kernel checks the audit_log-token version atomically with signal.
  actor=aidr_process_lookup(processes,target);audit_token_t token;memcpy(token.val,actor.process.token,sizeof(token.val));
  int result=proc_signal_with_audittoken(&token,SIGTERM);
  if(result==0){*slot=(response_entry){.used=true,.expires=expires,.target=actor};strlcpy(slot->id,ident.UTF8String,sizeof(slot->id));}
  os_unfair_lock_unlock(&lock);
  emit(@"response",actor,@{@"command_id":ident,@"result":result==0?@"executed":@"rejected",@"reason_code":result==0?@"aidr_response_signal_sent":@"aidr_response_signal_rejected"});
}
static void *control(void *unused){
  (void)unused;char line[90000];
  while(!stopping && fgets(line,sizeof(line),stdin)){
    @autoreleasepool {
      if(!strchr(line,'\n')){health(@"aidr_enforcement_control_oversized");break;}
      NSData *data=[[NSString stringWithUTF8String:line] dataUsingEncoding:NSUTF8StringEncoding];
      NSDictionary *message=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
      if(![message isKindOfClass:NSDictionary.class] || message.count!=2 || ![message[@"envelope"] isKindOfClass:NSDictionary.class]){health(@"aidr_enforcement_control_invalid");continue;}
      NSData *envelope=[NSJSONSerialization dataWithJSONObject:message[@"envelope"] options:NSJSONWritingSortedKeys error:nil];
      if(!aidr_collection_input(message[@"type"],collection_only)){health(@"aidr_enforcement_collection_control_rejected");continue;}
      if([message[@"type"] isEqual:@"policy"] || [message[@"type"] isEqual:@"attribution"])apply(envelope,false);
      else if([message[@"type"] isEqual:@"terminate"])command(envelope);
      else if([message[@"type"] isEqual:@"health"] && [@[@"aidr_enforcement_transport_failed",@"aidr_enforcement_transport_restored"] containsObject:message[@"envelope"][@"code"]])health(message[@"envelope"][@"code"]);
      else health(@"aidr_enforcement_control_invalid");
    }
  }
  if(!stopping){
    atomic_store(&supervisor_disconnected,true);
    health(@"aidr_enforcement_control_disconnected");
  }
  return NULL;
}
static void stop(int sig){(void)sig;stopping=1;}
int main(int argc,char **argv){
  @autoreleasepool {
    if(argc==2 && !strcmp(argv[1],"--capabilities")){puts("{\"protocol\":1,\"collection_only\":true,\"signed_attribution\":true}");return 0;}
    collection_only=argc==6 && !strcmp(argv[5],"--collection-only");
    if((argc!=5 && !collection_only) || geteuid()!=0){fprintf(stderr,"usage (root): aidr-enforcer PUBLIC_KEY_X963 DEVICE PRIVATE_STATE_DIR DURATION_SECONDS [--collection-only]\n");return 64;}
    char *end;errno=0;long duration=strtol(argv[4],&end,10);if(end==argv[4] || *end || errno==ERANGE || duration<0)return 64;
    state_fd=open(argv[3],O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);struct stat st;
    if(state_fd<0 || fstat(state_fd,&st)!=0 || st.st_uid!=0 || st.st_mode&077){fprintf(stderr,"aidr_enforcement_state_invalid\n");return 65;}
    int keyfd=open(argv[1],O_RDONLY|O_NOFOLLOW|O_CLOEXEC);unsigned char key[66];struct stat key_stat;
    bool trusted=keyfd>=0 && fstat(keyfd,&key_stat)==0 && S_ISREG(key_stat.st_mode) && key_stat.st_uid==0 && !(key_stat.st_mode&022);
    ssize_t keylen=trusted?read(keyfd,key,sizeof(key)):-1;if(keyfd>=0)close(keyfd);
    if(keylen!=65){fprintf(stderr,"aidr_enforcement_key_invalid\n");return 65;}
    public_key=[NSData dataWithBytes:key length:65];device_id=[NSString stringWithUTF8String:argv[2]];
    if(!device_id.length || device_id.length>128)return 65;
    char boot[64];size_t size=sizeof(boot);if(sysctlbyname("kern.bootsessionuuid",boot,&size,NULL,0)!=0)return 70;
    boot_id=[[NSString stringWithUTF8String:boot] lowercaseString];monitor_id=NSUUID.UUID.UUIDString.lowercaseString;
    audit_token_t own;mach_msg_type_number_t count=TASK_AUDIT_TOKEN_COUNT;
    struct proc_bsdinfo info;if(task_info(mach_task_self(),TASK_AUDIT_TOKEN,(task_info_t)&own,&count)!=KERN_SUCCESS || proc_pidinfo(getpid(),PROC_PIDTBSDINFO,0,&info,sizeof(info))!=sizeof(info))return 70;
    memcpy(self_identity.token,own.val,sizeof(self_identity.token));self_identity.start_us=info.pbi_start_tvsec*1000000+info.pbi_start_tvusec;self_identity.valid=true;
    mach_timebase_info(&timebase);processes=aidr_processes_create();audit_log=bounded_log_create(STDOUT_FILENO,1024,65536);if(!processes || !audit_log)return 70;
    signal(SIGINT,stop);signal(SIGTERM,stop);signal(SIGPIPE,SIG_IGN);
    NSData *cached=read_private(aidr_collection_cache(collection_only));if(cached && !apply(cached,true)){bounded_log_shutdown(audit_log,1000);return 65;}
    es_new_client_result_t created=es_new_client(&client,^(es_client_t *c,const es_message_t *m){handle(c,m);});
    if(created!=ES_NEW_CLIENT_RESULT_SUCCESS){
      const char *reason=created==ES_NEW_CLIENT_RESULT_ERR_NOT_PERMITTED?"aidr_enforcement_fda_required":created==ES_NEW_CLIENT_RESULT_ERR_NOT_ENTITLED?"aidr_enforcement_entitlement_required":created==ES_NEW_CLIENT_RESULT_ERR_NOT_PRIVILEGED?"aidr_enforcement_root_required":"aidr_enforcement_es_unavailable";
      fprintf(stderr,"%s:%d\n",reason,created);bounded_log_shutdown(audit_log,1000);return 77;
    }
    es_event_type_t events[AIDR_COLLECTION_EVENT_COUNT];size_t event_count=aidr_collection_events(events,collection_only);
    if(es_subscribe(client,events,(uint32_t)event_count)!=ES_RETURN_SUCCESS){fprintf(stderr,"aidr_enforcement_subscription_failed\n");es_delete_client(client);bounded_log_shutdown(audit_log,1000);return 77;}
    if(policy)emit(@"policy",(aidr_attribution){0},@{@"revision":decimal_string(policy->revision),@"result":@"applied",@"reason_code":collection_only?@"aidr_enforcement_attribution_restored":@"aidr_enforcement_policy_restored"});
    pthread_t input;if(pthread_create(&input,NULL,control,NULL)!=0){es_unsubscribe_all(client);es_delete_client(client);health(@"aidr_enforcement_control_unavailable");bounded_log_shutdown(audit_log,1000);return 70;}pthread_detach(input);
    for(uint64_t seconds=0;(!duration || seconds<(uint64_t)duration) && !stopping && !atomic_load(&supervisor_disconnected);seconds++){sample_network();health(@"aidr_enforcement_active");sleep(1);}
    stopping=1;es_unsubscribe_all(client);es_delete_client(client);health(@"aidr_enforcement_stopped");os_unfair_lock_lock(&audit_lock);bounded_log_shutdown(audit_log,2000);os_unfair_lock_unlock(&audit_lock);
    // The OS closes the bounded control reader and writer on process exit.
    return 0;
  }
}
