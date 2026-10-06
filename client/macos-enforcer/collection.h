#ifndef AIDR_COLLECTION_H
#define AIDR_COLLECTION_H

#include <EndpointSecurity/EndpointSecurity.h>
#include "policy.h"

// Collection retains verified executable selectors, with no authorization or
// response authority. The original signed envelope stays independently valid.
void aidr_collection_project(aidr_policy *policy);
size_t aidr_collection_events(es_event_type_t events[4], bool collection_only);
bool aidr_collection_input(NSString *type, bool collection_only);
const char *aidr_collection_cache(bool collection_only);

#endif
