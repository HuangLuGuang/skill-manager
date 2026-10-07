#pragma once
#import <Foundation/Foundation.h>
#include "identity.h"

// A successful read is a point-in-time socket inventory, not a flow lifecycle.
NSArray<NSDictionary *> *aidr_network_snapshot(aidr_identity process, NSString **status);
bool aidr_network_identity_matches(aidr_identity process);
