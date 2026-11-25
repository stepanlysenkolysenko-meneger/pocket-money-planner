"""Read-only Privat24 for Business AutoClient API integration."""

import json
import urllib.error
import urllib.parse
import urllib.request


API_URL = "https://acp.privatbank.ua/api"


def _get(path: str, token: str, params: dict | None = None):
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(
        f"{API_URL}{path}{query}",
        headers={
            "token": token,
            "User-Agent": "PocketMoney/1.0",
            "Content-Type": "application/json;charset=utf-8",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        messages = {401: "Токен Приват24 недійсний або відкликаний", 403: "Токен не має доступу до балансів і транзакцій", 429: "ПриватБанк тимчасово обмежив частоту запитів"}
        raise ValueError(messages.get(error.code, f"ПриватБанк повернув помилку {error.code}")) from error
    except urllib.error.URLError as error:
        raise ValueError("Немає з’єднання з ПриватБанком. Перевір інтернет") from error
    if str(payload.get("status", "SUCCESS")).upper() not in {"SUCCESS", "OK"}:
        raise ValueError(payload.get("message") or payload.get("error") or "ПриватБанк не підтвердив запит")
    return payload


def verify(token: str):
    return _get("/statements/settings", token)


def _paged(path: str, token: str, params: dict, key: str):
    result = []
    follow_id = None
    for _ in range(100):
        page_params = {**params, "limit": 100}
        if follow_id:
            page_params["followId"] = follow_id
        payload = _get(path, token, page_params)
        result.extend(payload.get(key) or [])
        if not payload.get("exist_next_page") or not payload.get("next_page_id"):
            break
        follow_id = payload["next_page_id"]
    return result


def balances(token: str, start_date: str, end_date: str):
    return _paged("/statements/balance", token, {"startDate": start_date, "endDate": end_date}, "balances")


def transactions(token: str, account: str, start_date: str, end_date: str):
    return _paged("/statements/transactions", token, {"acc": account, "startDate": start_date, "endDate": end_date}, "transactions")
