#pragma once
#import <Foundation/Foundation.h>
#include <stdbool.h>
#include <stdint.h>
#include <sys/types.h>

#define AIDR_RULE_MAX 128
#define AIDR_ROOT_MAX 32
typedef struct {
  char path[1024], id[65];
  dev_t device; ino_t inode;
  bool agent_only, deny;
} aidr_rule;
#define AIDR_ROOT_HASH_MAX 64
typedef struct {char path[1024];dev_t device;ino_t inode;size_t hash_count;unsigned char cdhashes[AIDR_ROOT_HASH_MAX][20];} aidr_root_image;
typedef struct {
  uint64_t revision, expires;
  bool unknown_deny, expired_deny;
  size_t rule_count, root_count;
  aidr_rule rules[AIDR_RULE_MAX];
  aidr_root_image roots[AIDR_ROOT_MAX];
} aidr_policy;

NSDictionary *aidr_verify_envelope(NSData *envelope, NSData *public_key, NSString **reason);
bool aidr_equal_envelopes(NSData *first, NSData *second);
bool aidr_compile_policy(NSDictionary *value, NSString *device, bool restore_expired,
                         aidr_policy *output, NSString **reason);
bool aidr_compile_attribution(NSDictionary *value, NSString *device, bool restore_expired,
                              aidr_policy *output, NSString **reason);
bool aidr_decimal(id value, uint64_t *out);
