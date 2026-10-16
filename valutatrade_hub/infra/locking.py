"""Повторно входимая блокировка хранилища для потоков и процессов."""

import os
import threading

from valutatrade_hub.core.exceptions import StorageError


class DatabaseLock:
    """ОС освобождает файловую блокировку и при аварийном выходе процесса."""

    def __init__(self, path_factory):
        self._path_factory = path_factory
        self._thread_lock = threading.RLock()
        self._depth = 0
        self._stream = None

    def __enter__(self):
        self._thread_lock.acquire()
        try:
            if self._depth == 0:
                path = self._path_factory()
                path.parent.mkdir(parents=True, exist_ok=True)
                self._stream = path.open("a+b")
                if os.name == "nt":
                    import msvcrt

                    if path.stat().st_size == 0:
                        self._stream.write(b"\0")
                        self._stream.flush()
                    self._stream.seek(0)
                    msvcrt.locking(self._stream.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX)
            self._depth += 1
            return self
        except Exception as error:
            if self._stream is not None and self._depth == 0:
                self._stream.close()
                self._stream = None
            self._thread_lock.release()
            if isinstance(error, OSError):
                raise StorageError("Не удалось заблокировать каталог данных") from error
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self._depth -= 1
            if self._depth == 0:
                # Закрытие дескриптора освобождает flock / locking.
                self._stream.close()
                self._stream = None
        finally:
            self._thread_lock.release()
