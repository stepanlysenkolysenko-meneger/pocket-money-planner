"""Read-only Binance integration. Keys are never used for trading or withdrawals."""

import hashlib
import hmac
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://api.binance.com"


def _request(path: str, api_key: str = "", secret: str = "", signed: bool = False):
    params = {}
    if signed:
        params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000}
        query = urlencode(params)
        params["signature"] = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{API_URL}{path}"
    if params:
        url += "?" + urlencode(params)
    request = Request(url, headers={"X-MBX-APIKEY": api_key, "User-Agent": "PocketMoney/1.0"})
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("msg")
        except Exception:
            detail = None
        raise ValueError(detail or f"Binance повернув помилку {error.code}") from error
    except URLError as error:
        raise ValueError("Немає з’єднання з Binance. Перевір інтернет") from error


def verify_read_only(api_key: str, secret: str):
    permissions = _request("/sapi/v1/account/apiRestrictions", api_key, secret, True)
    if not permissions.get("enableReading"):
        raise ValueError("Для API-ключа потрібно увімкнути читання")
    if permissions.get("enableWithdrawals") or permissions.get("enableSpotAndMarginTrading") or permissions.get("enableFutures"):
        raise ValueError("З міркувань безпеки створи окремий API-ключ лише для читання: вимкни торгівлю та виведення")
    return permissions


def balances(api_key: str, secret: str):
    account = _request("/api/v3/account", api_key, secret, True)
    result = []
    for row in account.get("balances", []):
        free = float(row.get("free") or 0)
        locked = float(row.get("locked") or 0)
        if free + locked <= 0:
            continue
        symbol = row["asset"].upper()
        price = 1.0 if symbol in {"USDT", "USDC", "FDUSD"} else 0.0
        if not price:
            try:
                price = float(_request(f"/api/v3/ticker/price?symbol={symbol}USDT").get("price") or 0)
            except Exception:
                price = 0.0
        result.append({"symbol": symbol, "free": free, "locked": locked, "price_usdt": price, "value_usdt": (free + locked) * price})
    return result
