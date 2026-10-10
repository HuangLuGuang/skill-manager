# macOS runtime observation client

This package consumes protocol version 1 from the explicitly started macOS root relay. `agent-manager-client runtime-watch` runs without privilege and never sends commands, policy, paths, or process-selection requests to the relay.

Each transport connection starts with `reset=true`. The relay's `hello` declares `stream_start=late_join` and `attribution_baseline=unknown`; consumers must build state only from subsequent frames. Disconnect, slow-consumer eviction, reconnect, and a new monitor session all invalidate connection-local attribution. Transport connectivity and observer health are separate fields. Business-event silence does not make the observer stale; only the relay heartbeat status does.

The client accepts only an absolute Unix-socket path whose ancestors are root-owned directories without group/other write permission. The socket must be owned by the current user with mode `0600`, and the connected peer must have effective UID 0. Other platforms return `runtime_observation_unsupported_platform`.

The feed contains system-wide process metadata visible to Endpoint Security. It is not filtered to the authorized user's processes. Granting a user access to the socket is an explicit administrator decision to disclose that metadata.

On macOS, stdout backpressure retains the current JSON record and waits for pipe writability, checking cancellation at most every 100 ms. Partial writes resume at the remaining byte offset. A record has a 30-second write deadline; expiry terminates the watch with `runtime_observation_output_failure: runtime_observation_output_backpressure_timeout` on stderr. No additional event queue is allocated. A terminal failure may leave an incomplete last record, so consumers must invalidate their current attribution rather than accept that fragment. The desktop retains recognized output error codes with bounded diagnostic buffering and presents localized coverage failure.

This wait does not guarantee lossless recovery from arbitrary consumer pauses: the relay can independently evict a slow subscriber. A subsequent connection explicitly resets attribution and starts a new late-join subscription. Display-history eviction alone does not invalidate the native process state.
