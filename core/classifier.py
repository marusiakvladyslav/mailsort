"""
classifier.py — модуль класифікації пошти (v3).
"""
import os

from config import MODEL_PATH, CATEGORIES
from preprocessor import preprocess

# ─── Поріг впевненості ───────────────────────────────────────────
CONFIDENCE_THRESHOLD = 0.30
UNKNOWN_LABEL = "Невизначено"

# ─── Навчальні дані (~25 прикладів на категорію) ─────────────────
TRAINING_DATA = [

    # ── Новини та розсилки ────────────────────────────────────────
    # Масові розсилки, публікації на сайті, інформаційні бюлетені
    ("Загальна розсилка для всіх студентів та співробітників університету", "Новини та розсилки"),
    ("Інформаційний бюлетень університету за поточний місяць", "Новини та розсилки"),
    ("Розсилка новин ЧНУ оголошення для студентів і викладачів", "Новини та розсилки"),
    ("Університет опублікував новини тижня на офіційному сайті", "Новини та розсилки"),
    ("Масова розсилка важлива інформація для всіх факультетів", "Новини та розсилки"),
    ("Новини університету актуальна інформація від адміністрації", "Новини та розсилки"),
    ("Підписка на новини університету щотижневий дайджест подій", "Новини та розсилки"),
    ("Університетський newsletter новини досягнення оголошення", "Новини та розсилки"),
    ("Рейтинг університету покращився нові публікації та здобутки", "Новини та розсилки"),
    ("Вітаємо з початком навчального року загальне звернення ректора", "Новини та розсилки"),
    ("Оголошення для всього університетського співтовариства важливе", "Новини та розсилки"),
    ("Новини факультету розсилка для студентів денної форми навчання", "Новини та розсилки"),
    ("Інформаційне повідомлення розповсюджується всім студентам", "Новини та розсилки"),
    ("Університет запрошує ознайомитись з новинами та подіями місяця", "Новини та розсилки"),
    ("Щомісячна розсилка новин ЧНУ підсумки та майбутні заходи", "Новини та розсилки"),
    ("Публікація на сайті університету нова стаття важливе оголошення", "Новини та розсилки"),
    ("Дайджест подій університету за поточний тиждень всім підрозділам", "Новини та розсилки"),
    ("Університет нагороджений почесною грамотою розсилка новин", "Новини та розсилки"),
    ("Загальноуніверситетське оголошення просимо ознайомитись всіх", "Новини та розсилки"),
    ("Новини та оголошення університету розсилка по електронній пошті", "Новини та розсилки"),
    ("Актуальні новини від університету важлива розсилка для всіх", "Новини та розсилки"),
    ("Університетська газета електронний випуск новини та оголошення", "Новини та розсилки"),
    ("Офіційний сайт університету нова публікація просимо переглянути", "Новини та розсилки"),
    ("Розсилка від деканату факультету оголошення для всіх студентів", "Новини та розсилки"),
    ("Загальне повідомлення від університету важливо для всіх читати", "Новини та розсилки"),

    # ── Moodle ───────────────────────────────────────────────────
    # Системні сповіщення від LMS Moodle
    ("Нагадування про дедлайн здачі завдання в системі Moodle курс", "Moodle"),
    ("Moodle повідомляє нове завдання додано до вашого курсу перевірте", "Moodle"),
    ("Викладач залишив коментар до вашої роботи в Moodle зверніть увагу", "Moodle"),
    ("Нова оцінка виставлена у журналі Moodle перегляньте результат", "Moodle"),
    ("Нагадування Moodle термін виконання тесту закінчується завтра", "Moodle"),
    ("Системне повідомлення Moodle ваш курс оновлено новий матеріал", "Moodle"),
    ("Moodle notification новий форум повідомлення від викладача курс", "Moodle"),
    ("Зарахування на курс в системі Moodle підтвердження запису", "Moodle"),
    ("Moodle reminder дедлайн здачі лабораторної роботи через два дні", "Moodle"),
    ("Тест в Moodle доступний для проходження термін до кінця тижня", "Moodle"),
    ("Викладач додав нові матеріали до курсу в Moodle повідомлення", "Moodle"),
    ("Moodle system завдання перевірено оцінку виставлено журнал курсу", "Moodle"),
    ("Повідомлення від Moodle обговорення на форумі курсу нова відповідь", "Moodle"),
    ("Moodle нагадує здайте звіт до лабораторної роботи до вказаного терміну", "Moodle"),
    ("Системне сповіщення LMS Moodle дедлайн курсового завдання", "Moodle"),
    ("Moodle: ваша відповідь на тест отримала автоматичну оцінку", "Moodle"),
    ("Нове повідомлення від викладача в системі Moodle перегляньте курс", "Moodle"),
    ("Moodle badge отримано відзнаку за виконання завдання курсу", "Moodle"),
    ("Нагадування Moodle не забудьте здати практичну роботу вчасно", "Moodle"),
    ("Moodle повідомляє ваш курс буде відкрито до реєстрації незабаром", "Moodle"),
    ("Сповіщення від системи дистанційного навчання Moodle нове завдання", "Moodle"),
    ("Moodle: термін дії тесту спливає сьогодні проходьте зараз", "Moodle"),
    ("Повідомлення з системи Moodle результати тесту доступні для перегляду", "Moodle"),
    ("Moodle нова лекційна презентація додана до матеріалів курсу", "Moodle"),
    ("Moodle reminder: завтра останній день здачі підсумкового тесту", "Moodle"),

    # ── Навчальний процес ─────────────────────────────────────────
    # Розклад, сесія, дипломні, іспити, практика
    ("Розклад занять на наступний навчальний семестр вже опубліковано", "Навчальний процес"),
    ("Зміна розкладу пара з математики перенесена на іншу аудиторію", "Навчальний процес"),
    ("Розклад сесії для студентів денної та заочної форм навчання", "Навчальний процес"),
    ("Результати іспиту з бази даних відомість виставлена в деканат", "Навчальний процес"),
    ("Консультації перед захистом дипломних робіт графік викладача", "Навчальний процес"),
    ("Вимоги до оформлення дипломної роботи відповідно до стандарту", "Навчальний процес"),
    ("Переатестація студентів з академічними заборгованостями дата", "Навчальний процес"),
    ("Інформація щодо проходження виробничої практики поточний семестр", "Навчальний процес"),
    ("Розподіл тем курсових робіт студентам третього курсу кафедра", "Навчальний процес"),
    ("Лекція з програмування перенесена на іншу дату повідомлення", "Навчальний процес"),
    ("Підсумки навчального року оцінки студентів відомість деканат", "Навчальний процес"),
    ("Захист курсового проекту відбудеться у вівторок підготуйтесь", "Навчальний процес"),
    ("Навчальна програма курсу оновлена нові теми лабораторні роботи", "Навчальний процес"),
    ("Онлайн курс з веб розробки відкритий для запису студентів", "Навчальний процес"),
    ("Семінар з програмування для студентів другого курсу кафедра", "Навчальний процес"),
    ("Графік консультацій викладача перед іспитом розклад прийому", "Навчальний процес"),
    ("Зміни у навчальному плані спеціальності нові вибіркові дисципліни", "Навчальний процес"),
    ("Перегляд оцінок та апеляція після сесії терміни та порядок", "Навчальний процес"),
    ("Олімпіада з інформатики для студентів реєстрація до кінця місяця", "Навчальний процес"),
    ("Державна підсумкова атестація розклад та вимоги для випускників", "Навчальний процес"),
    ("Навчальний семінар основи Python відкритий для всіх охочих", "Навчальний процес"),
    ("Практичне заняття перенесено через відрядження викладача повідомлення", "Навчальний процес"),
    ("Нові навчальні матеріали для підготовки до іспиту завантажте зараз", "Навчальний процес"),
    ("Студенти-заочники розклад сесії та терміни здачі контрольних", "Навчальний процес"),
    ("Медична довідка для допуску до занять де і як оформити", "Навчальний процес"),

    # ── Адміністрація ─────────────────────────────────────────────
    # Офіційні листи, накази, деканат, ректор
    ("Наказ ректора про затвердження змін у внутрішньому розпорядку", "Адміністрація"),
    ("Деканат повідомляє про зміни у правилах відвідування занять", "Адміністрація"),
    ("Офіційне розпорядження адміністрації університету для ознайомлення", "Адміністрація"),
    ("Повідомлення від ректорату щодо стратегії розвитку університету", "Адміністрація"),
    ("Наказ про зарахування студентів на перший курс список груп", "Адміністрація"),
    ("Адміністрація університету повідомляє про зміну режиму роботи", "Адміністрація"),
    ("Офіційне звернення від проректора з навчальної роботи наказ", "Адміністрація"),
    ("Наказ про відрахування та поновлення студентів рішення ради", "Адміністрація"),
    ("Деканат просить підтвердити академічну групу реєстрація даних", "Адміністрація"),
    ("Офіційний лист від юридичного відділу університету для підпису", "Адміністрація"),
    ("Розпорядження про проведення інвентаризації майна університету", "Адміністрація"),
    ("Наказ про переведення студентів між групами та спеціальностями", "Адміністрація"),
    ("Адміністрація: нові правила пропускного режиму кампус безпека", "Адміністрація"),
    ("Листування з деканатом щодо академічної відпустки документи", "Адміністрація"),
    ("Офіційне повідомлення про зміну ректора виконання обов'язків", "Адміністрація"),
    ("Наказ про встановлення нових правил складання заліків та іспитів", "Адміністрація"),
    ("Рішення вченої ради університету протокол засідання для ознайомлення", "Адміністрація"),
    ("Адміністрація оголошує конкурс на заміщення посади завідувача", "Адміністрація"),
    ("Доручення деканату підготувати звіт кафедри до наступного засідання", "Адміністрація"),
    ("Наказ університету нові вимоги до оформлення дипломних робіт", "Адміністрація"),
    ("Офіційне повідомлення про карантинні заходи та режим роботи", "Адміністрація"),
    ("Адміністрація повідомляє зміна порядку видачі документів студентам", "Адміністрація"),
    ("Розпорядження ректора про відзначення річниці університету захід", "Адміністрація"),
    ("Деканат запрошує на збори групи з поважних причин обов'язково", "Адміністрація"),
    ("Наказ університету перехід на електронний документообіг порядок", "Адміністрація"),

    # ── Заходи та події ───────────────────────────────────────────
    # Конференції, семінари, олімпіади, культурні заходи, змагання
    ("Запрошення на міжнародну наукову конференцію з інформаційних технологій", "Заходи та події"),
    ("Семінар з машинного навчання та аналізу великих даних реєстрація", "Заходи та події"),
    ("Студентська олімпіада з математики умови участі та реєстрація", "Заходи та події"),
    ("Культурний захід університету вечір поезії запрошуємо всіх", "Заходи та події"),
    ("Науково-практична конференція студентів подача тез до 20 числа", "Заходи та події"),
    ("Спортивні змагання між факультетами запрошення для студентів", "Заходи та події"),
    ("Міжнародний форум молодих вчених реєстрація учасників відкрита", "Заходи та події"),
    ("Відкрита лекція запрошеного науковця з Польщі вхід безкоштовний", "Заходи та події"),
    ("Виставка студентських проектів та наукових розробок університет", "Заходи та події"),
    ("Конкурс студентських наукових робіт подача матеріалів до кінця місяця", "Заходи та події"),
    ("Круглий стіл з питань цифрової трансформації освіти учасники", "Заходи та події"),
    ("День відкритих дверей університету запрошуємо абітурієнтів", "Заходи та події"),
    ("Воркшоп з розробки мобільних додатків для всіх охочих студентів", "Заходи та події"),
    ("Запрошення на хакатон для студентів ІТ спеціальностей призи", "Заходи та події"),
    ("Університетська конференція підсумки наукових досліджень кафедри", "Заходи та події"),
    ("Захід до річниці університету святкова програма для всіх", "Заходи та події"),
    ("Запрошення взяти участь у міжвузівській студентській олімпіаді", "Заходи та події"),
    ("Вебінар з актуальних питань кібербезпеки для студентів та викладачів", "Заходи та події"),
    ("Міжнародний обмін студентами відбіркові співбесіди та умови", "Заходи та події"),
    ("Студентська конференція прийом тез доповідей вимоги до оформлення", "Заходи та події"),
    ("Запрошення на літню школу програмування реєстрація до кінця тижня", "Заходи та події"),
    ("Конкурс наукових проектів з природничих наук призовий фонд", "Заходи та події"),
    ("Відкрита лекція запрошеного фахівця з бізнес-аналітики університет", "Заходи та події"),
    ("Інтелектуальна гра квіз для студентів реєстрація команд відкрита", "Заходи та події"),
    ("Захист дипертаційних досліджень аспірантів відкрите засідання ради", "Заходи та події"),

]

