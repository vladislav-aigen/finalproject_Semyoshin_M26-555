"""JSON-хранилище с атомарной заменой файлов."""

import copy
import json
import os
import tempfile
import threading
from pathlib import Path

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.infra.settings import SettingsLoader


class DatabaseManager:
    """Единый менеджер файлов; __new__ не создаёт лишних экземпляров."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.lock = threading.RLock()
        return cls._instance

    def path(self, name: str) -> Path:
        """Построить путь к файлу внутри каталога данных."""
        if Path(name).name != name:
            raise ValueError("Ожидается имя файла без пути")
        return Path(SettingsLoader().get("data_dir")).resolve() / name

    def read(self, name: str, default):
        """Прочитать JSON; отсутствие файла трактовать как пустое хранилище."""
        with self.lock:
            path = self.path(name)
            try:
                with path.open(encoding="utf-8") as stream:
                    value = json.load(stream)
                if not isinstance(value, type(default)):
                    raise ValueError("Неверный тип корневого объекта")
                return value
            except FileNotFoundError:
                return copy.deepcopy(default)
            except (OSError, ValueError) as error:
                raise StorageError(f"Не удалось прочитать {name}") from error

    def write(self, name: str, data):
        """Записать временный файл, затем атомарно заменить целевой."""
        with self.lock:
            path = self.path(name)
            temporary = None
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=path.parent,
                    delete=False,
                    suffix=".tmp",
                    prefix=f".{path.name}.",
                ) as stream:
                    temporary = Path(stream.name)
                    json.dump(
                        data, stream, ensure_ascii=False, indent=2, allow_nan=False
                    )
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            except (OSError, ValueError, TypeError) as error:
                raise StorageError(f"Не удалось сохранить {name}") from error
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
