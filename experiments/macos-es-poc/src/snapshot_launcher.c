#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern char **environ;
static volatile sig_atomic_t interrupted = 0;
static pid_t owned_child = 0;

static void stop(int signal_number) {
    (void)signal_number;
    interrupted = 1;
}

static long long monotonic_ms(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) return 0;
    return (long long)value.tv_sec * 1000 + value.tv_nsec / 1000000;
}

static void kill_and_reap(void) {
    if (owned_child <= 0) return;
    kill(owned_child, SIGKILL);
    while (waitpid(owned_child, NULL, 0) < 0 && errno == EINTR) {}
    owned_child = 0;
}

int main(int argc, char **argv) {
    if (argc < 4 || strcmp(argv[1], "--timeout-ms") != 0) {
        fprintf(stderr, "usage: %s --timeout-ms MILLISECONDS EXECUTABLE [ARG ...]\n", argv[0]);
        return 64;
    }
    char *end = NULL;
    long timeout_ms = strtol(argv[2], &end, 10);
    if (!end || *end != '\0' || timeout_ms < 100 || timeout_ms > 30000) return 64;
    struct sigaction action = {.sa_handler = stop};
    sigemptyset(&action.sa_mask);
    sigaction(SIGINT, &action, NULL); sigaction(SIGTERM, &action, NULL); sigaction(SIGHUP, &action, NULL);
    posix_spawnattr_t attr;
    if (posix_spawnattr_init(&attr) != 0 ||
        posix_spawnattr_setflags(&attr, POSIX_SPAWN_START_SUSPENDED) != 0) {
        perror("posix_spawnattr");
        return 70;
    }
    pid_t child = 0;
    int error = posix_spawn(&child, argv[3], NULL, &attr, &argv[3], environ);
    posix_spawnattr_destroy(&attr);
    if (error != 0) {
        fprintf(stderr, "posix_spawn: %s\n", strerror(error));
        return 71;
    }
    owned_child = child;
    printf("%d\n", child);
    fflush(stdout);
    struct pollfd input = {.fd = STDIN_FILENO, .events = POLLIN};
    int ready;
    do { ready = poll(&input, 1, (int)timeout_ms); } while (ready < 0 && errno == EINTR && !interrupted);
    char command = 0;
    if (interrupted || ready <= 0 || read(STDIN_FILENO, &command, 1) != 1 || command != 'c') {
        kill_and_reap();
        return 72;
    }
    if (kill(child, SIGCONT) != 0) {
        perror("SIGCONT");
        kill_and_reap();
        return 73;
    }
    int status = 0;
    long long deadline = monotonic_ms() + timeout_ms;
    for (;;) {
        pid_t waited = waitpid(child, &status, WNOHANG);
        if (waited == child) { owned_child = 0; break; }
        if (waited < 0 && errno != EINTR) { perror("waitpid"); kill_and_reap(); return 74; }
        if (interrupted || monotonic_ms() >= deadline) { kill_and_reap(); return interrupted ? 75 : 124; }
        struct timespec pause = {.tv_sec = 0, .tv_nsec = 10000000};
        nanosleep(&pause, NULL);
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    return 128 + (WIFSIGNALED(status) ? WTERMSIG(status) : 0);
}
