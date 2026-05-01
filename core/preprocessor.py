"""
preprocessor.py — модуль попередньої обробки тексту.

Кроки обробки:
  1. Нижній регістр
  2. Видалення HTML-тегів
  3. Видалення спецсимволів, цифр, URL
  4. Токенізація
  5. Видалення стоп-слів (українська + англійська)
  6. Злиття токенів назад у рядок
"""
import re


# Стоп-слова для української мови (базовий набір)
UA_STOPWORDS = {
    "і", "в", "на", "що", "як", "це", "та", "але", "або", "з", "до",
    "по", "про", "за", "від", "при", "між", "через", "без", "під",
    "над", "після", "якщо", "коли", "де", "яке", "який", "яка",
    "він", "вона", "вони", "ми", "ви", "я", "ти", "не", "ні", "так",
    "також", "ще", "вже", "тільки", "дуже", "більш", "менш", "може",
    "є", "був", "була", "були", "буде", "будуть", "має", "мають",
    "для", "щоб", "тому", "тоді", "потім", "зараз", "тут", "там",
    "всі", "кожен", "будь", "інший", "цей", "той", "свій",
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "it", "its",
    "this", "that", "these", "those", "i", "you", "he", "she", "we",
    "they", "me", "him", "her", "us", "them", "our", "your", "their",
}


def remove_html(text: str) -> str:
    """Видаляє HTML-теги."""
    return re.sub(r"<[^>]+>", " ", text)


def remove_urls(text: str) -> str:
    """Видаляє URL-адреси."""
    return re.sub(r"https?://\S+|www\.\S+", " ", text)


def remove_email_headers(text: str) -> str:
    """Прибирає типові заголовки листа (From:, To:, Subject: тощо)."""
    lines = text.splitlines()
    clean = []
    for line in lines:
        if re.match(r"^(From|To|Cc|Date|Subject|Sent|Reply-To)\s*:", line, re.I):
            continue
        clean.append(line)
    return "\n".join(clean)


def clean_text(text: str) -> str:
    """Повна очистка тексту."""
    if not text:
        return ""

    text = remove_email_headers(text)
    text = remove_html(text)
    text = remove_urls(text)

    # Нижній регістр
    text = text.lower()

    # Тільки літери (кирилиця + латиниця), пробіли
    text = re.sub(r"[^а-яіїєґёa-z\s]", " ", text)

    # Токенізація — розбиваємо на слова
    tokens = text.split()

    # Видалення стоп-слів і дуже коротких токенів (< 2 символи)
    tokens = [t for t in tokens if t not in UA_STOPWORDS and len(t) > 1]

    return " ".join(tokens)


def preprocess(subject: str, body: str) -> str:
    """
    Об'єднує тему та тіло листа, виконує повну обробку.
    Тема важливіша — повторюємо її 3 рази для підсилення ваги.
    """
    combined = f"{subject} {subject} {subject} {body}"
    return clean_text(combined)
