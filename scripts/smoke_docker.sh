#!/usr/bin/env bash
#
# Smoke-tests a running SightOps stack through its public entry point.
#
# This is what CI runs after `docker compose up -d --wait`, and it is also usable
# against a local stack by hand:
#
#   docker compose up -d --wait
#   scripts/smoke_docker.sh
#
# SIGHTOPS_SMOKE_BASE overrides the origin (default http://127.0.0.1:8080).
#
# It asserts behaviour, not just status codes: that the image really is served, that
# the container really is running OpenCV 5, that the full industrial demonstration
# still walks from "waiting for a better view" to a human approval gate and then to
# completed, and that the annotation the agent concluded from is a real PNG. A
# container that boots but cannot measure anything fails here.
#
# It deliberately does not call text-to-speech: that would spend a real ElevenLabs
# character budget on every run. Voice configuration is checked by presence only.

set -euo pipefail

BASE="${SIGHTOPS_SMOKE_BASE:-http://127.0.0.1:8080}"
CURL=(curl --silent --show-error --max-time 30)

pass_count=0
fail_count=0

pass() { printf '  [PASS] %s\n' "$1"; pass_count=$((pass_count + 1)); }
fail() { printf '  [FAIL] %s\n' "$1" >&2; fail_count=$((fail_count + 1)); }

# check <description> <expected> <actual>
check() {
  if [ "$2" = "$3" ]; then
    pass "$1 ($3)"
  else
    fail "$1: expected $2, got $3"
  fi
}

# json <python expression over `body`> — reads the response on stdin
json() {
  python3 -c '
import json, sys
body = json.load(sys.stdin)
print('"$1"')
'
}

status_of() { "${CURL[@]}" -o /dev/null -w '%{http_code}' "$@"; }

echo "SightOps container smoke test against ${BASE}"
echo

# ---------------------------------------------------------------- the web app ---
echo "web application"
check "GET / is served" 200 "$(status_of "${BASE}/")"
check "GET /industrial is served" 200 "$(status_of "${BASE}/industrial")"
check "GET /system is served" 200 "$(status_of "${BASE}/system")"

landing="$("${CURL[@]}" "${BASE}/")"
case "$landing" in
  *SightOps*) pass "the served HTML names the product" ;;
  *) fail "the served HTML does not name the product" ;;
esac

# --------------------------------------------------------------------- health ---
echo
echo "health and capability"
health="$("${CURL[@]}" "${BASE}/health")"
check "database reachable" "True" "$(printf '%s' "$health" | json 'body["database"] is True')"
check "OpenCV major version" "5" "$(printf '%s' "$health" | json 'body["opencv_version"].split(".")[0]')"

system="$("${CURL[@]}" "${BASE}/api/system/status")"
check "system status reports OpenCV 5" "5" \
  "$(printf '%s' "$system" | json 'body["opencv_version"].split(".")[0]')"
check "AWS is reported as not implemented" "NOT IMPLEMENTED" \
  "$(printf '%s' "$system" | json 'body["aws_integration"]')"
check "the capability report names every provider" "3" \
  "$(printf '%s' "$system" | json 'len(body["providers"])')"

voice="$("${CURL[@]}" "${BASE}/api/voice/status")"
check "voice provider is reported" "elevenlabs" "$(printf '%s' "$voice" | json 'body["provider"]')"
check "voice configuration is a presence flag, not a key" "True" \
  "$(printf '%s' "$voice" | json 'isinstance(body["configured"], bool)')"

# ------------------------------------------------- the demonstration, end to end ---
echo
echo "industrial demonstration"
started="$("${CURL[@]}" -X POST "${BASE}/api/demo/industrial")"
inspection_id="$(printf '%s' "$started" | json 'body["id"]')"
if [ -n "$inspection_id" ]; then
  pass "the flow started an inspection ($inspection_id)"
else
  fail "the flow did not return an inspection"
  exit 1
fi

check "observation 1 hands the turn back to the user" "WAITING_FOR_USER" \
  "$(printf '%s' "$started" | json 'body["state"]')"
check "observation 1 asked for a specific region" "pressure_gauge_01" \
  "$(printf '%s' "$started" | json 'body["pending_request"]["target_region"]')"

second="$("${CURL[@]}" -X POST "${BASE}/api/demo/${inspection_id}/next-observation")"
check "observation 2 stops at the approval gate" "AWAITING_APPROVAL" \
  "$(printf '%s' "$second" | json 'body["state"]')"
check "the second observation measured the gauge" "True" \
  "$(printf '%s' "$second" | json '
any(m["component_id"] == "pressure_gauge_01" and m["value"] is not None
    for o in body["observations"] for m in (o["analysis"] or {}).get("measurements", []))')"

evidence="$("${CURL[@]}" -D - -o /dev/null "${BASE}/api/inspections/${inspection_id}/evidence/$(printf '%s' "$second" | json 'body["observations"][-1]["image_id"]')?annotated=true" | tr -d '\r' | awk 'tolower($1)=="content-type:" {print $2; exit}')"
check "the annotated evidence is a PNG" "image/png" "$evidence"

calls="$("${CURL[@]}" "${BASE}/api/inspections/${inspection_id}/tool-calls")"
check "the tool trace is inside the documented bound" "True" \
  "$(printf '%s' "$calls" | json '0 < len(body) <= 12')"
check "every tool call is typed" "True" \
  "$(printf '%s' "$calls" | json 'all(c.get("tool") and c.get("ok") is not None for c in body)')"

timeline="$("${CURL[@]}" "${BASE}/api/inspections/${inspection_id}/timeline")"
check "the timeline is recorded for audit" "True" \
  "$(printf '%s' "$timeline" | json 'len(body) >= 5')"

# The decision is the route, so the body carries only the operator's note.
check "the approval is accepted" 200 "$(status_of -X POST \
  "${BASE}/api/inspections/${inspection_id}/approve" \
  -H 'Content-Type: application/json' -d '{"note":"reviewed the annotated evidence"}')"
final="$("${CURL[@]}" "${BASE}/api/inspections/${inspection_id}")"
check "approval completes the inspection" "COMPLETED" "$(printf '%s' "$final" | json 'body["state"]')"

# -------------------------------------------------------------------- verdict ---
echo
if [ "$fail_count" -gt 0 ]; then
  echo "FAIL: ${fail_count} check(s) failed, ${pass_count} passed"
  exit 1
fi
echo "PASS: ${pass_count} checks passed"
