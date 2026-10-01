#!/usr/bin/env python3
"""Glitch Loom local server. This computer only. Internal Glitch tool.

It serves the page, keeps courses as files in the data folder, and runs the Claude command-line tool when asked.
Files are never cached, so a refresh always shows the latest version.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from loom_server.http_api import serve  # noqa: E402

if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8790)
