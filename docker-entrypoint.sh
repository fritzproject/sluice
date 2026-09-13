#!/bin/sh
# Drops privileges to PUID:PGID before starting.
#
# Downloading as root is the classic way to end up with files nothing else can
# move or import: the media server, the file manager and the backup job all run
# as somebody else. Running as the same user they do avoids the whole problem.
set -e

: "${PUID:=1000}"
: "${PGID:=1000}"

if [ "$(id -u)" != "0" ]; then
    # Already unprivileged (docker run --user, or a build-time UID): nothing to
    # drop, just run.
    exec "$@"
fi

if ! getent group "$PGID" >/dev/null 2>&1; then
    groupadd -g "$PGID" sluice
fi
if ! getent passwd "$PUID" >/dev/null 2>&1; then
    useradd -u "$PUID" -g "$PGID" -M -s /usr/sbin/nologin sluice
fi

# Only the top level: a recursive chown over a large download folder would
# make every start crawl, and would fight with whatever else owns those files.
chown "$PUID:$PGID" /downloads /state 2>/dev/null || true

exec setpriv --reuid "$PUID" --regid "$PGID" --init-groups "$@"
