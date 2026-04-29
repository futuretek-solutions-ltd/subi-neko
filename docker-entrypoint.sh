#!/bin/sh
set -e

: "${PUID:=1000}"
: "${PGID:=1000}"
: "${UMASK:=002}"

case "$PUID:$PGID" in
    *[!0-9:]* | :* | *:)
        echo "PUID and PGID must be numeric" >&2
        exit 1
        ;;
esac

case "$UMASK" in
    *[!0-7]* | "")
        echo "UMASK must be an octal value" >&2
        exit 1
        ;;
esac

umask "$UMASK"

if [ "$(id -u)" != "0" ]; then
    exec "$@"
fi

group_name="$(getent group "$PGID" | cut -d: -f1 || true)"
if [ -z "$group_name" ]; then
    group_name=app
    groupadd --gid "$PGID" "$group_name"
fi

user_name="$(getent passwd "$PUID" | cut -d: -f1 || true)"
if [ -z "$user_name" ]; then
    user_name=app
    useradd --uid "$PUID" --gid "$PGID" --home-dir /app --shell /usr/sbin/nologin "$user_name"
fi

chown -R "$PUID:$PGID" /app/config /app/media

exec gosu "$PUID:$PGID" "$@"
