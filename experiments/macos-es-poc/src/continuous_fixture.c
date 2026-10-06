#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static int write_pid(const char *path, pid_t pid) {
  int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
  if (fd < 0)
    return -1;
  dprintf(fd, "%d\n", pid);
  return close(fd);
}

int main(int argc, char **argv) {
  if (argc != 4) {
    fprintf(stderr, "usage: %s GO_FILE PARENT_PID_FILE CHILD_PID_FILE\n",
            argv[0]);
    return 64;
  }
  if (write_pid(argv[2], getpid()) != 0) {
    perror("parent pid file");
    return 1;
  }
  for (int i = 0; i < 1000 && access(argv[1], F_OK) != 0; i++) {
    struct timespec pause = {.tv_sec = 0, .tv_nsec = 10000000};
    nanosleep(&pause, NULL);
  }
  if (access(argv[1], F_OK) != 0)
    return 75;
  pid_t child = fork();
  if (child < 0) {
    perror("fork");
    return 1;
  }
  if (child == 0) {
    if (write_pid(argv[3], getpid()) != 0)
      _exit(1);
    struct timespec pause = {.tv_sec = 0, .tv_nsec = 200000000};
    nanosleep(&pause, NULL);
    execl("/bin/sleep", "sleep", "1", NULL);
    _exit(127);
  }
  return 0;
}
