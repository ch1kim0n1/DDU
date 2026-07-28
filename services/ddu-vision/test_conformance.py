#!/usr/bin/env python3
"""Conformance test for ddu-vision service."""

import sys
import os

# Add parent directory to path to import from ddu_common
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../libs/ddu-py-common/src'))

from ddu_common.conformance import run_contract_test

if __name__ == "__main__":
    # Default to localhost:8101 for ddu-vision
    base_url = os.environ.get("DDU_VISION_URL", "http://localhost:8101")
    success = run_contract_test(base_url, "ddu-vision")
    sys.exit(0 if success else 1)