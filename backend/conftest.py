"""Root pytest configuration — adds the backend directory to sys.path so
that 'import app.*' works regardless of the working directory pytest was
invoked from.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