# ─── Моделі (word + char n-gram FeatureUnion) ────────────────────
# Lazy imports — завантажуються тільки при першому виклику classify/train

def _word_tfidf():
    from sklearn.feature_extraction.text import TfidfVectorizer
    return TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        max_features=20_000,
        sublinear_tf=True,
        min_df=1,
    )

def _char_tfidf():
    from sklearn.feature_extraction.text import TfidfVectorizer
    return TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 4),
        max_features=30_000,
        sublinear_tf=True,
        min_df=1,
    )

# Для сумісності з старим кодом
def _tfidf():
    return _word_tfidf()

def _features():
    from sklearn.pipeline import FeatureUnion
    return FeatureUnion([
        ("word", _word_tfidf()),
        ("char", _char_tfidf()),
    ])

def _build_lr():
    from sklearn.pipeline import Pipeline
    from sklearn.linear_model import LogisticRegression
    # multi_class видалено у sklearn 1.5 (тепер автоматично multinomial для lbfgs).
    return Pipeline([
        ("features", _features()),
        ("clf", LogisticRegression(C=5.0, max_iter=1000, solver="lbfgs")),
    ])

def _build_svm():
    from sklearn.pipeline import Pipeline
    from sklearn.svm import LinearSVC
    from sklearn.calibration import CalibratedClassifierCV
    return Pipeline([
        ("features", _features()),
        ("clf", CalibratedClassifierCV(LinearSVC(C=1.0, max_iter=2000))),
    ])

