"""Cheap Kubernetes worker health check, independent of task duration."""
import sys
import time
from pathlib import Path

try:
    healthy = time.time() - Path("/tmp/" + sys.argv[1] + "-heartbeat").stat().st_mtime < 45
except OSError:
    healthy = False
sys.exit(0 if healthy else 1)
