"""
gmail_fetcher.py — отримання листів через Gmail API (OAuth).
Оптимізована версія для безкоштовного хостингу.
"""
import os
import time
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests

from database import (save_emails_bulk, get_setting, get_user_by_id,
                      update_user_tokens, get_user_uids)
from spam_filter import check as detect_spam


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE   = "https://gmail.googleapis.com/gmail/v1"


def _refresh_access_token(user: dict) -> str | None:
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
    expiry = user.get("token_expiry")
    if expiry:
        try:
            exp = datetime.fromisoformat(expiry).timestamp()
            if time.time() < exp - 60:
                return user.get("access_token")
        except Exception:
            pass
    return _refresh_access_token(user)


def _api_get(session: requests.Session, token: str, path: str, params=None):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GMAIL_API_BASE}{path}"
    r = session.get(url, headers=headers, params=params, timeout=20)
    if r.status_code == 401:
        raise PermissionError("Token expired or invalid")
    r.raise_for_status()
    return r.json()


def _get_header(headers: list, name: str) -> str:
    name_low = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_low:
            return h.get("value", "")
    return ""


def fetch_and_classify(user_id: int, limit: int = 0, progress_callback=None) -> dict:
    """
    Оптимізації:
    - format=metadata замість full (без важкого тіла) - 5-10x швидше
    - snippet (~200 символів) як body для класифікації
    - HTTP-сесія з keep-alive
    - Skip duplicates по UID
    - Прогрес на кожен лист
    - Збереження батчами по 10 - юзер бачить листи раніше
    """
    stats = {
        "total_on_server": 0,
        "fetched":         0,
        "skipped":         0,
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
        _emit(phase="error", message=stats["error_msg"])
        return stats

    token = _get_valid_token(user)
    if not token:
        stats["error_msg"] = "Не вдалося отримати токен. Увійдіть знову через Google."
        _emit(phase="error", message=stats["error_msg"])
        return stats

    fetch_limit = limit if limit > 0 else int(get_setting("fetch_limit", "25"))
    fetch_limit = max(1, min(fetch_limit, 200))

    session = requests.Session()

    try:
        _emit(phase="scanning", message="Запит списку листів…")
        list_resp = _api_get(session, token, "/users/me/messages", params={
            "maxResults": fetch_limit,
            "labelIds":   "INBOX",
        })
        messages = list_resp.get("messages", [])
        stats["total_on_server"] = len(messages)

        existing_uids = get_user_uids(user_id)
        new_messages = [m for m in messages
                        if f"gmail_{m['id']}" not in existing_uids]
        stats["skipped"] = len(messages) - len(new_messages)

        if not new_messages:
            _emit(phase="done",
                  message=f"Все актуально (пропущено {stats['skipped']})")
            return stats

        _emit(phase="processing",
              message=f"Нових: {len(new_messages)}, обробляю…",
              total=len(new_messages), current=0)

        # Прогріваємо класифікатор один раз
        from classifier import classify

        rows_to_save = []
        for idx, m in enumerate(new_messages):
            try:
                msg = _api_get(session, token,
                               f"/users/me/messages/{m['id']}",
                               params={
                                   "format": "metadata",
                                   "metadataHeaders": ["Subject", "From", "Date"],
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

                body = msg.get("snippet", "")

                spam_result = detect_spam(sender, subject, body)
                if spam_result:
                    category, confidence = spam_result[0], spam_result[1]
                    stats["spam_filtered"] += 1
                else:
                    cat, conf = classify(subject, body)
                    category, confidence = cat, conf

                rows_to_save.append({
                    "uid":        f"gmail_{m['id']}",
                    "sender":     sender,
                    "subject":    subject,
                    "body":       body[:5000],
                    "date":       date_iso,
                    "category":   category,
                    "confidence": confidence,
                })
                stats["fetched"] += 1

                _emit(phase="processing",
                      message=f"Оброблено {idx+1}/{len(new_messages)}",
                      current=idx+1, total=len(new_messages),
                      last_subject=subject[:80],
                      last_category=category)

                if len(rows_to_save) >= 10:
                    save_emails_bulk(rows_to_save, user_id=user_id)
                    rows_to_save = []

            except PermissionError:
                token = _refresh_access_token(user)
                if not token:
                    stats["error_msg"] = "Авторизація закінчилась."
                    break
            except Exception:
                stats["errors"] += 1
                continue

        if rows_to_save:
            save_emails_bulk(rows_to_save, user_id=user_id)

        _emit(phase="done",
              message=f"Готово: +{stats['fetched']} нових")

    except PermissionError:
        stats["error_msg"] = "Сесія Google закінчилась — увійдіть знову."
        _emit(phase="error", message=stats["error_msg"])
    except requests.HTTPError as e:
        stats["error_msg"] = f"Помилка Gmail API: {e}"
        _emit(phase="error", message=stats["error_msg"])
    except Exception as e:
        stats["error_msg"] = f"Помилка: {e}"
        _emit(phase="error", message=stats["error_msg"])
    finally:
        session.close()

    return stats