def _build_svm_word():
    from sklearn.pipeline import Pipeline
    from sklearn.svm import LinearSVC
    from sklearn.calibration import CalibratedClassifierCV
    return Pipeline([
        ("tfidf", _word_tfidf()),
        ("clf", CalibratedClassifierCV(LinearSVC(C=2.0, max_iter=2000))),
    ])

def _build_nb():
    from sklearn.pipeline import Pipeline
    from sklearn.naive_bayes import ComplementNB
    return Pipeline([
        ("tfidf", _word_tfidf()),
        ("clf", ComplementNB(alpha=0.3)),
    ])

def _build_ensemble():
    """
    Soft-voting ансамбль з двох найкращих моделей (LR + SVM). NB виключено,
    бо на малих вибірках тягне середній F1 донизу. LR має більшу вагу,
    оскільки на власних замірах показує найвищу якість.
    """
    from sklearn.pipeline import Pipeline
    from sklearn.ensemble import VotingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.svm import LinearSVC
    from sklearn.calibration import CalibratedClassifierCV

    voter = VotingClassifier(
        estimators=[
            ("lr",  LogisticRegression(C=5.0, max_iter=1000, solver="lbfgs")),
            ("svm", CalibratedClassifierCV(LinearSVC(C=1.0, max_iter=2000))),
        ],
        voting="soft",
        weights=[1.5, 1.0],
    )
    return Pipeline([
        ("features", _features()),
        ("clf", voter),
    ])

