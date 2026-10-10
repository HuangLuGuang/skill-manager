SDKROOT := $(shell xcrun --sdk macosx --show-sdk-path)
CC := xcrun --sdk macosx clang
CFLAGS := -std=c17 -O2 -Wall -Wextra -Werror -mmacosx-version-min=13.0 -isysroot $(SDKROOT)
BUILD_DIR := build

.PHONY: all clean adhoc-sign fault-sign inspect-signature

all: $(BUILD_DIR)/es-monitor $(BUILD_DIR)/es-continuous-observer $(BUILD_DIR)/file-probe $(BUILD_DIR)/continuous-fixture $(BUILD_DIR)/agent-launcher $(BUILD_DIR)/snapshot-launcher $(BUILD_DIR)/test-attribution $(BUILD_DIR)/test-continuous-state $(BUILD_DIR)/test-continuous-faults $(BUILD_DIR)/test-bounded-log $(BUILD_DIR)/test-bounded-log-enospc

$(BUILD_DIR):
	mkdir -p $@

$(BUILD_DIR)/es-monitor: src/es_monitor.m src/attribution.c src/attribution.h entitlements.plist | $(BUILD_DIR)
	$(CC) $(CFLAGS) -fobjc-arc -lEndpointSecurity -lbsm -framework Foundation src/es_monitor.m src/attribution.c -o $@

$(BUILD_DIR)/es-continuous-observer: src/es_continuous_observer.m src/continuous_state.c src/continuous_state.h src/bounded_log.c src/bounded_log.h entitlements.plist | $(BUILD_DIR)
	$(CC) $(CFLAGS) -fobjc-arc -lEndpointSecurity -lbsm -framework Foundation src/es_continuous_observer.m src/continuous_state.c src/bounded_log.c -o $@

$(BUILD_DIR)/es-continuous-replay-test: src/es_continuous_observer.m src/continuous_state.c src/continuous_state.h src/bounded_log.c src/bounded_log.h entitlements.plist | $(BUILD_DIR)
	$(CC) $(CFLAGS) -fobjc-arc -DCONTINUOUS_FAULT_BUILD -DEVENT_CAPACITY=1024 -DFAULT_HOLD_MS=1500 '-DFAULT_MODE="replay"' -lEndpointSecurity -lbsm -framework Foundation src/es_continuous_observer.m src/continuous_state.c src/bounded_log.c -o $@

$(BUILD_DIR)/es-continuous-overflow-test: src/es_continuous_observer.m src/continuous_state.c src/continuous_state.h src/bounded_log.c src/bounded_log.h entitlements.plist | $(BUILD_DIR)
	$(CC) $(CFLAGS) -fobjc-arc -DCONTINUOUS_FAULT_BUILD -DFAULT_WAIT_OVERFLOW -DEVENT_CAPACITY=4 -DFAULT_HOLD_MS=1500 '-DFAULT_MODE="overflow"' -lEndpointSecurity -lbsm -framework Foundation src/es_continuous_observer.m src/continuous_state.c src/bounded_log.c -o $@

$(BUILD_DIR)/file-probe: src/file_probe.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) $< -o $@

$(BUILD_DIR)/continuous-fixture: src/continuous_fixture.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) $< -o $@

$(BUILD_DIR)/agent-launcher: src/agent_launcher.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) $< -o $@

$(BUILD_DIR)/snapshot-launcher: src/snapshot_launcher.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) $< -o $@

$(BUILD_DIR)/test-attribution: test_attribution.c src/attribution.c src/attribution.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) test_attribution.c src/attribution.c -o $@

$(BUILD_DIR)/test-continuous-state: test_continuous_state.c src/continuous_state.c src/continuous_state.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) test_continuous_state.c src/continuous_state.c -o $@

$(BUILD_DIR)/test-bounded-log: test_bounded_log.c src/bounded_log.c src/bounded_log.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) -DBOUNDED_LOG_TESTING test_bounded_log.c src/bounded_log.c -o $@

$(BUILD_DIR)/test-continuous-faults: test_continuous_faults.c src/continuous_state.c src/continuous_state.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) test_continuous_faults.c src/continuous_state.c -o $@

$(BUILD_DIR)/test-bounded-log-enospc: test_bounded_log_enospc.c src/bounded_log.c src/bounded_log.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) test_bounded_log_enospc.c -o $@

adhoc-sign: all
	codesign --force --sign - --entitlements entitlements.plist $(BUILD_DIR)/es-monitor
	codesign --force --sign - --entitlements entitlements.plist $(BUILD_DIR)/es-continuous-observer
	codesign --force --sign - $(BUILD_DIR)/file-probe
	codesign --force --sign - $(BUILD_DIR)/continuous-fixture
	codesign --force --sign - $(BUILD_DIR)/agent-launcher
	codesign --force --sign - $(BUILD_DIR)/snapshot-launcher
	codesign --force --sign - $(BUILD_DIR)/test-attribution
	codesign --force --sign - $(BUILD_DIR)/test-continuous-state
	codesign --force --sign - $(BUILD_DIR)/test-bounded-log
	codesign --force --sign - $(BUILD_DIR)/test-continuous-faults
	codesign --force --sign - $(BUILD_DIR)/test-bounded-log-enospc

fault-sign: $(BUILD_DIR)/es-continuous-replay-test $(BUILD_DIR)/es-continuous-overflow-test
	codesign --force --sign - --entitlements entitlements.plist $(BUILD_DIR)/es-continuous-replay-test
	codesign --force --sign - --entitlements entitlements.plist $(BUILD_DIR)/es-continuous-overflow-test

inspect-signature: all
	codesign --display --verbose=4 --entitlements :- $(BUILD_DIR)/es-monitor

clean:
	rm -rf $(BUILD_DIR)
