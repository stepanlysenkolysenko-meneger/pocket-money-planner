import base64
import ctypes
from ctypes import wintypes
import json
import urllib.error
import urllib.request


API_URL = "https://api.monobank.ua"


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect_token(token: str) -> str:
    source, source_buffer = _blob(token.encode("utf-8"))
    result = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), "Pocket Money", None, None, None, 0,
        ctypes.byref(result),
    ):
        raise OSError("Windows не зміг захистити банківський токен")
    try:
        encrypted = ctypes.string_at(result.pbData, result.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)
        del source_buffer


def unprotect_token(value: str) -> str:
    source, source_buffer = _blob(base64.b64decode(value))
    result = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0,
        ctypes.byref(result),
    ):
        raise OSError("Не вдалося розшифрувати банківський токен цього користувача Windows")
    try:
        return ctypes.string_at(result.pbData, result.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)
        del source_buffer


def _get(path: str, token: str):
    request = urllib.request.Request(
        f"{API_URL}{path}",
        headers={"X-Token": token, "User-Agent": "PocketMoney/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        messages = {
            401: "Токен Monobank недійсний або відкликаний",
            403: "Monobank заборонив доступ до цього рахунку",
            429: "Monobank дозволяє синхронізацію не частіше одного разу на 60 секунд",
        }
        raise ValueError(messages.get(error.code, f"Monobank повернув помилку {error.code}")) from error
    except urllib.error.URLError as error:
        raise ValueError("Немає з’єднання з Monobank. Перевір інтернет") from error


def client_info(token: str):
    return _get("/personal/client-info", token)


def statement(token: str, account_id: str, from_timestamp: int, to_timestamp: int):
    return _get(f"/personal/statement/{account_id}/{from_timestamp}/{to_timestamp}", token)


def _merchant_hint(description: str | None) -> str | None:
    value = (description or "").casefold()
    keywords = (
        (("атб", "silpo", "сільпо", "novus", "varus", "фора", "metro cash", "ашан", "auchan"), "Супермаркети"),
        (("glovo", "bolt food", "uber eats", "mcdonald", "kfc", "restaurant", "cafe", "кав’яр", "кафе"), "Кафе та ресторани"),
        (("аптека", "pharmacy", "tabletki", "подорожник", "anc.ua"), "Аптеки"),
        (("okko", "wog", "upg", "socar", "shell", "brsm", "бензин", "fuel"), "Пальне"),
        (("bolt", "uklon", "uber", "таксі", "taxi"), "Таксі"),
        (("steam", "playstation", "xbox", "nintendo", "epic games"), "Ігри"),
        (("netflix", "spotify", "youtube premium", "megogo", "sweet.tv"), "Підписки"),
        (("rozetka", "comfy", "foxtrot", "allo.ua", "цитрус"), "Техніка"),
        (("нова пошта", "novaposhta", "укрпошта", "meest"), "Доставка"),
    )
    for variants, category in keywords:
        if any(word in value for word in variants):
            return category
    return None


def category_for_mcc(mcc: int | None, description: str | None = None) -> str:
    hint = _merchant_hint(description)
    if hint:
        return hint
    mcc = int(mcc or 0)
    if mcc in {5411, 5422, 5441, 5451, 5462, 5499}:
        return "Супермаркети"
    if mcc in {5811, 5812, 5813, 5814}:
        return "Кафе та ресторани"
    if mcc == 5912:
        return "Аптеки"
    if mcc in {8011, 8021, 8031, 8041, 8042, 8043, 8049, 8050, 8062, 8071, 8099}:
        return "Медицина"
    if mcc in {4111, 4112, 4131, 4784, 4789}:
        return "Громадський транспорт"
    if mcc == 4121:
        return "Таксі"
    if mcc in {5172, 5541, 5542, 5983}:
        return "Пальне"
    if mcc in {5511, 5521, 5531, 5532, 5533, 5571, 7531, 7534, 7535, 7538, 7542, 7549}:
        return "Авто"
    if mcc in {7523}:
        return "Паркування"
    if mcc in {4812, 4814, 4816, 4821, 4899, 4900}:
        return "Комунальні послуги та зв’язок"
    if mcc in {5200, 5211, 5231, 5251, 5261, 5712, 5713, 5714, 5718, 5719}:
        return "Дім і ремонт"
    if mcc in {5137, 5139, 5611, 5621, 5631, 5641, 5651, 5655, 5661, 5681, 5691, 5697, 5698, 5699, 5931}:
        return "Одяг і взуття"
    if mcc in {5045, 5065, 5722, 5732, 5734, 5735, 5946}:
        return "Техніка"
    if mcc in {5815, 5816, 5817, 5818, 5968}:
        return "Цифрові покупки та підписки"
    if mcc in {7832, 7841, 7911, 7922, 7929, 7932, 7933, 7941, 7991, 7992, 7993, 7994, 7995, 7996, 7997, 7998, 7999}:
        return "Розваги"
    if mcc in {5945}:
        return "Ігри"
    if mcc in {5941, 7032, 7033}:
        return "Спорт і відпочинок"
    if mcc in {5192, 5942, 5994, 8211, 8220, 8241, 8244, 8249, 8299}:
        return "Освіта та книги"
    if mcc in {7230, 7297, 7298, 5977}:
        return "Краса та догляд"
    if mcc in {742, 5995}:
        return "Домашні тварини"
    if mcc in {3000, 3001, 3002, 3003, 3004, 3005, 3006, 3007, 3008, 3009, 4511, 4722} or 3000 <= mcc <= 3299:
        return "Подорожі та авіаквитки"
    if 3500 <= mcc <= 3999 or mcc in {7011, 7012}:
        return "Готелі"
    if mcc in {5947}:
        return "Подарунки"
    if mcc in {6300, 6381, 6399}:
        return "Страхування"
    if mcc in {6010, 6011, 6012, 6051, 4829}:
        return "Перекази та готівка"
    if mcc in {8398, 8641, 8651, 8661}:
        return "Благодійність"
    if mcc in {9211, 9222, 9311, 9399, 9402}:
        return "Податки та держпослуги"
    if mcc in {4215, 4225, 9409}:
        return "Доставка"
    return "Інші покупки"


def business_category_for_mcc(mcc: int | None, description: str | None = None) -> str:
    mcc = int(mcc or 0)
    if mcc in {7311, 5964, 5965, 5966, 5967, 5968, 5969}:
        return "Реклама і маркетинг"
    if mcc in {4214, 4215, 4225, 4511, 4582, 4722, 4789, 9409} or 3000 <= mcc <= 3299:
        return "Логістика та доставка"
    if 3500 <= mcc <= 3999 or mcc in {7011, 7012}:
        return "Відрядження"
    if mcc in {4812, 4814, 4816, 4821, 4899, 4900}:
        return "Зв’язок і комунальні послуги"
    if mcc in {5044, 5045, 5065, 5111, 5943, 5946}:
        return "Офіс і техніка"
    if mcc in {5172, 5541, 5542, 5983, 7523, 7531, 7534, 7535, 7538, 7542, 7549}:
        return "Транспорт і пальне"
    if mcc in {5815, 5816, 5817, 5818, 5734, 5735}:
        return "ПЗ та підписки"
    if mcc in {7299, 7392, 7393, 7394, 7395, 7399, 8111, 8931}:
        return "Професійні послуги"
    if mcc in {9311, 9399, 9402}:
        return "Податки та збори"
    if mcc == 6513:
        return "Оренда"
    if mcc in {6010, 6011, 6012, 6051, 4829}:
        return "Банківські операції"
    hint = _merchant_hint(description)
    if hint in {"Доставка", "Пальне", "Техніка", "Підписки"}:
        return {"Доставка": "Логістика та доставка", "Пальне": "Транспорт і пальне", "Техніка": "Офіс і техніка", "Підписки": "ПЗ та підписки"}[hint]
    return "Товари та закупівлі"
