"""
email_fetcher.py — модуль отримання листів через IMAP.
"""
import imaplib
import email
import hashlib
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime

from database import get_setting, save_email, save_emails_bulk, get_connection
from preprocessor import clean_text
from classifier import classify


def _decode_str(value, charset=None):
    if isinstance(value, bytes):
        try:
            return value.decode(charset or "utf-8", errors="replace")
        except Exception:
            return value.decode("utf-8", errors="replace")
    return value or ""


def _decode_header_field(raw):
    parts = decode_header(raw or "")
    return "".join(_decode_str(p, c) for p, c in parts)


def _get_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if "attachment" in str(part.get("Content-Disposition", "")):
                continue
            if ctype == "text/plain" and not body:
                charset = part.get_content_charset() or "utf-8"
                body = part.get_payload(decode=True).decode(charset, errors="replace")
                break
            if ctype == "text/html" and not body:
                charset = part.get_content_charset() or "utf-8"
                body = part.get_payload(decode=True).decode(charset, errors="replace")
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            body = msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            body = ""
    return body


def _parse_date(msg):
    try:
        return parsedate_to_datetime(msg.get("Date", "")).isoformat()
    except Exception:
        return datetime.utcnow().isoformat()


def _make_uid(msg_id, subject, date_str=""):
    """
    Генерує стабільний uid листа.
    Якщо Message-ID є — використовує тільки його (стандартний унікальний ідентифікатор).
    Якщо порожній — додає тему + дату щоб уникнути колізій між різними листами.
    """
    if msg_id and len(msg_id) > 5:
        raw = msg_id.encode("utf-8")
    else:
        raw = f"{subject or 'no-subject'}|{date_str or 'no-date'}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _extract_attachment_text(msg) -> str:
    """
    Витягує текст з .docx / .doc / .txt вкладень листа.
    Повертає об'єднаний текст усіх вкладень (до 3000 символів).
    """
    texts = []
    for part in msg.walk():
        filename = part.get_filename() or ""
        ctype    = part.get_content_type()
        content_disp = str(part.get("Content-Disposition",""))

        # Тільки вкладення
        if "attachment" not in content_disp and not filename:
            continue

        fname_lower = filename.lower()

        try:
            payload = part.get_payload(decode=True)
            if not payload:
                continue

            # .docx
            if fname_lower.endswith(".docx") or                ctype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                import io
                from docx import Document
                doc = Document(io.BytesIO(payload))
                text = " ".join(p.text for p in doc.paragraphs if p.text.strip())
                if text:
                    texts.append(f"[Вкладення {filename}]: {text[:1500]}")

            # .txt
            elif fname_lower.endswith(".txt") or ctype == "text/plain":
                try:
                    text = payload.decode("utf-8", errors="replace")
                except Exception:
                    text = payload.decode("cp1251", errors="replace")
                if text.strip():
                    texts.append(f"[Вкладення {filename}]: {text[:1000]}")

        except Exception as e:
            print(f"[fetcher] Вкладення {filename}: {e}")

    return " ".join(texts)[:3000]


