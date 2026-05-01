"""
chnu_trainer.py — завантажує новини з сайту ЧНУ та перенавчає класифікатор.

Версія 2: покращений парсер + ансамблева модель + char n-gram TF-IDF.

Запуск:
    python chnu_trainer.py              # тихий режим
    python chnu_trainer.py --verbose    # з деталями
"""
import os, sys, json, time, re, argparse
import requests
from bs4 import BeautifulSoup

BASE = "https://www.chnu.edu.ua"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
}

# Категорії сайту ЧНУ → наші категорії
CATEGORY_MAP = {
    "Новини та розсилки": [
        "/novyny/",
        "/novyny/aktualni-novyny/",
        "/novyny/university-news/",
        "/news/",
    ],
    "Навчальний процес": [
        "/novyny/osvitnya-diyalnist/",
        "/novyny/education/",
        "/novyny/osvita/",
    ],
    "Адміністрація": [
        "/novyny/do-obhovoryennya/",
        "/novyny/announcements/",
        "/novyny/vstup/",
    ],
    "Заходи та події": [
        "/novyny/naukova-diyalnist/",
        "/novyny/mizhnarodna-diyalnist/",
        "/novyny/nauka/",
        "/novyny/international/",
    ],
    "Фінанси та стипендії": [
        "/novyny/priyom/",
        "/novyny/admissions/",
        "/novyny/vakansii/",
    ],
    # Moodle — не можна скрапити з chnu.edu.ua,
    # класифікатор навчений на ручних прикладах.
}

EXTRA_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "chnu_training.json")

# Селектори для витягування посилань зі сторінок категорій
LINK_SELECTORS = [
    "article h2 a", "article h3 a", "article h4 a",
    ".news__title a", ".news-list__title a",
    ".views-field-title a", ".field-title a",
    "h2.entry-title a", "h3.entry-title a",
    ".node-title a",
    ".wysiwyg h2 a",
    ".views-row h3 a", ".views-row h2 a",
    "h2 a[href*='novyn']", "h3 a[href*='novyn']",
    "h2 a", "h3 a", "h4 a",
    "a[href*='novyn']",
]

# Селектори основного контенту статті
CONTENT_SELECTORS = [
    ".wysiwyg",
    ".field--name-body",
    ".field-body",
    ".field-name-body",
    ".entry-content",
    "article .content",
    ".article-body",
    ".node__content",
    ".region-content .field",
    "article",
    "main",
    "#content",
]


def fetch(url, timeout=12):
    r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.text


def get_article_links(html, base):
    """Витягує посилання на статті зі сторінки категорії."""
    soup = BeautifulSoup(html, "html.parser")

    # Видаляємо nav/footer щоб не підбирати зайві посилання
    for tag in soup.select("nav, header, footer, script, style, .breadcrumb, aside"):
        tag.decompose()

    links, seen = [], set()

    for sel in LINK_SELECTORS:
        found = soup.select(sel)
        if len(found) < 2:
            continue

        batch = []
        for a in found:
            href = a.get("href", "").strip()
            title = a.get_text(strip=True)
            if len(title) < 8:
                continue
            if href.startswith("/"):
                href = base + href
            if not href.startswith("http") or href in seen:
                continue
            # Пропускаємо якщо це посилання на категорію (надто коротке)
            path = href.replace(base, "")
            segs = [s for s in path.split("/") if s]
            if len(segs) < 2:
                continue
            seen.add(href)
            batch.append({"title": title[:120], "link": href})

        if len(batch) >= 3:
            links.extend(batch)
            break

    return links[:20]