MODELS = {
    "LR + char+word":  _build_lr,
    "SVM + char+word": _build_svm,
    "SVM (word)":      _build_svm_word,
    "Naive Bayes":     _build_nb,
    "Ensemble (soft voting)": _build_ensemble,
}


# ─── Завантаження корпусу (базовий + корекції користувача) ───────

def _load_corpus():
    """
    Формує навчальну вибірку з TRAINING_DATA + user_corrections.
    Корекції дублюються з вагою 2 (додаються двічі) — щоб модель
    швидше реагувала на виправлення.
    """
    texts, labels, sources = [], [], []
    for t, cat in TRAINING_DATA:
        texts.append(preprocess(t, ""))
        labels.append(cat)
        sources.append("base")

    n_corr = 0
    try:
        from database import get_all_corrections
        for c in get_all_corrections():
            text = preprocess(c["subject"] or "", c["body"] or "")
            if not text:
                continue
            # додаємо двічі для підсилення сигналу
            for _ in range(2):
                texts.append(text)
                labels.append(c["new_category"])
                sources.append("user")
            n_corr += 1
    except Exception as ex:
        print(f"[classifier] Корекції недоступні: {ex}")

    return texts, labels, sources, n_corr


# ─── Benchmark ───────────────────────────────────────────────────