def fetch_and_classify(limit: int = 0, progress_callback=None) -> dict:
    """
    Завантажує листи з IMAP.
    limit=0 → всі листи (нові яких ще немає в БД)
    limit>0 → останні N листів

    progress_callback — функція, що викликається з dict-оновленнями стану:
      {"phase": "...", "current": N, "total": N, "fetched": N,
       "saved": N, "skipped": N, "errors": N, "last_subject": "..."}
    Викликається на ключових етапах і після кожного листа.
    """
    stats = {"fetched": 0, "saved": 0, "skipped": 0, "errors": 0}

    def _emit(**kwargs):
        """Безпечно викликає progress_callback з поточним станом."""
        if progress_callback is None:
            return
        try:
            payload = {
                "current": stats["fetched"],
                "total": stats.get("total_on_server", 0),
                "saved": stats["saved"],
                "skipped": stats["skipped"],
                "errors": stats["errors"],
            }
            payload.update(kwargs)
            progress_callback(payload)
        except Exception:
            pass  # колбек не має блокувати синхронізацію

    _emit(phase="connecting", message="Підключення до сервера…")

    imap_host  = get_setting("imap_host",  "imap.gmail.com")
    imap_port  = int(get_setting("imap_port", "993"))
    email_user = get_setting("email_user", "")
    email_pass = get_setting("imap_pass",  "")

    if not email_user or not email_pass:
        stats["error_msg"] = "Email або пароль не налаштовано. Заповніть Налаштування."
        return stats

    try:
        mail = imaplib.IMAP4_SSL(imap_host, imap_port)
        mail.login(email_user, email_pass)
        mail.select("INBOX")

        _, data = mail.search(None, "ALL")
        all_uids = data[0].split()

        # Визначаємо ліміт: 0 = всі
        fetch_limit = int(get_setting("fetch_limit", "0"))
        effective   = limit or fetch_limit
        if effective > 0:
            all_uids = all_uids[-effective:]

        stats["total_on_server"] = len(all_uids)
        _emit(phase="scanning", message=f"Знайдено {len(all_uids)} листів на сервері, починаю обробку…")

        # Завантажуємо список вже наявних UID з БД
        with get_connection() as conn:
            existing = {r[0] for r in conn.execute("SELECT uid FROM emails").fetchall()}

        # Буфер для пакетних вставок у БД — значно швидше за по одному
        BATCH_SIZE = 25
        buffer = []

        def _flush_buffer():
            if not buffer:
                return
            try:
                save_emails_bulk(buffer)
            except Exception as ex:
                print(f"[fetcher] Помилка пакетної вставки: {ex}")
                # Резервний шлях: по одному
                for r in buffer:
                    try:
                        save_email(**r)
                    except Exception as ex2:
                        print(f"[fetcher] Резервна вставка провалилась: {ex2}")
            buffer.clear()

        for uid_bytes in reversed(all_uids):
            try:
                stats["fetched"] += 1
                _emit(phase="running")

                # Спочатку лише заголовки — щоб перевірити чи є в БД
                _, hdata = mail.fetch(uid_bytes, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT DATE)])")
                raw_h   = hdata[0][1] if hdata and hdata[0] else b""
                msg_h   = email.message_from_bytes(raw_h)
                msg_id  = msg_h.get("Message-ID", "").strip()
                subj_h  = _decode_header_field(msg_h.get("Subject", ""))
                date_h  = msg_h.get("Date", "").strip()
                uid     = _make_uid(msg_id, subj_h, date_h)

                if uid in existing:
                    stats["skipped"] += 1
                    _emit(phase="running")
                    continue

                # Тепер завантажуємо повний лист
                _, msg_data = mail.fetch(uid_bytes, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    _emit(phase="running")
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                subject = _decode_header_field(msg.get("Subject", ""))
                sender  = _decode_header_field(msg.get("From", ""))
                body    = _get_body(msg)
                attach  = _extract_attachment_text(msg)
                if attach:
                    body = body + "\n\n" + attach
                date    = _parse_date(msg)
                real_uid = _make_uid(msg.get("Message-ID", "").strip(), subject, msg.get("Date","").strip())

                category, confidence = classify(subject, body, sender=sender)

                # Override: moodle.chnu.edu.ua → завжди категорія Moodle
                if "moodle" in sender.lower() or "moodle" in subject.lower():
                    category, confidence = "Moodle", 0.99

                buffer.append({
                    "uid":        real_uid,
                    "sender":     sender,
                    "subject":    subject,
                    "body":       body[:5000],
                    "date":       date,
                    "category":   category,
                    "confidence": confidence,
                })
                existing.add(real_uid)
                stats["saved"] += 1
                print(f"[fetcher] В черзі: {subject[:50]} | {category} ({confidence:.0%})")
                _emit(phase="running", last_subject=subject[:80], last_category=category)

                # Скидаємо батч, коли набрали BATCH_SIZE
                if len(buffer) >= BATCH_SIZE:
                    _flush_buffer()

            except Exception as e:
                stats["errors"] += 1
                print(f"[fetcher] Помилка: {e}")
                _emit(phase="running")

        # Фінальний скид буфера
        _flush_buffer()

        mail.logout()
        print(f"[fetcher] Готово: перевірено={stats['fetched']} збережено={stats['saved']} пропущено={stats['skipped']} помилок={stats['errors']}")
        _emit(phase="done", message=f"Готово: +{stats['saved']} нових")

    except imaplib.IMAP4.error as e:
        stats["error_msg"] = f"IMAP: {e}"
        print(f"[fetcher] IMAP помилка: {e}")
        _emit(phase="error", message=f"IMAP: {e}")
    except Exception as e:
        stats["error_msg"] = str(e)
        print(f"[fetcher] Помилка: {e}")
        _emit(phase="error", message=str(e))

    return stats
