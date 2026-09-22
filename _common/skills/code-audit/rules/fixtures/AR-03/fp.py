import os

ROOT = os.environ.get("MY_ROOT", os.getcwd())
STATE_PATH = os.path.join(ROOT, ".git", "mytool.json")
