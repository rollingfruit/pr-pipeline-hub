#!/bin/sh
set +e
"$@"
status=$?
chown -R "$HOST_UID:$HOST_GID" "$E2E_SOURCE" "$AI_ROOT"
exit "$status"
