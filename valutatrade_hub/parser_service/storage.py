"""История наблюдений и актуальный снимок курсов."""

from valutatrade_hub.core.utils import parse_timestamp, utc_now
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.schema import validate_rate_record


class RatesStorage:
    """Сохраняет свежие наблюдения, не заменяя их старыми."""

    def __init__(self):
        self.db = DatabaseManager()
        self.last_refresh = None

    def save(self, updates: dict) -> int:
        """Дополнить историю и атомарно заменить снимок последних значений."""
        for pair, record in updates.items():
            validate_rate_record(pair, record)
        with self.db.lock:
            snapshot = self.db.read("rates.json", {"pairs": {}, "last_refresh": None})
            pairs = snapshot.setdefault("pairs", {})
            history = self.db.read("exchange_rates.json", [])
            known_observations = {
                (
                    item["from_currency"],
                    item["to_currency"],
                    parse_timestamp(item["timestamp"]),
                )
                for item in history
            }
            accepted = 0
            for pair, record in updates.items():
                from_code, to_code = pair.split("_")
                timestamp = parse_timestamp(record["updated_at"])
                old = pairs.get(pair)
                if old and timestamp <= parse_timestamp(old["updated_at"]):
                    continue
                pairs[pair] = dict(record)
                item_id = f"{pair}_{record['updated_at']}"
                observation = (from_code, to_code, timestamp)
                if observation not in known_observations:
                    history.append(
                        {
                            "id": item_id,
                            "from_currency": from_code,
                            "to_currency": to_code,
                            "rate": record["rate"],
                            "timestamp": record["updated_at"],
                            "source": record["source"],
                        }
                    )
                    known_observations.add(observation)
                accepted += 1
            if accepted:
                snapshot["last_refresh"] = utc_now()
                # История пишется первой: повтор после сбоя не создаёт дублей.
                self.db.write("exchange_rates.json", history)
                self.db.write("rates.json", snapshot)
            self.last_refresh = snapshot.get("last_refresh")
            return accepted
