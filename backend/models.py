from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class FinanceWorkspace(Base):
    __tablename__ = "finance_workspaces"
    __table_args__ = (UniqueConstraint("scope", "name", name="uq_workspace_scope_name"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(60), nullable=False)
    scope = Column(String(12), nullable=False, index=True)
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(10), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    category = Column(String(50), nullable=False, index=True)
    description = Column(String(160), nullable=False)
    date = Column(Date, nullable=False, index=True)
    receipt_data = Column(Text, nullable=True)
    external_id = Column(String(160), nullable=True, unique=True, index=True)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True, index=True)
    workspace_id = Column(Integer, ForeignKey("finance_workspaces.id"), nullable=True, index=True)
    currency_code = Column(Integer, nullable=True)
    mcc = Column(Integer, nullable=True, index=True)
    scope = Column(String(12), nullable=False, default="personal", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    bank_account = relationship("BankAccount")
    workspace = relationship("FinanceWorkspace")

    @property
    def bank_account_name(self):
        return self.bank_account.display_name if self.bank_account else None

    @property
    def workspace_name(self):
        return self.workspace.name if self.workspace else None


class Goal(Base):
    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=False)
    target_amount = Column(Numeric(12, 2), nullable=False)
    saved_amount = Column(Numeric(12, 2), nullable=False, default=0)
    deadline = Column(Date, nullable=False)
    scope = Column(String(12), nullable=False, default="personal", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, default=1)
    name = Column(String(40), nullable=False, unique=True)
    pin_hash = Column(String(200), nullable=False)
    is_authenticated = Column(Boolean, nullable=False, default=True)
    failed_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    ai_consent = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(String(20), nullable=False, unique=True, index=True)
    applied_at = Column(DateTime(timezone=True), server_default=func.now())


class BudgetLimit(Base):
    __tablename__ = "budget_limits_v2"
    __table_args__ = (UniqueConstraint("scope", "category", name="uq_budget_limit_scope_category"),)

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(50), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    scope = Column(String(12), nullable=False, default="personal", index=True)


class BankConnection(Base):
    __tablename__ = "bank_connections"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(30), nullable=False, unique=True)
    display_name = Column(String(100), nullable=False)
    encrypted_token = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id = Column(Integer, primary_key=True, index=True)
    connection_id = Column(Integer, ForeignKey("bank_connections.id"), nullable=False, index=True)
    workspace_id = Column(Integer, ForeignKey("finance_workspaces.id"), nullable=True, index=True)
    external_id = Column(String(100), nullable=False, unique=True, index=True)
    display_name = Column(String(100), nullable=False)
    masked_pan = Column(String(30), nullable=True)
    account_type = Column(String(30), nullable=False)
    currency_code = Column(Integer, nullable=False, default=980)
    balance = Column(Numeric(14, 2), nullable=False, default=0)
    credit_limit = Column(Numeric(14, 2), nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    balance_updated_at = Column(DateTime(timezone=True), nullable=True)
    last_sync = Column(DateTime(timezone=True), nullable=True)
    scope = Column(String(12), nullable=False, default="personal", index=True)
    connection = relationship("BankConnection")
    workspace = relationship("FinanceWorkspace")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(12), nullable=False)
    content = Column(Text, nullable=False)
    scope = Column(String(12), nullable=False, default="personal", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TaxProfile(Base):
    __tablename__ = "tax_profiles"

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String(12), nullable=False, default="business", unique=True)
    system = Column(String(24), nullable=False, default="group3_5")
    single_tax_rate = Column(Numeric(7, 5), nullable=False, default=0.05)
    single_tax_monthly = Column(Numeric(12, 2), nullable=False, default=0)
    military_rate = Column(Numeric(7, 5), nullable=False, default=0.01)
    military_monthly = Column(Numeric(12, 2), nullable=False, default=0)
    esv_monthly = Column(Numeric(12, 2), nullable=False, default=1902.34)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CryptoConnection(Base):
    __tablename__ = "crypto_connections"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(30), nullable=False, unique=True)
    display_name = Column(String(100), nullable=False)
    encrypted_api_key = Column(Text, nullable=False)
    encrypted_secret = Column(Text, nullable=False)
    last_sync = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CryptoAsset(Base):
    __tablename__ = "crypto_assets"
    __table_args__ = (UniqueConstraint("connection_id", "symbol", name="uq_crypto_connection_symbol"),)

    id = Column(Integer, primary_key=True, index=True)
    connection_id = Column(Integer, ForeignKey("crypto_connections.id"), nullable=False, index=True)
    symbol = Column(String(20), nullable=False)
    free = Column(Numeric(24, 10), nullable=False, default=0)
    locked = Column(Numeric(24, 10), nullable=False, default=0)
    price_usdt = Column(Numeric(24, 10), nullable=False, default=0)
    value_usdt = Column(Numeric(24, 2), nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    connection = relationship("CryptoConnection")