def benchmark(print_results: bool = True, texts=None, labels=None) -> dict:
    """
    Виконує 5-fold stratified CV для всіх моделей у MODELS.
    Повертає словник {назва: weighted_f1}.
    """
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from collections import Counter
    if texts is None or labels is None:
        texts, labels, _, _ = _load_corpus()

    # Якщо у якомусь класі менше за n_splits прикладів — зменшуємо splits
    min_count = min(Counter(labels).values())
    n_splits = max(2, min(5, min_count))

    results = {}
    for name, builder in MODELS.items():
        try:
            scores = cross_val_score(
                builder(), texts, labels,
                cv=StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42),
                scoring="f1_weighted",
            )
            results[name] = float(scores.mean())
        except Exception as ex:
            print(f"[classifier] {name} провалено: {ex}")
            results[name] = 0.0

    if print_results:
        print(f"\n=== Порівняння моделей ({n_splits}-fold CV, weighted F1) ===")
        for name, score in sorted(results.items(), key=lambda x: -x[1]):
            bar = "█" * int(score * 30)
            print(f"  {name:<28} {bar} {score:.3f}")

    return results


# ─── Калібрування порогу впевненості ─────────────────────────────

def _calibrate_threshold(pipeline, texts, labels, target_precision: float = 0.85) -> float:
    """
    Знаходить найменший поріг confidence, при якому precision на hold-out
    частині становить ≥ target_precision. Якщо недосяжно — повертає дефолт.
    """
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import precision_score
    import numpy as np
    try:
        X_tr, X_te, y_tr, y_te = train_test_split(
            texts, labels, test_size=0.25, random_state=42, stratify=labels
        )
        pipeline.fit(X_tr, y_tr)
        proba  = pipeline.predict_proba(X_te)
        preds  = pipeline.classes_[np.argmax(proba, axis=1)]
        confs  = np.max(proba, axis=1)

        # Пробуємо пороги 0.20…0.80
        best = CONFIDENCE_THRESHOLD
        for thr in np.linspace(0.20, 0.80, 25):
            mask = confs >= thr
            if mask.sum() < max(5, int(0.5 * len(y_te))):
                continue  # залишаємо забагато "Невизначено"
            p = precision_score(
                [y_te[i] for i in range(len(y_te)) if mask[i]],
                [preds[i] for i in range(len(preds)) if mask[i]],
                average="weighted", zero_division=0,
            )
            if p >= target_precision:
                best = float(thr)
                break
        return best
    except Exception as ex:
        print(f"[classifier] Калібрування порогу провалено: {ex}")
        return CONFIDENCE_THRESHOLD


