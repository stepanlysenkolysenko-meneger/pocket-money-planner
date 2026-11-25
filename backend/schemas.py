from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TransactionBase(BaseModel):
    type: Literal["income", "expense"]
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    category: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=160)
    date: date
    receipt_data: str | None = Field(default=None, max_length=3_000_000)
    scope: Literal["personal", "business"] = "personal"
    workspace_id: int | None = Field(default=None, ge=1)

    @field_validator("category", "description")
    @classmethod
    def no_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Поле не може бути порожнім")
        return value


class TransactionCreate(TransactionBase):
    pass


class TransactionUpdate(TransactionBase):
    pass


class TransactionOut(TransactionBase):
    id: int
    created_at: datetime
    external_id: str | None = None
    bank_account_id: int | None = None
    bank_account_name: str | None = None
    workspace_name: str | None = None
    currency_code: int | None = None
    mcc: int | None = None
    model_config = ConfigDict(from_attributes=True)


class GoalBase(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    target_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    saved_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    deadline: date
    scope: Literal["personal", "business"] = "personal"

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Назва не може бути порожньою")
        return value

    @model_validator(mode="after")
    def saved_not_over_target(self):
        if self.saved_amount > self.target_amount:
            raise ValueError("Накопичена сума не може перевищувати суму цілі")
        return self


class GoalCreate(GoalBase):
    pass


class GoalUpdate(GoalBase):
    pass


class GoalOut(GoalBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class GoalDeposit(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class AccountCredentials(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    pin: str = Field(pattern=r"^\d{6,8}$")

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Введи ім'я")
        return value


class PinConfirmation(BaseModel):
    pin: str = Field(pattern=r"^\d{6,8}$")


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    scope: Literal["personal", "business"]

    @field_validator("name")
    @classmethod
    def clean_workspace_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Введи назву")
        return value


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def clean_workspace_name(cls, value: str) -> str:
        return value.strip()


class BudgetLimitBase(BaseModel):
    category: str = Field(min_length=1, max_length=50)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    scope: Literal["personal", "business"] = "personal"


class BudgetLimitOut(BudgetLimitBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class ReceiptOcrRequest(BaseModel):
    image_data: str = Field(min_length=20, max_length=3_000_000)


class AiChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    scope: Literal["personal", "business"] = "personal"


class TranslateRequest(BaseModel):
    language: str = Field(min_length=2, max_length=60)
    texts: list[str] = Field(min_length=1, max_length=250)


class BankTokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=300)
    scope: Literal["personal", "business"] = "personal"
    workspace_id: int | None = Field(default=None, ge=1)

    @field_validator("token")
    @classmethod
    def clean_token(cls, value: str) -> str:
        return value.strip()


class PrivatBusinessTokenRequest(BankTokenRequest):
    scope: Literal["personal", "business"] = "business"


class BankAccountScopeRequest(BaseModel):
    scope: Literal["personal", "business"]


class BankAccountWorkspaceRequest(BaseModel):
    workspace_id: int = Field(ge=1)


class BankStatementImportRequest(BaseModel):
    bank: str = Field(min_length=2, max_length=60)
    account_name: str = Field(min_length=1, max_length=100)
    scope: Literal["personal", "business"] = "personal"
    workspace_id: int | None = Field(default=None, ge=1)
    file_data: str = Field(min_length=20, max_length=8_000_000)

    @field_validator("bank", "account_name")
    @classmethod
    def clean_bank_text(cls, value: str) -> str:
        return value.strip()


class TaxProfileRequest(BaseModel):
    system: Literal["group1", "group2", "group3_5", "group3_3_vat", "custom"] = "group3_5"
    single_tax_rate: Decimal = Field(default=Decimal("0.05"), ge=0, le=1)
    single_tax_monthly: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    military_rate: Decimal = Field(default=Decimal("0.01"), ge=0, le=1)
    military_monthly: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    esv_monthly: Decimal = Field(default=Decimal("1902.34"), ge=0, max_digits=12, decimal_places=2)


class CryptoConnectRequest(BaseModel):
    provider: Literal["binance"] = "binance"
    api_key: str = Field(min_length=20, max_length=300)
    api_secret: str = Field(min_length=20, max_length=300)

    @field_validator("api_key", "api_secret")
    @classmethod
    def clean_crypto_secret(cls, value: str) -> str:
        return value.strip()
