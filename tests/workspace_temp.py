"""Test directories inheriting workspace ACLs on Windows."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import uuid


@contextmanager
def temporary_directory():
    root = Path(__file__).resolve().parent
    path = root / ("test_output_" + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield str(path)
    finally:
        resolved = path.resolve()
        if resolved.parent != root or not resolved.name.startswith("test_output_"):
            raise ValueError("Unexpected test output path")
        shutil.rmtree(resolved)