# ─── Діагностика: матриця помилок, важливі ознаки ────────────────

def diagnose(pipeline=None) -> dict:
    """
    Повертає діагностичну інформацію для сторінки /ml-quality:
      - per-category precision/recall/F1
      - confusion matrix (список списків)
      - labels у тому ж порядку, що й рядки/стовпці матриці
      - приклади найбільш впевнено-помилкових класифікацій
    """
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report, confusion_matrix
    import numpy as np
    texts, labels, sources, _ = _load_corpus()
    if pipeline is None:
        pipeline = get_pipeline()
    try:
        X_tr, X_te, y_tr, y_te = train_test_split(
            texts, labels, test_size=0.25, random_state=42, stratify=labels
        )
    except ValueError:
        # Якщо якийсь клас має лише 1 приклад — stratify неможливий
        X_tr, X_te, y_tr, y_te = train_test_split(
            texts, labels, test_size=0.25, random_state=42
        )

    pipeline.fit(X_tr, y_tr)
    y_pred = pipeline.predict(X_te)
    proba  = pipeline.predict_proba(X_te)
    confs  = np.max(proba, axis=1)

    report = classification_report(y_te, y_pred, output_dict=True, zero_division=0)
    lbls   = sorted(set(labels))
    cm     = confusion_matrix(y_te, y_pred, labels=lbls).tolist()

    # Топ впевнених помилок (модель сказала X з confidence > 0.5, а було Y)
    mistakes = []
    for i, (true, pred, conf) in enumerate(zip(y_te, y_pred, confs)):
        if true != pred:
            mistakes.append({
                "text": X_te[i][:120],
                "true": true,
                "pred": pred,
                "confidence": float(conf),
            })
    mistakes.sort(key=lambda m: -m["confidence"])

    return {
        "labels":   lbls,
        "matrix":   cm,
        "per_class": {k: v for k, v in report.items()
                      if k in lbls},
        "accuracy": report.get("accuracy", 0.0),
        "f1_weighted": report["weighted avg"]["f1-score"] if "weighted avg" in report else 0.0,
        "test_size": len(y_te),
        "train_size": len(X_tr),
        "top_mistakes": mistakes[:10],
    }


# ─── Навчання (з логуванням версії + активним навчанням) ──────────

