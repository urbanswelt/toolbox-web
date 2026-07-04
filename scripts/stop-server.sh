#!/usr/bin/env bash
# stop-server.sh PORT NAME_PATTERN
#
# Gracefully stops (SIGTERM) the process LISTENING on tcp <PORT>, but only if
# its command line matches <NAME_PATTERN>. Used by toolbox-web's shutdown
# commands. Works with or without `ss`: if iproute2 isn't installed (some
# toolbox images), it falls back to parsing /proc directly.
#
# Only the single process that owns the listening socket is ever inspected or
# signalled, so there's no risk of matching the wrong server or this script.
set -u

port="${1:?usage: stop-server.sh PORT NAME_PATTERN}"
pat="${2:?usage: stop-server.sh PORT NAME_PATTERN}"

pid=""

# Preferred: ask ss who is listening on the port.
if command -v ss >/dev/null 2>&1; then
    pid=$(ss -ltnp "sport = :$port" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1)
fi

# Fallback (no ss): find the LISTEN socket's inode in /proc/net/tcp{,6}, then
# the process that holds a file descriptor for that socket.
if [ -z "$pid" ]; then
    hex=$(printf ':%04X' "$port")
    ino=$(awk -v p="$hex" '$4=="0A" && $2 ~ p"$" {print $10; exit}' \
              /proc/net/tcp /proc/net/tcp6 2>/dev/null)
    if [ -n "$ino" ]; then
        for f in /proc/[0-9]*/fd/*; do
            if [ "$(readlink "$f" 2>/dev/null)" = "socket:[$ino]" ]; then
                pid=$(printf '%s\n' "$f" | cut -d/ -f3)
                break
            fi
        done
    fi
fi

if [ -z "$pid" ]; then
    echo "No server listening on port $port."
    exit 0
fi

if tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q "$pat"; then
    kill -TERM "$pid" && \
        echo "Sent SIGTERM to '$pat' (pid $pid) on port $port — graceful shutdown in progress."
else
    echo "Refused: process on :$port (pid $pid) does not match '$pat' — left untouched."
fi
