#import <EndpointSecurity/EndpointSecurity.h>
#import <Foundation/Foundation.h>
#import <bsm/libbsm.h>
#import <dispatch/dispatch.h>
#import <fcntl.h>
#import <libgen.h>
#import <mach/mach_time.h>
#import <os/lock.h>
#import <signal.h>
#import <stdatomic.h>
#import <stdio.h>
#import <stdlib.h>
#import <string.h>
#import <sys/stat.h>
#import <unistd.h>
#include "attribution.h"

typedef struct {
    pid_t pid;
    int pidversion;
    bool active;
} process_instance_t;

static es_client_t *g_client;
static dispatch_queue_t g_log_queue;
static dispatch_queue_t g_control_queue;
static dispatch_group_t g_log_group;
static dispatch_semaphore_t g_log_slots;
static _Atomic uint64_t g_dropped_logs;
static _Atomic uint64_t g_response_errors;
static os_unfair_lock g_identity_lock = OS_UNFAIR_LOCK_INIT;
static process_instance_t g_target = {0};
static char g_probe_path[PATH_MAX];
static char g_protected_path[PATH_MAX];
static char g_bound_path[PATH_MAX];
static bool g_agent_mode;
static char g_launcher_path[PATH_MAX];
static char g_registration_nonce[256];
static char g_agent_entry_path[PATH_MAX];
static bool g_registration_consumed;
static _Atomic uint64_t g_attribution_gaps;
static attribution_table_t *g_attributions;

static void copy_token(es_string_token_t token, char output[PATH_MAX]) {
    size_t length = token.length < PATH_MAX - 1 ? token.length : PATH_MAX - 1;
    if (length > 0 && token.data) memcpy(output, token.data, length);
    output[length] = '\0';
}

static bool canonical_parent(const char *path, char output[PATH_MAX]) {
    char copy[PATH_MAX];
    if (strlcpy(copy, path, sizeof(copy)) >= sizeof(copy)) return false;
    char *parent = dirname(copy);
    return parent && realpath(parent, output) != NULL;
}

static void emit_json(NSString *json) {
    if (dispatch_semaphore_wait(g_log_slots, DISPATCH_TIME_NOW) != 0) {
        atomic_fetch_add(&g_dropped_logs, 1);
        return;
    }
    dispatch_group_enter(g_log_group);
    dispatch_async(g_log_queue, ^{
        fprintf(stdout, "%s\n", json.UTF8String);
        fflush(stdout);
        dispatch_semaphore_signal(g_log_slots);
        dispatch_group_leave(g_log_group);
    });
}

static NSString *json_string(const char *value) {
    NSString *text = [NSString stringWithUTF8String:value ?: ""] ?: @"";
    NSData *data = [NSJSONSerialization dataWithJSONObject:@[text] options:0 error:nil];
    NSString *array = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
    return [array substringWithRange:NSMakeRange(1, array.length - 2)];
}

static process_instance_t identity(const es_process_t *process) {
    audit_token_t token = process->audit_token;
    return (process_instance_t){
        .pid = audit_token_to_pid(token),
        .pidversion = audit_token_to_pidversion(token),
        .active = true,
    };
}

static process_key_t process_key(const es_process_t *process) {
    process_instance_t value = identity(process);
    return (process_key_t){.pid=value.pid, .version=value.pidversion};
}

static void log_attribution(const char *event, process_key_t key, attribution_t value, const char *path, bool entry_match) {
    emit_json([NSString stringWithFormat:
        @"{\"event\":\"attribution\",\"transition\":\"%s\",\"pid\":%d,\"pidversion\":%d,\"kind\":\"%s\",\"root_id\":%llu,\"root_pid\":%d,\"root_pidversion\":%d,\"path\":%@,\"agent_entry_match\":%s}",
        event, key.pid, key.version, attribution_name(value.kind), value.root_id, value.root.pid, value.root.version,
        json_string(path ?: ""), entry_match ? "true" : "false"]);
}

static bool same_instance(process_instance_t a, process_instance_t b) {
    return a.active && b.active && a.pid == b.pid && a.pidversion == b.pidversion;
}

