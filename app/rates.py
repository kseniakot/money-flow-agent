import json
from datetime import date as date_cls
from urllib.error import URLError
from urllib.request import urlopen

from app.config import config

_cache: dict[tuple[str, str], float] = {}


def _today() -> str:
    return date_cls.today().isoformat()


def _parse_rate(payload: dict) -> float:
    return float(payload["Cur_OfficialRate"]) / float(payload["Cur_Scale"])


def _fetch(currency: str, attempts: int = 3) -> float:
    last_err: Exception | None = None
    for _ in range(attempts):
        try:
            with urlopen(config.nbrb_url.format(cur=currency), timeout=10) as resp:
                payload = json.loads(resp.read().decode())
            return _parse_rate(payload)
        except (URLError, TimeoutError, ValueError, KeyError) as err:
            last_err = err
    raise last_err


def clear_cache() -> None:
    _cache.clear()


def byn_per_unit(currency: str, on_date: str | None = None) -> float:
    currency = currency.upper()
    if currency == "BYN":
        return 1.0
    on_date = on_date or _today()
    key = (currency, on_date)
    if key in _cache:
        return _cache[key]
    value = _fetch(currency)
    _cache[key] = value
    return value


def to_usd(amount: float, currency: str, on_date: str | None = None) -> float:
    on_date = on_date or _today()
    src = byn_per_unit(currency, on_date)
    usd = byn_per_unit("USD", on_date)
    return amount * src / usd