def train(print_report: bool = True):
    import joblib
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report, accuracy_score, f1_score

    texts, labels, sources, n_corr = _load_corpus()

    if print_report:
        print(f"\n=== Корпус: {len(texts)} прикладів "
              f"({len(texts) - n_corr*2} базових + {n_corr} корекцій × 2) ===")

    scores    = benchmark(print_results=print_report, texts=texts, labels=labels)
    best_name = max(scores, key=scores.get)
    if print_report:
        print(f"\n→ Обрано: {best_name} (F1={scores[best_name]:.3f})\n")

    try:
        X_tr, X_te, y_tr, y_te = train_test_split(
            texts, labels, test_size=0.2, random_state=42, stratify=labels
        )
    except ValueError:
        X_tr, X_te, y_tr, y_te = train_test_split(
            texts, labels, test_size=0.2, random_state=42
        )

    pipeline = MODELS[best_name]()
    pipeline.fit(X_tr, y_tr)

    y_pred = pipeline.predict(X_te)
    acc = accuracy_score(y_te, y_pred)
    f1w = f1_score(y_te, y_pred, average="weighted", zero_division=0)

    if print_report:
        print("=== Classification Report ===")
        print(classification_report(y_te, y_pred, zero_division=0))

    # Калібрування порогу
    threshold = _calibrate_threshold(MODELS[best_name](), texts, labels)
    if print_report:
        print(f"[classifier] Калібрований поріг впевненості: {threshold:.2f}")

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    # Вивчаємо chi-square маркери класів з того самого корпусу
    markers = _learn_class_keywords(texts, labels)
    if print_report and markers:
        print(f"[classifier] Chi-square маркери:")
        for cls, ms in sorted(markers.items()):
            print(f"  {cls}: {', '.join(sorted(ms)[:8])}" + ("…" if len(ms) > 8 else ""))

    joblib.dump({
        "pipeline":   pipeline,
        "model_name": best_name,
        "threshold":  threshold,
        "markers":    markers,
        "trained_at": __import__("datetime").datetime.now().isoformat(),
    }, MODEL_PATH)
    print(f"[classifier] Модель «{best_name}» збережено → {MODEL_PATH}")

    # Логуємо версію + позначаємо корекції використаними
    try:
        from database import log_model_version, mark_corrections_as_used
        log_model_version(
            model_name=best_name,
            n_samples=len(texts),
            n_corrections=n_corr,
            f1_weighted=float(f1w),
            accuracy=float(acc),
        )
        mark_corrections_as_used()
    except Exception as ex:
        print(f"[classifier] Логування версії провалено: {ex}")

    # Скидаємо кеш pipeline
    global _pipeline, _threshold, _keyword_markers
    _pipeline  = pipeline
    _threshold = threshold
    _keyword_markers = markers
    return pipeline


def load_or_train():
    import joblib
    global _threshold, _keyword_markers
    if os.path.exists(MODEL_PATH):
        saved = joblib.load(MODEL_PATH)
        if isinstance(saved, dict):
            print(f"[classifier] Завантажую «{saved['model_name']}»...")
            _threshold = float(saved.get("threshold", CONFIDENCE_THRESHOLD))
            _keyword_markers = saved.get("markers", {}) or {}
            return saved["pipeline"]
        return saved
    print("[classifier] Навчаю нову модель...")
    return train(print_report=False)


_pipeline = None
_threshold = CONFIDENCE_THRESHOLD  # оновлюється при load/train

# ─── Гібридна класифікація: chi-square маркери класів ─────────────
# Замість жорсткого "якщо у темі є 'moodle' → категорія Moodle" (як раніше
# в email_fetcher.py), модель вчить маркери автоматично. Для кожної
# категорії обираються ТОП-N слів, що мають найбільший chi-square score,
# тобто найсильніше пов'язані з цією категорією. При класифікації,
# якщо у листі зустрічається маркер категорії X — ймовірність proba[X]
# збільшується на фіксоване значення (boost). Це не перебиває ML-модель,
# а лише "натякає" на правильний клас у спірних випадках.

_keyword_markers = {}     # {"Moodle": {"moodle", "дедлайн", ...}, ...}
_keyword_boost = 0.20     # максимальна надбавка до ймовірності
_KEYWORDS_PER_CLASS = 15  # скільки маркерів брати на клас


