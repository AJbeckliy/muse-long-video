"""Merge settings from the studio and optional installers without losing concurrent edits."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
from uuid import uuid4


@contextmanager
def _exclusive(file):
    file.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def merge_settings(path, updates):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a+b") as guard, _exclusive(guard):
        value = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        value.update(updates)
        pending = path.with_name(path.name + ".new-" + uuid4().hex)
        pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        for attempt in range(6):
            try:
                pending.replace(path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(.025 * (attempt + 1))
        return value
