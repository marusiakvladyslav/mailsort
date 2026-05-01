import os

# Корінь проекту — на рівень вище від core/
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─── Email (IMAP) ────────────────────────────────────────────────
IMAP_HOST   = os.getenv("IMAP_HOST",  "imap.gmail.com")
IMAP_PORT   = int(os.getenv("IMAP_PORT", 993))
EMAIL_USER  = os.getenv("EMAIL_USER",  "")
EMAIL_PASS  = os.getenv("EMAIL_PASS",  "")
FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", 50))

# ─── Paths ───────────────────────────────────────────────────────
BASE_DIR   = _BASE
DB_PATH    = os.path.join(_BASE, "data",   "emails.db")
MODEL_PATH = os.path.join(_BASE, "models", "classifier.pkl")
VECT_PATH  = os.path.join(_BASE, "models", "vectorizer.pkl")

# ─── Категорії ───────────────────────────────────────────────────
CATEGORIES = [
    "Новини та розсилки",
    "Moodle",
    "Навчальний процес",
    "Адміністрація",
    "Заходи та події",
]

LABEL_SPAM    = "Спам / Реклама"
LABEL_UNKNOWN = "Невизначено"
ALL_LABELS    = CATEGORIES + [LABEL_SPAM, LABEL_UNKNOWN]

# ─── Спам-фільтр ─────────────────────────────────────────────────
SPAM_DOMAINS = {
    "pinterest.com", "pinterest.co.uk",
    "instagram.com", "facebookmail.com",
    "twitter.com", "twitteremail.com",
    "linkedin.com", "notifications.linkedin.com",
    "youtube.com", "accounts.youtube.com",
    "amazon.com", "amazon.co.uk", "amazon.de",
    "aliexpress.com", "alibaba.com",
    "booking.com", "airbnb.com",
    "olx.ua", "rozetka.com.ua", "prom.ua",
    "privatbank.ua", "monobank.ua",
    "nova-poshta.ua", "novaposhta.ua",
    "ukrposhta.ua",
    "tiktok.com", "snapchat.com",
    "mailchimp.com", "sendgrid.net",
    "info@prometheus.org.ua", "prometheus.org.ua",
    "notification", "noreply", "no-reply",
}

SPAM_SUBJECT_KEYWORDS = [
    "unsubscribe", "відписатись", "відписатися",
    "знижка", "розпродаж", "акція", "sale", "discount", "offer",
    "безкоштовно", "free", "виграш", "prize", "winner",
    "click here", "натисніть тут",
    "підтвердіть підписку", "confirm subscription",
    "your order", "ваше замовлення",
    "tracking number", "номер відстеження",
]

# ─── Правила відправника → категорія ─────────────────────────────
CATEGORY_SENDERS = {
    "noreply@moodle.chnu.edu.ua": "Moodle",
    "moodle@chnu.edu.ua":         "Moodle",
    "moodle.chnu.edu.ua":         "Moodle",
    "@moodle.":                   "Moodle",
}

CATEGORY_SENDER_LIKE = {
    "Moodle": ["%moodle.chnu.edu.ua%", "%@moodle.%"],
}

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-prod")
