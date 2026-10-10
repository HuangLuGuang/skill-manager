#import "policy.h"
#import "collection.h"
#import <Security/Security.h>
#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>
#include <mach-o/fat.h>
#include <libkern/OSByteOrder.h>

bool aidr_decimal(id value,uint64_t *out) {
  if (![value isKindOfClass:NSString.class]) return false;
  const char *s=[value UTF8String];size_t n=strlen(s);
  if(!n || n>20 || (n>1 && s[0]=='0'))return false;
  for(size_t i=0;i<n;i++)if(s[i]<'0'||s[i]>'9')return false;
  errno=0;char *end;unsigned long long result=strtoull(s,&end,10);
  if(errno || *end)return false;*out=result;return true;
}
static bool keys(NSDictionary *value,NSArray *allowed) {
  if(![value isKindOfClass:NSDictionary.class] || value.count!=allowed.count)return false;
  for(id key in value)if(![allowed containsObject:key])return false;
  return true;
}
bool aidr_equal_envelopes(NSData *first,NSData *second) {
  NSDictionary *a=[NSJSONSerialization JSONObjectWithData:first options:0 error:nil];
  NSDictionary *b=[NSJSONSerialization JSONObjectWithData:second options:0 error:nil];
  return keys(a,@[@"payload",@"signature"]) && keys(b,@[@"payload",@"signature"]) &&
    [a[@"payload"] isKindOfClass:NSString.class] && [a[@"signature"] isKindOfClass:NSString.class] && [a isEqual:b];
}
NSDictionary *aidr_verify_envelope(NSData *envelope,NSData *public_key,NSString **reason) {
  *reason=@"aidr_enforcement_signature_invalid";
  if(envelope.length>65536 || public_key.length!=65)return nil;
  NSDictionary *outer=[NSJSONSerialization JSONObjectWithData:envelope options:0 error:nil];
  if(!keys(outer,@[@"payload",@"signature"]) || ![outer[@"payload"] isKindOfClass:NSString.class] || ![outer[@"signature"] isKindOfClass:NSString.class])return nil;
  NSData *payload=[[NSData alloc] initWithBase64EncodedString:outer[@"payload"] options:0];
  NSData *signature=[[NSData alloc] initWithBase64EncodedString:outer[@"signature"] options:0];
  if(!payload || !signature)return nil;
  NSDictionary *attributes=@{(__bridge id)kSecAttrKeyType:(__bridge id)kSecAttrKeyTypeECSECPrimeRandom,(__bridge id)kSecAttrKeyClass:(__bridge id)kSecAttrKeyClassPublic,(__bridge id)kSecAttrKeySizeInBits:@256};
  SecKeyRef key=SecKeyCreateWithData((__bridge CFDataRef)public_key,(__bridge CFDictionaryRef)attributes,NULL);
  if(!key)return nil;
  bool valid=SecKeyVerifySignature(key,kSecKeyAlgorithmECDSASignatureMessageX962SHA256,(__bridge CFDataRef)payload,(__bridge CFDataRef)signature,NULL);CFRelease(key);
  if(!valid)return nil;
  id value=[NSJSONSerialization JSONObjectWithData:payload options:0 error:nil];
  if(![value isKindOfClass:NSDictionary.class])return nil;
  return value;
}
static bool decision(id value,bool *deny) {
  if([value isEqual:@"deny"]){*deny=true;return true;}
  if([value isEqual:@"allow"]){*deny=false;return true;}
  return false;
}
static bool path_value(id value,char output[1024]) {
  if(![value isKindOfClass:NSString.class])return false;
  const char *p=[value UTF8String];size_t n=strlen(p);
  if(n<2 || n>=1024 || p[0]!='/')return false;
  for(size_t i=0;i<n;i++)if((unsigned char)p[i]<32)return false;
  strlcpy(output,p,1024);return true;
}
static bool file(id value,char output[1024],struct stat *info) {
  if(!path_value(value,output))return false;
  const char *p=output;
  // Existing regular resources give an inode anchor for hard-link aliases.
  // Compilation resolves links once; callbacks never perform path I/O.
  char resolved[PATH_MAX];if(!realpath(p,resolved) || strlen(resolved)>=1024 || stat(resolved,info)!=0 || !S_ISREG(info->st_mode))return false;
  strlcpy(output,resolved,1024);return true;
}
static bool codehash_slice(const char *path,NSNumber *offset,aidr_root_image *output) {
  NSURL *url=[NSURL fileURLWithPath:[NSString stringWithUTF8String:path]];
  SecStaticCodeRef code=NULL;
  NSDictionary *attributes=offset?@{(__bridge id)kSecCodeAttributeUniversalFileOffset:offset}:@{};
  if(SecStaticCodeCreateWithPathAndAttributes((__bridge CFURLRef)url,kSecCSDefaultFlags,(__bridge CFDictionaryRef)attributes,&code)!=errSecSuccess)return false;
  CFDictionaryRef raw=NULL;bool valid=false;
  if(SecStaticCodeCheckValidity(code,kSecCSStrictValidate,NULL)==errSecSuccess && SecCodeCopySigningInformation(code,kSecCSSigningInformation,&raw)==errSecSuccess){
    NSDictionary *info=CFBridgingRelease(raw);NSArray *hashes=info[(__bridge id)kSecCodeInfoCdHashes];
    if(!hashes)hashes=@[info[(__bridge id)kSecCodeInfoUnique]?:NSData.data];
    valid=hashes.count>0;
    for(NSData *hash in hashes){
      if(![hash isKindOfClass:NSData.class] || hash.length!=20){valid=false;break;}
      bool duplicate=false;for(size_t i=0;i<output->hash_count;i++)if(!memcmp(output->cdhashes[i],hash.bytes,20))duplicate=true;
      if(!duplicate){if(output->hash_count==AIDR_ROOT_HASH_MAX){valid=false;break;}memcpy(output->cdhashes[output->hash_count++],hash.bytes,20);}
    }
  }
  CFRelease(code);return valid;
}
static bool codehash(const char *path,aidr_root_image *output){
  // Kernel-selected universal slices need not match Security.framework's
  // default architecture. Validate each bounded slice and pin its digests.
  int fd=open(path,O_RDONLY|O_CLOEXEC);if(fd<0)return false;
  struct fat_header header;ssize_t n=pread(fd,&header,sizeof(header),0);
  if(n!=sizeof(header)){close(fd);return false;}
  uint32_t magic=OSSwapBigToHostInt32(header.magic);
  if(magic!=FAT_MAGIC && magic!=FAT_MAGIC_64){close(fd);return codehash_slice(path,nil,output);}
  uint32_t count=OSSwapBigToHostInt32(header.nfat_arch);if(!count || count>16){close(fd);return false;}
  bool valid=true;
  for(uint32_t i=0;i<count;i++){
    uint64_t offset;
    if(magic==FAT_MAGIC_64){struct fat_arch_64 arch;if(pread(fd,&arch,sizeof(arch),sizeof(header)+(off_t)i*sizeof(arch))!=sizeof(arch)){valid=false;break;}offset=OSSwapBigToHostInt64(arch.offset);}
    else{struct fat_arch arch;if(pread(fd,&arch,sizeof(arch),sizeof(header)+(off_t)i*sizeof(arch))!=sizeof(arch)){valid=false;break;}offset=OSSwapBigToHostInt32(arch.offset);}
    if(!codehash_slice(path,@(offset),output)){valid=false;break;}
  }
  close(fd);return valid && output->hash_count>0;
}
static bool compile(NSDictionary *value,NSString *device,bool restore,bool collection_only,aidr_policy *p,NSString **reason) {
  *reason=@"aidr_enforcement_policy_invalid";memset(p,0,sizeof(*p));uint64_t issued;
  if(!keys(value,@[@"schema",@"device",@"revision",@"issued_at",@"expires_at",@"unknown_actor_action",@"expired_action",@"agent_executables",@"rules"]) || ![value[@"schema"] isEqual:@1] || ![value[@"device"] isEqual:device] || !aidr_decimal(value[@"revision"],&p->revision) || !p->revision || !aidr_decimal(value[@"issued_at"],&issued) || !aidr_decimal(value[@"expires_at"],&p->expires) || p->expires<=issued || p->expires-issued>30*86400 || issued>(uint64_t)time(NULL)+60 || (!restore && p->expires<=(uint64_t)time(NULL)) || !decision(value[@"unknown_actor_action"],&p->unknown_deny) || !decision(value[@"expired_action"],&p->expired_deny))return false;
  NSArray *roots=value[@"agent_executables"],*rules=value[@"rules"];
  if(![roots isKindOfClass:NSArray.class] || ![rules isKindOfClass:NSArray.class] || roots.count>AIDR_ROOT_MAX || rules.count>AIDR_RULE_MAX)return false;
  NSMutableSet *seen=[NSMutableSet set];
  for(id path in roots){
    aidr_root_image *root=&p->roots[p->root_count];struct stat info;
    *reason=@"aidr_enforcement_root_invalid";
    if(!file(path,root->path,&info) || !codehash(root->path,root))return false;
    NSString *canonical=[NSString stringWithUTF8String:root->path];if([seen containsObject:canonical])return false;[seen addObject:canonical];
    root->device=info.st_dev;root->inode=info.st_ino;p->root_count++;
  }
  [seen removeAllObjects];
  for(NSDictionary *rule in rules){
    *reason=@"aidr_enforcement_rule_invalid";aidr_rule *target=&p->rules[p->rule_count];struct stat info={0};
    if(!keys(rule,@[@"id",@"path",@"actor",@"decision"]) || ![rule[@"id"] isKindOfClass:NSString.class] || [rule[@"id"] length]<1 || [rule[@"id"] length]>64 || [seen containsObject:rule[@"id"]] || !decision(rule[@"decision"],&target->deny) || !(collection_only?path_value(rule[@"path"],target->path):file(rule[@"path"],target->path,&info)))return false;
    const char *ident=[rule[@"id"] UTF8String];for(const char *c=ident;*c;c++)if(!((*c>='a'&&*c<='z')||(*c>='A'&&*c<='Z')||(*c>='0'&&*c<='9')||*c=='-'||*c=='_'))return false;
    if([rule[@"actor"] isEqual:@"agent"])target->agent_only=true;
    else if(![rule[@"actor"] isEqual:@"all"])return false;
    strlcpy(target->id,ident,sizeof(target->id));target->device=info.st_dev;target->inode=info.st_ino;p->rule_count++;[seen addObject:rule[@"id"]];
  }
  return true;
}

bool aidr_compile_policy(NSDictionary *value,NSString *device,bool restore,aidr_policy *p,NSString **reason) {
  return compile(value,device,restore,false,p,reason);
}
bool aidr_compile_attribution(NSDictionary *value,NSString *device,bool restore,aidr_policy *p,NSString **reason) {
  bool ok=compile(value,device,restore,true,p,reason);
  if(ok)aidr_collection_project(p);
  return ok;
}
