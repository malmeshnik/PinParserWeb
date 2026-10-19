# Документація API PinParser

Цей документ містить короткий опис API сервісу PinParser.

> 📘 Повний довідник з усіма полями, статусами, помилками і сценаріями (зокрема для AI-агентів): [API_REFERENCE.md](API_REFERENCE.md).

## 1. Авторизація

API підтримує два методи авторизації: **Token Authentication** (рекомендовано для скриптів) та **Basic Authentication**.

### Token Authentication

Щоб використовувати Token Authentication, вам потрібно спочатку отримати токен для вашого користувача.

#### Отримання токена
**Endpoint:** `POST /api/auth/token/`

**Запит (curl):**
```bash
curl -X POST http://your-domain.com/api/auth/token/ \
     -d "username=your_username" \
     -d "password=your_password"
```

**Відповідь:**
```json
{
    "token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b"
}
```

#### Використання токена
У всіх наступних запитах додавайте заголовок `Authorization: Token <ваш_токен>`.

**Приклад (curl):**
```bash
curl -H "Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b" http://your-domain.com/api/tasks/
```

### Basic Authentication
Ви можете використовувати стандартну HTTP Basic Auth, передаючи логін та пароль у кожному запиті.

**Приклад (curl):**
```bash
curl -u username:password http://your-domain.com/api/tasks/
```

---

## 2. Ендпоінти API

Базовий URL для всіх запитів: `http://your-domain.com/api/`

### Завдання (Tasks)

Використовуються для створення та керування процесом парсингу.

*   **GET `/tasks/`** — Отримати список ваших завдань.
*   **POST `/tasks/`** — Створити нове завдання та автоматично запустити його.
    *   **Тіло запиту:**
        ```json
        {
            "name": "Назва завдання",
            "keywords": ["keyword1", "keyword2"],
            "threads": 3,
            "use_uniqueness": true,
            "auto_sheet_name": "Назва таблиці Google"
        }
        ```
*   **GET `/tasks/{id}/`** — Отримати детальну інформацію про завдання (статус, кількість знайдених/зібраних URL).
*   **POST `/tasks/{id}/stop/`** — Зупинити виконання завдання.
*   **POST `/tasks/{id}/restart/`** — Перезапустити завдання.

### Результати (Results)

Отримання даних, які були зібрані парсером.

*   **GET `/results/`** — Список усіх зібраних пінів.
    *   **Фільтрація:** Можна додати `?task_id={id}`, щоб отримати результати конкретного завдання.
*   **GET `/results/{id}/`** — Деталі конкретного піна.

### Акаунти Pinterest (Accounts)

*   **GET `/accounts/`** — Список підключених акаунтів Pinterest.
*   **POST `/accounts/`** — Додати новий акаунт (тільки адміни).
    *   **Тіло запиту:** `name`, `cookies` (у будь-якому форматі: JSON з розширення браузера, рядок `a=b; c=d`, cookies.txt), `proxy` (ID, опціонально), `user_agent` (опціонально).

### Проксі (Proxies)

*   **GET `/proxies/`** — Список ваших проксі.
*   **POST `/proxies/`** — Додати проксі.

### Автопостинг (Autopost)

Налаштування автопостингу пінів завдання. Одне налаштування на завдання; звичайні користувачі бачать і змінюють лише налаштування своїх завдань.

*   **GET `/autopost/`** — Список налаштувань. Фільтр: `?task_id={id}`.
*   **POST `/autopost/`** — Створити налаштування для завдання.
    *   **Тіло запиту:**
        ```json
        {
            "task": 12,
            "webhook_token": "11111111-1111-1111-1111-111111111111",
            "board_name": "My board",
            "min_interval": 100,
            "max_interval": 200,
            "site_url": "https://example.com/?",
            "use_uniqueness": true,
            "uniqueness_config": 1
        }
        ```
    *   `min_interval` / `max_interval` — хвилини між постами, `max_interval` не може бути меншим за `min_interval`.
    *   `uniqueness_config` — ID конфігу уникалізації (див. нижче). Якщо не передати, підставляється перший активний.
