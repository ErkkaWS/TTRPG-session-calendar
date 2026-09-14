#!/bin/sh
# This file never contains any secrets — it loads secrets.env
# (which you keep protected with chmod 600) and then runs the
# actual check script.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRETS_FILE="$SCRIPT_DIR/secrets.env"

if [ ! -f "$SECRETS_FILE" ]; then
    echo "ERROR: $SECRETS_FILE is missing." >&2
    echo "Copy secrets.env.example to secrets.env and fill in your real webhook URLs." >&2
    exit 1
fi

# Warn if the permissions are too loose (anyone on the machine could read it)
PERMS=$(stat -c "%a" "$SECRETS_FILE" 2>/dev/null || stat -f "%OLp" "$SECRETS_FILE" 2>/dev/null)
if [ "$PERMS" != "600" ]; then
    echo "WARNING: $SECRETS_FILE permissions are $PERMS, should be 600. Run: chmod 600 $SECRETS_FILE" >&2
fi

. "$SECRETS_FILE"

python3 "$SCRIPT_DIR/check.py"
