// Exercise the production control reader without creating an ES client.
#define main aidr_native_main
#import "enforcer.m"
#undef main
#include <assert.h>
#include <poll.h>
#include <sys/wait.h>

static int check_mode(bool audit_only) {
  int input_pipe[2],ready_pipe[2],output_pipe[2];
  assert(pipe(input_pipe)==0 && pipe(ready_pipe)==0 && pipe(output_pipe)==0);
  pid_t child=fork();
  assert(child>=0);
  if(child==0){
    @autoreleasepool {
      close(input_pipe[1]);close(ready_pipe[0]);close(output_pipe[0]);
      if(dup2(input_pipe[0],STDIN_FILENO)<0)_exit(2);
      close(input_pipe[0]);clearerr(stdin);
      collection_only=audit_only;
      boot_id=@"11111111-1111-1111-1111-111111111111";
      monitor_id=@"22222222-2222-2222-2222-222222222222";
      processes=aidr_processes_create();
      audit_log=bounded_log_create(output_pipe[1],16,16384);
      if(!processes || !audit_log)_exit(4);
      if(atomic_load(&supervisor_disconnected))_exit(5);
      if(write(ready_pipe[1],"R",1)!=1)_exit(6);
      close(ready_pipe[1]);
      control(NULL);
      // EOF must notify the collection loop and emit disconnection evidence.
      if(!atomic_load(&supervisor_disconnected) || atomic_load(&sequence)!=1)_exit(7);
      bounded_log_shutdown(audit_log,1000);
      close(output_pipe[1]);
      _exit(0);
    }
  }
  close(input_pipe[0]);close(ready_pipe[1]);close(output_pipe[1]);
  char ready=0;
  struct pollfd waiting={.fd=ready_pipe[0],.events=POLLIN};
  assert(poll(&waiting,1,3000)>0);
  assert(read(ready_pipe[0],&ready,1)==1 && ready=='R');
  close(ready_pipe[0]);
  int status;
  assert(waitpid(child,&status,WNOHANG)==0);
  close(input_pipe[1]); // A crashed owner's pipe is closed by the OS.
  for(int i=0;i<300;i++){
    pid_t ended=waitpid(child,&status,WNOHANG);
    if(ended==child){
      assert(WIFEXITED(status) && WEXITSTATUS(status)==0);
      char raw[2048];
      ssize_t bytes=read(output_pipe[0],raw,sizeof(raw));
      close(output_pipe[0]);
      assert(bytes>0 && bytes<(ssize_t)sizeof(raw) && raw[bytes-1]=='\n');
      @autoreleasepool {
        NSData *data=[NSData dataWithBytes:raw length:(NSUInteger)bytes];
        NSDictionary *event=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        assert([event[@"kind"] isEqual:@"health"]);
        assert([event[@"sequence"] isEqual:@"1"]);
        assert([event[@"reason_code"] isEqual:@"aidr_enforcement_control_disconnected"]);
      }
      puts("aidr_collection_supervisor_eof_passed_without_es");
      return 0;
    }
    assert(ended==0);
    usleep(10000);
  }
  kill(child,SIGKILL);waitpid(child,&status,0);
  assert(!"production control reader did not return after owner disconnect");
  return 1;
}

int main(void) {
  if(check_mode(true)!=0)return 1;
  return check_mode(false);
}
