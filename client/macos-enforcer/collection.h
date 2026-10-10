#ifndef AIDR_COLLECTION_H
#define AIDR_COLLECTION_H

#include <EndpointSecurity/EndpointSecurity.h>
#include "policy.h"

// Collection retains verified executable selectors, with no authorization or
// response authority. The original signed envelope stays independently valid.
void aidr_collection_project(aidr_policy *policy);
#define AIDR_COLLECTION_EVENT_COUNT 8
size_t aidr_collection_events(es_event_type_t events[AIDR_COLLECTION_EVENT_COUNT], bool collection_only);
bool aidr_collection_input(NSString *type, bool collection_only);
const char *aidr_collection_cache(bool collection_only);

#endif
