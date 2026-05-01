"""
spam_filter.py — дворівневий спам-фільтр з аналізом вмісту.

Рівні перевірки:
  1. Домен відправника (чорний список)
  2. Ключові слова в темі
  3. Аналіз вмісту листа (body scoring)
"""
import re
from config import SPAM_DOMAINS, SPAM_SUBJECT_KEYWORDS, LABEL_SPAM

# ── Ознаки спаму у вмісті листа ──────────────────────────────────
BODY_SPAM_PATTERNS = [
    # Маркетинг та розсилки
    (r"unsubscribe|відписат",           2),
    (r"click here|натисніть тут",        2),
    (r"view in browser|переглянути.*браузер", 1),
    (r"this email was sent to",          2),
    (r"you('re| are) receiving this",    2),
    (r"update.*preference|manage.*subscription", 2),
    # Реклама та акції
    (r"знижк[аи]|розпродаж|акці[яї]|sale|discount|offer", 2),
    (r"безкоштовн|free.*shipping|безплатн",               1),
    (r"limited time|тільки сьогодні|only today",          2),
    (r"buy now|купити зараз|order now",                    2),
    (r"best price|найкраща ціна|lowest price",             1),
    # Фінансові схеми / фішинг
    (r"verify.*account|підтвердіть.*акаунт",               3),
    (r"your account.*suspended|акаунт.*заблоковано",       3),
    (r"click.*link.*below|перейдіть.*посилання",           2),
    (r"password.*reset|скидання.*пароля",                  1),
    (r"won.*prize|виграли|congratulations.*winner",        3),
    # Соцмережі та нотифікації
    (r"commented on your|прокоментував",                   2),
    (r"tagged you|позначив вас",                           2),
    (r"new follower|новий підписник",                      2),
    (r"friend request|запит на дружбу",                    2),
    # Доставка та замовлення
    (r"your order|ваше замовлення|order.*confirm",         2),
    (r"tracking number|трек.номер|номер відстеження",      2),
    (r"package.*deliver|доставк.*посилк",                  1),
    # Технічні ознаки HTML-листів
    (r"<table|<td|<tr|<img",                               1),
    (r"font-family|font-size|background-color",            1),
    (r"padding:\s*\d+px|margin:\s*\d+px",                  1),
]

# Ознаки університетського листа (знижують spam score)
UNI_PATTERNS = [
    (r"університет|university|кафедр|факультет",   -4),
    (r"студент|викладач|ректор|декан|проректор",   -4),
    (r"навчальн|освіт|семестр|залік|іспит",        -3),
    (r"наук|дослідж|конференц|грант|дисертац",     -3),
    (r"вступ|абітурієнт|прийом.*документ",         -3),
    (r"розклад|аудиторі|лекці|практик",            -2),
    (r"chnu|буковин|чернівец",                     -5),
]

SPAM_BODY_THRESHOLD = 5   # сума балів вище якої → спам


def _extract_domain(sender: str) -> str:
    m = re.search(r'@([\w.\-]+)', sender.lower())
    return m.group(1) if m else ""


def _load_user_rules() -> tuple[set, list]:
    try:
        from database import get_spam_rules
        rules = get_spam_rules()
        domains  = {r["value"] for r in rules if r["rule_type"] == "domain"}
        keywords = [r["value"] for r in rules if r["rule_type"] == "keyword"]
        return domains, keywords
    except Exception:
        return set(), []


def _domain_is_spam(domain: str, extra_domains: set) -> bool:
    all_domains = SPAM_DOMAINS | extra_domains
    if not domain:
        return False
    for d in all_domains:
        if domain == d or domain.endswith("." + d):
            return True
        if d in ("noreply", "no-reply", "notification"):
            local = domain.split(".")[0]
            if d.replace("-", "") in local.replace("-", ""):
                return True
    return False


def _subject_is_spam(subject: str, extra_kw: list) -> bool:
    s = subject.lower()
    return any(kw.lower() in s for kw in list(SPAM_SUBJECT_KEYWORDS) + extra_kw)


def _is_uni_sender(sender: str, domain: str) -> bool:
    return any(domain.endswith(t) for t in (".edu.ua", ".edu", ".ac.uk")) \
           or "university" in domain \
           or any(w in sender.lower() for w in ("університет", "chnu", "буковин"))


def score_body(body: str) -> int:
    """
    Повертає spam-score по вмісту листа.
    Позитивні значення → ознаки спаму.
    Негативні → ознаки університетського листа.
    """
    if not body:
        return 0
    text = body.lower()
    score = 0
    for pattern, weight in BODY_SPAM_PATTERNS:
        if re.search(pattern, text):
            score += weight
    for pattern, weight in UNI_PATTERNS:
        if re.search(pattern, text):
            score += weight   # weight від'ємний
    return score


def check(sender: str, subject: str,
          body: str = "") -> tuple[str, float] | None:
    """
    Повертає (LABEL_SPAM, confidence) або None якщо лист чистий.
    """
    user_domains, user_keywords = _load_user_rules()
    domain = _extract_domain(sender)
    is_uni = _is_uni_sender(sender, domain)

    # Правило 1: домен у чорному списку → точно спам
    if _domain_is_spam(domain, user_domains):
        return LABEL_SPAM, 0.99

    # Правило 2: підозріла тема (не університетський відправник)
    if not is_uni and _subject_is_spam(subject, user_keywords):
        return LABEL_SPAM, 0.92

    # Правило 3: аналіз вмісту (якщо body передано)
    if body and not is_uni:
        spam_score = score_body(body)
        if spam_score >= SPAM_BODY_THRESHOLD:
            # Нормалізуємо confidence: score 5→0.70, 10→0.90, 15+→0.97
            conf = min(0.97, 0.60 + spam_score * 0.025)
            return LABEL_SPAM, round(conf, 2)

    return None
