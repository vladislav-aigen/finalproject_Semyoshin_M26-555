"""Декораторы журнала операций и подтверждения действий."""

import logging
from functools import wraps


def log_action(action: str, verbose: bool = False):
    """Записать результат операции и пробросить возникшее исключение."""

    def decorate(function):
        @wraps(function)
        def wrapper(self, currency_code, amount):
            event = {
                "action": action,
                "currency_code": currency_code,
                "amount": amount,
                "base": "USD",
                "user_id": self.current_user.user_id if self.current_user else None,
            }
            try:
                result = function(self, currency_code, amount)
                event.update(result="OK", rate=result.get("rate"))
                if verbose:
                    event["before"] = result.get("before")
                    event["after"] = result.get("after")
            except Exception as error:
                event.update(
                    result="ERROR",
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
                logging.getLogger("valutatrade.actions").info(
                    action, extra={"event": event}
                )
                raise
            logging.getLogger("valutatrade.actions").info(
                action, extra={"event": event}
            )
            return result

        return wrapper

    return decorate


def confirm_action(action_name: str):
    """Запросить подтверждение в интерфейсном слое перед действием."""

    def decorate(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            answer = input(f"Подтвердить {action_name}? [y/n]: ")
            if answer.strip().lower() != "y":
                print("Операция отменена")
                return None
            return function(*args, **kwargs)

        return wrapper

    return decorate
