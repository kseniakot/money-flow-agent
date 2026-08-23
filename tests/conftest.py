import os
import tempfile

os.environ["DB_PATH"] = tempfile.mktemp(suffix=".sqlite")
os.environ["CHECKPOINT_PATH"] = tempfile.mktemp(suffix=".sqlite")
