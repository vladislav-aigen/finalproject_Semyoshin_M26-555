"""Ошибки предметной области, отображаемые консольным интерфейсом."""


class ValutaTradeError(Exception):
    """Базовая ожидаемая ошибка приложения."""


class InsufficientFundsError(ValutaTradeError):
    """Сумма операции превышает доступный остаток."""

    def __init__(self, available: float, required: float, code: str):
        super().__init__(
            f"Недостаточно средств: доступно {available:.4f} {code}, "
            f"требуется {required:.4f} {code}"
        )


class CurrencyNotFoundError(ValutaTradeError):
    """Валюта отсутствует в реестре."""

    def __init__(self, code: str):
        super().__init__(f"Неизвестная валюта '{code}'")


class ApiRequestError(ValutaTradeError):
    """Не удалось получить или использовать внешний курс."""

    def __init__(self, reason: str):
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")


class StorageError(ValutaTradeError):
    """Хранилище недоступно или содержит повреждённые данные."""
