#!/bin/bash
# Glitch Loom — start the local prototype. Double-click this file, or run it in a terminal.
# It serves this folder on this computer only. Nothing is published.
cd "$(dirname "$0")"
PORT=8790
echo "Glitch Loom is running at http://127.0.0.1:$PORT"
echo "Leave this window open. Press Control+C to stop."
(sleep 1 && open "http://127.0.0.1:$PORT") &
exec python3 serve.py "$PORT"
