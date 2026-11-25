# Pocket Money — планувальник кишенькових грошей

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)](https://sqlite.org)
[![Chart.js](https://img.shields.io/badge/Chart.js-4-FF6384?logo=chart.js&logoColor=white)](https://chartjs.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?logo=windows&logoColor=white)](https://microsoft.com/windows)

> Навчальний локальний **full-stack** застосунок українською мовою для обліку доходів і витрат, накопичення на фінансові цілі та перегляду статистики. Дані зберігаються в SQLite, суми — у точному десятковому форматі.

---

## 🖥️ Демонстрація

| Головний екран | Статистика | Фінансові цілі |
|:---:|:---:|:---:|
| ![Головний](frontend/assets/images/pig-walk.png) | ![Статистика](frontend/assets/images/pig-deposit.png) | ![Цілі](frontend/assets/images/pig-expense.png) |

> *Додайте власні скріншоти програми у `frontend/assets/images/` для кращого вигляду.*

---

## ✨ Можливості

- ➕ **Операції** — додавання, редагування, видалення, фільтрація за категоріями/датами
- 💰 **Баланс** — автоматичний розрахунок доходів, витрат та поточного балансу
- 🎯 **Фінансові цілі** — створення цілей, відстеження прогресу, поповнення
- 📊 **Статистика** — інтерактивні кругові та стовпчикові діаграми (Chart.js)
- 🌓 **Теми** — світла та темна тема з автоматичним запам'ятовуванням
- 📱 **Адаптивність** — працює на екранах від 320px (мобільні/планшети/десктоп)
- 🔒 **Локальність** — всі дані лише на вашому комп'ютері, жодного інтернету
- 🔐 **PIN-авторизація** — 4-значний PIN для захисту профілю

---

## 🚀 Як запустити (для тебе і друзів)

Це **локальний десктопний додаток** — дані зберігаються на твоєму комп'ютері, не в хмарі.

### Найпростіше (Windows):
1. **Скачай** → Code → **Download ZIP** → розпакуй
2. **Запусти** → подвійний клік на `START_POCKET_MONEY.cmd`
3. **Готово** — на робочому столі з'явиться ярлик **Pocket Money** з власною іконкою

### Або через термінал:
```powershell
git clone https://github.com/stepanlysenkolysenko-meneger/pocket-money-planner.git
cd pocket-money-planner
START_POCKET_MONEY.cmd
```

> **Що потрібно:** Python 3.10+ (під час інсталяції постави галочку "Add Python to PATH")

---

## 🌐 Чому немає "посилання на сайт"?

Це **не веб-сайт**, а локальна програма:
- ✅ Дані твої — лише на твоєму ПК (SQLite файл)
- ✅ Не потребує інтернету після першого запуску
- ✅ Жодної реєстрації, жодного сервера
- ✅ PIN-код знаєш лише ти

**Хочеш поділитися з другом?** Надішли йому це посилання на GitHub — він скачає і запустить у себе так само.

---

## 🛠️ Технології

| Стек | Використання |
|------|-------------|
| **Python 3.10+** | Основна мова |
| **FastAPI** | Backend API, автоматична документація (Swagger) |
| **SQLAlchemy** | ORM для роботи з БД |
| **SQLite** | Локальна база даних (файл `pocket_money.db`) |
| **Pydantic** | Валідація даних та серіалізація |
| **Vanilla JS (ES6+)** | Frontend без фреймворків |
| **Chart.js** | Графіки та діаграми |
| **CSS Variables** | Теми, адаптивність, анімації |

---

## 📁 Структура проєкту

```text
pocket-money-planner/
├── frontend/                 # Клієнтська частина
│   ├── index.html            # Головна сторінка (SPA)
│   ├── css/                  # Стилі (теми, адаптивність, анімації)
│   ├── js/                   # Модульна JS архітектура
│   │   ├── app.js            # Головний контролер
│   │   ├── api.js            # Робота з API
│   │   ├── transactions.js   # Операції
│   │   ├── goals.js          # Цілі
│   │   ├── statistics.js     # Графіки
│   │   └── ...
│   └── assets/               # Іконки, зображення, шрифти
├── backend/                  # Серверна частина
│   ├── main.py               # Точка входу FastAPI
│   ├── database.py           # Налаштування БД
│   ├── models.py             # SQLAlchemy моделі
│   ├── schemas.py            # Pydantic схеми
│   ├── crud.py               # CRUD операції
│   ├── ai_service.py         # (опційно) AI функції
│   └── requirements.txt      # Залежності Python
├── .gitignore
├── LICENSE
├── README.md
├── INSTALL_POCKET_MONEY.cmd  # Windows інсталятор
├── install_shortcut.ps1      # Створення ярлика
├── start_app.py              # Запуск з системного трею
└── PocketMoney.spec          # PyInstaller конфіг
```

---

## ⚙️ Конфігурація

### Змінні середовища (`.env`)
```env
# Опціонально — для продакшену
SECRET_KEY=your-secret-key-here
DATABASE_URL=sqlite:///./pocket_money.db
CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
```

### Порт
За замовчуванням: **8000**. Змінити у `backend/main.py`:
```python
import os
port = int(os.environ.get("PORT", 8000))
uvicorn.run(app, host="0.0.0.0", port=port)
```

---

## 📝 Ліцензія

MIT License — вільне використання, модифікація, розповсюдження.

---

## 👤 Автор

**stepanlysenkolysenko-meneger** — [GitHub](https://github.com/stepanlysenkolysenko-meneger)

---

⭐ **Якщо проєкт корисний — поставіть зірочку на GitHub!**