*   **GET `/autopost/{id}/`** — Деталі: `status` (`idle`, `running`, `paused`, `completed`, `error`), `posted_count` / `total_count`, `error_message`, `next_post` (`{pin_id, scheduled_at}` наступного піна в черзі).
*   **PATCH `/autopost/{id}/`** — Змінити налаштування. При зміні інтервалів розклад черги перераховується автоматично.
*   **DELETE `/autopost/{id}/`** — Видалити налаштування разом з чергою.
*   **POST `/autopost/{id}/start/`** — Запустити автопостинг (або продовжити після паузи). `409`, якщо вже запущено або не заповнені `webhook_token` / `board_name`.
*   **POST `/autopost/{id}/stop/`** — Поставити на паузу. Черга зберігається.
*   **POST `/autopost/{id}/test/`** — Одразу опублікувати один пін (перший з черги або з результатів) для перевірки налаштувань. `200` — успіх, `502` — помилка публікації (текст у `error`).
*   **GET `/autopost/{id}/queue/`** — Черга постів у порядку публікації. Параметри: `?status=pending|posted|failed|skipped`, `?limit=100` (максимум 1000).

### Уникалізація автопостингу (Autopost uniqueness) — тільки для адміністраторів

Конфіги Groq, якими унікалізуються піни перед публікацією.

*   **GET `/autopost-uniqueness/`** — Список конфігів. Ключ повертається лише в маскованому вигляді (`api_key_preview`).
*   **POST `/autopost-uniqueness/`** — Створити конфіг: `name`, `api_key` (обов'язково), `model`, `prompt`, `is_active`.
*   **PATCH `/autopost-uniqueness/{id}/`** — Змінити конфіг (наприклад, лише `api_key` або `model`).
*   **DELETE `/autopost-uniqueness/{id}/`** — Видалити конфіг.
*   **POST `/autopost-uniqueness/{id}/test/`** — Тестовий запит до Groq. `200` з прикладом результату або `502` з текстом помилки.
*   **POST `/autopost-uniqueness/change-model/`** — Змінити модель на всіх конфігах:
    ```json
    {"model": "llama-3.3-70b"}
    ```
    Щоб змінити лише деякі — додайте `"ids": [1, 2]`. Відповідь: `{"model": "...", "updated": 2}`.

---

## 3. Приклади використання на Python (requests)

### Створення завдання та отримання результатів

```python
import requests
import time

BASE_URL = "http://your-domain.com/api"
TOKEN = "your_token_here"
HEADERS = {"Authorization": f"Token {TOKEN}"}

# 1. Створюємо завдання
task_data = {
    "name": "Python API Task",
    "keywords": ["interior design", "modern kitchen"],
    "threads": 2
}
response = requests.post(f"{BASE_URL}/tasks/", json=task_data, headers=HEADERS)
task = response.json()
task_id = task['id']
print(f"Завдання створено! ID: {task_id}")

# 2. Чекаємо завершення (спрощено)
while True:
    status_resp = requests.get(f"{BASE_URL}/tasks/{task_id}/", headers=HEADERS)
    status = status_resp.json()['status']
    print(f"Поточний статус: {status}")
    if status in ['done', 'stopped', 'error']:
        break
    time.sleep(10)

# 3. Отримуємо результати
results_resp = requests.get(f"{BASE_URL}/results/?task_id={task_id}", headers=HEADERS)
results = results_resp.json()
print(f"Зібрано {len(results)} пінів.")
for pin in results[:5]:
    print(f"- {pin['title']}: {pin['pin_url']}")
```

### Налаштування та запуск автопостингу

```python
# 1. Створюємо налаштування автопостингу для завдання
config = requests.post(f"{BASE_URL}/autopost/", json={
    "task": task_id,
    "webhook_token": "11111111-1111-1111-1111-111111111111",
    "board_name": "My board",
    "min_interval": 100,
    "max_interval": 200,
    "site_url": "https://example.com/?",
}, headers=HEADERS).json()

# 2. Перевіряємо публікацію одним піном
print(requests.post(f"{BASE_URL}/autopost/{config['id']}/test/", headers=HEADERS).json())

# 3. Запускаємо і дивимось прогрес
requests.post(f"{BASE_URL}/autopost/{config['id']}/start/", headers=HEADERS)
info = requests.get(f"{BASE_URL}/autopost/{config['id']}/", headers=HEADERS).json()
print(info["status"], f"{info['posted_count']}/{info['total_count']}", info["next_post"])
```

---

## 4. Інтерактивна документація

Ви можете переглянути повний перелік ендпоінтів та протестувати їх через вебінтерфейс:

*   **Swagger UI:** `/api/schema/swagger-ui/`
*   **Redoc:** `/api/schema/redoc/`
