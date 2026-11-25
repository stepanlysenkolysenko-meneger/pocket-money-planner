import json
import os
from pathlib import Path

from dotenv import load_dotenv
MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
DATA_DIR = Path(os.environ.get("POCKET_MONEY_DATA_DIR", Path(__file__).resolve().parent))
ENV_FILE = DATA_DIR / ".env"


def load_api_key() -> str | None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    load_dotenv(ENV_FILE, override=True)
    global MODEL
    MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    return os.environ.get("OPENROUTER_API_KEY")


def configured() -> bool:
    return bool(load_api_key())


def client():
    # Import the network SDK only when an AI feature is actually used. This
    # keeps normal desktop startup noticeably lighter.
    from openai import OpenAI

    key = load_api_key()
    if not key:
        raise ValueError("Спочатку додай OpenRouter API-ключ у налаштуваннях AI")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key, default_headers={"HTTP-Referer": "https://pocket-money.local", "X-OpenRouter-Title": "Pocket Money"})


def json_response(name: str, schema: dict, instructions: str, content):
    response = client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": instructions}, {"role": "user", "content": content}],
        response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}},
        extra_body={"provider": {"require_parameters": True}},
    )
    return json.loads(response.choices[0].message.content)


def understand_command(message: str, context: dict, history: list[dict] | None = None) -> dict:
    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add_transaction", "add_goal", "set_limit", "answer"]},
            "reply": {"type": "string"},
            "transaction": {"type": ["object", "null"], "properties": {
                "type": {"type": "string", "enum": ["income", "expense"]}, "amount": {"type": "number"},
                "category": {"type": "string"}, "description": {"type": "string"}, "date": {"type": "string"}},
                "required": ["type", "amount", "category", "description", "date"], "additionalProperties": False},
            "goal": {"type": ["object", "null"], "properties": {"title": {"type": "string"}, "target_amount": {"type": "number"}, "saved_amount": {"type": "number"}, "deadline": {"type": "string"}}, "required": ["title", "target_amount", "saved_amount", "deadline"], "additionalProperties": False},
            "limit": {"type": ["object", "null"], "properties": {"category": {"type": "string"}, "amount": {"type": "number"}}, "required": ["category", "amount"], "additionalProperties": False},
        },
        "required": ["action", "reply", "transaction", "goal", "limit"], "additionalProperties": False,
    }
    instructions = """You are the confident action-capable financial assistant inside Pocket Money. Understand commands in any language and use conversation history to resolve short follow-ups such as 'yes', 'I confirm', 'then 50000', a date, or a category. Never make the user repeat information already present in recent conversation. Be decisive, concise, and friendly; do not moralize or refuse an ordinary financial logging request. When the user explicitly says to spend/add all available money, use the exact positive balance from context. Treat an explicit confirmation as confirmation of the immediately preceding proposed action. If one total amount is assigned to several purposes without a requested split, create one transaction with a concise combined category and description instead of asking how to divide it. Use today's date supplied in context when the user omits a transaction date. Dates must contain exactly YYYY-MM-DD and nothing else. For add_transaction choose income or expense and infer a concise category and description. Never invent an amount unless it is explicitly 'all available balance'. Never create a goal unless a positive target amount and deadline exist in the current message or conversation history; ask only for the one missing value. Never use zero, empty strings, or fabricated dates as placeholders. Use action=answer only when essential information is genuinely absent. Reply in the user's language."""
    transcript = {"context": context, "conversation_history": history or [], "current_user_message": message}
    return json_response("pocket_money_command", schema, instructions, json.dumps(transcript, ensure_ascii=False))


def read_receipt(image_data: str) -> dict:
    schema = {"type": "object", "properties": {
        "amount": {"type": ["number", "null"]}, "currency": {"type": ["string", "null"]},
        "date": {"type": ["string", "null"]}, "merchant": {"type": ["string", "null"]},
        "category": {"type": "string"}, "description": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}}, "language": {"type": ["string", "null"]}},
        "required": ["amount", "currency", "date", "merchant", "category", "description", "items", "language"], "additionalProperties": False}
    instructions = """Read this receipt in any language and script. Extract the final actually paid total, not change, subtotal, commission, card number, item price, or tax. Return ISO date YYYY-MM-DD when visible. Infer a short spending category and useful description in Ukrainian. Preserve merchant meaning. If uncertain about total return null."""
    content = [{"type": "text", "text": "Analyze this receipt carefully."}, {"type": "image_url", "image_url": {"url": image_data, "detail": "high"}}]
    return json_response("receipt", schema, instructions, content)


def translate(texts: list[str], language: str) -> list[str]:
    schema = {"type": "object", "properties": {"translations": {"type": "array", "items": {"type": "string"}}}, "required": ["translations"], "additionalProperties": False}
    instructions = "Translate UI strings naturally and concisely. Preserve numbers, currency symbols, emoji, punctuation, and brand name Pocket Money. Return exactly the same number of strings in the same order."
    result = json_response("ui_translation", schema, instructions, json.dumps({"target_language": language, "texts": texts}, ensure_ascii=False))
    if len(result["translations"]) != len(texts):
        raise ValueError("Translation count mismatch")
    return result["translations"]
