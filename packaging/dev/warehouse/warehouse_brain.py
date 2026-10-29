"""Moved into the package (agentos/demos/warehouse_brain.py) so `bento demo warehouse` ships with it."""
import sys

import uvicorn

from agentos.demos.warehouse_brain import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
