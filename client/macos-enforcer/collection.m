#import "collection.h"
#include <string.h>

void aidr_collection_project(aidr_policy *policy) {
  policy->rule_count=0;
  memset(policy->rules,0,sizeof(policy->rules));
  policy->unknown_deny=false;
  policy->expired_deny=false;
}

size_t aidr_collection_events(es_event_type_t events[4],bool collection_only) {
  events[0]=ES_EVENT_TYPE_NOTIFY_FORK;
  events[1]=ES_EVENT_TYPE_NOTIFY_EXEC;
  events[2]=ES_EVENT_TYPE_NOTIFY_EXIT;
  if(collection_only)return 3;
  events[3]=ES_EVENT_TYPE_AUTH_OPEN;
  return 4;
}

bool aidr_collection_input(NSString *type,bool collection_only) {
  if([type isEqual:@"health"])return true;
  return collection_only?[type isEqual:@"attribution"]:([type isEqual:@"policy"] || [type isEqual:@"terminate"]);
}

const char *aidr_collection_cache(bool collection_only) {
  return collection_only?"collection-policy.json":"policy.json";
}
