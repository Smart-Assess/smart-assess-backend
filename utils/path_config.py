import os
import sys

# Get project root path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add to Python path if not already there
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)