def _learn_class_keywords(texts: list, labels: list, top_k: int = None) -> dict:
    """
    Через chi-square вибирає top-K найбільш інформативних слів для кожного класу.
    Повертає словник {клас: множина_слів}.
    """
    from sklearn.feature_extraction.text import CountVectorizer
    from sklearn.feature_selection import chi2
    import numpy as np

    top_k = top_k or _KEYWORDS_PER_CLASS
    try:
        # Для chi2 потрібна саме частотна матриця, не TF-IDF.
        vec = CountVectorizer(min_df=2, max_features=10_000, ngram_range=(1, 1))
        X = vec.fit_transform(texts)
        feat_names = vec.get_feature_names_out()

        result = {}
        unique_labels = sorted(set(labels))
        labels_arr = np.array(labels)

        for cls in unique_labels:
            # one-vs-rest chi2: як одне слово відрізняє цей клас від решти
            y_binary = (labels_arr == cls).astype(int)
            chi, _ = chi2(X, y_binary)
            chi = np.nan_to_num(chi, nan=0.0)
            top_idx = np.argsort(-chi)[:top_k]
            # Беремо лише слова, де цей клас реально переважає
            class_mask = labels_arr == cls
            markers = set()
            for i in top_idx:
                if chi[i] <= 0:
                    continue
                in_class = X[class_mask, i].sum()
                out_class = X[~class_mask, i].sum()
                # Маркер — слово, яке частіше у класі, ніж поза ним
                if in_class > out_class:
                    markers.add(feat_names[i])
            if markers:
                result[cls] = markers
        return result
    except Exception as ex:
        print(f"[classifier] chi2 маркери не сформовано: {ex}")
        return {}


def _apply_keyword_boost(text: str, proba, classes) -> "np.ndarray":
    """
    Якщо в тексті знайдено маркер класу X — підвищуємо proba[X]
    пропорційно кількості знайдених маркерів (max = _keyword_boost),
    потім перенормовуємо розподіл.
    """
    import numpy as np
    if not _keyword_markers:
        return proba
    tokens = set(text.split())
    adjusted = proba.copy()
    for i, cls in enumerate(classes):
        markers = _keyword_markers.get(cls)
        if not markers:
            continue
        hits = len(tokens & markers)
        if hits == 0:
            continue
        # Логарифмічне насичення: 1 маркер → 50% boost, 3+ → 100% boost
        boost = _keyword_boost * min(1.0, hits / 3.0)
        adjusted[i] = min(0.99, adjusted[i] + boost)
    # Перенормовуємо, щоб сума = 1
    total = adjusted.sum()
    if total > 0:
        adjusted = adjusted / total
    return adjusted


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = load_or_train()
    return _pipeline


def get_threshold() -> float:
    """Поточний (можливо, калібрований) поріг впевненості."""
    get_pipeline()  # гарантуємо, що load відбувся
    return _threshold


def get_keyword_markers() -> dict:
    """Для діагностичної сторінки — показати, що вивчив chi-square."""
    get_pipeline()
    return {k: sorted(v) for k, v in _keyword_markers.items()}


def classify(subject: str, body: str,
             sender: str = "") -> tuple[str, float]:
    """
    Класифікує лист.
    1. Спам-фільтр → LABEL_SPAM
    2. Правила по відправнику → точна категорія (напр. Moodle)
    3. ML-класифікатор (TF-IDF + ансамбль/SVM) з chi-square boost
    4. Поріг впевненості (калібрований) → UNKNOWN_LABEL
    """
    # ── Рівень 1: спам-фільтр (домен + тема + вміст) ────────────
    from spam_filter import check as spam_check
    spam_result = spam_check(sender, subject, body)
    if spam_result is not None:
        return spam_result   # (LABEL_SPAM, 0.99)

    # ── Рівень 2: Правила по відправнику ───────────────────────
    from config import CATEGORY_SENDERS
    sender_lower = sender.lower().strip()
    for pattern, cat in CATEGORY_SENDERS.items():
        p = pattern.lower()
        if sender_lower == p or sender_lower.endswith('@' + p) or sender_lower.endswith('.' + p):
            return cat, 0.99

    # ── Рівень 3: класифікатор з chi-square boost ──────────────
    import numpy as np
    pipe       = get_pipeline()
    text       = preprocess(subject, body)
    proba      = pipe.predict_proba([text])[0]
    proba      = _apply_keyword_boost(text, proba, pipe.classes_)
    idx        = int(np.argmax(proba))
    confidence = float(proba[idx])
    category   = pipe.classes_[idx]

    if confidence < _threshold:
        return UNKNOWN_LABEL, confidence

    return category, confidence
