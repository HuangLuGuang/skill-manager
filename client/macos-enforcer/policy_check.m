#import "policy.h"
#include <stdio.h>
int main(int argc,char **argv){
  @autoreleasepool {
    if(argc!=4)return 64;
    NSData *envelope=[NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]];
    NSData *key=[NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[2]]];
    NSString *reason;NSDictionary *value=aidr_verify_envelope(envelope,key,&reason);
    aidr_policy *policy=calloc(1,sizeof(*policy));
    bool ok=value && aidr_compile_policy(value,[NSString stringWithUTF8String:argv[3]],false,policy,&reason);
    printf("%s\n",ok?"aidr_enforcement_policy_valid":reason.UTF8String);free(policy);return ok?0:1;
  }
}
