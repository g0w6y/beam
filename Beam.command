#!/usr/bin/env bash
# Start Beam.  Any arguments are passed straight to server.py:
#   ./run.sh                      share ~/Drop on port 8080 with a random PIN
#   ./run.sh --dir ~/Movies       share something else
#   ./run.sh --no-pin             skip the PIN (only on a network you trust)
cd "$(dirname "$0")"
# The full path matters: it is what makes `pkill -f beam/server.py` work.
exec /usr/bin/env python3 "$PWD/server.py" "$@"
