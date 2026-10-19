# PinParser API — повний довідник

Довідник для автоматичного використання сервісу (скрипти, AI-агенти). Описує **всі** ендпоінти, поля, типи, права доступу, статуси, помилки та типові сценарії. Поведінка описана так, як вона реалізована в коді.

## Зміст

1. [Що вміє сервіс](#1-що-вміє-сервіс)
2. [Загальні правила](#2-загальні-правила)
3. [Авторизація](#3-авторизація)
4. [Права доступу](#4-права-доступу)
5. [Помилки](#5-помилки)
6. [Завдання парсингу — `/api/tasks/`](#6-завдання-парсингу--apitasks)
7. [Результати — `/api/results/`](#7-результати--apiresults)
8. [Автопостинг — `/api/autopost/`](#8-автопостинг--apiautopost)
9. [Уникалізація автопостингу — `/api/autopost-uniqueness/`](#9-уникалізація-автопостингу--apiautopost-uniqueness)
10. [Уникалізація парсингу — `/api/uniqueness/`](#10-уникалізація-парсингу--apiuniqueness)
11. [Акаунти Pinterest — `/api/accounts/`](#11-акаунти-pinterest--apiaccounts)
12. [Проксі — `/api/proxies/`](#12-проксі--apiproxies)
13. [Типові сценарії](#13-типові-сценарії)
14. [Правила для AI-агента](#14-правила-для-ai-агента)
15. [Швидкий перелік ендпоінтів](#15-швидкий-перелік-ендпоінтів)

---

## 1. Що вміє сервіс

PinParser збирає піни з Pinterest за ключовими словами і може автоматично публікувати їх на свою дошку.

Повний цикл:

1. **Парсинг.** Створюєте завдання з ключовими словами → сервіс через залогінений Pinterest-акаунт шукає піни, заходить у кожен і зберігає дані (заголовок, опис, картинка, анотація, кількість збережень…).
2. **Уникалізація (опційно).** AI переписує заголовок і опис кожного піна (`utitle`, `udescription`) і будує slug-посилання.
3. **Експорт.** Формується Excel-файл з усіма пінами (`export_file`).
4. **Автопостинг (опційно).** Піни завдання по черзі публікуються на дошку Pinterest з випадковим інтервалом між постами; перед публікацією текст може унікалізуватись через Groq.

Усі довгі операції виконуються у фоні. API лише ставить їх у чергу і показує статус — результат треба **опитувати** (polling).

---

## 2. Загальні правила

| Правило | Значення |
|---|---|
| Базовий URL | `http://<сервер>:8000/api/` (локально `http://localhost:8000/api/`) |
| Формат | JSON. Заголовок `Content-Type: application/json` для POST/PUT/PATCH |
| Кодування | UTF-8 |
| Дати | ISO 8601 з часовою зоною, UTC: `"2026-10-17T12:30:00.123456Z"` |
| Пагінація | **Немає.** Списки повертаються повним JSON-масивом. Фільтруйте через query-параметри (`?task_id=`) |
| `PUT` vs `PATCH` | `PUT` — повна заміна (передавайте всі обов'язкові поля). Для змін використовуйте **`PATCH`** — лише змінені поля |
| Слеш у кінці | Обов'язковий: `/api/tasks/12/`, а не `/api/tasks/12` |
| Мова повідомлень | Повідомлення помилок можуть бути українською або російською — орієнтуйтеся на HTTP-код і ключі JSON, а не на текст |
| Інтерактивна схема | Swagger UI: `/api/schema/swagger-ui/`, Redoc: `/api/schema/redoc/`, OpenAPI YAML: `/api/schema/` |

---

## 3. Авторизація

Кожен запит до `/api/` (крім отримання токена) потребує авторизації.

### Отримати токен

`POST /api/auth/token/` — без авторизації.

Запит:
```json
{"username": "my_user", "password": "my_password"}
```

Відповідь `200`:
```json
{"token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b"}
```

Невірний логін/пароль → `400` `{"non_field_errors": ["..."]}`.

Токен постійний (не має терміну дії). Один користувач — один токен.

### Використання токена (рекомендовано)

```
Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b
```

### Альтернативи

- **Basic Auth:** `Authorization: Basic base64(username:password)` у кожному запиті.
- **Сесія** адмінки (cookie) — лише для браузера, для API не використовуйте.

---

## 4. Права доступу

Є два типи користувачів:

- **Звичайний користувач** — працює лише зі **своїми** завданнями, їхніми результатами та автопостингом. Чужі об'єкти для нього не існують (`404`).
- **Адміністратор** (`is_staff`) — має доступ до інфраструктури: акаунти Pinterest, проксі, конфіги уникалізації. **Суперюзер** бачить завдання всіх користувачів.

| Ресурс | Звичайний користувач | Адміністратор |
|---|---|---|
| `/api/tasks/` | свої завдання (суперюзер — усі) | так |
| `/api/results/` | результати своїх завдань (суперюзер — усі) | так |
| `/api/autopost/` | автопостинг своїх завдань (суперюзер — усі) | так |
| `/api/autopost-uniqueness/` | ❌ `403` | ✅ |
| `/api/uniqueness/` | ❌ `403` | ✅ |
| `/api/accounts/` | ❌ `403` | ✅ |
| `/api/proxies/` | ❌ `403` | ✅ |

---

## 5. Помилки

| Код | Коли | Тіло |
|---|---|---|
| `200` / `201` / `204` | Успіх (`204` — видалено, тіла немає) | — |
| `400` | Помилка валідації | `{"<поле>": ["повідомлення", ...]}` або `{"detail": "..."}` або `{"non_field_errors": [...]}` |
| `401` | Немає або невірний токен | `{"detail": "Учетные данные не были предоставлены."}` |
| `403` | Недостатньо прав (ресурс лише для адмінів) | `{"detail": "У вас недостаточно прав для выполнения данного действия."}` |
| `404` | Об'єкт не існує **або належить іншому користувачу** | `{"detail": "No ParseTask matches the given query."}` |
| `405` | Метод не підтримується | `{"detail": "..."}` |
| `409` | Дія неможлива в поточному стані (вже запущено / не запущено) | `{"detail": "..."}` або `{"status": "..."}` |
| `502` | Зовнішній сервіс (Groq, сервіс публікації) повернув помилку | `{"success": false, "error": "..."}` |

Приклад `400`:
```json
{"max_interval": ["Максимальний інтервал має бути не меншим за мінімальний"]}
```

---

## 6. Завдання парсингу — `/api/tasks/`

Завдання = набір ключових слів, за якими збираються піни.

### Об'єкт `ParseTask`

| Поле | Тип | Запис | Опис |
|---|---|---|---|
| `id` | integer | — | ID завдання |
| `name` | string (≤255) | **обов'язкове** | Назва. Використовується в назві Excel-файлу |
| `keywords` | array of string | **обов'язкове** | Ключові слова пошуку. Можна передати рядок — він розіб'ється по нових рядках і комах |
| `annotation_filter_words` | string \| null (≤255) | так | Слова через кому. Якщо задано — зберігаються лише піни, в анотації яких є **хоча б одне** зі слів (без урахування регістру) |
| `threads` | integer | так | Кількість потоків. За замовчуванням `3`. Фактично використовується не більше `3` |
| `use_uniqueness` | boolean | так | Уникалізувати піни після парсингу. За замовчуванням `true` |
| `uniqueness_config` | integer \| null | так | ID конфігу уникалізації (`/api/uniqueness/`). `null` або не передано — перший активний конфіг |
| `auto_sheet_name` | boolean | так | Службове поле, за замовчуванням `true` |
| `table_name` | string \| null | так | Службове поле |
| `status` | enum | — | Статус, див. нижче |
| `total_urls` | integer | — | Скільки пінів **знайдено** в пошуку |
| `processed_urls` | integer | — | Скільки пінів **зібрано** (збережено в результати) |
| `error_message` | string \| null | — | Текст помилки. Може бути заповнений і при `done` — тоді це некритичні збої (див. нижче) |
| `export_file` | string (URL) \| null | — | Повне посилання на Excel з результатами, з'являється після завершення. Завантажується звичайним `GET` **без токена** |
| `owner` | integer | — | ID власника. Виставляється автоматично, змінити не можна |
| `celery_task_id` | string \| null | — | Службове |
| `created_at` / `started_at` / `finished_at` | datetime \| null | — | Час створення / старту / завершення |

### Статуси завдання (`status`)

| Значення | Що означає | Фінальний? |
|---|---|---|
| `pending` | Створене або в черзі на виконання | ні |
| `running` | Йде парсинг: збір посилань і пінів | ні |
| `waiting_uniqueness` | Парсинг завершено, чекає на уникалізацію | ні |
| `uniqueness` | Йде уникалізація / генерація slug | ні |
| `done` | Готово, Excel сформовано | **так** |
| `error` | Критична помилка, причина в `error_message` | **так** |
| `stopped` | Зупинено користувачем | **так** |

Послідовність: `pending → running → [waiting_uniqueness → uniqueness] → done`. На будь-якому кроці можливий перехід у `error` або `stopped`.

**Важливо про `error_message` при `done`:** якщо частину пінів не вдалося завантажити або уникалізувати, завдання все одно завершується `done`, а в `error_message` буде пояснення, наприклад `"Не вдалося завантажити 12 з 500 пінів, деталі в логах помилок"`. Статус `error` ставиться, лише коли результату немає взагалі (немає акаунтів, не зібрано жодного піна, невірний API-ключ уникалізації тощо).

### `GET /api/tasks/` — список завдань

Відповідь `200`: масив `ParseTask`, новіші першими.

### `POST /api/tasks/` — створити і одразу запустити

Тіло:

| Поле | Обов'язкове | За замовчуванням |
|---|---|---|
| `name` | так | — |
| `keywords` | так | — |
| `threads` | ні | `3` |
| `use_uniqueness` | ні | `true` |
| `uniqueness_config` | ні | перший активний |
| `annotation_filter_words` | ні | `null` |
| `auto_sheet_name` | ні | `true` |

```json
{
  "name": "Kitchen ideas",
  "keywords": ["modern kitchen", "kitchen island ideas"],
  "threads": 3,
  "use_uniqueness": true,
  "annotation_filter_words": "kitchen, interior"
}
```

Відповідь `201`: об'єкт `ParseTask` зі `status: "pending"`. Завдання **вже поставлене в чергу** — окремо запускати не потрібно.

Помилки: `400` — немає `name`, порожні `keywords`.

### `GET /api/tasks/{id}/` — деталі та прогрес

Відповідь `200`: `ParseTask`. Використовуйте для опитування статусу.

### `PATCH /api/tasks/{id}/` — змінити

Змінюються лише поля з колонки «Запис». Зміни застосуються при **наступному** запуску (`restart`).
`PUT` вимагає `name` і `keywords`.

### `DELETE /api/tasks/{id}/` — видалити

Відповідь `204`. Видаляються також усі результати, автопостинг і його черга. Запущене завдання спершу зупиніть (`stop`).

### `POST /api/tasks/{id}/stop/` — зупинити

Тіла немає. Працює в статусах `pending`, `running`, `waiting_uniqueness`, `uniqueness`.

- `200` `{"status": "task stopping"}` — статус стає `stopped`. Уже зібрані піни зберігаються.
- `409` `{"status": "task is not running"}` — завдання вже у фінальному статусі.

### `POST /api/tasks/{id}/restart/` — перезапустити

Тіла немає. Запускає парсинг заново з поточними налаштуваннями. Уже зібрані піни не дублюються.

- `200` `{"status": "task restarted"}` — статус `pending`.
- `409` `{"status": "task is already running"}` — завдання ще виконується.

---

## 7. Результати — `/api/results/`

Зібрані піни. Тільки читання.

### Об'єкт `PinResult`

| Поле | Тип | Опис |
|---|---|---|
| `id` | integer | ID результату (використовується в черзі автопостингу як `pin`) |
| `task` | integer | ID завдання |
| `keyword` | string | Ключове слово, за яким знайдено пін |
| `pin_url` | string (URL) | Посилання на пін: `https://www.pinterest.com/pin/<id>/` |
| `pin_id` | string \| null | ID піна в Pinterest |
| `title` | string \| null | Оригінальний заголовок |
| `description` | string \| null | Оригінальний опис |
| `utitle` | string \| null | Уникалізований заголовок (`null`, якщо уникалізації не було або вона не вдалася) |
| `udescription` | string \| null | Уникалізований опис |
| `slug_url` | string \| null | Slug-посилання, побудоване з уникалізованого заголовка |
| `image_url` | string (URL) \| null | Оригінальне посилання на картинку в Pinterest |
| `local_image` | string (URL) \| null | Копія картинки на сервері |
| `alt_text` | string \| null | Alt-текст картинки |
| `annotation` | string \| null | Анотації (теги) Pinterest через кому |
| `domain` | string \| null | Домен джерела піна |
| `saves` | integer \| null | Кількість збережень |
| `pinner_username` | string \| null | Автор піна |
| `creation_date` | string \| null | Дата створення піна в Pinterest (як рядок) |
| `created_at` | datetime | Коли пін збережено в сервісі |

### `GET /api/results/` — список

| Query-параметр | Опис |
|---|---|
| `task_id` | **Рекомендовано завжди.** Результати одного завдання |

Відповідь `200`: масив `PinResult`. Без `task_id` повертаються **всі** ваші піни одним масивом (може бути дуже великим).

### `GET /api/results/{id}/` — один пін

Відповідь `200`: `PinResult`.

---

## 8. Автопостинг — `/api/autopost/`

Налаштування публікації пінів завдання на дошку Pinterest. **Одне налаштування на одне завдання.**

Як працює: після `start` усі піни завдання стають у чергу. Перший публікується при найближчій обробці черги (протягом ~3 хвилин), кожен наступний — через випадкову кількість хвилин від `min_interval` до `max_interval` після попереднього. Черга обробляється у фоні кожні 3 хвилини. Вже опубліковані піни повторно не публікуються.

### Об'єкт `AutoPostConfig`

| Поле | Тип | Запис | Опис |
|---|---|---|---|
| `id` | integer | — | ID налаштування (використовується в URL дій) |
| `task` | integer | **обов'язкове**, лише при створенні | ID **свого** завдання. Змінити потім не можна |
| `board_name` | string (≤255) | **обов'язкове** | Назва дошки Pinterest |
| `webhook_token` | string (UUID) \| null | так | Токен акаунта в сервісі публікації. **Без нього запуск неможливий** |
| `min_interval` | integer | так | Мінімальний інтервал між постами, хвилини. За замовчуванням `100` |
| `max_interval` | integer | так | Максимальний інтервал, хвилини. За замовчуванням `200`. Має бути `>= min_interval` |
| `site_url` | string (URL) | так | Базове посилання, до якого додається slug заголовка. За замовчуванням `"https://example.com/?"` → посилання поста `https://example.com/?my-pin-title` |
| `use_uniqueness` | boolean | так | Уникалізувати текст через Groq перед публікацією. За замовчуванням `true` |
| `uniqueness_config` | integer \| null | так | ID конфігу з `/api/autopost-uniqueness/`. Не передано — перший активний. `null` або неактивний конфіг — пости йдуть з оригінальним текстом |
| `status` | enum | — | `idle`, `running`, `paused`, `completed`, `error` |
| `posted_count` | integer | — | Опубліковано пінів |
| `total_count` | integer | — | Усього пінів завдання |
| `error_message` | string \| null | — | Причина помилки або кількість неопублікованих пінів |
| `next_post` | object \| null | — | Наступний пін у черзі: `{"pin_id": 15, "scheduled_at": "2026-10-17T14:05:00Z"}`. `null` — черга порожня |
| `started_at` / `finished_at` | datetime \| null | — | Старт / завершення |
| `created_at` / `updated_at` | datetime | — | Службові |

### Статуси автопостингу (`status`)

| Значення | Що означає |
|---|---|
| `idle` | Створено, ще не запускався |
| `running` | Публікує за розкладом |
| `paused` | Зупинено через `stop`. Черга збережена, `start` продовжить |
| `completed` | Усі піни оброблено. Якщо частину не вдалося опублікувати — пояснення в `error_message` |
| `error` | Не вдалося опублікувати жодного піна, причина в `error_message` |

### `GET /api/autopost/` — список

| Query-параметр | Опис |
|---|---|
| `task_id` | Налаштування конкретного завдання |

Відповідь `200`: масив `AutoPostConfig`.

### `POST /api/autopost/` — створити

```json
{
  "task": 12,
  "board_name": "Kitchen ideas",
  "webhook_token": "3f2b1c9e-8a7d-4e6f-9b0a-1c2d3e4f5a6b",
  "min_interval": 100,
  "max_interval": 200,
  "site_url": "https://example.com/?",
  "use_uniqueness": true
}
```

Відповідь `201`: `AutoPostConfig` зі `status: "idle"`. Публікація **не запускається** автоматично — викличте `start`.

Помилки `400`:
- `{"task": ["Немає доступу до цього завдання"]}` — чуже завдання;
- `{"task": ["... уже существует."]}` — для завдання вже є налаштування (використайте `PATCH`);
- `{"max_interval": [...]}` — `max_interval < min_interval`.

### `GET /api/autopost/{id}/` — деталі та прогрес

### `PATCH /api/autopost/{id}/` — змінити

Якщо змінено `min_interval` або `max_interval`, розклад неопублікованих пінів автоматично перераховується від поточного моменту.

### `DELETE /api/autopost/{id}/` — видалити

`204`. Видаляється разом із чергою. Піни завдання не видаляються.

### `POST /api/autopost/{id}/start/` — запустити / продовжити

Тіла немає.
- `200` `{"detail": "Автопостинг запущено. Черга створюється..."}`. Черга будується у фоні за кілька секунд, після цього `status` стає `running`.
- `409` `{"detail": "Автопостинг вже запущено"}`.
- `409` `{"detail": "Заповніть webhook токен та назву дошки перед запуском"}`.

Після `paused` продовжує існуючу чергу: перший пін одразу, решта з інтервалами від поточного моменту. Після `completed`/`error` створює нову чергу лише з ще не опублікованих пінів.

### `POST /api/autopost/{id}/stop/` — пауза

- `200` `{"detail": "Автопостинг зупинено"}` → `paused`.
- `409` `{"detail": "Автопостинг не запущено"}`.

### `POST /api/autopost/{id}/test/` — тестова публікація одного піна

Публікує **один реальний пін зараз**: перший неопублікований з черги, а якщо черги немає — перший пін завдання. Запит синхронний і може тривати до ~2 хвилин.

- `200`:
  ```json
  {"success": true, "pin_id": 15, "title": "...", "response_status": 200, "message": "Пін успішно опубліковано на Pinterest"}
  ```
  Якщо пін був у черзі, він позначається опублікованим.
- `502` `{"success": false, "pin_id": 15, "error": "Помилка публікації (...): ..."}`.
- `400` `{"detail": "Заповніть webhook токен та назву дошки перед тестом"}`.

### `GET /api/autopost/{id}/queue/` — черга постів

| Query-параметр | Опис |
|---|---|
| `status` | `pending`, `posted`, `failed`, `skipped`. Інше значення → `400` |
| `limit` | Кількість записів, `1–1000`, за замовчуванням `100` |

Відповідь `200` — масив у порядку публікації:
```json
[
  {
    "id": 101,
    "pin": 15,
    "pin_title": "Modern kitchen with island",
    "status": "posted",
    "scheduled_at": "2026-10-17T12:00:00Z",
    "posted_at": "2026-10-17T12:00:41Z",
    "attempts": 1,
    "error_message": null
  }
]
```

Статуси елемента черги: `pending` (чекає), `posted` (опубліковано), `failed` (помилка, текст в `error_message`; повторюється лише при новому `start` після завершення), `skipped` (пропущено).

---

## 9. Уникалізація автопостингу — `/api/autopost-uniqueness/`

**Тільки для адміністраторів.** Конфіги Groq, якими переписується текст піна перед публікацією. Параметри генерації фіксовані в коді (temperature 0.5, JSON-відповідь, таймаут 30 с, 3 спроби); налаштовуються лише ключ, модель і промпт.

### Об'єкт `AutoPostUniquenessConfig`

| Поле | Тип | Запис | Опис |
|---|---|---|---|
| `id` | integer | — | ID |
| `name` | string (≤255) | **обов'язкове** | Назва |
| `is_active` | boolean | так | За замовчуванням `true`. Неактивний конфіг не використовується |
| `api_key` | string | **обов'язкове при створенні**, лише запис | Groq API-ключ. У відповідях **не повертається** |
| `api_key_preview` | string | — | Маскований ключ: `"gsk_...abcd"` |
| `model` | string (≤100) | так | Модель Groq. За замовчуванням `"qwen/qwen3.6-27b"` |
| `prompt` | string | так | Промпт. Змінні: `{{title}}`, `{{description}}`, `{{alt_text}}`, `{{annotation}}`. Модель має повернути JSON з ключами `title` і `description` |
| `created_at` / `updated_at` | datetime | — | Службові |

### Ендпоінти

- `GET /api/autopost-uniqueness/` — список.
- `POST /api/autopost-uniqueness/` — створити: `{"name": "Groq main", "api_key": "gsk_...", "model": "llama-3.3-70b-versatile"}`. Без `api_key` → `400`.
- `GET /api/autopost-uniqueness/{id}/` — деталі.
- `PATCH /api/autopost-uniqueness/{id}/` — змінити (наприклад, лише `{"api_key": "gsk_new"}`).
- `DELETE /api/autopost-uniqueness/{id}/` — `204`. Налаштування автопостингу з цим конфігом публікуватимуть без уникалізації.

### `POST /api/autopost-uniqueness/{id}/test/` — перевірити ключ і модель

Робить реальний тестовий запит до Groq.
- `200` `{"success": true, "result": {"title": "...", "description": "..."}}`
- `502` `{"success": false, "error": "401: {\"error\": ...}"}` — невірний ключ, неіснуюча модель тощо.

### `POST /api/autopost-uniqueness/change-model/` — змінити модель масово

```json
{"model": "llama-3.3-70b-versatile"}
```
Змінює модель на **всіх** конфігах. Лише для деяких — додайте `"ids": [1, 3]`.

Відповідь `200`: `{"model": "llama-3.3-70b-versatile", "updated": 2}`.

---

## 10. Уникалізація парсингу — `/api/uniqueness/`

**Тільки для адміністраторів.** Конфіги AI, якими уникалізуються піни після парсингу (крок `uniqueness` завдання). Підтримуються OpenAI і Omniroute (OpenAI-сумісний API).

> ⚠️ Цей ресурс повертає API-ключі **у відкритому вигляді**.

### Об'єкт `UniquenessConfig`

| Поле | Тип | Опис |
|---|---|---|
| `id` | integer | ID (передається в `uniqueness_config` завдання) |
| `name` | string \| null | Назва |
| `is_active` | boolean | Активний. Завдання без явного конфігу беруть перший активний |
| `uniqueness_method` | enum | `gpt` (OpenAI) або `omniroute` |
| `openai_api_key` | string | Ключ OpenAI (для `gpt`) |
| `model` | string | Модель OpenAI, за замовчуванням `"gpt-4o-mini"` |
| `omniroute_api_key` | string | Ключ Omniroute (для `omniroute`) |
| `omniroute_base_url` | string | URL Omniroute, за замовчуванням `"http://localhost:20128/v1"` |
| `omniroute_model` | string | Модель Omniroute |
| `prompt_template` | string | Промпт. Змінні: `{{title}}`, `{{description}}`, `{{alt_text}}`, `{{annotation}}`, `{{domain}}`, `{{image_url}}`, `{{keyword}}`. Модель має повернути JSON з `title` і `description` |
| `use_title`, `use_description`, `use_alt_text`, `use_annotation`, `use_domain`, `use_image_url`, `use_keyword` | boolean | Які поля піна підставляти в промпт |
| `temperature` | number | За замовчуванням `1.0` |
| `max_tokens_title`, `max_tokens_description` | integer | Ліміт токенів відповіді (сумуються) |
| `max_requests_per_minute` | integer | Ліміт запитів до AI на хвилину, за замовчуванням `450` |
| `max_workers` | integer | Паралельних запитів, за замовчуванням `5` |
| `model_provider` | string \| null | Застаріле, не використовується |
| `created_at` | datetime | Службове |

Ендпоінти: `GET/POST /api/uniqueness/`, `GET/PUT/PATCH/DELETE /api/uniqueness/{id}/`. Усі поля, крім `id` і `created_at`, доступні на запис; обов'язкових полів немає.

Якщо ключ невірний, завдання парсингу завершиться `error` з `error_message: "Помилка API уникалізації: ..."`.

---

## 11. Акаунти Pinterest — `/api/accounts/`

**Тільки для адміністраторів.** Залогінені акаунти Pinterest, через які йде парсинг. Сервіс сам обирає акаунт (найдавніше використаний з активних) і переходить до наступного при помилках.

### Об'єкт `PinterestAccount`

| Поле | Тип | Запис | Опис |
|---|---|---|---|
| `id` | integer | — | ID |
| `name` | string (≤255) | **обов'язкове** | Довільна назва |
| `cookies` | будь-який формат → array | **обов'язкове** | Cookies залогіненого браузера, див. нижче |
| `proxy` | integer \| null | так | ID проксі з `/api/proxies/` |
| `user_agent` | string \| null | так | User-Agent. Порожній — підбирається автоматично |
| `is_active` | boolean | так | Використовувати для парсингу. За замовчуванням `true` |
| `status` | enum | так | `active`, `banned`, `error`. Після 3 помилок стає `error` і не використовується, доки не повернути `active` |
| `fail_count` | integer | так | Лічильник помилок. Скиньте в `0` разом зі `status: "active"` |
| `last_used_at` | datetime \| null | так | Коли використовувався востаннє |
| `created_at` | datetime | — | Службове |

### Формат `cookies`

Приймається **будь-який** поширений формат — сервіс сам приводить його до формату Playwright:

- JSON-експорт розширення браузера (Cookie-Editor, EditThisCookie) — масив з `expirationDate`, `hostOnly`, `sameSite: "no_restriction"` тощо;
- формат Playwright / Puppeteer / Selenium;
- `{"cookies": [...]}` (Playwright storage_state);
- об'єкт `{"_pinterest_sess": "...", "csrftoken": "..."}`;
- рядок `"_pinterest_sess=...; csrftoken=..."` (можна з префіксом `Cookie:`);
- рядок із вмістом файлу `cookies.txt` (Netscape).

У відповіді `cookies` завжди повертається нормалізованим масивом:
```json
[{"name": "_pinterest_sess", "value": "...", "domain": ".pinterest.com", "path": "/",
  "expires": 1830000000.0, "httpOnly": true, "secure": true, "sameSite": "None"}]
```

Куки інших сайтів і прострочені відкидаються. Для роботи **обов'язкова** cookie `_pinterest_sess` (сесія входу) — без неї акаунт не залогінений, і парсинг через нього не працюватиме (API таке збереже, перевіряйте самі).

Помилка формату → `400` `{"cookies": ["Не знайдено жодної дійсної cookie. ..."]}`.

Ендпоінти: `GET/POST /api/accounts/`, `GET/PUT/PATCH/DELETE /api/accounts/{id}/`.

```json
POST /api/accounts/
{"name": "Account 1", "cookies": "_pinterest_sess=TWc9PSZ...; csrftoken=abc123", "proxy": 2}
```

> ⚠️ Відповідь містить cookies у відкритому вигляді.

---

## 12. Проксі — `/api/proxies/`

**Тільки для адміністраторів.** Проксі, через які акаунти ходять у Pinterest.

### Об'єкт `Proxy`

| Поле | Тип | Опис |
|---|---|---|
| `id` | integer | ID (передається в `proxy` акаунта) |
| `name` | string (≤255), **обов'язкове** | Назва |
| `host` | string \| null | Хост |
| `port` | integer \| null | Порт |
| `username`, `password` | string \| null | Авторизація проксі (`password` повертається у відкритому вигляді) |
| `is_9proxy` | boolean | Динамічний проксі 9Proxy (зараз не використовується — залишайте `false`) |
| `country`, `state`, `city`, `zip`, `isp` | string \| null | Фільтри для 9Proxy |
| `status` | enum | `active`, `dead`, `error` |
| `fail_count` | integer | Лічильник помилок |
| `is_active` | boolean | Використовувати |
| `last_checked_at` | datetime \| null | Остання перевірка |
| `created_at` | datetime | Службове |

Ендпоінти: `GET/POST /api/proxies/`, `GET/PUT/PATCH/DELETE /api/proxies/{id}/`.

### `POST /api/proxies/{id}/check_health/` — перевірити проксі

Робить запит через проксі. Відповідь `200`: `{"is_active": true, "status": "active"}`. Після 3 невдалих перевірок `status` стає `dead`.

---

## 13. Типові сценарії

Нижче `BASE = http://<сервер>:8000/api`, усі запити з заголовком `Authorization: Token <token>`.

### A. Зібрати піни і отримати результат

1. `POST {BASE}/tasks/` з `name` і `keywords` → збережіть `id`.
2. Кожні 15–30 с: `GET {BASE}/tasks/{id}/`. Прогрес — `processed_urls` / `total_urls`.
3. Чекайте фінального статусу: `done`, `error` або `stopped`.
4. При `done`:
   - піни — `GET {BASE}/results/?task_id={id}`;
   - Excel — завантажте `export_file`;
   - якщо `error_message` не порожній — частина пінів не оброблена, повідомте про це.
5. При `error` — покажіть `error_message`.

Тривалість: від кількох хвилин до години-двох залежно від кількості ключових слів. Ліміт виконання одного етапу — 3 години.

### B. Запустити автопостинг завдання

1. Переконайтеся, що завдання `done` і має піни.
2. `GET {BASE}/autopost/?task_id={id}` — якщо масив порожній, створіть: `POST {BASE}/autopost/` з `task`, `board_name`, `webhook_token`. Якщо є — за потреби `PATCH`.
3. (Рекомендовано) `POST {BASE}/autopost/{config_id}/test/` — перевірити, що публікація працює. Це **реальний** пост.
4. `POST {BASE}/autopost/{config_id}/start/`.
5. Прогрес: `GET {BASE}/autopost/{config_id}/` → `status`, `posted_count`/`total_count`, `next_post`. Деталі: `GET {BASE}/autopost/{config_id}/queue/?status=failed`.

### C. Поставити автопостинг на паузу і змінити інтервал

1. `POST {BASE}/autopost/{config_id}/stop/`.
2. `PATCH {BASE}/autopost/{config_id}/` з `{"min_interval": 60, "max_interval": 120}`.
3. `POST {BASE}/autopost/{config_id}/start/`.

(Інтервали можна міняти і без паузи — розклад перерахується автоматично.)

### D. Змінити модель уникалізації автопостингу (адмін)

1. `POST {BASE}/autopost-uniqueness/change-model/` з `{"model": "<нова модель>"}`.
2. Для кожного конфігу `POST {BASE}/autopost-uniqueness/{id}/test/` — перевірити, що модель відповідає.

### E. Додати Pinterest-акаунт (адмін)

1. (Опційно) `POST {BASE}/proxies/` → `id` проксі; `POST {BASE}/proxies/{id}/check_health/`.
2. `POST {BASE}/accounts/` з `name`, `cookies` (будь-який формат), `proxy`.
3. Перевірте, що у відповіді в `cookies` є запис з `"name": "_pinterest_sess"`.

### F. Завдання впало через акаунти

`error_message` на кшталт «Немає доступних активних аккаунтів Pinterest» або «Не вдалося зібрати піни жодним з доступних аккаунтів»:
1. `GET {BASE}/accounts/` — подивіться `status` і `fail_count`.
2. Оновіть cookies (`PATCH` з новими `cookies`) і поверніть `{"status": "active", "fail_count": 0}`.
3. `POST {BASE}/tasks/{id}/restart/`.

---

## 14. Правила для AI-агента

1. **Опитування.** Не опитуйте статус частіше ніж раз на 10 секунд. Фінальні статуси завдання: `done`, `error`, `stopped`; автопостингу: `completed`, `error` (а `paused` — до явного `start`).
2. **`409` — не помилка мережі.** Це «дія вже виконана або неможлива зараз»: прочитайте поточний стан (`GET`) і дійте відповідно. Не повторюйте той самий запит у циклі.
3. **`404` на існуючий ID** означає, що об'єкт належить іншому користувачу. Не намагайтеся його обійти.
4. **`403`** — ресурс лише для адміністратора. Повідомте користувача, що потрібні права адміна.
5. **Реальні дії.** `POST /autopost/{id}/test/` і `start` публікують у Pinterest **по-справжньому**; `POST /autopost-uniqueness/{id}/test/` витрачає запит до Groq. Виконуйте лише за явним наміром користувача.
6. **Видалення незворотне.** `DELETE` завдання видаляє всі його піни й автопостинг. Перепитуйте користувача.
7. **Секрети.** Не показуйте користувачу повні cookies, паролі проксі, API-ключі з `/api/uniqueness/`. Для ключів Groq використовуйте `api_key_preview`.
8. **Великі списки.** Завжди фільтруйте `/results/` через `task_id`. Для черги використовуйте `limit` і `status`.
9. **Часткові помилки.** `done` з непорожнім `error_message` = успіх із застереженням — повідомте користувача, скільки пінів не оброблено.
10. **Зміна налаштувань запущеного завдання** не впливає на поточний запуск — потрібен `restart` після завершення або `stop`.
11. **Дати в UTC.** Перед показом користувачу переводьте в його часову зону.

---

## 15. Швидкий перелік ендпоінтів

| Метод | Шлях | Хто | Призначення |
|---|---|---|---|
| POST | `/api/auth/token/` | всі | Отримати токен |
| GET | `/api/tasks/` | user | Список завдань |
| POST | `/api/tasks/` | user | Створити і запустити завдання |
| GET | `/api/tasks/{id}/` | user | Статус і прогрес |
| PUT / PATCH | `/api/tasks/{id}/` | user | Змінити завдання |
| DELETE | `/api/tasks/{id}/` | user | Видалити завдання з результатами |
| POST | `/api/tasks/{id}/stop/` | user | Зупинити |
| POST | `/api/tasks/{id}/restart/` | user | Перезапустити |
| GET | `/api/results/?task_id=` | user | Піни завдання |
| GET | `/api/results/{id}/` | user | Один пін |
| GET | `/api/autopost/?task_id=` | user | Налаштування автопостингу |
| POST | `/api/autopost/` | user | Створити налаштування |
| GET | `/api/autopost/{id}/` | user | Статус і прогрес автопостингу |
| PUT / PATCH | `/api/autopost/{id}/` | user | Змінити налаштування |
| DELETE | `/api/autopost/{id}/` | user | Видалити налаштування і чергу |
| POST | `/api/autopost/{id}/start/` | user | Запустити / продовжити |
| POST | `/api/autopost/{id}/stop/` | user | Пауза |
| POST | `/api/autopost/{id}/test/` | user | Опублікувати один пін зараз |
| GET | `/api/autopost/{id}/queue/` | user | Черга постів |
| GET / POST | `/api/autopost-uniqueness/` | admin | Конфіги Groq |
| GET / PUT / PATCH / DELETE | `/api/autopost-uniqueness/{id}/` | admin | Конфіг Groq |
| POST | `/api/autopost-uniqueness/{id}/test/` | admin | Тест ключа і моделі |
| POST | `/api/autopost-uniqueness/change-model/` | admin | Змінити модель на всіх конфігах |
| GET / POST | `/api/uniqueness/` | admin | Конфіги AI-уникалізації парсингу |
| GET / PUT / PATCH / DELETE | `/api/uniqueness/{id}/` | admin | Конфіг AI-уникалізації |
| GET / POST | `/api/accounts/` | admin | Акаунти Pinterest |
| GET / PUT / PATCH / DELETE | `/api/accounts/{id}/` | admin | Акаунт Pinterest |
| GET / POST | `/api/proxies/` | admin | Проксі |
| GET / PUT / PATCH / DELETE | `/api/proxies/{id}/` | admin | Проксі |
| POST | `/api/proxies/{id}/check_health/` | admin | Перевірити проксі |
