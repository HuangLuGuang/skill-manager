#import "collection.h"
#include <string.h>

void aidr_collection_project(aidr_policy *policy) {
  policy->rule_count=0;
  memset(policy->rules,0,sizeof(policy->rules));
  policy->unknown_deny=false;
  policy->expired_deny=false;
}

size_t aidr_collection_events(es_event_type_t events[AIDR_COLLECTION_EVENT_COUNT],bool collection_only) {
  events[0]=ES_EVENT_TYPE_NOTIFY_FORK;
  events[1]=ES_EVENT_TYPE_NOTIFY_EXEC;
  events[2]=ES_EVENT_TYPE_NOTIFY_EXIT;
  events[3]=ES_EVENT_TYPE_NOTIFY_CREATE;
  events[4]=ES_EVENT_TYPE_NOTIFY_CLOSE;
  events[5]=ES_EVENT_TYPE_NOTIFY_RENAME;
  events[6]=ES_EVENT_TYPE_NOTIFY_UNLINK;
  if(collection_only)return 7;
  events[7]=ES_EVENT_TYPE_AUTH_OPEN;
  return 8;
}

bool aidr_collection_input(NSString *type,bool collection_only) {
  if([type isEqual:@"health"])return true;
  return collection_only?[type isEqual:@"attribution"]:([type isEqual:@"policy"] || [type isEqual:@"terminate"]);
}

const char *aidr_collection_cache(bool collection_only) {
  return collection_only?"collection-policy.json":"policy.json";
}
