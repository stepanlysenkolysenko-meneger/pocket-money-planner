import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


TEST_DATA = tempfile.TemporaryDirectory(prefix="pocket-money-test-")
os.environ["POCKET_MONEY_DATA_DIR"] = TEST_DATA.name
os.environ["POCKET_MONEY_RESOURCE_DIR"] = str(Path(__file__).resolve().parent.parent)

from database import SessionLocal, engine
import main
import models
import schemas


class NewFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.startup()
        cls.db = SessionLocal()

    def setUp(self):
        main.BANK_BALANCE_REFRESHED_AT.clear()
        self.db.query(models.Transaction).delete()
        self.db.query(models.BankAccount).delete()
        self.db.query(models.BankConnection).delete()
        self.db.query(models.Account).delete()
        self.db.query(models.TaxProfile).delete()
        self.db.query(models.CryptoAsset).delete()
        self.db.query(models.CryptoConnection).delete()
        self.db.query(models.FinanceWorkspace).filter(models.FinanceWorkspace.is_default.is_(False)).delete()
        self.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        engine.dispose()
        TEST_DATA.cleanup()

    def test_pwa_assets_are_served(self):
        self.assertTrue((main.FRONTEND_DIR / "manifest.webmanifest").is_file())
        self.assertTrue((main.FRONTEND_DIR / "sw.js").is_file())
        self.assertTrue((Path(os.environ["POCKET_MONEY_RESOURCE_DIR"]) / "assets" / "pocket-money.png").is_file())

    def test_tax_defaults_and_quarter_calculation(self):
        profile = main.read_tax_profile(self.db)
        self.assertEqual(profile["system"], "group3_5")
        summary = main.tax_summary(2026, 1, self.db)
        self.assertEqual(summary["esv"], 5707.02)
        self.assertEqual(summary["total"], 5707.02)

    def test_custom_tax_profile(self):
        data = schemas.TaxProfileRequest(system="custom", single_tax_rate=0.04, single_tax_monthly=0, military_rate=0.01, military_monthly=0, esv_monthly=2000)
        response = main.save_tax_profile(data, self.db)
        self.assertEqual(response["system"], "custom")

    def test_crypto_starts_disconnected(self):
        response = main.crypto_status(self.db)
        self.assertFalse(response["connected"])

    def test_pin_uses_salted_slow_hash(self):
        first = main.hash_pin("1234")
        second = main.hash_pin("1234")
        self.assertTrue(first.startswith("pbkdf2_sha256$600000$"))
        self.assertNotEqual(first, second)
        self.assertEqual(main.verify_pin("1234", first), (True, False))
        self.assertEqual(main.verify_pin("0000", first), (False, False))

    def test_login_locks_after_five_failed_attempts(self):
        account = models.Account(id=1, name="Марко", pin_hash=main.hash_pin("1234"), is_authenticated=False)
        self.db.add(account)
        self.db.commit()
        for _ in range(5):
            with self.assertRaises(Exception):
                main.login(schemas.AccountCredentials(name="Марко", pin="9999"), self.db)
        self.db.refresh(account)
        self.assertIsNotNone(account.locked_until)

    def test_startup_requires_login_again(self):
        account = models.Account(id=1, name="Марко", pin_hash=main.hash_pin("1234"), is_authenticated=True)
        self.db.add(account)
        self.db.commit()

        main.startup()

        self.db.refresh(account)
        self.assertFalse(account.is_authenticated)

    def test_bank_vault_pin_upgrades_legacy_hash(self):
        legacy = __import__("hashlib").sha256(b"pocket-money:1234").hexdigest()
        account = models.Account(id=1, name="Марко", pin_hash=legacy, is_authenticated=True)
        self.db.add(account)
        self.db.commit()
        response = main.unlock_bank_vault(schemas.PinConfirmation(pin="1234"), self.db)
        self.db.refresh(account)
        self.assertTrue(account.pin_hash.startswith("pbkdf2_sha256$600000$"))
        self.assertIn("pocket_bank_vault=", response.headers.get("set-cookie", ""))
        self.assertIn("HttpOnly", response.headers.get("set-cookie", ""))

    def test_bank_payload_only_exposes_last_four_digits(self):
        connection = models.BankConnection(provider="test", display_name="Test Bank", encrypted_token="encrypted")
        self.db.add(connection)
        self.db.flush()
        account = models.BankAccount(
            connection_id=connection.id, external_id="account-1", display_name="Картка",
            masked_pan="444111******4362", account_type="card", currency_code=980,
            balance=0, credit_limit=0,
        )
        self.db.add(account)
        self.db.commit()
        payload = main.bank_account_payload(account)
        self.assertEqual(payload["masked_pan"], "•••• 4362")
        self.assertNotIn("444111", payload["masked_pan"])

    def test_multiple_businesses_have_separate_and_combined_statistics(self):
        first = main.create_workspace(schemas.WorkspaceCreate(name="Магазин", scope="business"), self.db)
        second = main.create_workspace(schemas.WorkspaceCreate(name="Майстерня", scope="business"), self.db)
        main.add_transaction(schemas.TransactionCreate(type="income", amount=1000, category="Продажі", description="Замовлення", date="2026-10-14", scope="business", workspace_id=first["id"]), self.db)
        main.add_transaction(schemas.TransactionCreate(type="income", amount=2500, category="Послуги", description="Проєкт", date="2026-10-14", scope="business", workspace_id=second["id"]), self.db)
        combined = main.summary("business", None, self.db)
        only_first = main.summary("business", first["id"], self.db)
        self.assertEqual(float(combined["income"]), 3500)
        self.assertEqual(float(only_first["income"]), 1000)

    def test_card_move_also_moves_its_transactions(self):
        first = main.create_workspace(schemas.WorkspaceCreate(name="Бізнес A", scope="business"), self.db)
        second = main.create_workspace(schemas.WorkspaceCreate(name="Бізнес B", scope="business"), self.db)
        connection = models.BankConnection(provider="move-test", display_name="Test Bank", encrypted_token="encrypted")
        self.db.add(connection)
        self.db.flush()
        card = models.BankAccount(connection_id=connection.id, workspace_id=first["id"], external_id="move-card", display_name="Картка", account_type="business", currency_code=980, balance=0, credit_limit=0, scope="business")
        self.db.add(card)
        self.db.flush()
        transaction = models.Transaction(type="expense", amount=50, category="Інше", description="Тест", date=__import__("datetime").date(2026, 10, 14), bank_account_id=card.id, workspace_id=first["id"], scope="business")
        self.db.add(transaction)
        self.db.commit()
        main.set_bank_account_workspace(card.id, schemas.BankAccountWorkspaceRequest(workspace_id=second["id"]), self.db)
        self.db.refresh(transaction)
        self.assertEqual(transaction.workspace_id, second["id"])

    def test_monthly_report_combines_scopes_and_downloads_csv(self):
        personal = self.db.query(models.FinanceWorkspace).filter_by(scope="personal", is_default=True).one()
        business = self.db.query(models.FinanceWorkspace).filter_by(scope="business", is_default=True).one()
        main.add_transaction(schemas.TransactionCreate(type="income", amount=700, category="Дохід", description="Побут", date="2026-09-05", scope="personal", workspace_id=personal.id), self.db)
        main.add_transaction(schemas.TransactionCreate(type="expense", amount=200, category="Товари", description="Бізнес", date="2026-09-10", scope="business", workspace_id=business.id), self.db)
        main.add_transaction(schemas.TransactionCreate(type="income", amount=999, category="Інше", description="Інший місяць", date="2026-10-01", scope="personal", workspace_id=personal.id), self.db)
        report = main.monthly_report(2026, 9, "all", None, self.db)
        self.assertEqual(report["summary"]["income"], 700.0)
        self.assertEqual(report["summary"]["expense"], 200.0)
        self.assertEqual(report["summary"]["transaction_count"], 2)
        self.assertEqual(len(report["scope_totals"]), 2)
        csv_response = main.monthly_report_csv(2026, 9, "all", None, self.db)
        self.assertTrue(csv_response.body.decode("utf-8").startswith("\ufeffPocket Money"))
        self.assertIn("Pocket-Money-2026-09.csv", csv_response.headers["content-disposition"])

    @patch("main.privat_service.balances")
    @patch("main.privat_service.verify")
    def test_privat_business_connects_real_accounts(self, verify, balances):
        verify.return_value = {"status": "SUCCESS"}
        balances.return_value = [{"acc": "UA123456789012345678901234567", "currency": "UAH", "balanceOut": "1234.56", "nameACC": "ФОП рахунок"}]
        result = main.connect_privat_business(schemas.PrivatBusinessTokenRequest(token="x" * 32), self.db)
        self.assertTrue(result["connected"])
        self.assertEqual(result["accounts"][0]["balance"], 1234.56)
        self.assertEqual(result["accounts"][0]["scope"], "business")

    @patch("main.privat_service.transactions")
    @patch("main.privat_service.balances")
    @patch("main.privat_service.verify")
    def test_privat_business_syncs_transactions(self, verify, balances, transactions):
        verify.return_value = {"status": "SUCCESS"}
        balances.return_value = [{"acc": "UA123456789012345678901234567", "currency": "UAH", "balanceOut": "900.00", "nameACC": "ФОП рахунок"}]
        connected = main.connect_privat_business(schemas.PrivatBusinessTokenRequest(token="x" * 32), self.db)
        transactions.return_value = [{"TECHNICAL_TRANSACTION_ID": "tx-1", "TRANTYPE": "D", "SUM": "100.00", "CCY": "UAH", "DAT_OD": "07.10.2026", "OSND": "Google Ads реклама"}]
        result = main.sync_bank_account(connected["accounts"][0]["id"], self.db)
        self.assertEqual(result["imported"], 1)
        saved = self.db.query(models.Transaction).one()
        self.assertEqual(saved.type, "expense")
        self.assertEqual(saved.scope, "business")
        self.assertEqual(balances.call_count, 1)

    @patch("main.bank_service.unprotect_token", return_value="token")
    @patch("main.bank_service.client_info")
    def test_balance_refresh_updates_live_accounts_and_deactivates_missing_cards(self, client_info, _unprotect):
        workspace = self.db.query(models.FinanceWorkspace).filter_by(scope="personal", is_default=True).one()
        connection = models.BankConnection(provider="monobank", display_name="Monobank", encrypted_token="encrypted")
        self.db.add(connection)
        self.db.flush()
        active = models.BankAccount(connection_id=connection.id, workspace_id=workspace.id, external_id="active-card", display_name="Old", account_type="white", currency_code=980, balance=100, credit_limit=0, scope="personal")
        missing = models.BankAccount(connection_id=connection.id, workspace_id=workspace.id, external_id="missing-card", display_name="Missing", account_type="black", currency_code=980, balance=999, credit_limit=0, scope="personal")
        self.db.add_all([active, missing])
        self.db.commit()
        client_info.return_value = {"accounts": [{"id": "active-card", "type": "white", "maskedPan": ["444111******6103"], "currencyCode": 980, "balance": 1175950, "creditLimit": 0}]}
        result = main.refresh_bank_balances(self.db)
        self.db.refresh(active)
        self.db.refresh(missing)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(float(active.balance), 11759.50)
        self.assertTrue(active.is_active)
        self.assertFalse(missing.is_active)
        self.assertIsNotNone(active.balance_updated_at)

    @patch("main.bank_service.statement")
    @patch("main.bank_service.client_info")
    @patch("main.bank_service.unprotect_token", return_value="token")
    def test_monobank_sync_uses_account_currency_and_live_balance(self, _unprotect, client_info, statement):
        workspace = self.db.query(models.FinanceWorkspace).filter_by(scope="personal", is_default=True).one()
        connection = models.BankConnection(provider="monobank", display_name="Monobank", encrypted_token="encrypted")
        self.db.add(connection)
        self.db.flush()
        account = models.BankAccount(connection_id=connection.id, workspace_id=workspace.id, external_id="card-1", display_name="Mono", account_type="white", currency_code=980, balance=100, credit_limit=0, scope="personal")
        self.db.add(account)
        self.db.flush()
        existing = models.Transaction(type="expense", amount=10, category="Інше", description="Стара", date=__import__("datetime").date(2026, 10, 1), external_id="monobank:old", bank_account_id=account.id, workspace_id=workspace.id, currency_code=840, scope="personal")
        self.db.add(existing)
        self.db.commit()
        client_info.return_value = {"accounts": [{"id": "card-1", "type": "white", "maskedPan": ["444111******6103"], "currencyCode": 980, "balance": 1175950, "creditLimit": 0}]}
        statement.return_value = [
            {"id": "old", "time": 1790812800, "amount": -5000, "operationAmount": -120, "currencyCode": 840, "mcc": 5411, "description": "Магазин", "hold": False},
            {"id": "new", "time": 1790812800, "amount": -175146, "operationAmount": -4200, "currencyCode": 840, "mcc": 5411, "description": "Foreign shop", "hold": False},
        ]
        result = main.sync_bank_account(account.id, self.db)
        self.db.refresh(account)
        self.db.refresh(existing)
        created = self.db.query(models.Transaction).filter_by(external_id="monobank:new").one()
        self.assertEqual(result["imported"], 1)
        self.assertEqual(float(account.balance), 11759.50)
        self.assertEqual(existing.currency_code, 980)
        self.assertEqual(created.currency_code, 980)
        self.assertEqual(float(created.amount), 1751.46)


    def test_migration_version_tracking(self):
        """Версійовані міграції відслідковуються у schema_migrations."""
        from database import SessionLocal as SL
        with SL() as sec:
            v1 = sec.query(models.SchemaMigration).filter_by(version="001").first()
            self.assertIsNotNone(v1, "Міграція 001 має бути застосована при startup")
            v2 = sec.query(models.SchemaMigration).filter_by(version="002").first()
            self.assertIsNotNone(v2, "Міграція 002 має бути застосована при startup")

    def test_pin_must_be_6_to_8_digits(self):
        """PIN-код тепер має містити 6–8 цифр, а не рівно 4."""
        import schemas
        # 4 цифри — заборонено
        with self.assertRaises(Exception):
            schemas.AccountCredentials(name="Тест", pin="1234")
        # 6 цифр — дозволено
        creds = schemas.AccountCredentials(name="Тест", pin="123456")
        self.assertEqual(creds.pin, "123456")
        # 8 цифр — дозволено
        creds = schemas.AccountCredentials(name="Тест", pin="12345678")
        self.assertEqual(creds.pin, "12345678")
        # 9 цифр — заборонено
        with self.assertRaises(Exception):
            schemas.AccountCredentials(name="Тест", pin="123456789")

    def test_csv_escape_formula_values(self):
        """Значення, що починаються з =, +, -, @, екрануються апострфом у CSV."""
        self.assertEqual(main._escape_csv_value("=SUM(A1:A10)"), "'=SUM(A1:A10)")
        self.assertEqual(main._escape_csv_value("+100000"), "'+100000")
        self.assertEqual(main._escape_csv_value("-500"), "'-500")
        self.assertEqual(main._escape_csv_value("@bad"), "'@bad")
        self.assertEqual(main._escape_csv_value("Нормальний опис"), "Нормальний опис")
        self.assertEqual(main._escape_csv_value(None), "")
        self.assertEqual(main._escape_csv_value(""), "")

    def test_transactions_pagination(self):
        """get_transactions підтримує limit/offset."""
        for i in range(15):
            crud.create_transaction(self.db, schemas.TransactionCreate(
                type="expense", amount=10.00 + i, category="Тест",
                description=f"Транзакція {i}", date=__import__("datetime").date.today(),
                scope="personal",
            ))
        all_tx = crud.get_transactions(self.db, "personal")
        self.assertEqual(len(all_tx), 15)

        first_page = crud.get_transactions(self.db, "personal", limit=5, offset=0)
        self.assertEqual(len(first_page), 5)

        second_page = crud.get_transactions(self.db, "personal", limit=5, offset=5)
        self.assertEqual(len(second_page), 5)
        self.assertNotEqual(first_page[0].id, second_page[0].id)

    def test_field_encryption_roundtrip(self):
        """Чутливі поля шифруються при записі і розшифровуються при читанні."""
        created = crud.create_transaction(self.db, schemas.TransactionCreate(
            type="expense", amount=42.00, category="Секрет",
            description="Таємний опис", date=__import__("datetime").date.today(),
            scope="personal",
        ))
        # У БД значення зашифроване
        raw = self.db.query(models.Transaction).filter_by(id=created.id).first()
        self.assertNotEqual(raw.description, "Таємний опис")
        self.assertIsNotNone(raw.description)
        # Після читання через crud — розшифроване
        read_back = crud.get_transactions(self.db, "personal", limit=1)
        self.assertEqual(read_back[0].description, "Таємний опис")

    def test_ai_requires_consent(self):
        """AI-чати вимагають явної згоди користувача (ai_consent=True)."""
        account = self.db.query(models.Account).first()
        account.ai_consent = False
        self.db.commit()

        import schemas as s
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            main.ai_chat(s.AiChatRequest(message="Привіт", scope="personal"), self.db)
        self.assertEqual(ctx.exception.status_code, 403)

        # Після згоди — доступ дозволений (ми не викликаємо реальний OpenRouter,
        # але перевіряємо що 403 більше не виникає на етапі перевірки згоди)
        account.ai_consent = True
        self.db.commit()
        try:
            main.ai_chat(s.AiChatRequest(message="Привіт", scope="personal"), self.db)
        except HTTPException as e:
            self.assertNotEqual(e.status_code, 403, "Згода має прибрати блокування 403")
        except Exception:
            # Інша помилка (наприклад, немає OpenRouter ключа) — нормально, важливо що не 403
            pass

    def test_startup_resets_authentication(self):
        """Повторний запуск додатка скидає is_authenticated — вимагається PIN."""
        account = self.db.query(models.Account).first()
        account.is_authenticated = True
        self.db.commit()

        main.startup()
        self.db.refresh(account)
        self.assertFalse(account.is_authenticated,
                         "Після старту додатка користувач має бути неавторизованим")


if __name__ == "__main__":
    unittest.main()
