#!/bin/bash
echo "Status: 200"
echo "Content-type: application/json"
echo
# Query the heartbeat endpoint (NB_PREFIX-aware when set by the notebook controller)
if [ -n "${NB_PREFIX:-}" ]; then
    HEALTHZ_URL="http://127.0.0.1:8888${NB_PREFIX}/codeserver/healthz"
else
    HEALTHZ_URL="http://127.0.0.1:8888/codeserver/healthz"
fi
HEALTHZ=$(curl -s "$HEALTHZ_URL")
# Extract lastHeartbeat as integer milliseconds (handles 0 and multi-field JSON)
LAST_MS=$(echo "$HEALTHZ" | grep -oP '"lastHeartbeat"\s*:\s*\K[0-9]+' | head -1)
LAST_MS=${LAST_MS:-0}
LAST_SEC=$((LAST_MS / 1000))
LAST_ACTIVITY=$(date -u -d "@${LAST_SEC}" -Iseconds 2>/dev/null || date -d "@${LAST_SEC}" -Iseconds)
# Extract status and replace with terms expected by culler
RAW_STATUS=$(echo "$HEALTHZ" | grep -oP '"status"\s*:\s*"\K[^"]*' | head -1)
STATUS=$(sed 's/alive/busy/;s/expired/idle/' <<< "$RAW_STATUS")
# Export in format expected by the culling engine
echo '[{"id":"code-server","name":"code-server","last_activity":"'$LAST_ACTIVITY'","execution_state":"'$STATUS'","connections":1}]'
