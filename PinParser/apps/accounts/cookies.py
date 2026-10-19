"""
Нормалізація cookies Pinterest-акаунта до формату Playwright (context.add_cookies).

Приймає будь-який поширений формат:
  * Playwright / Puppeteer: [{"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}]
  * розширення браузера (Cookie-Editor, EditThisCookie, J2TEAM): "expirationDate", "hostOnly",
    "session", "sameSite": "no_restriction" / "unspecified", "storeId", "id" ...
  * Selenium: "expiry"
  * Playwright storage_state: {"cookies": [...], "origins": [...]}
  * словник {"name": "value", ...}
  * рядок заголовка: "a=b; c=d" або "Cookie: a=b; c=d"
  * файл cookies.txt (Netscape), у т.ч. з префіксом "#HttpOnly_"
  * усе перелічене, передане JSON-рядком

Результат — список словників лише з ключами, які приймає Playwright, з правильними типами.
"""
import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

DEFAULT_DOMAIN = ".pinterest.com"
SESSION_COOKIE = "_pinterest_sess"
SAME_SITE_MAP = {
    "strict": "Strict",
    "lax": "Lax",
    "none": "None",
    "no_restriction": "None",
}


class CookieFormatError(ValueError):
    pass


def normalize_cookies(raw) -> list[dict]:
    items = _to_items(raw)
    cookies = [c for c in (_normalize_one(item) for item in items) if c]

    # Прибираємо прострочені (Playwright їх все одно не збереже)
    now = time.time()
    cookies = [c for c in cookies if c["expires"] == -1 or c["expires"] > now]

    # Експорт «усіх сайтів» з розширення: лишаємо тільки Pinterest, якщо вони є
    pinterest = [c for c in cookies if "pinterest." in c["domain"]]
    if pinterest:
        cookies = pinterest

    # Дублі (name, domain, path) — перемагає останній
    unique = {}
    for cookie in cookies:
        unique[(cookie["name"], cookie["domain"], cookie["path"])] = cookie
    cookies = list(unique.values())

    if not cookies:
        raise CookieFormatError(
            "Не знайдено жодної дійсної cookie. Вставте експорт cookies з браузера "
            "(JSON із розширення, рядок «name=value; ...» або cookies.txt)."
        )
    return cookies


def has_session_cookie(cookies) -> bool:
    return any(isinstance(c, dict) and c.get("name") == SESSION_COOKIE for c in cookies or [])


# ---------- розбір вхідних даних ----------

def _to_items(raw) -> list:
    if raw is None:
        return []
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "ignore")

    if isinstance(raw, str):
        text = raw.strip().lstrip("﻿").strip()
        if not text:
            return []
        if text[0] in "[{":
            try:
                return _to_items(json.loads(text))
            except json.JSONDecodeError as e:
                raise CookieFormatError(f"Некоректний JSON: {e}")
        if _looks_like_netscape(text):
            return _parse_netscape(text)
        return _parse_header(text)

    if isinstance(raw, dict):
        if isinstance(raw.get("cookies"), list):        # storage_state
            return raw["cookies"]
        if _key(raw, "name") is not None and _key(raw, "value") is not None:
            return [raw]                                 # одна cookie
        return [{"name": k, "value": v} for k, v in raw.items()]  # {name: value}

    if isinstance(raw, list):
        items = []
        for entry in raw:
            if isinstance(entry, dict):
                items.append(entry)
            elif isinstance(entry, str):
                items.extend(_parse_header(entry))
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                items.append({"name": entry[0], "value": entry[1]})
        return items

    raise CookieFormatError(f"Непідтримуваний формат cookies: {type(raw).__name__}")


def _parse_header(text: str) -> list[dict]:
    if text.lower().startswith("cookie:"):
        text = text[len("cookie:"):]
    items = []
    for part in text.replace("\n", ";").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        if name.strip():
            items.append({"name": name.strip(), "value": value.strip()})
    return items


def _looks_like_netscape(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    return any(line.count("\t") >= 6 for line in lines)


def _parse_netscape(text: str) -> list[dict]:
    items = []
    for line in text.splitlines():
        http_only = False
        if line.startswith("#HttpOnly_"):
            http_only = True
            line = line[len("#HttpOnly_"):]
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, include_subdomains, path, secure, expires, name, value = parts[:7]
        items.append({
            "name": name,
            "value": value.rstrip("\r\n"),
            "domain": domain,
            "hostOnly": not _to_bool(include_subdomains),
            "path": path,
            "secure": _to_bool(secure),
            "expires": expires,
            "httpOnly": http_only,
        })
    return items


# ---------- нормалізація однієї cookie ----------

def _key(item: dict, *names):
    """Значення за ключем без урахування регістру (Name / name / NAME)."""
    lowered = {str(k).lower(): v for k, v in item.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _normalize_one(item: dict) -> dict | None:
    name = _key(item, "name")
    value = _key(item, "value")
    if name is None or str(name).strip() == "" or value is None:
        return None

    domain = str(_key(item, "domain", "host") or DEFAULT_DOMAIN).strip()
    if "://" in domain:  # хтось вставив url замість домену
        domain = domain.split("://", 1)[1].split("/", 1)[0]
    host_only = _to_bool(_key(item, "hostOnly"))
    if host_only and domain.startswith("."):
        domain = domain[1:]

    path = str(_key(item, "path") or "/").strip() or "/"
    if not path.startswith("/"):
        path = "/" + path

    secure = _to_bool(_key(item, "secure"), default=True)
    same_site = _same_site(_key(item, "sameSite", "same_site"))
    if same_site == "None":
        secure = True  # Chromium відкидає SameSite=None без Secure

    return {
        "name": str(name).strip(),
        "value": str(value).strip(),
        "domain": domain,
        "path": path,
        "expires": _expires(item),
        "httpOnly": _to_bool(_key(item, "httpOnly", "http_only")),
        "secure": secure,
        "sameSite": same_site,
    }


def _expires(item: dict) -> float:
    if _to_bool(_key(item, "session")):
        return -1
    raw = _key(item, "expires", "expirationDate", "expiry", "expiration")
    if raw in (None, "", "Session", "session"):
        return -1

    if isinstance(raw, str):
        text = raw.strip()
        try:
            raw = float(text)
        except ValueError:
            moment = _parse_date(text)
            return moment.timestamp() if moment else -1

    try:
        value = float(raw)
    except (TypeError, ValueError):
        return -1
    if value <= 0:
        return -1
    if value > 1e11:  # мілісекунди
        value /= 1000
    return round(value, 3)


def _parse_date(text: str):
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            moment = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _same_site(raw) -> str:
    if raw is None:
        return "Lax"
    return SAME_SITE_MAP.get(str(raw).strip().lower(), "Lax")


def _to_bool(raw, default=False) -> bool:
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw != 0
    return str(raw).strip().lower() in ("true", "1", "yes", "y", "on")
