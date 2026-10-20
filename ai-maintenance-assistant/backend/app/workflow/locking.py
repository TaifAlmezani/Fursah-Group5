"""Per-conversation locks shared by workers using the same checkpoint storage."""
from contextlib import contextmanager
import errno
from hashlib import sha256
import os
from pathlib import Path


class ContinuationInProgressError(Exception):
    pass


@contextmanager
def continuation_lock(thread_id: str, checkpoints_db_path: str):
    # Hash user input so it cannot escape the lock directory. Keep lock files:
    # unlinking a released lock can let workers lock different file inodes.
    directory = Path(str(Path(checkpoints_db_path).resolve()) + ".locks")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (sha256(thread_id.encode()).hexdigest() + ".lock")
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                raise ContinuationInProgressError from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ContinuationInProgressError from exc
        try:
            yield
        finally:
            # The OS also releases the lock if a worker exits unexpectedly.
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
