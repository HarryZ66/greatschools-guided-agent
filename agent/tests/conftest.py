import os
import sys
from pathlib import Path

# Fixed "today" so freshness rules are reproducible; set before gs_agent.config is imported.
os.environ.setdefault("GS_TODAY", "2026-11-03")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
