"""
gmail_fetcher.py — отримання листів через Gmail API (OAuth).
Замінює email_fetcher.py для multi-user системи.
"""
import os
import time
import base64
import re
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests

from database import (save_emails_bulk, get_setting, get_user_by_id,
                      update_user_tokens)
from preprocessor import preprocess
from spam_filter import detect_spam


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE   = "https://gmail.googleapis.com/gmail/v1"


def _refresh_access_token(user: dict) -> str | None:
    """Оновлює access_token через refresh_token. Повертає новий token або None."""
    refresh = user.get("refresh_token")
    if not refresh:
        return None

    client_id     = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None

    try:
        resp = requests.post(GOOGLE_TOKEN_URL, data={
            "client_id":     client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type":    "refresh_token",
        }, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        access_token = data.get("access_token")
        expires_in   = int(data.get("expires_in", 3600))
        expiry_iso   = datetime.utcfromtimestamp(time.time() + expires_in).isoformat()
        update_user_tokens(user["id"], access_token, expiry_iso)
        return access_token
    except Exception:
        return None


def _get_valid_token(user: dict) -> str | None:
    """Повертає валідний access_token (оновлює якщо протермінований)."""
    expiry = user.get("token_expiry")
    if expiry:
        try:
            exp = datetime.fromisoformat(expiry).timestamp()
            if time.time() < exp - 60:
                return user.get("access_token")
        except Exception:
            pass
    # Інакше — оновлюємо
    return _refresh_access_token(user)


def _api_get(token: str, path: str, params=None):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GMAIL_API_BASE}{path}"
    r = requests.get(url, headers=headers, params=params, timeout=30)
    if r.status_code == 401:
        raise PermissionError("Token expired or invalid")
    r.raise_for_status()
    return r.json()


def _decode_body(body_data: str) -> str:
    if not body_data:
        return ""
    try:
        return base64.urlsafe_b64decode(body_data + "===").decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _extract_text_from_payload(payload: dict) -> str:
    """Рекурсивно витягує text/plain з payload Gmail API."""
    if not payload:
        return ""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    parts = payload.get("parts", [])

    if mime == "text/plain" and body.get("data"):
        return _decode_body(body["data"])

    if mime == "text/html" and body.get("data") and not parts:
        html = _decode_body(body["data"])
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    text = ""
    for p in parts:
        text += _extract_text_from_payload(p) + "\n"
    return text.strip()


def _get_header(headers: list, name: str) -> str:
    name_low = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_low:
            return h.get("value", "")
    return ""


def fetch_and_classify(user_id: int, limit: int = 50, progress_callback=None) -> dict:
    """
    Отримує листи з Gmail через API і класифікує їх.
    user_id: ID користувача в локальній БД (звідти беремо OAuth токени).
    Повертає словник зі статистикою.
    """
    stats = {
        "total_on_server": 0,
        "fetched":         0,
        "spam_filtered":   0,
        "errors":          0,
        "error_msg":       "",
    }

    def _emit(**kw):
        if progress_callback:
            try:
                progress_callback({**stats, **kw})
            except Exception:
                pass

    _emit(phase="connecting", message="Підключення до Gmail…")

    user = get_user_by_id(user_id)
    if not user:
        stats["error_msg"] = "Користувач не знайдений."
        return stats

    token = _get_valid_token(user)
    if not token:
        stats["error_msg"] = "Не вдалося отримати токен. Увійдіть знову через Google."
        return stats

    # Беремо ліміт з налаштувань або переданий
    fetch_limit = limit if limit > 0 else int(get_setting("fetch_limit", "50"))
    fetch_limit = max(1, min(fetch_limit, 500))  # обмежуємо для безкоштовного хостингу

    try:
        _emit(phase="scanning", message="Запит списку листів…")
        # Отримуємо список ID листів з INBOX
        list_resp = _api_get(token, "/users/me/messages", params={
            "maxResults": fetch_limit,
            "labelIds":   "INBOX",
        })
        messages = list_resp.get("messages", [])
        stats["total_on_server"] = len(messages)
        _emit(phase="scanning", message=f"Знайдено {len(messages)} листів, обробляю…")

        # Імпортуємо класифікатор з lazy
        from classifier import classify

        rows_to_save = []
        for idx, m in enumerate(messages):
            try:
                msg = _api_get(token, f"/users/me/messages/{m['id']}", params={
                    "format": "full",
                })
                payload = msg.get("payload", {})
                headers = payload.get("headers", [])

                subject = _get_header(headers, "Subject")
                sender  = _get_header(headers, "From")
                date_h  = _get_header(headers, "Date")
                try:
                    date_iso = parsedate_to_datetime(date_h).isoformat() if date_h else ""
                except Exception:
                    date_iso = ""

                body = _extract_text_from_payload(payload)
                if not body:
                    body = msg.get("snippet", "")

                # Спам?
                is_spam, _reason = detect_spam(sender, subject, body)
                if is_spam:
                    category   = "Спам / Реклама"
                    confidence = 1.0
                    stats["spam_filtered"] += 1
                else:
                    cat, conf = classify(subject, body)
                    category   = cat
                    confidence = conf

                rows_to_save.append({
                    "uid":        f"gmail_{m['id']}",
                    "sender":     sender,
                    "subject":    subject,
                    "body":       body[:50000],  # обмежуємо розмір
                    "date":       date_iso,
                    "category":   category,
                    "confidence": confidence,
                })
                stats["fetched"] += 1

                if (idx + 1) % 10 == 0:
                    _emit(phase="processing",
                          message=f"Оброблено {idx+1}/{len(messages)}")
            except PermissionError:
                token = _refresh_access_token(user)
                if not token:
                    stats["error_msg"] = "Авторизація закінчилась."
                    break
            except Exception as e:
                stats["errors"] += 1
                continue

        if rows_to_save:
            _emit(phase="saving", message=f"Збереження {len(rows_to_save)} листів…")
            save_emails_bulk(rows_to_save, user_id=user_id)

        _emit(phase="done", message="Готово")

    except PermissionError:
        stats["error_msg"] = "Сесія Google закінчилась — увійдіть знову."
    except requests.HTTPError as e:
        stats["error_msg"] = f"Помилка Gmail API: {e}"
    except Exception as e:
        stats["error_msg"] = f"Помилка: {e}"

    return stats
