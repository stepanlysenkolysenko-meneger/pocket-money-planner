import base64
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
import re

import bank_service


def _normalize(value: str) -> str:
    return re.sub(r"[^a-zа-яіїєґ0-9]+", "", str(value or "").casefold())


def _find(headers: list[str], names: set[str]) -> str | None:
    normalized = {_normalize(header): header for header in headers}
    for name in names:
        if _normalize(name) in normalized:
            return normalized[_normalize(name)]
    for key, original in normalized.items():
        if any(_normalize(name) in key for name in names):
            return original
    return None


def _number(value) -> Decimal | None:
    raw = str(value or "").strip().replace("\u00a0", "").replace(" ", "")
    if not raw:
        return None
    if raw.count(",") == 1 and raw.count(".") == 0:
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(",", "")
    raw = re.sub(r"[^0-9.\-+]", "", raw)
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _date(value: str):
    raw = str(value or "").strip()
    for pattern in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw[:19], pattern).date()
        except ValueError:
            continue
    match = re.search(r"(\d{2})[.\-/](\d{2})[.\-/](\d{4})", raw)
    if match:
        return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1))).date()
    return None


def decode_file(data_url: str) -> str:
    encoded = data_url.split(",", 1)[-1]
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > 5_000_000:
        raise ValueError("Виписка має бути не більшою за 5 МБ")
    for encoding in ("utf-8-sig", "utf-16", "cp1251", "windows-1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Не вдалося визначити кодування CSV-файлу")


def parse(data_url: str, provider: str, account_key: str, scope: str) -> list[dict]:
    content = decode_file(data_url)
    sample = content[:10000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    rows = list(csv.DictReader(io.StringIO(content), dialect=dialect))
    if not rows or not rows[0]:
        raise ValueError("CSV-виписка порожня або не має заголовків")
    headers = list(rows[0].keys())
    date_col = _find(headers, {"дата", "дата операції", "дата транзакції", "date", "transaction date", "trandate", "dat od"})
    amount_col = _find(headers, {"сума", "сума операції", "сума у валюті картки", "amount", "cardamount", "sum"})
    debit_col = _find(headers, {"дебет", "витрата", "списання", "debit", "debit amount", "sum dt"})
    credit_col = _find(headers, {"кредит", "дохід", "зарахування", "credit", "credit amount", "sum kt"})
    description_col = _find(headers, {"опис", "опис операції", "деталі", "призначення платежу", "description", "details", "merchant", "osnd"})
    mcc_col = _find(headers, {"mcc", "merchant category code"})
    currency_col = _find(headers, {"валюта", "currency", "ccy"})
    if not date_col or not description_col or not (amount_col or debit_col or credit_col):
        raise ValueError("Не знайдено потрібні колонки. Потрібні: дата, сума або дебет/кредит, опис операції")

    result = []
    for row in rows:
        operation_date = _date(row.get(date_col, ""))
        description = str(row.get(description_col, "") or "Банківська операція").strip()[:160]
        amount = _number(row.get(amount_col)) if amount_col else None
        if amount is None:
            debit = abs(_number(row.get(debit_col)) or Decimal("0")) if debit_col else Decimal("0")
            credit = abs(_number(row.get(credit_col)) or Decimal("0")) if credit_col else Decimal("0")
            amount = credit - debit
        if not operation_date or amount == 0:
            continue
        mcc_raw = re.sub(r"\D", "", str(row.get(mcc_col, ""))) if mcc_col else ""
        mcc = int(mcc_raw[:4]) if mcc_raw else None
        currency = str(row.get(currency_col, "UAH") or "UAH").upper() if currency_col else "UAH"
        currency_code = {"UAH": 980, "USD": 840, "EUR": 978, "PLN": 985}.get(currency, 980)
        digest = hashlib.sha256(f"{provider}|{account_key}|{operation_date}|{amount}|{description}".encode("utf-8")).hexdigest()[:32]
        category = "Продажі" if amount > 0 and scope == "business" else "Надходження на картку" if amount > 0 else bank_service.business_category_for_mcc(mcc, description) if scope == "business" else bank_service.category_for_mcc(mcc, description)
        result.append({"external_id": f"file:{digest}", "type": "income" if amount > 0 else "expense", "amount": abs(amount), "category": category, "description": description, "date": operation_date, "currency_code": currency_code, "mcc": mcc})
    if not result:
        raise ValueError("У виписці не знайдено операцій із коректною датою та сумою")
    return result
