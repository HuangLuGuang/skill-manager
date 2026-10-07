CC := xcrun --sdk macosx clang
CFLAGS := -std=c17 -O2 -Wall -Wextra -Werror -mmacosx-version-min=13.0
BUILD := build
.PHONY: test
all: $(BUILD)/aidr-enforcer $(BUILD)/policy-check $(BUILD)/test-identity $(BUILD)/test-collection $(BUILD)/test-supervisor $(BUILD)/lifecycle-probe
$(BUILD):
	mkdir -p $@
$(BUILD)/test-identity: identity.c identity.h test_identity.c | $(BUILD)
	$(CC) $(CFLAGS) identity.c test_identity.c -o $@
test: $(BUILD)/test-network $(BUILD)/test-identity $(BUILD)/test-collection $(BUILD)/test-supervisor $(BUILD)/test-events
	$(abspath $(BUILD))/test-network
	$(abspath $(BUILD))/test-identity
	$(abspath $(BUILD))/test-collection
	$(abspath $(BUILD))/test-supervisor
	$(abspath $(BUILD))/test-events
$(BUILD)/test-events: test_events.m enforcer.m network.m network.h identity.c identity.h policy.m policy.h collection.m collection.h ../../experiments/macos-es-poc/src/bounded_log.c | $(BUILD)
	$(CC) $(CFLAGS) -fobjc-arc -framework Foundation -framework Security -lEndpointSecurity -lbsm test_events.m network.m identity.c policy.m collection.m ../../experiments/macos-es-poc/src/bounded_log.c -o $@
$(BUILD)/test-supervisor: test_supervisor.m enforcer.m network.m network.h identity.c identity.h policy.m policy.h collection.m collection.h ../../experiments/macos-es-poc/src/bounded_log.c | $(BUILD)
	$(CC) $(CFLAGS) -fobjc-arc -framework Foundation -framework Security -lEndpointSecurity -lbsm test_supervisor.m network.m identity.c policy.m collection.m ../../experiments/macos-es-poc/src/bounded_log.c -o $@
$(BUILD)/test-collection: collection.m collection.h test_collection.m policy.m policy.h | $(BUILD)
	$(CC) $(CFLAGS) -fobjc-arc -framework Foundation -framework Security policy.m collection.m test_collection.m -o $@
$(BUILD)/policy-check: policy.m policy.h policy_check.m collection.m collection.h | $(BUILD)
	$(CC) $(CFLAGS) -fobjc-arc -framework Foundation -framework Security policy.m collection.m policy_check.m -o $@
$(BUILD)/aidr-enforcer: enforcer.m network.m network.h identity.c identity.h policy.m policy.h collection.m collection.h ../../experiments/macos-es-poc/src/bounded_log.c | $(BUILD)
	$(CC) $(CFLAGS) -fobjc-arc -framework Foundation -framework Security -lEndpointSecurity -lbsm enforcer.m network.m identity.c policy.m collection.m ../../experiments/macos-es-poc/src/bounded_log.c -o $@
$(BUILD)/lifecycle-probe: lifecycle_probe.c | $(BUILD)
	$(CC) $(CFLAGS) $< -o $@
adhoc-sign: $(BUILD)/aidr-enforcer $(BUILD)/lifecycle-probe
	codesign --force --sign - --entitlements ../../experiments/macos-es-poc/entitlements.plist $<
	codesign --force --sign - $(BUILD)/lifecycle-probe

$(BUILD)/test-network: network.m network.h identity.h test_network.m enforcer.m identity.c policy.m policy.h collection.m collection.h ../../experiments/macos-es-poc/src/bounded_log.c | $(BUILD)
	$(CC) $(CFLAGS) -fobjc-arc -framework Foundation -framework Security -lEndpointSecurity -lbsm network.m test_network.m identity.c policy.m collection.m ../../experiments/macos-es-poc/src/bounded_log.c -o $@
