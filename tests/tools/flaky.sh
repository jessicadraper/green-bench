#!/bin/sh
# A workload that works for the first few calls, then fails: simulates a crash mid-experiment.
#   GB_FLAKY_FAIL_AT   call number from which it fails (default 5; warm-ups count as calls)
#   GB_FLAKY_COUNTER   file used to count calls (default /tmp/gb-flaky-count; delete it to reset)
f="${GB_FLAKY_COUNTER:-/tmp/gb-flaky-count}"
n=$(cat "$f" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$f"
if [ "$n" -ge "${GB_FLAKY_FAIL_AT:-5}" ]; then
  echo "Error: database connection lost" >&2
  exit 1
fi
sleep 1
