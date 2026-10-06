#include <stdio.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc < 5 || argv[1][0] == '\0') { fprintf(stderr, "usage: agent-launcher NONCE BOUND CLI [ARGS...]\n"); return 64; }
    struct stat marker; struct timespec pause={.tv_sec=0,.tv_nsec=10000000};
    int bound=0; for(int i=0;i<500;i++){ if(stat(argv[2],&marker)==0){bound=1;break;} nanosleep(&pause,NULL); }
    if(!bound){fprintf(stderr,"agent root registration timeout\n");return 75;}
    execv(argv[3], &argv[3]);
    perror("execv agent CLI");
    return 71;
}