def get_article_text(url):
    """
    Завантажує повний текст статті.
    Пробує: og:description → основний контент → перші абзаци.
    """
    try:
        html = fetch(url, timeout=10)
        soup = BeautifulSoup(html, "html.parser")

        # Open Graph мета-теги
        og_title = ""
        og_desc = ""
        og_t = soup.find("meta", property="og:title")
        if og_t:
            og_title = og_t.get("content", "").strip()
        og_d = soup.find("meta", property="og:description")
        if og_d:
            og_desc = og_d.get("content", "").strip()

        # Основний контент
        content = ""
        for sel in CONTENT_SELECTORS:
            el = soup.select_one(sel)
            if not el:
                continue
            # Видаляємо шуми
            for tag in el.select("nav, aside, script, style, .breadcrumb, .tags, "
                                 ".share-buttons, .social, footer, .pagination"):
                tag.decompose()
            paragraphs = [p.get_text(" ", strip=True) for p in el.find_all("p")]
            text = " ".join(p for p in paragraphs if len(p) > 25)
            if len(text) > 80:
                content = text[:4000]
                break

        # Якщо абзаців немає — беремо весь текст блоку
        if not content:
            for sel in CONTENT_SELECTORS:
                el = soup.select_one(sel)
                if el:
                    t = el.get_text(" ", strip=True)
                    if len(t) > 80:
                        content = t[:4000]
                        break

        # Комбінуємо
        parts = [p for p in [og_title, og_desc, content] if len(p) > 15]
        return " ".join(parts)[:4000] if parts else ""

    except Exception:
        return ""


def scrape_category(category, urls, verbose=False, max_articles=20):
    """Завантажує статті для однієї категорії."""
    examples = []

    for url in urls:
        try:
            if verbose:
                print(f"  Завантаження: {url}")
            html = fetch(url)
            links = get_article_links(html, BASE)

            if not links:
                if verbose:
                    print("    Посилань не знайдено")
                continue

            if verbose:
                print(f"    Знайдено {len(links)} статей")

            for item in links:
                if len(examples) >= max_articles:
                    break

                text = get_article_text(item["link"])
                if not text or len(text) < 30:
                    text = item["title"]

                if len(text) >= 15:
                    examples.append({
                        "text":     text[:3000],
                        "category": category,
                        "source":   item["link"],
                        "title":    item["title"][:100],
                    })
                    if verbose:
                        print(f"    + [{category}] {item['title'][:60]}")

                time.sleep(0.25)

            if examples:
                break

        except Exception as e:
            if verbose:
                print(f"    Помилка {url}: {e}")

    return examples


