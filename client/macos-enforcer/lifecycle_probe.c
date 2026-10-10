// Independent bounded workload: expected child PIDs and wait statuses come
// from the parent, not from the sensor under test.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
int main(int argc,char **argv){
  if(argc==2 && !strcmp(argv[1],"--sleep")){execl("/bin/sleep","sleep","30",NULL);return 127;}
  if(argc==2 && !strcmp(argv[1],"--orphan")){
    pid_t p=fork();if(p<0)return 1;
    if(p==0){struct timespec wait={.tv_sec=0,.tv_nsec=200000000};nanosleep(&wait,NULL);execl("/bin/sleep","sleep","1",NULL);_exit(127);}
    printf("%d\n",p);return 0;
  }
  if(argc!=2 || strcmp(argv[1],"--thousand"))return 64;
  for(int batch=0;batch<40;batch++){
    pid_t children[25];
    for(int i=0;i<25;i++){
      pid_t p=fork();if(p<0)return 1;
      if(p==0){execl("/usr/bin/true","true",NULL);_exit(127);}
      children[i]=p;printf("%d\n",p);
    }
    fflush(stdout);
    for(int i=0;i<25;i++){int status;if(waitpid(children[i],&status,0)!=children[i] || !WIFEXITED(status) || WEXITSTATUS(status)!=0)return 1;}
  }
  return 0;
}