static void log_lifecycle(const char *event, const es_process_t *process, pid_t parent_pid) {
    char path[PATH_MAX];
    copy_token(process->executable->path, path);
    process_instance_t instance = identity(process);
    uint64_t timestamp_ns = (uint64_t)([NSDate date].timeIntervalSince1970 * 1000000000.0);
    emit_json([NSString stringWithFormat:
        @"{\"event\":\"%s\",\"time_unix_ns\":%llu,\"pid\":%d,\"pidversion\":%d,\"parent_pid\":%d,\"path\":%@}",
        event, timestamp_ns, instance.pid, instance.pidversion, parent_pid, json_string(path)]);
}

static void handle_message(es_client_t *client, const es_message_t *message) {
    switch (message->event_type) {
        case ES_EVENT_TYPE_AUTH_OPEN: {
            process_instance_t actor = identity(message->process);
            char file_path[PATH_MAX];
            copy_token(message->event.open.file->path, file_path);
            bool target;
            os_unfair_lock_lock(&g_identity_lock);
            target = same_instance(actor, g_target);
            os_unfair_lock_unlock(&g_identity_lock);
            attribution_t attributed = g_agent_mode ? attribution_lookup(g_attributions, process_key(message->process)) : (attribution_t){0};
            if (g_agent_mode) target = attributed.kind == ATTR_DIRECT || attributed.kind == ATTR_INHERITED;
            bool protected_file = strcmp(file_path, g_protected_path) == 0;
            uint32_t authorized = target && protected_file ? 0 : UINT32_MAX;
            es_respond_result_t response = es_respond_flags_result(client, message, authorized, false);
            if (response != ES_RESPOND_RESULT_SUCCESS) atomic_fetch_add(&g_response_errors, 1);
            if (target && protected_file) {
                uint64_t now = mach_absolute_time();
                uint64_t remaining = message->deadline > now ? message->deadline - now : 0;
                emit_json([NSString stringWithFormat:
                    @"{\"event\":\"auth_open\",\"decision\":\"deny\",\"pid\":%d,\"pidversion\":%d,\"path\":%@,\"response\":%d,\"cache\":false,\"deadline_remaining_ticks\":%llu,\"attribution\":\"%s\",\"root_id\":%llu}",
                    actor.pid, actor.pidversion, json_string(file_path), response, remaining,
                    attribution_name(attributed.kind), attributed.root_id]);
            }
            break;
        }
        case ES_EVENT_TYPE_NOTIFY_EXEC: {
            const es_process_t *target = message->event.exec.target;
            char path[PATH_MAX];
            copy_token(target->executable->path, path);
            process_instance_t instance = identity(target);
            if (g_agent_mode) {
                process_key_t before = process_key(message->process), after = process_key(target);
                attribution_t previous = attribution_lookup(g_attributions, before);
                attribution_t attributed = attribution_exec(g_attributions, before, after);
                bool registration = strcmp(path, g_launcher_path) == 0;
                if (registration && es_exec_arg_count(&message->event.exec) > 1) {
                    char nonce[PATH_MAX]; copy_token(es_exec_arg(&message->event.exec, 1), nonce);
                    registration = strcmp(nonce, g_registration_nonce) == 0;
                } else registration = false;
                os_unfair_lock_lock(&g_identity_lock);
                if (g_registration_consumed) registration = false;
                if (registration) g_registration_consumed = true;
                os_unfair_lock_unlock(&g_identity_lock);
                bool entry_match = strcmp(path, g_agent_entry_path) == 0;
                if (registration) {
                    attributed = attribution_register_root(g_attributions, after);
                    dispatch_async(g_control_queue, ^{
                        int marker = open(g_bound_path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
                        if (marker >= 0) close(marker);
                    });
                }
                if ((registration || previous.kind != ATTR_UNKNOWN) && attributed.kind == ATTR_UNKNOWN)
                    atomic_fetch_add(&g_attribution_gaps, 1);
                log_attribution("exec", after, attributed, path, entry_match);
            }
            if (strcmp(path, g_probe_path) == 0) {
                os_unfair_lock_lock(&g_identity_lock);
                g_target = instance;
                os_unfair_lock_unlock(&g_identity_lock);
                dispatch_async(g_control_queue, ^{
                    int marker = open(g_bound_path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
                    if (marker >= 0) close(marker);
                });
            }
            log_lifecycle("exec", target, target->ppid);
            break;
        }
        case ES_EVENT_TYPE_NOTIFY_FORK:
            if (g_agent_mode) {
                process_key_t child = process_key(message->event.fork.child);
                attribution_t parent = attribution_lookup(g_attributions, process_key(message->process));
                attribution_t result = attribution_fork(g_attributions, process_key(message->process), child);
                if (parent.kind != ATTR_UNKNOWN && result.kind == ATTR_UNKNOWN) atomic_fetch_add(&g_attribution_gaps, 1);
                log_attribution("fork", child, result, "", false);
            }
            log_lifecycle("fork", message->event.fork.child, message->event.fork.child->ppid);
            break;
        case ES_EVENT_TYPE_NOTIFY_EXIT: {
            process_instance_t actor = identity(message->process);
            os_unfair_lock_lock(&g_identity_lock);
            if (same_instance(actor, g_target)) g_target = (process_instance_t){0};
            os_unfair_lock_unlock(&g_identity_lock);
            if (g_agent_mode) {
                process_key_t key = process_key(message->process);
                attribution_t attributed = attribution_lookup(g_attributions, key);
                log_attribution("exit", key, attributed, "", false);
                attribution_exit(g_attributions, key);
            }
            log_lifecycle("exit", message->process, message->process->ppid);
            break;
        }
        default:
            break;
    }
}

static const char *new_client_error(es_new_client_result_t result) {
    switch (result) {
        case ES_NEW_CLIENT_RESULT_ERR_NOT_ENTITLED: return "not entitled";
        case ES_NEW_CLIENT_RESULT_ERR_NOT_PERMITTED: return "not permitted (grant Full Disk Access)";
        case ES_NEW_CLIENT_RESULT_ERR_NOT_PRIVILEGED: return "not privileged (run as root)";
        case ES_NEW_CLIENT_RESULT_ERR_TOO_MANY_CLIENTS: return "too many ES clients";
        case ES_NEW_CLIENT_RESULT_ERR_INTERNAL: return "internal error";
        case ES_NEW_CLIENT_RESULT_ERR_INVALID_ARGUMENT: return "invalid argument";
        default: return "unknown error";
    }
}

int main(int argc, char **argv) {
    @autoreleasepool {
        bool observe = argc == 3 && strcmp(argv[1], "--observe") == 0;
        bool enforce = argc == 6 && strcmp(argv[1], "--enforce") == 0;
        g_agent_mode = argc == 8 && strcmp(argv[1], "--agent-enforce") == 0;
        if (!observe && !enforce && !g_agent_mode) {
            fprintf(stderr, "usage: %s --observe READY | --enforce PROBE PROTECTED READY BOUND | --agent-enforce LAUNCHER NONCE AGENT_ENTRY PROTECTED READY BOUND\n", argv[0]);
            return 64;
        }
        const char *ready_path = observe ? argv[2] : g_agent_mode ? argv[6] : argv[4];
        if (g_agent_mode) {
            if (!realpath(argv[2], g_launcher_path) || !realpath(argv[4], g_agent_entry_path) || !realpath(argv[5], g_protected_path) || strlen(argv[3]) >= sizeof(g_registration_nonce)) {
                perror("agent mode arguments"); return 66;
            }
            strlcpy(g_registration_nonce, argv[3], sizeof(g_registration_nonce));
            strlcpy(g_bound_path, argv[7], sizeof(g_bound_path));
            g_attributions = attribution_create();
            if (!g_attributions) return 70;
        }
        if (enforce && (!realpath(argv[2], g_probe_path) || !realpath(argv[3], g_protected_path))) {
            perror("realpath");
            return 66;
        }
        if (enforce || g_agent_mode) {
            int protectedIndex=g_agent_mode?5:3, readyIndex=g_agent_mode?6:4, boundIndex=g_agent_mode?7:5;
            char protectedDirectory[PATH_MAX], readyDirectory[PATH_MAX], boundDirectory[PATH_MAX];
            char protectedCopy[PATH_MAX];
            strlcpy(protectedCopy, argv[protectedIndex], sizeof(protectedCopy));
            const char *protectedName = basename(protectedCopy);
            struct stat file_info, directory_info;
            bool parents_resolved = canonical_parent(argv[protectedIndex], protectedDirectory) &&
                canonical_parent(argv[readyIndex], readyDirectory) &&
                canonical_parent(argv[boundIndex], boundDirectory);
            bool private_fixture = parents_resolved && strcmp(protectedName, "protected.txt") == 0 &&
                strcmp(protectedDirectory, readyDirectory) == 0 && strcmp(protectedDirectory, boundDirectory) == 0 &&
                lstat(argv[protectedIndex], &file_info) == 0 && S_ISREG(file_info.st_mode) &&
                stat(protectedDirectory, &directory_info) == 0 &&
                S_ISDIR(directory_info.st_mode) && (directory_info.st_mode & 0777) == 0700;
            if (!private_fixture) {
                fprintf(stderr, "enforce mode requires protected.txt, ready, and bound in one private 0700 directory\n");
                return 65;
            }
            strlcpy(g_bound_path, argv[boundIndex], sizeof(g_bound_path));
        }
        g_log_queue = dispatch_queue_create("macos-es-poc.log", DISPATCH_QUEUE_SERIAL);
        g_control_queue = dispatch_queue_create("macos-es-poc.control", DISPATCH_QUEUE_SERIAL);
        g_log_group = dispatch_group_create();
        g_log_slots = dispatch_semaphore_create(1024);
        es_new_client_result_t created = es_new_client(&g_client, ^(es_client_t *client, const es_message_t *message) {
            @autoreleasepool { handle_message(client, message); }
        });
        if (created != ES_NEW_CLIENT_RESULT_SUCCESS) {
            fprintf(stderr, "es_new_client failed: %s (%d)\n", new_client_error(created), created);
            return 77;
        }
        es_event_type_t notify_events[] = {ES_EVENT_TYPE_NOTIFY_FORK, ES_EVENT_TYPE_NOTIFY_EXEC, ES_EVENT_TYPE_NOTIFY_EXIT};
        es_event_type_t enforce_events[] = {ES_EVENT_TYPE_NOTIFY_FORK, ES_EVENT_TYPE_NOTIFY_EXEC, ES_EVENT_TYPE_NOTIFY_EXIT, ES_EVENT_TYPE_AUTH_OPEN};
        bool authorization = enforce || g_agent_mode;
        es_return_t subscribed = es_subscribe(g_client, authorization ? enforce_events : notify_events,
            authorization ? sizeof(enforce_events) / sizeof(enforce_events[0]) : sizeof(notify_events) / sizeof(notify_events[0]));
        if (subscribed != ES_RETURN_SUCCESS) {
            fprintf(stderr, "es_subscribe failed: %d\n", subscribed);
            es_delete_client(g_client);
            return 78;
        }
        int ready = open(ready_path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
        if (ready < 0) {
            perror("create ready file");
            es_unsubscribe_all(g_client);
            es_delete_client(g_client);
            return 73;
        }
        close(ready);
        fprintf(stderr, "READY mode=%s probe=%s protected=%s cache=false\n", g_agent_mode ? "agent-enforce" : enforce ? "enforce" : "observe", g_probe_path, g_protected_path);

        signal(SIGTERM, SIG_IGN);
        signal(SIGINT, SIG_IGN);
        dispatch_source_t term = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGTERM, 0, dispatch_get_main_queue());
        dispatch_source_t interrupt = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGINT, 0, dispatch_get_main_queue());
        void (^shutdown)(void) = ^{
            es_unsubscribe_all(g_client);
            es_delete_client(g_client);
            long drained = dispatch_group_wait(g_log_group, dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC));
            fprintf(stderr, "SUMMARY response_errors=%llu dropped_logs=%llu log_drain=%s\n",
                atomic_load(&g_response_errors), atomic_load(&g_dropped_logs), drained == 0 ? "complete" : "timeout");
            if (g_agent_mode) fprintf(stderr, "ATTRIBUTION gaps=%llu registration_consumed=%s\n",
                atomic_load(&g_attribution_gaps), g_registration_consumed ? "true" : "false");
            exit(0);
        };
        dispatch_source_set_event_handler(term, shutdown);
        dispatch_source_set_event_handler(interrupt, shutdown);
        dispatch_resume(term);
        dispatch_resume(interrupt);
        dispatch_main();
    }
}
