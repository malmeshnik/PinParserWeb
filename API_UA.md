# Документація API PinParser

Цей документ містить опис того, як взаємодіяти з API сервісу PinParser для автоматизації роботи з парсером Pinterest.

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
            "keywords": "keyword1\nkeyword2",
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
*   **POST `/accounts/`** — Додати новий акаунт.
    *   **Тіло запиту:** `email`, `password`, `proxy` (ID), `user_agent` (опціонально).

### Проксі (Proxies)

*   **GET `/proxies/`** — Список ваших проксі.
*   **POST `/proxies/`** — Додати проксі.

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
    "keywords": "interior design\nmodern kitchen",
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
    if status in ['DONE', 'STOPPED', 'ERROR']:
        break
    time.sleep(10)

# 3. Отримуємо результати
results_resp = requests.get(f"{BASE_URL}/results/?task_id={task_id}", headers=HEADERS)
results = results_resp.json()
print(f"Зібрано {len(results)} пінів.")
for pin in results[:5]:
    print(f"- {pin['title']}: {pin['pin_url']}")
```

---

## 4. Інтерактивна документація

Ви можете переглянути повний перелік ендпоінтів та протестувати їх через вебінтерфейс:

*   **Swagger UI:** `/api/schema/swagger-ui/`
*   **Redoc:** `/api/schema/redoc/`
