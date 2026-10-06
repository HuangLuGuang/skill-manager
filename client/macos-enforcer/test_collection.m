#import "collection.h"
#import <Security/Security.h>
#include <assert.h>
#include <string.h>
#include <stdlib.h>

int main(void) {
  @autoreleasepool {
    aidr_policy *policy=calloc(1,sizeof(*policy));
    assert(policy);
    policy->revision=7;
    policy->expires=1800000000;
    policy->root_count=1;
    strcpy(policy->roots[0].path,"/fixture/agent");
    policy->roots[0].device=11;
    policy->roots[0].inode=22;
    policy->roots[0].hash_count=1;
    memset(policy->roots[0].cdhashes[0],0x5a,20);
    policy->rule_count=2;
    policy->rules[0].deny=true;
    policy->unknown_deny=policy->expired_deny=true;
    aidr_root_image root=policy->roots[0];
    aidr_collection_project(policy);
    assert(policy->rule_count==0 && !policy->unknown_deny && !policy->expired_deny);
    assert(policy->revision==7 && policy->expires==1800000000 && policy->root_count==1 && !memcmp(&root,&policy->roots[0],sizeof(root)));
    aidr_rule empty={0};
    for(size_t i=0;i<128;i++)assert(!memcmp(&empty,&policy->rules[i],sizeof(empty)));
    es_event_type_t events[4];
    size_t count=aidr_collection_events(events,true);
    assert(count==3);
    for(size_t i=0;i<count;i++)assert(events[i]!=ES_EVENT_TYPE_AUTH_OPEN);
    assert(events[0]==ES_EVENT_TYPE_NOTIFY_FORK && events[1]==ES_EVENT_TYPE_NOTIFY_EXEC && events[2]==ES_EVENT_TYPE_NOTIFY_EXIT);
    assert(aidr_collection_input(@"attribution",true));
    assert(aidr_collection_input(@"health",true));
    assert(!aidr_collection_input(@"policy",true) && !aidr_collection_input(@"terminate",true));
    assert(aidr_collection_input(@"policy",false) && aidr_collection_input(@"terminate",false));
    assert(!aidr_collection_input(@"attribution",false));
    assert(strcmp(aidr_collection_cache(true),aidr_collection_cache(false)));
    assert(aidr_collection_events(events,false)==4 && events[3]==ES_EVENT_TYPE_AUTH_OPEN);
    NSString *missing=[@"/private/tmp/aidr-collection-" stringByAppendingString:NSUUID.UUID.UUIDString];
    uint64_t now=(uint64_t)NSDate.date.timeIntervalSince1970;
    NSDictionary *input=@{@"schema":@1,@"device":@"fixture",@"revision":@"9",
      @"issued_at":[NSString stringWithFormat:@"%llu",(unsigned long long)(now-1)],
      @"expires_at":[NSString stringWithFormat:@"%llu",(unsigned long long)(now+600)],
      @"unknown_actor_action":@"deny",@"expired_action":@"deny",
      @"agent_executables":@[@"/usr/bin/true"],
      @"rules":@[@{@"id":@"absent",@"path":missing,@"actor":@"agent",@"decision":@"deny"}]};
    NSString *reason;
    SecKeyRef key=SecKeyCreateRandomKey((__bridge CFDictionaryRef)@{(__bridge id)kSecAttrKeyType:(__bridge id)kSecAttrKeyTypeECSECPrimeRandom,(__bridge id)kSecAttrKeySizeInBits:@256},NULL);
    assert(key);
    SecKeyRef public=SecKeyCopyPublicKey(key);
    NSData *public_data=CFBridgingRelease(SecKeyCopyExternalRepresentation(public,NULL));
    NSData *payload=[NSJSONSerialization dataWithJSONObject:input options:0 error:nil];
    NSData *signature=CFBridgingRelease(SecKeyCreateSignature(key,kSecKeyAlgorithmECDSASignatureMessageX962SHA256,(__bridge CFDataRef)payload,NULL));
    assert(signature);
    NSMutableDictionary *envelope=[@{@"payload":[payload base64EncodedStringWithOptions:0],@"signature":[signature base64EncodedStringWithOptions:0]} mutableCopy];
    NSData *wire=[NSJSONSerialization dataWithJSONObject:envelope options:0 error:nil];
    NSData *formatted=[NSJSONSerialization dataWithJSONObject:envelope options:NSJSONWritingPrettyPrinted|NSJSONWritingSortedKeys error:nil];
    assert(aidr_equal_envelopes(wire,formatted));
    NSMutableDictionary *changed=[envelope mutableCopy];changed[@"signature"]=@"changed";
    assert(!aidr_equal_envelopes(wire,[NSJSONSerialization dataWithJSONObject:changed options:0 error:nil]));
    changed=[envelope mutableCopy];changed[@"payload"]=@"changed";
    assert(!aidr_equal_envelopes(wire,[NSJSONSerialization dataWithJSONObject:changed options:0 error:nil]));
    NSDictionary *verified=aidr_verify_envelope(wire,public_data,&reason);
    assert(verified && [verified[@"rules"] isEqual:input[@"rules"]]);
    assert(aidr_compile_attribution(verified,@"fixture",false,policy,&reason));
    assert(policy->rule_count==0 && policy->root_count==1);
    NSMutableDictionary *tampered=[input mutableCopy];tampered[@"device"]=@"other-device";
    envelope[@"payload"]=[[NSJSONSerialization dataWithJSONObject:tampered options:0 error:nil] base64EncodedStringWithOptions:0];
    wire=[NSJSONSerialization dataWithJSONObject:envelope options:0 error:nil];
    assert(!aidr_verify_envelope(wire,public_data,&reason));
    assert([reason isEqual:@"aidr_enforcement_signature_invalid"]);
    CFRelease(public);CFRelease(key);
    assert(!aidr_compile_policy(input,@"fixture",false,policy,&reason));
    assert([reason isEqual:@"aidr_enforcement_rule_invalid"]);
    assert(aidr_compile_attribution(input,@"fixture",false,policy,&reason));
    assert(policy->revision==9 && policy->expires==now+600 && policy->root_count==1 && policy->roots[0].hash_count>0);
    assert(policy->rule_count==0 && !policy->unknown_deny && !policy->expired_deny);
    assert(!aidr_compile_attribution(input,@"other-device",false,policy,&reason));
    NSMutableDictionary *invalid=[input mutableCopy];
    invalid[@"rules"]=@[@{@"id":@"bad",@"path":@"relative",@"actor":@"agent",@"decision":@"deny"}];
    assert(!aidr_compile_attribution(invalid,@"fixture",false,policy,&reason));
    free(policy);
    puts("aidr_collection_boundary_passed");
  }
  return 0;
}
