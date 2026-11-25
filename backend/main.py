from collections import defaultdict
import base64
import csv
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import hmac
import io
import os
from pathlib import Path
import re
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session

import ai_service, bank_service, crypto_service, crud, models, privat_service, schemas
import statement_import
from database import Base, SessionLocal, engine, get_db

app = FastAPI(title="Pocket Money API", version="1.0.0")
ocr_engine = None
BOOTSTRAP_TOKEN = os.environ.get("POCKET_MONEY_BOOTSTRAP_TOKEN", "")
APP_SESSION_TOKEN = secrets.token_urlsafe(48)
BANK_VAULT_TOKEN = secrets.token_urlsafe(48)
BANK_BALANCE_REFRESH_INTERVAL = timedelta(seconds=60)
BANK_BALANCE_REFRESHED_AT = {}
APP_ORIGIN = "http://127.0.0.1:8765"
PUBLIC_API_PATHS = {"/api/health"}
AUTH_API_PATHS = {"/api/auth/status", "/api/auth/register", "/api/auth/login", "/api/auth/logout"}
FRONTEND_DIR = Path(
    os.environ.get(
        "POCKET_MONEY_RESOURCE_DIR",
        Path(__file__).resolve().parent.parent,
    )
) / "frontend"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[APP_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


@app.middleware("http")
async def local_security(request: Request, call_next):
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    if host not in {"127.0.0.1", "localhost", "testserver"}:
        return JSONResponse(status_code=400, content={"detail": "Невірний локальний хост"})
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC_API_PATHS:
        supplied = request.cookies.get("pocket_session", "")
        if not supplied or not hmac.compare_digest(supplied, APP_SESSION_TOKEN):
            return JSONResponse(status_code=401, content={"detail": "Захищена сесія недійсна. Перезапусти Pocket Money"})
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin != APP_ORIGIN:
                return JSONResponse(status_code=403, content={"detail": "Запит з іншого джерела заблоковано"})
        if path not in AUTH_API_PATHS:
            with SessionLocal() as security_db:
                account = security_db.query(models.Account).first()
                if not account or not account.is_authenticated:
                    return JSONResponse(status_code=401, content={"detail": "Спочатку увійди в Pocket Money"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=(), payment=(), usb=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.on_event("shutdown")
def shutdown():
    """Скидати прапор автентифікації при закритті сервера, щоб між запусками не вимагався PIN."""
    with SessionLocal() as security_db:
        account = security_db.query(models.Account).first()
        if account:
            account.is_authenticated = False
            security_db.commit()


MIGRATIONS = [
    {
        "version": "001",
        "sql": [
            "ALTER TABLE transactions ADD COLUMN receipt_data TEXT",
            "ALTER TABLE transactions ADD COLUMN external_id VARCHAR(160)",
            "ALTER TABLE transactions ADD COLUMN bank_account_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN currency_code INTEGER",
            "ALTER TABLE transactions ADD COLUMN mcc INTEGER",
            "ALTER TABLE transactions ADD COLUMN scope VARCHAR(12) NOT NULL DEFAULT 'personal'",
            "ALTER TABLE transactions ADD COLUMN workspace_id INTEGER",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_transactions_external_id ON transactions (external_id)",
            "ALTER TABLE goals ADD COLUMN scope VARCHAR(12) NOT NULL DEFAULT 'personal'",
            "ALTER TABLE bank_accounts ADD COLUMN scope VARCHAR(12) NOT NULL DEFAULT 'personal'",
            "ALTER TABLE bank_accounts ADD COLUMN workspace_id INTEGER",
            "ALTER TABLE bank_accounts ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
            "ALTER TABLE bank_accounts ADD COLUMN balance_updated_at DATETIME",
            "ALTER TABLE chat_messages ADD COLUMN scope VARCHAR(12) NOT NULL DEFAULT 'personal'",
            "ALTER TABLE accounts ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE accounts ADD COLUMN locked_until DATETIME",
            "ALTER TABLE accounts ADD COLUMN ai_consent BOOLEAN NOT NULL DEFAULT 0",
            "UPDATE accounts SET is_authenticated = 0",
            "INSERT OR IGNORE INTO finance_workspaces (name, scope, is_default) VALUES ('Основний побут', 'personal', 1)",
            "INSERT OR IGNORE INTO finance_workspaces (name, scope, is_default) VALUES ('Основний бізнес', 'business', 1)",
            "UPDATE transactions SET workspace_id = (SELECT id FROM finance_workspaces WHERE scope = transactions.scope AND is_default = 1 LIMIT 1) WHERE workspace_id IS NULL",
            "UPDATE bank_accounts SET workspace_id = (SELECT id FROM finance_workspaces WHERE scope = bank_accounts.scope AND is_default = 1 LIMIT 1) WHERE workspace_id IS NULL",
            "UPDATE transactions SET workspace_id = (SELECT workspace_id FROM bank_accounts WHERE bank_accounts.id = transactions.bank_account_id) WHERE bank_account_id IS NOT NULL",
            "UPDATE transactions SET currency_code = (SELECT bank_accounts.currency_code FROM bank_accounts WHERE bank_accounts.id = transactions.bank_account_id) WHERE bank_account_id IN (SELECT bank_accounts.id FROM bank_accounts JOIN bank_connections ON bank_connections.id = bank_accounts.connection_id WHERE bank_connections.provider = 'monobank')",
        ],
    },
    {
        "version": "002",
        "sql": [
            "INSERT INTO budget_limits_v2 (category, amount, scope) SELECT category, amount, 'personal' FROM budget_limits WHERE NOT EXISTS (SELECT 1 FROM budget_limits_v2)",
        ],
    },
]


def _column_exists(table: str, column: str) -> bool:
    return column in {c["name"] for c in inspect(engine).get_columns(table)}


def _run_migration(version: str, sql_statements: list[str], connection) -> None:
    with SessionLocal() as sec_db:
        already = sec_db.query(models.SchemaMigration).filter_by(version=version).first()
    if already:
        return
    for stmt in sql_statements:
        try:
            connection.execute(text(stmt))
        except Exception:
            pass
    with SessionLocal() as sec_db:
        sec_db.add(models.SchemaMigration(version=version))
        sec_db.commit()


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        for migration in MIGRATIONS:
            _run_migration(migration["version"], migration["sql"], connection)

    # Back-compat для старих БД: додаємо відсутні стовпчики індивідуально
    with engine.begin() as connection:
        if not _column_exists("transactions", "receipt_data"):
            connection.execute(text("ALTER TABLE transactions ADD COLUMN receipt_data TEXT"))
        if not _column_exists("transactions", "external_id"):
            connection.execute(text("ALTER TABLE transactions ADD COLUMN external_id VARCHAR(160)"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_transactions_external_id ON transactions (external_id)"))
        if not _column_exists("transactions", "bank_account_id"):
            connection.execute(text("ALTER TABLE transactions ADD COLUMN bank_account_id INTEGER"))
        if not _column_exists("transactions", "currency_code"):
            connection.execute(text("ALTER TABLE transactions ADD COLUMN currency_code INTEGER"))
        if not _column_exists("transactions", "mcc"):
            connection.execute(text("ALTER TABLE transactions ADD COLUMN mcc INTEGER"))
        if not _column_exists("transactions", "scope"):
            connection.execute(text("ALTER TABLE transactions ADD COLUMN scope VARCHAR(12) NOT NULL DEFAULT 'personal'"))
        if not _column_exists("transactions", "workspace_id"):
            connection.execute(text("ALTER TABLE transactions ADD COLUMN workspace_id INTEGER"))
        if not _column_exists("goals", "scope"):
            connection.execute(text("ALTER TABLE goals ADD COLUMN scope VARCHAR(12) NOT NULL DEFAULT 'personal'"))
        if not _column_exists("bank_accounts", "scope"):
            connection.execute(text("ALTER TABLE bank_accounts ADD COLUMN scope VARCHAR(12) NOT NULL DEFAULT 'personal'"))
        if not _column_exists("bank_accounts", "workspace_id"):
            connection.execute(text("ALTER TABLE bank_accounts ADD COLUMN workspace_id INTEGER"))
        if not _column_exists("bank_accounts", "is_active"):
            connection.execute(text("ALTER TABLE bank_accounts ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
        if not _column_exists("bank_accounts", "balance_updated_at"):
            connection.execute(text("ALTER TABLE bank_accounts ADD COLUMN balance_updated_at DATETIME"))
        if not _column_exists("chat_messages", "scope"):
            connection.execute(text("ALTER TABLE chat_messages ADD COLUMN scope VARCHAR(12) NOT NULL DEFAULT 'personal'"))
        if not _column_exists("accounts", "failed_attempts"):
            connection.execute(text("ALTER TABLE accounts ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0"))
        if not _column_exists("accounts", "locked_until"):
            connection.execute(text("ALTER TABLE accounts ADD COLUMN locked_until DATETIME"))
        if not _column_exists("accounts", "ai_consent"):
            connection.execute(text("ALTER TABLE accounts ADD COLUMN ai_consent BOOLEAN NOT NULL DEFAULT 0"))

        tables = set(inspect(engine).get_table_names())
        if "budget_limits" in tables and "budget_limits_v2" in tables:
            count = connection.execute(text("SELECT COUNT(*) FROM budget_limits_v2")).scalar()
            if not count:
                connection.execute(text("INSERT INTO budget_limits_v2 (category, amount, scope) SELECT category, amount, 'personal' FROM budget_limits"))

        connection.execute(text("UPDATE accounts SET is_authenticated = 0"))
        connection.execute(text("UPDATE transactions SET workspace_id = (SELECT id FROM finance_workspaces WHERE scope = transactions.scope AND is_default = 1 LIMIT 1) WHERE workspace_id IS NULL"))
        connection.execute(text("UPDATE bank_accounts SET workspace_id = (SELECT id FROM finance_workspaces WHERE scope = bank_accounts.scope AND is_default = 1 LIMIT 1) WHERE workspace_id IS NULL"))
        connection.execute(text("UPDATE transactions SET workspace_id = (SELECT workspace_id FROM bank_accounts WHERE bank_accounts.id = transactions.bank_account_id) WHERE bank_account_id IS NOT NULL"))


def _escape_csv_value(value: str | None) -> str:
    """Захист від ін’єкції формул електронних таблиць.

    Значення, що починаються з =, +, - або @, можуть бути інтерпретовані
    як формула при відкритті CSV в Excel / LibreOffice. Додаємо апострф
    на початок, щоб табличний редактор трактував текст як рядок.
    """
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in {"=", "+", "-", "@"}:
        return "'" + text
    return text


def get_or_404(db: Session, model, item_id: int, label: str):
    item = db.get(model, item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"{label} не знайдено")
    return item


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/manifest.webmanifest", include_in_schema=False)
def web_manifest():
    return FileResponse(FRONTEND_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(FRONTEND_DIR / "sw.js", media_type="application/javascript", headers={"Service-Worker-Allowed": "/"})


@app.get("/app-icon.png", include_in_schema=False)
def app_icon():
    resource_root = Path(os.environ.get("POCKET_MONEY_RESOURCE_DIR", Path(__file__).resolve().parent.parent))
    return FileResponse(resource_root / "assets" / "pocket-money.png", media_type="image/png")


@app.get("/api/ai/status")
def ai_status():
    return {"configured": ai_service.configured(), "model": ai_service.MODEL}


def clean_iso_date(value) -> str | None:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(0)).isoformat()
    except ValueError:
        return None


def clean_scope(value: str) -> str:
    if value not in {"personal", "business"}:
        raise HTTPException(status_code=400, detail="Невідомий фінансовий простір")
    return value


def resolve_workspace(db: Session, scope: str, workspace_id: int | None = None) -> models.FinanceWorkspace:
    scope = clean_scope(scope)
    query = db.query(models.FinanceWorkspace).filter(models.FinanceWorkspace.scope == scope)
    workspace = query.filter(models.FinanceWorkspace.id == workspace_id).first() if workspace_id else query.filter(models.FinanceWorkspace.is_default.is_(True)).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Фінансовий профіль не знайдено")
    return workspace


def validate_workspace_filter(db: Session, scope: str, workspace_id: int | None) -> int | None:
    if workspace_id is None:
        return None
    return resolve_workspace(db, scope, workspace_id).id


def workspace_payload(workspace: models.FinanceWorkspace, db: Session):
    return {
        "id": workspace.id,
        "name": workspace.name,
        "scope": workspace.scope,
        "is_default": workspace.is_default,
        "card_count": db.query(models.BankAccount).filter(models.BankAccount.workspace_id == workspace.id, models.BankAccount.is_active.is_(True)).count(),
        "transaction_count": db.query(models.Transaction).filter(models.Transaction.workspace_id == workspace.id).count(),
    }


@app.get("/api/workspaces")
def workspaces(scope: str = "personal", db: Session = Depends(get_db)):
    scope = clean_scope(scope)
    rows = db.query(models.FinanceWorkspace).filter(models.FinanceWorkspace.scope == scope).order_by(models.FinanceWorkspace.is_default.desc(), models.FinanceWorkspace.name).all()
    return [workspace_payload(row, db) for row in rows]


@app.post("/api/workspaces", status_code=status.HTTP_201_CREATED)
def create_workspace(data: schemas.WorkspaceCreate, db: Session = Depends(get_db)):
    exists = db.query(models.FinanceWorkspace).filter(models.FinanceWorkspace.scope == data.scope, models.FinanceWorkspace.name == data.name).first()
    if exists:
        raise HTTPException(status_code=409, detail="Профіль із такою назвою вже існує")
    workspace = models.FinanceWorkspace(name=data.name, scope=data.scope, is_default=False)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace_payload(workspace, db)


@app.put("/api/workspaces/{workspace_id}")
def rename_workspace(workspace_id: int, data: schemas.WorkspaceUpdate, db: Session = Depends(get_db)):
    workspace = get_or_404(db, models.FinanceWorkspace, workspace_id, "Фінансовий профіль")
    duplicate = db.query(models.FinanceWorkspace).filter(models.FinanceWorkspace.scope == workspace.scope, models.FinanceWorkspace.name == data.name, models.FinanceWorkspace.id != workspace.id).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Профіль із такою назвою вже існує")
    workspace.name = data.name
    db.commit()
    db.refresh(workspace)
    return workspace_payload(workspace, db)


@app.delete("/api/workspaces/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(workspace_id: int, db: Session = Depends(get_db)):
    workspace = get_or_404(db, models.FinanceWorkspace, workspace_id, "Фінансовий профіль")
    if workspace.is_default:
        raise HTTPException(status_code=400, detail="Основний профіль видалити не можна")
    default = resolve_workspace(db, workspace.scope)
    db.query(models.BankAccount).filter(models.BankAccount.workspace_id == workspace.id).update({models.BankAccount.workspace_id: default.id}, synchronize_session=False)
    db.query(models.Transaction).filter(models.Transaction.workspace_id == workspace.id).update({models.Transaction.workspace_id: default.id}, synchronize_session=False)
    db.delete(workspace)
    db.commit()


def require_bank_vault(request: Request) -> bool:
    supplied = request.cookies.get("pocket_bank_vault", "")
    if not supplied or not hmac.compare_digest(supplied, BANK_VAULT_TOKEN):
        raise HTTPException(status_code=403, detail="Підтвердь PIN-код, щоб змінювати банківські підключення")
    return True


@app.get("/api/security/bank-vault")
def bank_vault_status(request: Request):
    supplied = request.cookies.get("pocket_bank_vault", "")
    return {
        "unlocked": bool(supplied and hmac.compare_digest(supplied, BANK_VAULT_TOKEN)),
        "expires_in_minutes": 5,
        "windows_encryption": True,
        "payments_disabled": True,
    }


@app.post("/api/security/bank-vault/unlock")
def unlock_bank_vault(data: schemas.PinConfirmation, db: Session = Depends(get_db)):
    account = db.query(models.Account).first()
    if not account:
        raise HTTPException(status_code=404, detail="Профіль не знайдено")
    now = datetime.now()
    if account.locked_until and account.locked_until.replace(tzinfo=None) > now:
        seconds = int((account.locked_until.replace(tzinfo=None) - now).total_seconds()) + 1
        raise HTTPException(status_code=429, detail=f"Забагато невдалих спроб. Спробуй через {seconds} с")
    pin_valid, legacy_hash = verify_pin(data.pin, account.pin_hash)
    if not pin_valid:
        account.failed_attempts = int(account.failed_attempts or 0) + 1
        if account.failed_attempts >= 5:
            account.locked_until = now + timedelta(minutes=5)
            account.failed_attempts = 0
        db.commit()
        raise HTTPException(status_code=401, detail="Неправильний PIN-код")
    if legacy_hash:
        account.pin_hash = hash_pin(data.pin)
    account.failed_attempts = 0
    account.locked_until = None
    db.commit()
    response = JSONResponse({"unlocked": True, "expires_in_minutes": 5})
    response.set_cookie(
        "pocket_bank_vault", BANK_VAULT_TOKEN, max_age=300, httponly=True,
        samesite="strict", secure=False, path="/api/",
    )
    return response


@app.post("/api/security/bank-vault/lock")
def lock_bank_vault():
    response = JSONResponse({"unlocked": False})
    response.delete_cookie("pocket_bank_vault", path="/api/")
    return response


@app.post("/api/ai/chat")
def ai_chat(data: schemas.AiChatRequest, db: Session = Depends(get_db)):
    account = db.query(models.Account).first()
    if account and not account.ai_consent:
        raise HTTPException(
            status_code=403,
            detail="Давай згоди на обробку фінансових даних AI. Увімкни дозвіл у налаштуваннях штучного інтелекту.",
        )
    scope = clean_scope(data.scope)
    items = crud.get_transactions(db, scope)
    income = sum((x.amount for x in items if x.type == "income"), Decimal("0"))
    expense = sum((x.amount for x in items if x.type == "expense"), Decimal("0"))
    context = {"today": date.today().isoformat(), "scope": scope, "balance": float(income - expense), "income": float(income), "expense": float(expense),
               "recent_transactions": [{"type": x.type, "amount": float(x.amount), "category": x.category, "description": x.description, "date": x.date.isoformat()} for x in items[:30]]}
    history_rows = db.query(models.ChatMessage).filter(models.ChatMessage.scope == scope).order_by(models.ChatMessage.id.desc()).limit(24).all()
    history = [{"role": row.role, "content": decrypt_field(row.content)} for row in reversed(history_rows)]

    def respond(reply: str, action: str = "answer", changed: bool = False):
        db.add(models.ChatMessage(role="user", content=encrypt_field(data.message), scope=scope))
        db.add(models.ChatMessage(role="assistant", content=encrypt_field(reply), scope=scope))
        db.commit()
        return {"reply": reply, "action": action, "changed": changed}

    try:
        result = ai_service.understand_command(data.message, context, history)
        action = result["action"]
        created = None
        if action == "add_transaction" and result["transaction"]:
            transaction = result["transaction"]
            if float(transaction.get("amount") or 0) <= 0:
                return respond("Уточни суму операції — вона має бути більшою за нуль.")
            transaction["date"] = clean_iso_date(transaction.get("date")) or date.today().isoformat()
            transaction["scope"] = scope
            transaction["workspace_id"] = resolve_workspace(db, scope).id
            created = crud.create_transaction(db, schemas.TransactionCreate(**transaction))
        elif action == "add_goal" and result["goal"]:
            goal = result["goal"]
            if float(goal.get("target_amount") or 0) <= 0:
                return respond("Яку суму потрібно зібрати на цю ціль?")
            deadline = clean_iso_date(goal.get("deadline"))
            if not deadline:
                return respond("До якої дати ти хочеш зібрати гроші?")
            goal["deadline"] = deadline
            goal["saved_amount"] = max(0, float(goal.get("saved_amount") or 0))
            goal["scope"] = scope
            created = crud.create_goal(db, schemas.GoalCreate(**goal))
        elif action == "set_limit" and result["limit"]:
            if float(result["limit"].get("amount") or 0) <= 0:
                return respond("Уточни суму ліміту — вона має бути більшою за нуль.")
            result["limit"]["scope"] = scope
            limit_data = schemas.BudgetLimitBase(**result["limit"])
            created = db.query(models.BudgetLimit).filter(models.BudgetLimit.scope == scope, models.BudgetLimit.category == limit_data.category).first()
            if created: created.amount = limit_data.amount
            else: created = models.BudgetLimit(**limit_data.model_dump()); db.add(created)
            db.commit(); db.refresh(created)
        return respond(result["reply"], action, created is not None)
    except Exception as error:
        message = str(error)
        if "API key" in message or "api_key" in message or "401" in message: message = "OpenRouter API-ключ недійсний або не має доступу"
        elif "validation error" in message.lower(): message = "Не вдалося виконати команду: уточни суму, дату або назву"
        raise HTTPException(status_code=400, detail=message) from error


@app.get("/api/ai/history")
def ai_history(scope: str = "personal", db: Session = Depends(get_db)):
    scope = clean_scope(scope)
    rows = db.query(models.ChatMessage).filter(models.ChatMessage.scope == scope).order_by(models.ChatMessage.id.desc()).limit(50).all()
    return [{"role": row.role, "content": decrypt_field(row.content)} for row in reversed(rows)]


@app.post("/api/ai/receipt")
def ai_receipt(data: schemas.ReceiptOcrRequest, db: Session = Depends(get_db)):
    account = db.query(models.Account).first()
    if account and not account.ai_consent:
        raise HTTPException(
            status_code=403,
            detail="Давай згоди на обробку фінансових даних AI. Увімкни дозвіл у налаштуваннях штучного інтелекту.",
        )
    try: return ai_service.read_receipt(data.image_data)
    except Exception as error: raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/ai/translate")
def ai_translate(data: schemas.TranslateRequest):
    try: return {"translations": ai_service.translate(data.texts, data.language)}
    except Exception as error: raise HTTPException(status_code=400, detail=str(error)) from error


def bank_account_payload(account: models.BankAccount):
    digits = re.sub(r"\D", "", account.masked_pan or "")
    masked_pan = f"•••• {digits[-4:]}" if len(digits) >= 4 else None
    return {
        "id": account.id,
        "provider": account.connection.provider,
        "bank_name": account.connection.display_name,
        "display_name": account.display_name,
        "masked_pan": masked_pan,
        "account_type": account.account_type,
        "currency_code": account.currency_code,
        "balance": float(account.balance),
        "credit_limit": float(account.credit_limit),
        "is_active": account.is_active,
        "balance_updated_at": account.balance_updated_at.isoformat() if account.balance_updated_at else None,
        "last_sync": account.last_sync.isoformat() if account.last_sync else None,
        "scope": account.scope,
        "workspace_id": account.workspace_id,
        "workspace_name": account.workspace.name if account.workspace else None,
    }


def _refresh_due(connection_id: int) -> bool:
    refreshed_at = BANK_BALANCE_REFRESHED_AT.get(connection_id)
    return not refreshed_at or datetime.now() - refreshed_at >= BANK_BALANCE_REFRESH_INTERVAL


def _refresh_monobank_accounts(connection: models.BankConnection, info: dict, target_workspace: models.FinanceWorkspace, db: Session):
    now = datetime.now()
    accounts = db.query(models.BankAccount).filter(models.BankAccount.connection_id == connection.id).all()
    by_external_id = {account.external_id: account for account in accounts}
    for account in accounts:
        account.is_active = False
    refreshed = []
    for source in info.get("accounts", []):
        external_id = str(source.get("id") or "").strip()
        if not external_id:
            continue
        account = by_external_id.get(external_id)
        if not account:
            account = models.BankAccount(
                connection_id=connection.id,
                external_id=external_id,
                scope=target_workspace.scope,
                workspace_id=target_workspace.id,
            )
            db.add(account)
            by_external_id[external_id] = account
        masked = (source.get("maskedPan") or [None])[0]
        card_type = source.get("type") or "card"
        last_four = masked[-4:] if masked else external_id[-4:]
        account.connection_id = connection.id
        account.display_name = f"Monobank {card_type} •{last_four}"
        account.masked_pan = masked
        account.account_type = card_type
        if not account.workspace_id:
            account.scope = target_workspace.scope
            account.workspace_id = target_workspace.id
        account.currency_code = int(source.get("currencyCode") or 980)
        account.balance = Decimal(str(source.get("balance", 0))) / 100
        account.credit_limit = Decimal(str(source.get("creditLimit", 0))) / 100
        account.balance_updated_at = now
        account.is_active = True
        refreshed.append(account)
    BANK_BALANCE_REFRESHED_AT[connection.id] = now
    return refreshed


def _refresh_privat_accounts(connection: models.BankConnection, balances: list, target_workspace: models.FinanceWorkspace, db: Session):
    now = datetime.now()
    accounts = db.query(models.BankAccount).filter(models.BankAccount.connection_id == connection.id).all()
    by_external_id = {account.external_id: account for account in accounts}
    for account in accounts:
        account.is_active = False
    refreshed = []
    for source in balances:
        iban = str(source.get("acc") or "").strip()
        if not iban:
            continue
        external_id = f"privat-business:{iban}"
        account = by_external_id.get(external_id)
        if not account:
            account = models.BankAccount(
                connection_id=connection.id,
                external_id=external_id,
                scope=target_workspace.scope,
                workspace_id=target_workspace.id,
            )
            db.add(account)
            by_external_id[external_id] = account
        account.connection_id = connection.id
        account.display_name = (source.get("nameACC") or f"ПриватБанк •{iban[-4:]}").strip()[:100]
        account.masked_pan = f"{iban[:4]}••••••••{iban[-4:]}" if len(iban) >= 8 else iban
        account.account_type = "business"
        account.currency_code = CURRENCY_CODES.get(str(source.get("currency") or "UAH").upper(), 980)
        raw_balance = source.get("balanceOut")
        if raw_balance is None:
            raw_balance = source.get("balanceOutEq")
        account.balance = Decimal(str(raw_balance or 0))
        account.credit_limit = Decimal("0")
        if not account.workspace_id:
            account.scope = target_workspace.scope
            account.workspace_id = target_workspace.id
        account.balance_updated_at = now
        account.is_active = True
        refreshed.append(account)
    BANK_BALANCE_REFRESHED_AT[connection.id] = now
    return refreshed


@app.get("/api/banks/accounts")
def bank_accounts(db: Session = Depends(get_db)):
    accounts = db.query(models.BankAccount).filter(models.BankAccount.is_active.is_(True)).order_by(models.BankAccount.id).all()
    return [bank_account_payload(account) for account in accounts]


@app.post("/api/banks/refresh")
def refresh_bank_balances(db: Session = Depends(get_db)):
    updated = 0
    deactivated = 0
    errors = []
    connections = db.query(models.BankConnection).filter(models.BankConnection.provider.in_({"monobank", "privat_business"})).all()
    for connection in connections:
        if not _refresh_due(connection.id):
            continue
        try:
            token = bank_service.unprotect_token(connection.encrypted_token)
            existing = db.query(models.BankAccount).filter(models.BankAccount.connection_id == connection.id).order_by(models.BankAccount.id).first()
            target_workspace = existing.workspace if existing and existing.workspace else resolve_workspace(db, "business" if connection.provider == "privat_business" else "personal")
            active_before = db.query(models.BankAccount).filter(models.BankAccount.connection_id == connection.id, models.BankAccount.is_active.is_(True)).count()
            if connection.provider == "monobank":
                refreshed = _refresh_monobank_accounts(connection, bank_service.client_info(token), target_workspace, db)
            else:
                today = date.today().strftime("%d-%m-%Y")
                refreshed = _refresh_privat_accounts(connection, privat_service.balances(token, today, today), target_workspace, db)
            updated += len(refreshed)
            active_after = sum(1 for account in refreshed if account.is_active)
            deactivated += max(0, active_before - active_after)
            db.commit()
        except Exception as error:
            db.rollback()
            errors.append(f"{connection.display_name}: {error}")
    return {"updated": updated, "deactivated": deactivated, "errors": errors}


@app.post("/api/banks/monobank/connect")
def connect_monobank(data: schemas.BankTokenRequest, db: Session = Depends(get_db), _vault: bool = Depends(require_bank_vault)):
    try:
        target_workspace = resolve_workspace(db, data.scope, data.workspace_id)
        info = bank_service.client_info(data.token)
        connection = db.query(models.BankConnection).filter(models.BankConnection.provider == "monobank").first()
        if not connection:
            connection = models.BankConnection(provider="monobank", display_name="Monobank", encrypted_token="")
            db.add(connection)
            db.flush()
        connection.display_name = "Monobank"
        connection.encrypted_token = bank_service.protect_token(data.token)

        _refresh_monobank_accounts(connection, info, target_workspace, db)
        db.commit()
        accounts = db.query(models.BankAccount).filter(models.BankAccount.connection_id == connection.id, models.BankAccount.is_active.is_(True)).all()
        return {"connected": True, "client_name": info.get("name"), "accounts": [bank_account_payload(item) for item in accounts]}
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Не вдалося підключити Monobank: {error}") from error


@app.post("/api/banks/import")
def import_bank_statement(data: schemas.BankStatementImportRequest, db: Session = Depends(get_db), _vault: bool = Depends(require_bank_vault)):
    try:
        target_workspace = resolve_workspace(db, data.scope, data.workspace_id)
        provider_key = f"file-{hashlib.sha256(data.bank.casefold().encode('utf-8')).hexdigest()[:16]}"
        connection = db.query(models.BankConnection).filter(models.BankConnection.provider == provider_key).first()
        if not connection:
            connection = models.BankConnection(provider=provider_key, display_name=data.bank, encrypted_token="statement-file")
            db.add(connection)
            db.flush()
        account_key = hashlib.sha256(f"{data.bank.casefold()}|{data.account_name.casefold()}".encode("utf-8")).hexdigest()[:24]
        external_id = f"import-{account_key}"
        account = db.query(models.BankAccount).filter(models.BankAccount.external_id == external_id).first()
        if not account:
            account = models.BankAccount(
                connection_id=connection.id,
                external_id=external_id,
                display_name=f"{data.bank} · {data.account_name}",
                account_type="imported",
                currency_code=980,
                balance=0,
                credit_limit=0,
                scope=data.scope,
                workspace_id=target_workspace.id,
            )
            db.add(account)
            db.flush()
        account.scope = data.scope
        account.workspace_id = target_workspace.id
        parsed = statement_import.parse(data.file_data, provider_key, account_key, data.scope)
        imported = 0
        duplicates = 0
        for item in parsed:
            existing = db.query(models.Transaction).filter(models.Transaction.external_id == item["external_id"]).first()
            if existing:
                duplicates += 1
                continue
            db.add(models.Transaction(**item, bank_account_id=account.id, scope=data.scope, workspace_id=target_workspace.id))
            imported += 1
        db.flush()
        transactions = db.query(models.Transaction).filter(models.Transaction.bank_account_id == account.id).all()
        account.balance = sum((item.amount if item.type == "income" else -item.amount for item in transactions), Decimal("0"))
        account.last_sync = datetime.now()
        db.commit()
        db.refresh(account)
        return {"imported": imported, "duplicates": duplicates, "account": bank_account_payload(account)}
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Не вдалося імпортувати виписку: {error}") from error


CURRENCY_CODES = {"UAH": 980, "USD": 840, "EUR": 978, "PLN": 985}


@app.post("/api/banks/privat-business/connect")
def connect_privat_business(data: schemas.PrivatBusinessTokenRequest, db: Session = Depends(get_db), _vault: bool = Depends(require_bank_vault)):
    try:
        target_workspace = resolve_workspace(db, data.scope, data.workspace_id)
        privat_service.verify(data.token)
        today = date.today()
        date_text = today.strftime("%d-%m-%Y")
        balances = privat_service.balances(data.token, date_text, date_text)
        if not balances:
            raise ValueError("API не повернув активних рахунків. Перевір доступ «Баланси й транзакції» у Приват24 для бізнесу")
        connection = db.query(models.BankConnection).filter(models.BankConnection.provider == "privat_business").first()
        if not connection:
            connection = models.BankConnection(provider="privat_business", display_name="ПриватБанк для бізнесу", encrypted_token="")
            db.add(connection)
            db.flush()
        connection.encrypted_token = bank_service.protect_token(data.token)
        _refresh_privat_accounts(connection, balances, target_workspace, db)
        db.commit()
        accounts = db.query(models.BankAccount).filter(models.BankAccount.connection_id == connection.id, models.BankAccount.is_active.is_(True)).all()
        return {"connected": True, "accounts": [bank_account_payload(item) for item in accounts]}
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Не вдалося підключити ПриватБанк: {error}") from error


def sync_privat_business_account(account: models.BankAccount, db: Session):
    token = bank_service.unprotect_token(account.connection.encrypted_token)
    iban = account.external_id.removeprefix("privat-business:")
    today = date.today()
    start = (today - timedelta(days=31)).strftime("%d-%m-%Y")
    end = today.strftime("%d-%m-%Y")
    rows = privat_service.transactions(token, iban, start, end)
    imported = 0
    recategorized = 0
    for source in rows:
        reference = str(source.get("TECHNICAL_TRANSACTION_ID") or source.get("ID") or "").strip()
        if not reference and (source.get("REF") or source.get("REFN")):
            reference = f"{source.get('REF', '')}:{source.get('REFN', '')}"
        if not reference:
            continue
        external_id = f"privat-business:{iban}:{reference}"
        transaction = db.query(models.Transaction).filter(models.Transaction.external_id == external_id).first()
        description = str(source.get("OSND") or source.get("AUT_CNTR_NAM") or "Операція ПриватБанку").strip()[:160]
        raw_type = str(source.get("TRANTYPE") or "D").upper()
        item_type = "income" if raw_type == "C" else "expense"
        category = "Продажі" if item_type == "income" and account.scope == "business" else "Надходження на картку" if item_type == "income" else bank_service.business_category_for_mcc(None, description) if account.scope == "business" else bank_service.category_for_mcc(None, description)
        if transaction:
            transaction.bank_account_id = account.id
            transaction.scope = account.scope
            transaction.workspace_id = account.workspace_id
            transaction.currency_code = account.currency_code
            if transaction.category in {"Інше", "Інші покупки", "Товари та закупівлі"} and transaction.category != category:
                transaction.category = category
                recategorized += 1
            continue
        raw_date = str(source.get("DAT_OD") or source.get("DAT_KL") or "")[:10]
        try:
            item_date = datetime.strptime(raw_date, "%d.%m.%Y").date()
        except ValueError:
            item_date = today
        source_currency = CURRENCY_CODES.get(str(source.get("CCY") or "UAH").upper(), account.currency_code)
        raw_amount = source.get("SUM")
        if source_currency != account.currency_code and source.get("SUM_E") is not None:
            raw_amount = source.get("SUM_E")
        amount = abs(Decimal(str(raw_amount or 0)))
        if amount <= 0:
            continue
        db.add(models.Transaction(
            type=item_type, amount=amount, category=category, description=description, date=item_date,
            external_id=external_id, bank_account_id=account.id, currency_code=account.currency_code,
            scope=account.scope, workspace_id=account.workspace_id,
        ))
        imported += 1
    if _refresh_due(account.connection.id):
        balance_rows = privat_service.balances(token, end, end)
        target_workspace = account.workspace if account.workspace else resolve_workspace(db, account.scope)
        _refresh_privat_accounts(account.connection, balance_rows, target_workspace, db)
    if account.is_active:
        account.last_sync = datetime.now()
    db.commit()
    return {"imported": imported, "recategorized": recategorized, "account": bank_account_payload(account)}


@app.post("/api/banks/accounts/{account_id}/sync")
def sync_bank_account(account_id: int, db: Session = Depends(get_db)):
    account = get_or_404(db, models.BankAccount, account_id, "Картку")
    now = datetime.now()
    latest_connection_sync = db.query(func.max(models.BankAccount.last_sync)).filter(models.BankAccount.connection_id == account.connection_id).scalar()
    if latest_connection_sync and now - latest_connection_sync.replace(tzinfo=None) < timedelta(seconds=60):
        wait_seconds = 60 - int((now - latest_connection_sync.replace(tzinfo=None)).total_seconds())
        raise HTTPException(status_code=429, detail=f"Наступна синхронізація буде доступна через {wait_seconds} с")
    try:
        if account.connection.provider == "privat_business":
            return sync_privat_business_account(account, db)
        if account.connection.provider != "monobank":
            raise ValueError("Для цієї картки доступне оновлення через повторний імпорт файлу")
        token = bank_service.unprotect_token(account.connection.encrypted_token)
        if _refresh_due(account.connection.id):
            target_workspace = account.workspace if account.workspace else resolve_workspace(db, account.scope)
            _refresh_monobank_accounts(account.connection, bank_service.client_info(token), target_workspace, db)
            if not account.is_active:
                db.commit()
                return {"imported": 0, "recategorized": 0, "inactive": True, "account": bank_account_payload(account)}
        from_time = now - timedelta(days=31)
        statement = bank_service.statement(token, account.external_id, int(from_time.timestamp()), int(now.timestamp()))
        imported = 0
        recategorized = 0
        for source in statement:
            if source.get("hold") or not source.get("id") or not source.get("amount"):
                continue
            external_id = f"monobank:{source['id']}"
            existing = db.query(models.Transaction).filter(models.Transaction.external_id == external_id).first()
            mcc = int(source.get("mcc") or 0) or None
            description = (source.get("description") or source.get("comment") or "Операція Monobank").strip()[:160]
            automatic_category = bank_service.business_category_for_mcc(mcc, description) if account.scope == "business" else bank_service.category_for_mcc(mcc, description)
            if existing:
                existing.mcc = mcc
                raw_amount = int(source["amount"])
                existing.type = "income" if raw_amount > 0 else "expense"
                existing.amount = Decimal(abs(raw_amount)) / 100
                existing.currency_code = account.currency_code
                existing.bank_account_id = account.id
                existing.scope = account.scope
                existing.workspace_id = account.workspace_id
                if existing.category in {"Інше", "Інші покупки", "Закупівлі", "Товари та закупівлі"}:
                    if existing.category != automatic_category:
                        recategorized += 1
                    existing.category = automatic_category
                continue
            raw_amount = int(source["amount"])
            db.add(models.Transaction(
                type="income" if raw_amount > 0 else "expense",
                amount=Decimal(abs(raw_amount)) / 100,
                category="Продажі" if raw_amount > 0 and account.scope == "business" else "Надходження на картку" if raw_amount > 0 else automatic_category,
                description=description,
                date=datetime.fromtimestamp(int(source.get("time") or now.timestamp())).date(),
                external_id=external_id,
                bank_account_id=account.id,
                workspace_id=account.workspace_id,
                currency_code=account.currency_code,
                mcc=mcc,
                scope=account.scope,
            ))
            imported += 1
        account.last_sync = now
        db.commit()
        return {"imported": imported, "recategorized": recategorized, "account": bank_account_payload(account)}
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Не вдалося синхронізувати картку: {error}") from error


@app.patch("/api/banks/accounts/{account_id}/scope")
def set_bank_account_scope(account_id: int, data: schemas.BankAccountScopeRequest, db: Session = Depends(get_db)):
    account = get_or_404(db, models.BankAccount, account_id, "Картку")
    old_scope = account.scope
    account.scope = data.scope
    account.workspace_id = resolve_workspace(db, data.scope).id
    db.query(models.Transaction).filter(
        models.Transaction.bank_account_id == account.id,
        models.Transaction.scope == old_scope,
    ).update({models.Transaction.scope: data.scope, models.Transaction.workspace_id: account.workspace_id}, synchronize_session=False)
    for transaction in db.query(models.Transaction).filter(models.Transaction.bank_account_id == account.id, models.Transaction.type == "expense").all():
        transaction.category = bank_service.business_category_for_mcc(transaction.mcc, transaction.description) if data.scope == "business" else bank_service.category_for_mcc(transaction.mcc, transaction.description)
    db.commit()
    db.refresh(account)
    return bank_account_payload(account)


@app.patch("/api/banks/accounts/{account_id}/workspace")
def set_bank_account_workspace(account_id: int, data: schemas.BankAccountWorkspaceRequest, db: Session = Depends(get_db)):
    account = get_or_404(db, models.BankAccount, account_id, "Картку")
    workspace = db.get(models.FinanceWorkspace, data.workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Фінансовий профіль не знайдено")
    account.scope = workspace.scope
    account.workspace_id = workspace.id
    transactions = db.query(models.Transaction).filter(models.Transaction.bank_account_id == account.id).all()
    for transaction in transactions:
        transaction.scope = workspace.scope
        transaction.workspace_id = workspace.id
        if transaction.type == "expense":
            transaction.category = bank_service.business_category_for_mcc(transaction.mcc, transaction.description) if workspace.scope == "business" else bank_service.category_for_mcc(transaction.mcc, transaction.description)
    db.commit()
    db.refresh(account)
    return bank_account_payload(account)


@app.delete("/api/banks/monobank", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_monobank(db: Session = Depends(get_db), _vault: bool = Depends(require_bank_vault)):
    connection = db.query(models.BankConnection).filter(models.BankConnection.provider == "monobank").first()
    if not connection:
        return
    accounts = db.query(models.BankAccount).filter(models.BankAccount.connection_id == connection.id).all()
    account_ids = [item.id for item in accounts]
    if account_ids:
        db.query(models.Transaction).filter(models.Transaction.bank_account_id.in_(account_ids)).update(
            {models.Transaction.bank_account_id: None}, synchronize_session=False
        )
        db.query(models.BankAccount).filter(models.BankAccount.id.in_(account_ids)).delete(synchronize_session=False)
    db.delete(connection)
    db.commit()


@app.delete("/api/banks/privat-business", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_privat_business(db: Session = Depends(get_db), _vault: bool = Depends(require_bank_vault)):
    connection = db.query(models.BankConnection).filter(models.BankConnection.provider == "privat_business").first()
    if not connection:
        return
    accounts = db.query(models.BankAccount).filter(models.BankAccount.connection_id == connection.id).all()
    account_ids = [item.id for item in accounts]
    if account_ids:
        db.query(models.Transaction).filter(models.Transaction.bank_account_id.in_(account_ids)).update({models.Transaction.bank_account_id: None}, synchronize_session=False)
        db.query(models.BankAccount).filter(models.BankAccount.id.in_(account_ids)).delete(synchronize_session=False)
    db.delete(connection)
    db.commit()


TAX_DEFAULTS = {
    "group1": {"single_tax_rate": Decimal("0"), "single_tax_monthly": Decimal("332.80"), "military_rate": Decimal("0"), "military_monthly": Decimal("864.70"), "esv_monthly": Decimal("1902.34")},
    "group2": {"single_tax_rate": Decimal("0"), "single_tax_monthly": Decimal("1729.40"), "military_rate": Decimal("0"), "military_monthly": Decimal("864.70"), "esv_monthly": Decimal("1902.34")},
    "group3_5": {"single_tax_rate": Decimal("0.05"), "single_tax_monthly": Decimal("0"), "military_rate": Decimal("0.01"), "military_monthly": Decimal("0"), "esv_monthly": Decimal("1902.34")},
    "group3_3_vat": {"single_tax_rate": Decimal("0.03"), "single_tax_monthly": Decimal("0"), "military_rate": Decimal("0.01"), "military_monthly": Decimal("0"), "esv_monthly": Decimal("1902.34")},
}


def tax_profile_payload(profile: models.TaxProfile):
    return {
        "system": profile.system,
        "single_tax_rate": float(profile.single_tax_rate),
        "single_tax_monthly": float(profile.single_tax_monthly),
        "military_rate": float(profile.military_rate),
        "military_monthly": float(profile.military_monthly),
        "esv_monthly": float(profile.esv_monthly),
    }


def get_tax_profile(db: Session):
    profile = db.query(models.TaxProfile).filter(models.TaxProfile.scope == "business").first()
    if not profile:
        profile = models.TaxProfile(scope="business", system="group3_5", **TAX_DEFAULTS["group3_5"])
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@app.get("/api/tax/profile")
def read_tax_profile(db: Session = Depends(get_db)):
    return tax_profile_payload(get_tax_profile(db))


@app.put("/api/tax/profile")
def save_tax_profile(data: schemas.TaxProfileRequest, db: Session = Depends(get_db)):
    profile = get_tax_profile(db)
    values = TAX_DEFAULTS.get(data.system, data.model_dump(exclude={"system"}))
    profile.system = data.system
    for field in ("single_tax_rate", "single_tax_monthly", "military_rate", "military_monthly", "esv_monthly"):
        setattr(profile, field, values[field])
    db.commit()
    db.refresh(profile)
    return tax_profile_payload(profile)


@app.get("/api/tax/summary")
def tax_summary(year: int = date.today().year, quarter: int = (date.today().month - 1) // 3 + 1, db: Session = Depends(get_db)):
    if year < 2000 or year > 2100 or quarter not in {1, 2, 3, 4}:
        raise HTTPException(status_code=400, detail="Невірний рік або квартал")
    profile = get_tax_profile(db)
    start_month = (quarter - 1) * 3 + 1
    start = date(year, start_month, 1)
    end = date(year + (1 if quarter == 4 else 0), 1 if quarter == 4 else start_month + 3, 1)
    rows = db.query(models.Transaction).filter(
        models.Transaction.scope == "business",
        models.Transaction.type == "income",
        models.Transaction.date >= start,
        models.Transaction.date < end,
    ).all()
    income = sum((row.amount for row in rows), Decimal("0"))
    single = income * profile.single_tax_rate + profile.single_tax_monthly * 3
    military = income * profile.military_rate + profile.military_monthly * 3
    esv = profile.esv_monthly * 3
    total = single + military + esv
    return {
        "year": year, "quarter": quarter, "income": float(income),
        "single_tax": float(single.quantize(Decimal("0.01"))),
        "military_tax": float(military.quantize(Decimal("0.01"))),
        "esv": float(esv.quantize(Decimal("0.01"))),
        "total": float(total.quantize(Decimal("0.01"))),
        "transaction_count": len(rows), "profile": tax_profile_payload(profile),
        "notice": "Орієнтовний розрахунок. Перед сплатою перевір суми в Електронному кабінеті платника.",
    }


def crypto_payload(connection: models.CryptoConnection, db: Session):
    assets = db.query(models.CryptoAsset).filter(models.CryptoAsset.connection_id == connection.id).order_by(models.CryptoAsset.value_usdt.desc()).all()
    return {
        "connected": True, "provider": connection.provider, "display_name": connection.display_name,
        "last_sync": connection.last_sync.isoformat() if connection.last_sync else None,
        "total_usdt": float(sum((item.value_usdt for item in assets), Decimal("0"))),
        "assets": [{"symbol": item.symbol, "free": float(item.free), "locked": float(item.locked), "price_usdt": float(item.price_usdt), "value_usdt": float(item.value_usdt)} for item in assets],
    }


def sync_crypto_connection(connection: models.CryptoConnection, db: Session):
    api_key = bank_service.unprotect_token(connection.encrypted_api_key)
    secret = bank_service.unprotect_token(connection.encrypted_secret)
    balances = crypto_service.balances(api_key, secret)
    received = set()
    for source in balances:
        received.add(source["symbol"])
        asset = db.query(models.CryptoAsset).filter(models.CryptoAsset.connection_id == connection.id, models.CryptoAsset.symbol == source["symbol"]).first()
        if not asset:
            asset = models.CryptoAsset(connection_id=connection.id, symbol=source["symbol"])
            db.add(asset)
        for field in ("free", "locked", "price_usdt", "value_usdt"):
            setattr(asset, field, Decimal(str(source[field])))
    for asset in db.query(models.CryptoAsset).filter(models.CryptoAsset.connection_id == connection.id).all():
        if asset.symbol not in received:
            db.delete(asset)
    connection.last_sync = datetime.now()
    db.commit()
    db.refresh(connection)
    return crypto_payload(connection, db)


@app.get("/api/crypto")
def crypto_status(db: Session = Depends(get_db)):
    connection = db.query(models.CryptoConnection).filter(models.CryptoConnection.provider == "binance").first()
    return crypto_payload(connection, db) if connection else {"connected": False, "assets": [], "total_usdt": 0}


@app.post("/api/crypto/connect")
def connect_crypto(data: schemas.CryptoConnectRequest, db: Session = Depends(get_db)):
    try:
        crypto_service.verify_read_only(data.api_key, data.api_secret)
        connection = db.query(models.CryptoConnection).filter(models.CryptoConnection.provider == data.provider).first()
        if not connection:
            connection = models.CryptoConnection(provider=data.provider, display_name="Binance", encrypted_api_key="", encrypted_secret="")
            db.add(connection)
            db.flush()
        connection.encrypted_api_key = bank_service.protect_token(data.api_key)
        connection.encrypted_secret = bank_service.protect_token(data.api_secret)
        db.commit()
        return sync_crypto_connection(connection, db)
    except Exception as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Не вдалося підключити Binance: {error}") from error


@app.post("/api/crypto/sync")
def sync_crypto(db: Session = Depends(get_db)):
    connection = db.query(models.CryptoConnection).filter(models.CryptoConnection.provider == "binance").first()
    if not connection:
        raise HTTPException(status_code=404, detail="Binance ще не підключено")
    try:
        return sync_crypto_connection(connection, db)
    except Exception as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.delete("/api/crypto", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_crypto(db: Session = Depends(get_db)):
    connection = db.query(models.CryptoConnection).filter(models.CryptoConnection.provider == "binance").first()
    if connection:
        db.query(models.CryptoAsset).filter(models.CryptoAsset.connection_id == connection.id).delete(synchronize_session=False)
        db.delete(connection)
        db.commit()


@app.post("/api/receipts/read")
def read_receipt(data: schemas.ReceiptOcrRequest):
    global ocr_engine
    try:
        from rapidocr_onnxruntime import RapidOCR
        header, encoded = data.image_data.split(",", 1)
        if not header.startswith("data:image/"):
            raise ValueError("unsupported image")
        image_bytes = base64.b64decode(encoded, validate=True)
        if len(image_bytes) > 2 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Фото чека має бути до 2 МБ")
        if ocr_engine is None:
            ocr_engine = RapidOCR()
        result, _ = ocr_engine(image_bytes)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=400, detail="Не вдалося прочитати фото чека") from error

    lines = [str(item[1]) for item in (result or []) if len(item) >= 2]
    candidates = []
    amount_pattern = re.compile(r"(?<!\d)(\d{1,7}(?:[\s.,]\d{2})?)(?!\d)")
    for index, line in enumerate(lines):
        normalized = line.replace(" ", "")
        keyword_bonus = 3 if re.search(r"total|sum|amount|всього|сума|разом|оплат", line, re.I) else 0
        for match in amount_pattern.finditer(normalized):
            raw = match.group(1).replace(" ", "").replace(",", ".")
            try:
                value = float(raw)
            except ValueError:
                continue
            if 0 < value < 10_000_000 and not (1900 <= value <= 2100):
                decimal_bonus = 1 if re.search(r"[.,]\d{2}$", match.group(1)) else 0
                candidates.append({"value": value, "score": keyword_bonus + decimal_bonus + index / max(len(lines), 1)})
    candidates.sort(key=lambda item: (item["score"], item["value"]), reverse=True)
    amount = candidates[0]["value"] if candidates else None
    return {"amount": amount, "lines": lines[:30]}


PIN_ITERATIONS = 600_000


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, PIN_ITERATIONS)
    return f"pbkdf2_sha256${PIN_ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_pin(pin: str, stored: str) -> tuple[bool, bool]:
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt_text, digest_text = stored.split("$", 3)
            salt = base64.urlsafe_b64decode(salt_text)
            expected = base64.urlsafe_b64decode(digest_text)
            actual = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, int(iterations))
            return hmac.compare_digest(actual, expected), False
        except (ValueError, TypeError):
            return False, False
    legacy = hashlib.sha256(f"pocket-money:{pin}".encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy, stored), True


@app.get("/api/auth/status")
def auth_status(db: Session = Depends(get_db)):
    account = db.query(models.Account).first()
    return {
        "exists": account is not None,
        "authenticated": bool(account and account.is_authenticated),
        "name": account.name if account else None,
    }


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register(data: schemas.AccountCredentials, db: Session = Depends(get_db)):
    if db.query(models.Account).first():
        raise HTTPException(status_code=409, detail="Профіль уже створено")
    account = models.Account(id=1, name=data.name, pin_hash=hash_pin(data.pin), is_authenticated=True)
    db.add(account)
    db.commit()
    return {"name": account.name, "authenticated": True}


@app.post("/api/auth/login")
def login(data: schemas.AccountCredentials, db: Session = Depends(get_db)):
    account = db.query(models.Account).first()
    if not account:
        raise HTTPException(status_code=404, detail="Профілю ще немає. Спочатку зареєструйся")
    now = datetime.now()
    if account.locked_until and account.locked_until.replace(tzinfo=None) > now:
        seconds = int((account.locked_until.replace(tzinfo=None) - now).total_seconds()) + 1
        raise HTTPException(status_code=429, detail=f"Забагато невдалих спроб. Спробуй через {seconds} с")
    pin_valid, legacy_hash = verify_pin(data.pin, account.pin_hash)
    name_valid = hmac.compare_digest(account.name.casefold().encode("utf-8"), data.name.casefold().encode("utf-8"))
    if not name_valid or not pin_valid:
        account.failed_attempts = int(account.failed_attempts or 0) + 1
        if account.failed_attempts >= 5:
            account.locked_until = now + timedelta(minutes=5)
            account.failed_attempts = 0
        db.commit()
        raise HTTPException(status_code=401, detail="Неправильне ім'я або PIN-код")
    if legacy_hash:
        account.pin_hash = hash_pin(data.pin)
    account.failed_attempts = 0
    account.locked_until = None
    account.is_authenticated = True
    db.commit()
    return {"name": account.name, "authenticated": True}


@app.post("/api/auth/logout")
def logout(db: Session = Depends(get_db)):
    account = db.query(models.Account).first()
    if account:
        account.is_authenticated = False
        db.commit()
    return {"authenticated": False}


@app.get("/", include_in_schema=False)
def frontend(request: Request, bootstrap: str | None = None):
    """Віддає головну сторінку застосунку разом з API."""
    current_session = request.cookies.get("pocket_session", "")
    bootstrap_valid = bool(BOOTSTRAP_TOKEN and bootstrap and hmac.compare_digest(bootstrap, BOOTSTRAP_TOKEN))
    session_valid = bool(current_session and hmac.compare_digest(current_session, APP_SESSION_TOKEN))
    if not bootstrap_valid and not session_valid:
        return JSONResponse(status_code=403, content={"detail": "Відкрий Pocket Money через іконку програми"})
    response = FileResponse(FRONTEND_DIR / "index.html")
    if bootstrap_valid:
        response.set_cookie("pocket_session", APP_SESSION_TOKEN, httponly=True, samesite="strict", secure=False, path="/")
    return response


@app.get("/api/transactions", response_model=list[schemas.TransactionOut])
def transactions(
    scope: str = "personal",
    workspace_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
    db: Session = Depends(get_db),
):
    scope = clean_scope(scope)
    return crud.get_transactions(
        db,
        scope,
        validate_workspace_filter(db, scope, workspace_id),
        limit=limit,
        offset=offset,
    )


@app.post("/api/transactions", response_model=schemas.TransactionOut, status_code=status.HTTP_201_CREATED)
def add_transaction(data: schemas.TransactionCreate, db: Session = Depends(get_db)):
    workspace = resolve_workspace(db, data.scope, data.workspace_id)
    data = data.model_copy(update={"workspace_id": workspace.id, "scope": workspace.scope})
    item = crud.create_transaction(db, data)
    item.description = decrypt_field(item.description)
    item.receipt_data = decrypt_field(item.receipt_data)
    return item


@app.put("/api/transactions/{transaction_id}", response_model=schemas.TransactionOut)
def edit_transaction(transaction_id: int, data: schemas.TransactionUpdate, db: Session = Depends(get_db)):
    item = get_or_404(db, models.Transaction, transaction_id, "Операцію")
    workspace = resolve_workspace(db, data.scope, data.workspace_id or item.workspace_id)
    data = data.model_copy(update={"workspace_id": workspace.id, "scope": workspace.scope})
    item = crud.update_transaction(db, item, data)
    item.description = decrypt_field(item.description)
    item.receipt_data = decrypt_field(item.receipt_data)
    return item


@app.delete("/api/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_transaction(transaction_id: int, db: Session = Depends(get_db)):
    crud.delete_item(db, get_or_404(db, models.Transaction, transaction_id, "Операцію"))


@app.get("/api/limits", response_model=list[schemas.BudgetLimitOut])
def limits(scope: str = "personal", db: Session = Depends(get_db)):
    return db.query(models.BudgetLimit).filter(models.BudgetLimit.scope == clean_scope(scope)).order_by(models.BudgetLimit.category).all()


@app.post("/api/limits", response_model=schemas.BudgetLimitOut)
def save_limit(data: schemas.BudgetLimitBase, db: Session = Depends(get_db)):
    item = db.query(models.BudgetLimit).filter(models.BudgetLimit.scope == data.scope, models.BudgetLimit.category == data.category).first()
    if item:
        item.amount = data.amount
    else:
        item = models.BudgetLimit(**data.model_dump())
        db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.delete("/api/limits/{limit_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_limit(limit_id: int, db: Session = Depends(get_db)):
    crud.delete_item(db, get_or_404(db, models.BudgetLimit, limit_id, "Ліміт"))


@app.get("/api/goals", response_model=list[schemas.GoalOut])
def goals(scope: str = "personal", db: Session = Depends(get_db)):
    return crud.get_goals(db, clean_scope(scope))


@app.post("/api/goals", response_model=schemas.GoalOut, status_code=status.HTTP_201_CREATED)
def add_goal(data: schemas.GoalCreate, db: Session = Depends(get_db)):
    return crud.create_goal(db, data)


@app.put("/api/goals/{goal_id}", response_model=schemas.GoalOut)
def edit_goal(goal_id: int, data: schemas.GoalUpdate, db: Session = Depends(get_db)):
    return crud.update_goal(db, get_or_404(db, models.Goal, goal_id, "Ціль"), data)


@app.delete("/api/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_goal(goal_id: int, db: Session = Depends(get_db)):
    crud.delete_item(db, get_or_404(db, models.Goal, goal_id, "Ціль"))


@app.patch("/api/goals/{goal_id}/deposit", response_model=schemas.GoalOut)
def deposit(goal_id: int, data: schemas.GoalDeposit, db: Session = Depends(get_db)):
    goal = get_or_404(db, models.Goal, goal_id, "Ціль")
    if goal.saved_amount + data.amount > goal.target_amount:
        raise HTTPException(status_code=400, detail="Внесок перевищує суму, що залишилася до цілі")
    return crud.deposit_goal(db, goal, data.amount)


@app.get("/api/summary")
def summary(scope: str = "personal", workspace_id: int | None = None, db: Session = Depends(get_db)):
    scope = clean_scope(scope)
    items = crud.get_transactions(db, scope, validate_workspace_filter(db, scope, workspace_id))
    income = sum((x.amount for x in items if x.type == "income"), Decimal("0"))
    expense = sum((x.amount for x in items if x.type == "expense"), Decimal("0"))
    return {"balance": income - expense, "income": income, "expense": expense}


@app.get("/api/statistics")
def statistics(scope: str = "personal", workspace_id: int | None = None, db: Session = Depends(get_db)):
    scope = clean_scope(scope)
    items = crud.get_transactions(db, scope, validate_workspace_filter(db, scope, workspace_id))
    expenses = defaultdict(Decimal)
    months = defaultdict(lambda: {"income": Decimal("0"), "expense": Decimal("0")})
    for item in items:
        if item.type == "expense":
            expenses[item.category] += item.amount
        key = item.date.strftime("%Y-%m")
        months[key][item.type] += item.amount
    month_keys = sorted(months.keys())[-6:]
    top = max(expenses, key=expenses.get) if expenses else None
    return {
        "expenses_by_category": [{"category": k, "amount": v} for k, v in sorted(expenses.items(), key=lambda x: x[1], reverse=True)],
        "monthly": [{"month": key, **months[key]} for key in month_keys],
        "top_expense_category": top,
        "transaction_count": len(items),
    }


def monthly_report_data(year: int, month: int, scope: str, workspace_id: int | None, db: Session):
    if not 2000 <= year <= 2100 or not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail="Неправильний місяць звіту")
    if scope not in {"all", "personal", "business"}:
        raise HTTPException(status_code=400, detail="Неправильний розділ звіту")
    start = date(year, month, 1)
    end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    query = db.query(models.Transaction).filter(models.Transaction.date >= start, models.Transaction.date < end)
    if scope != "all":
        query = query.filter(models.Transaction.scope == scope)
    if workspace_id is not None:
        workspace = db.get(models.FinanceWorkspace, workspace_id)
        if not workspace or (scope != "all" and workspace.scope != scope):
            raise HTTPException(status_code=404, detail="Фінансовий профіль не знайдено")
        query = query.filter(models.Transaction.workspace_id == workspace_id)
    items = query.order_by(models.Transaction.date, models.Transaction.id).all()

    income = sum((item.amount for item in items if item.type == "income"), Decimal("0"))
    expense = sum((item.amount for item in items if item.type == "expense"), Decimal("0"))
    expense_categories = defaultdict(Decimal)
    income_categories = defaultdict(Decimal)
    workspace_totals = defaultdict(lambda: {"income": Decimal("0"), "expense": Decimal("0"), "count": 0, "scope": "personal"})
    scope_totals = defaultdict(lambda: {"income": Decimal("0"), "expense": Decimal("0"), "count": 0})
    card_totals = defaultdict(lambda: {"income": Decimal("0"), "expense": Decimal("0"), "count": 0})
    daily = defaultdict(lambda: {"income": Decimal("0"), "expense": Decimal("0")})
    for item in items:
        categories = income_categories if item.type == "income" else expense_categories
        categories[item.category] += item.amount
        workspace_name = item.workspace_name or ("Основний бізнес" if item.scope == "business" else "Основний побут")
        workspace_key = (item.workspace_id or 0, workspace_name)
        workspace_totals[workspace_key][item.type] += item.amount
        workspace_totals[workspace_key]["count"] += 1
        workspace_totals[workspace_key]["scope"] = item.scope
        scope_totals[item.scope][item.type] += item.amount
        scope_totals[item.scope]["count"] += 1
        if item.bank_account_name:
            card_totals[item.bank_account_name][item.type] += item.amount
            card_totals[item.bank_account_name]["count"] += 1
        daily[item.date.isoformat()][item.type] += item.amount

    cards_query = db.query(models.BankAccount)
    if scope != "all":
        cards_query = cards_query.filter(models.BankAccount.scope == scope)
    if workspace_id is not None:
        cards_query = cards_query.filter(models.BankAccount.workspace_id == workspace_id)
    connected_cards = [bank_account_payload(card) for card in cards_query.order_by(models.BankAccount.id).all()]
    transaction_rows = [{
        "id": item.id, "date": item.date.isoformat(), "type": item.type, "amount": float(item.amount),
        "category": item.category, "description": item.description, "scope": item.scope,
        "workspace_id": item.workspace_id, "workspace_name": item.workspace_name,
        "bank_account_name": item.bank_account_name,
    } for item in items]
    return {
        "period": f"{year:04d}-{month:02d}",
        "period_start": start.isoformat(),
        "period_end": (end - timedelta(days=1)).isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "filter": {"scope": scope, "workspace_id": workspace_id},
        "summary": {"income": float(income), "expense": float(expense), "balance": float(income - expense), "transaction_count": len(items)},
        "expense_categories": [{"category": key, "amount": float(value)} for key, value in sorted(expense_categories.items(), key=lambda pair: pair[1], reverse=True)],
        "income_categories": [{"category": key, "amount": float(value)} for key, value in sorted(income_categories.items(), key=lambda pair: pair[1], reverse=True)],
        "scope_totals": [{"scope": key, "income": float(value["income"]), "expense": float(value["expense"]), "balance": float(value["income"] - value["expense"]), "count": value["count"]} for key, value in scope_totals.items()],
        "workspace_totals": [{"workspace_id": key[0] or None, "workspace_name": key[1], "scope": value["scope"], "income": float(value["income"]), "expense": float(value["expense"]), "balance": float(value["income"] - value["expense"]), "count": value["count"]} for key, value in workspace_totals.items()],
        "card_totals": [{"card_name": key, "income": float(value["income"]), "expense": float(value["expense"]), "balance": float(value["income"] - value["expense"]), "count": value["count"]} for key, value in card_totals.items()],
        "daily": [{"date": key, "income": float(value["income"]), "expense": float(value["expense"])} for key, value in sorted(daily.items())],
        "connected_cards": connected_cards,
        "transactions": transaction_rows,
    }


@app.get("/api/reports/monthly")
def monthly_report(year: int, month: int, scope: str = "all", workspace_id: int | None = None, db: Session = Depends(get_db)):
    return monthly_report_data(year, month, scope, workspace_id, db)


@app.get("/api/reports/monthly.csv")
def monthly_report_csv(year: int, month: int, scope: str = "all", workspace_id: int | None = None, db: Session = Depends(get_db)):
    report = monthly_report_data(year, month, scope, workspace_id, db)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Pocket Money", "Місячний звіт", report["period"]])
    writer.writerow(["Доходи", report["summary"]["income"]])
    writer.writerow(["Витрати", report["summary"]["expense"]])
    writer.writerow(["Баланс", report["summary"]["balance"]])
    writer.writerow(["Операцій", report["summary"]["transaction_count"]])
    writer.writerow([])
    writer.writerow(["Дата", "Тип", "Сума", "Категорія", "Опис", "Розділ", "Профіль", "Картка"])
    for item in report["transactions"]:
        writer.writerow([
            item["date"],
            "Дохід" if item["type"] == "income" else "Витрата",
            item["amount"],
            _escape_csv_value(item["category"]),
            _escape_csv_value(item["description"]),
            "Бізнес" if item["scope"] == "business" else "Побут",
            _escape_csv_value(item["workspace_name"] or ""),
            _escape_csv_value(item["bank_account_name"] or ""),
        ])
    content = "\ufeff" + output.getvalue()
    filename = f"Pocket-Money-{report['period']}.csv"
    return Response(content=content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
