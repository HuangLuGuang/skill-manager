#import "network.h"
#include <arpa/inet.h>
#include <errno.h>
#include <libproc.h>
#include <sys/socket.h>

bool aidr_network_identity_matches(aidr_identity process) {
  if (!process.valid) return false;
  audit_token_t token; memcpy(token.val, process.token, sizeof(token.val));
  char path[PROC_PIDPATHINFO_MAXSIZE];
  struct proc_bsdinfo info;
  // Apple's proc_pidpath_audittoken compares the process idversion in kernel.
  return proc_pidpath_audittoken(&token, path, sizeof(path)) > 0 &&
    proc_pidinfo(process.token[5], PROC_PIDTBSDINFO, 0, &info, sizeof(info)) == sizeof(info) &&
    info.pbi_start_tvsec * 1000000 + info.pbi_start_tvusec == process.start_us;
}

NSArray<NSDictionary *> *aidr_network_snapshot(aidr_identity process, NSString **status) {
  *status = @"partial";
  errno = 0;
  if (!aidr_network_identity_matches(process)) {
    if (errno == EPERM || errno == EACCES) *status = @"permission_denied";
    return @[];
  }
  // Bounded per-process work. An inventory at capacity is explicitly partial.
  struct proc_fdinfo fds[1024];
  errno = 0;
  int size = proc_pidinfo(process.token[5], PROC_PIDLISTFDS, 0, fds, sizeof(fds));
  if (size < 0) { if (errno == EPERM || errno == EACCES) *status = @"permission_denied"; return @[]; }
  if (size == 0 && errno) { if (errno == EPERM || errno == EACCES) *status = @"permission_denied"; return @[]; }
  *status = size >= (int)sizeof(fds) ? @"partial" : @"sampled";
  NSMutableArray *records = [NSMutableArray array];
  for (size_t i=0; i<(size_t)size/sizeof(fds[0]); i++) {
    if (fds[i].proc_fdtype != PROX_FDTYPE_SOCKET) continue;
    struct socket_fdinfo fd;
    if (proc_pidfdinfo(process.token[5], fds[i].proc_fd, PROC_PIDFDSOCKETINFO, &fd, sizeof(fd)) != sizeof(fd)) {
      if (![*status isEqual:@"permission_denied"]) *status = (errno == EPERM || errno == EACCES) ? @"permission_denied" : @"partial"; continue;
    }
    struct socket_info *s = &fd.psi;
    bool tcp = s->soi_kind == SOCKINFO_TCP && s->soi_protocol == IPPROTO_TCP;
    bool udp = s->soi_kind == SOCKINFO_IN && s->soi_protocol == IPPROTO_UDP;
    if ((!tcp && !udp) || (s->soi_family != AF_INET && s->soi_family != AF_INET6)) continue;
    struct in_sockinfo *in = tcp ? &s->soi_proto.pri_tcp.tcpsi_ini : &s->soi_proto.pri_in;
    // Exclude listeners and unconnected UDP sockets: neither identifies a peer.
    if (!in->insi_fport || (tcp && s->soi_proto.pri_tcp.tcpsi_state == TSI_S_LISTEN)) continue;
    int family = in->insi_vflag & INI_IPV4 ? AF_INET : AF_INET6;
    char local[INET6_ADDRSTRLEN], remote[INET6_ADDRSTRLEN];
    if (!inet_ntop(family, family == AF_INET ? (void *)&in->insi_laddr.ina_46.i46a_addr4 : (void *)&in->insi_laddr.ina_6, local, sizeof(local)) ||
        !inet_ntop(family, family == AF_INET ? (void *)&in->insi_faddr.ina_46.i46a_addr4 : (void *)&in->insi_faddr.ina_6, remote, sizeof(remote))) continue;
    NSArray *states = @[@"closed", @"listen", @"syn_sent", @"syn_received", @"established", @"close_wait", @"fin_wait_1", @"closing", @"last_ack", @"fin_wait_2", @"time_wait"];
    int state = tcp ? s->soi_proto.pri_tcp.tcpsi_state : -1;
    NSString *stateName = state >= 0 && state < (int)states.count ? states[state] : @"unknown";
    // Opaque kernel identifiers are used only locally; never upload addresses.
    NSString *key = [NSString stringWithFormat:@"%llu:%llu:%llu:%s:%d:%s:%d", s->soi_so, s->soi_pcb, in->insi_gencnt, local, in->insi_lport, remote, in->insi_fport];
    if (!in->insi_gencnt) key = NSUUID.UUID.UUIDString;
    [records addObject:@{@"key":key, @"source":@"libproc_snapshot", @"protocol":tcp?@"tcp":@"udp", @"direction":@"unknown",
      @"local_ip":@(local), @"local_port":@(ntohs((uint16_t)in->insi_lport)), @"remote_ip":@(remote), @"remote_port":@(ntohs((uint16_t)in->insi_fport)), @"state":stateName}];
  }
  // Discard the complete batch if exec/exit/PID reuse raced the read.
  if (!aidr_network_identity_matches(process)) { *status = @"partial"; return @[]; }
  return records;
}
