// Exercise native notification projection without creating an ES client.
#define main aidr_native_main
#import "enforcer.m"
#undef main
#include <assert.h>

static es_file_t file(const char *path){es_file_t value={0};value.path.data=path;value.path.length=strlen(path);return value;}
int main(void){
  @autoreleasepool {
    const char *argument="token=verbatim\n中文😀";
    es_string_token_t token={.data=argument,.length=strlen(argument)};size_t length;
    assert([argument_prefix(token,8192,&length) isEqual:@"token=verbatim\n中文😀"]);
    assert([argument_prefix(token,token.length-1,&length) isEqual:@"token=verbatim\n中文"]);
    const char malformed[]={ (char)0xff,'a','b','c','d','e','f','g' };
    token=(es_string_token_t){.data=malformed,.length=sizeof(malformed)};
    assert(!argument_prefix(token,7,&length));
    assert(length==4);
    int output[2];assert(pipe(output)==0);
    boot_id=@"11111111-1111-1111-1111-111111111111";monitor_id=@"22222222-2222-2222-2222-222222222222";
    processes=aidr_processes_create();audit_log=bounded_log_create(output[1],32,65536);mach_timebase_info(&timebase);
    es_process_t process={0};process.audit_token.val[5]=123;process.audit_token.val[7]=2;process.start_time.tv_sec=time(NULL)-2;
    es_file_t executable=file("/bin/sh"),source=file("/private/tmp/a"),destination=file("/private/tmp/b");process.executable=&executable;
    es_message_t m={0};m.version=3;m.process=&process;m.action_type=ES_ACTION_TYPE_NOTIFY;m.action.notify.result_type=ES_RESULT_TYPE_AUTH;m.action.notify.result.auth=ES_AUTH_RESULT_ALLOW;
    aidr_identity id=identity(&process,3);aidr_process_exec(processes,id,id,1);
    remember(id,@{@"argv":@[@"sh",@"-c",@"printf secret=verbatim"],@"cwd":@"/private/tmp",@"activity_origin":@"client_probe"});
    m.event_type=ES_EVENT_TYPE_NOTIFY_CREATE;m.event.create.destination_type=ES_DESTINATION_TYPE_EXISTING_FILE;m.event.create.destination.existing_file=&source;handle(NULL,&m);
    m.event_type=ES_EVENT_TYPE_NOTIFY_CLOSE;m.event.close.target=&source;m.event.close.modified=false;handle(NULL,&m);
    m.seq_num=1;m.event.close.modified=true;handle(NULL,&m);m.seq_num=0;
    m.event_type=ES_EVENT_TYPE_NOTIFY_RENAME;m.event.rename.source=&source;m.event.rename.destination_type=ES_DESTINATION_TYPE_EXISTING_FILE;m.event.rename.destination.existing_file=&destination;handle(NULL,&m);
    m.event_type=ES_EVENT_TYPE_NOTIFY_UNLINK;m.event.unlink.target=&destination;handle(NULL,&m);
    m.event_type=ES_EVENT_TYPE_NOTIFY_EXIT;m.event.exit.stat=7<<8;handle(NULL,&m);
    assert(!aidr_process_lookup(processes,id).kind);
    // First event from an already-running signed root establishes attribution
    // before its newly forked child inherits the exact parent identity.
    policy=calloc(1,sizeof(*policy));policy->root_count=1;policy->roots[0].hash_count=1;
    strcpy(policy->roots[0].path,"/bin/sh");
    process.audit_token.val[5]=124;process.codesigning_flags=kSecCodeStatusValid;
    es_process_t child=process;child.audit_token.val[5]=125;
    m.event_type=ES_EVENT_TYPE_NOTIFY_FORK;m.event.fork.child=&child;handle(NULL,&m);
    aidr_attribution inherited=aidr_process_lookup(processes,identity(&child,3));
    assert(inherited.kind==2 && inherited.root.token[5]==124);
    process.audit_token.val[5]=126;process.codesigning_flags=0;
    m.event_type=ES_EVENT_TYPE_NOTIFY_CLOSE;m.seq_num=2;m.event.close.target=&source;m.event.close.modified=true;handle(NULL,&m);
    assert(!aidr_process_lookup(processes,identity(&process,3)).kind);
    bounded_log_shutdown(audit_log,1000);close(output[1]);
    NSMutableData *data=[NSMutableData data];char buffer[4096];ssize_t n;while((n=read(output[0],buffer,sizeof(buffer)))>0)[data appendBytes:buffer length:n];close(output[0]);
    NSArray *lines=[[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] componentsSeparatedByString:@"\n"];
    assert(lines.count==8);NSArray *operations=@[@"create",@"modify",@"rename",@"delete"];
    for(NSUInteger i=0;i<5;i++){
      NSDictionary *event=[NSJSONSerialization JSONObjectWithData:[lines[i] dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];
      assert([event[@"argv"][2] isEqual:@"printf secret=verbatim"]);
      assert([event[@"activity_origin"] isEqual:@"client_probe"]);
      if(i<4){assert([event[@"kind"] isEqual:@"file"]);assert([event[@"operation"] isEqual:operations[i]]);}
      if(i==2)assert([event[@"destination_path"] isEqual:@"/private/tmp/b"]);
      if(i==4){assert([event[@"exit_code"] isEqual:@7]);assert([event[@"duration_ms"] longLongValue]>=1000);}
    }
    assert(!aidr_process_lookup(processes,id).kind);
    NSMutableDictionary *signalled=[NSMutableDictionary dictionary];exit_details(signalled,SIGTERM,1,1000000);
    assert([signalled[@"exit_signal"] isEqual:@(SIGTERM)] && !signalled[@"exit_code"]);
    puts("aidr_native_file_and_exit_evidence_passed_without_es");
  }
  return 0;
}
