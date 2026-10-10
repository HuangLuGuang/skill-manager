#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static int read_once(const char *path) {
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return errno;
    char byte;
    ssize_t result = read(fd, &byte, sizeof(byte));
    int saved = result < 0 ? errno : 0;
    close(fd);
    return saved;
}

int main(int argc, char **argv) {
    if (argc == 3 && strcmp(argv[1], "--read-once") == 0) {
        int error = read_once(argv[2]);
        printf("{\"pid\":%d,\"read_success\":%s,\"errno\":%d}\n", getpid(), error == 0 ? "true" : "false", error);
        return error == 0 ? 0 : 1;
    }
    if (argc != 6 || strcmp(argv[1], "--check") != 0) {
        fprintf(stderr, "usage: %s --check PROTECTED ALLOWED ITERATIONS BOUND_MARKER\n", argv[0]);
        return 64;
    }
    char *end = NULL;
    long iterations = strtol(argv[4], &end, 10);
    if (!end || *end != '\0' || iterations < 1 || iterations > 10000) {
        fprintf(stderr, "invalid iteration count\n");
        return 64;
    }

    struct timespec interval = {.tv_sec = 0, .tv_nsec = 10000000};
    struct stat marker;
    int bound = 0;
    for (int i = 0; i < 500; i++) {
        if (stat(argv[5], &marker) == 0 && S_ISREG(marker.st_mode)) { bound = 1; break; }
        nanosleep(&interval, NULL);
    }
    if (!bound) { fprintf(stderr, "process-instance binding timeout\n"); return 75; }

    long denied = 0, unexpected_protected_success = 0, allowed = 0, allowed_failures = 0;
    int last_denied_errno = 0;
    for (long i = 0; i < iterations; i++) {
        int error = read_once(argv[2]);
        if (error == EACCES || error == EPERM) {
            denied++;
            last_denied_errno = error;
        } else if (error == 0) {
            unexpected_protected_success++;
        }
    }
    for (long i = 0; i < iterations; i++) {
        int error = read_once(argv[3]);
        if (error == 0) allowed++;
        else allowed_failures++;
    }

    printf("{\"pid\":%d,\"protected_denied\":%ld,\"protected_unexpected_success\":%ld,"
           "\"allowed_success\":%ld,\"allowed_failures\":%ld,\"last_denied_errno\":%d}\n",
           getpid(), denied, unexpected_protected_success, allowed, allowed_failures, last_denied_errno);
    return denied == iterations && allowed == iterations ? 0 : 1;
}