def retrain(extra_data, verbose=False):
    """
    Перенавчає класифікатор з новими прикладами.
    Версія 2: додає char n-gram модель + ансамбль.
    """
    sys.path.insert(0, os.path.dirname(__file__))
    from classifier import TRAINING_DATA, CONFIDENCE_THRESHOLD
    from preprocessor import preprocess
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import Pipeline, FeatureUnion
    from sklearn.linear_model import LogisticRegression
    from sklearn.svm import LinearSVC
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.naive_bayes import ComplementNB
    from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
    from sklearn.metrics import classification_report
    import numpy as np
    import joblib

    # Базові навчальні дані + нові з ЧНУ
    all_data = list(TRAINING_DATA)
    for item in extra_data:
        if item.get("text") and len(item["text"]) >= 15:
            all_data.append((item["text"], item["category"]))

    if verbose or True:
        print(f"\nДатасет: {len(TRAINING_DATA)} базових + {len(extra_data)} з ЧНУ "
              f"= {len(all_data)} прикладів")

    texts = [preprocess(t, "") for t, _ in all_data]
    labels = [cat for _, cat in all_data]

    # --- Моделі з покращеним TF-IDF (word + char n-gram) ---
    def _word_tfidf():
        return TfidfVectorizer(
            analyzer="word", ngram_range=(1, 2),
            max_features=20_000, sublinear_tf=True, min_df=1,
        )

    def _char_tfidf():
        return TfidfVectorizer(
            analyzer="char_wb", ngram_range=(2, 4),
            max_features=30_000, sublinear_tf=True, min_df=1,
        )

    def _features():
        return FeatureUnion([
            ("word", _word_tfidf()),
            ("char", _char_tfidf()),
        ])

    def _build_lr():
        return Pipeline([
            ("features", _features()),
            ("clf", LogisticRegression(C=5.0, max_iter=1000, solver="lbfgs",
                                        multi_class="multinomial")),
        ])

    def _build_svm():
        return Pipeline([
            ("features", _features()),
            ("clf", CalibratedClassifierCV(LinearSVC(C=1.0, max_iter=2000))),
        ])

    def _build_svm_word():
        """SVM тільки на word n-gram (швидший)."""
        return Pipeline([
            ("tfidf", _word_tfidf()),
            ("clf", CalibratedClassifierCV(LinearSVC(C=2.0, max_iter=2000))),
        ])

    def _build_nb():
        return Pipeline([
            ("tfidf", _word_tfidf()),
            ("clf", ComplementNB(alpha=0.3)),
        ])

    MODELS_V2 = {
        "LR + char+word":    _build_lr,
        "SVM + char+word":   _build_svm,
        "SVM (word)":        _build_svm_word,
        "Naive Bayes":       _build_nb,
    }

    # 5-fold CV для кожної моделі
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    best_name, best_score = None, 0

    for name, builder in MODELS_V2.items():
        try:
            scores = cross_val_score(builder(), texts, labels,
                                     cv=skf, scoring="f1_weighted", n_jobs=-1)
            mean = scores.mean()
            if verbose:
                print(f"  {name:<25} F1={mean:.3f} ± {scores.std():.3f}")
            if mean > best_score:
                best_score, best_name = mean, name
        except Exception as e:
            if verbose:
                print(f"  {name}: помилка — {e}")

    print(f"\nНайкраща модель: {best_name} (F1={best_score:.3f})")

    # Навчаємо на всіх даних і зберігаємо
    pipe = MODELS_V2[best_name]()
    pipe.fit(texts, labels)

    model_path = os.path.join(os.path.dirname(__file__), "models", "classifier.pkl")
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    joblib.dump({
        "pipeline":   pipe,
        "model_name": best_name,
        "trained_on": len(all_data),
        "f1":         best_score,
    }, model_path)
    print(f"Модель збережено: {model_path}")

    # Hold-out тест для звіту
    X_tr, X_te, y_tr, y_te = train_test_split(
        texts, labels, test_size=0.2, random_state=42, stratify=labels)
    pipe2 = MODELS_V2[best_name]()
    pipe2.fit(X_tr, y_tr)
    y_pred = pipe2.predict(X_te)
    print("\nЗвіт по категоріях (hold-out 20%):")
    print(classification_report(y_te, y_pred, zero_division=0))

    return best_score


def load_saved():
    if os.path.exists(EXTRA_DATA_PATH):
        with open(EXTRA_DATA_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_data(data):
    os.makedirs(os.path.dirname(EXTRA_DATA_PATH), exist_ok=True)
    with open(EXTRA_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Збережено {len(data)} прикладів у {EXTRA_DATA_PATH}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--retrain-only", action="store_true",
                        help="Перенавчити на вже збережених даних без завантаження")
    parser.add_argument("--max", type=int, default=20,
                        help="Макс. статей на категорію (default: 20)")
    args = parser.parse_args()
    verbose = args.verbose

    if args.retrain_only:
        data = load_saved()
        if not data:
            print("Немає збережених даних. Запустіть без --retrain-only")
            return
        print(f"Перенавчання на {len(data)} збережених прикладах...")
        retrain(data, verbose=verbose)
        return

    print("=" * 60)
    print("  MailSort — Навчання на новинах ЧНУ  (v2)")
    print("=" * 60)

    all_examples = []

    for category, urls in CATEGORY_MAP.items():
        print(f"\n[{category}]")
        examples = scrape_category(
            category, [BASE + u for u in urls],
            verbose=verbose, max_articles=args.max,
        )
        print(f"  Зібрано: {len(examples)} прикладів")
        all_examples.extend(examples)
        time.sleep(0.5)

    print(f"\n{'=' * 60}")
    print(f"Всього зібрано: {len(all_examples)} прикладів")

    if not all_examples:
        print("\nНічого не зібрано! Перевірте підключення до інтернету.")
        return

    save_data(all_examples)
    print("\nПерезапуск класифікатора...")
    score = retrain(all_examples, verbose=verbose)

    print(f"\n{'=' * 60}")
    print(f"  Готово! Weighted F1 = {score:.1%}")
    print(f"  Модель перенавчена на реальних новинах ЧНУ")
    print("=" * 60)


if __name__ == "__main__":
    main()
