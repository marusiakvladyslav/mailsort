"""
news_fetcher.py — парсер новин ЧНУ v5.
Тільки стандартна бібліотека Python (urllib, re, xml).
Не потребує pip install.
"""
import time
import urllib.request
import urllib.error
import gzip
import re
import html as _html_mod
import xml.etree.ElementTree as ET
from database import get_connection

CACHE_TTL = 1800
BASE      = "https://www.chnu.edu.ua"
TIMEOUT   = 15

RSS_URLS = [
    f"{BASE}/rss.xml",
    f"{BASE}/novyny/rss.xml",
    f"{BASE}/novyny/feed/",
    f"{BASE}/feed/",
]

HTML_URLS = [
    f"{BASE}/novyny/",
    f"{BASE}/novyny/aktualni-novyny/",
]

HEADERS = [
    ("User-Agent",      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"),
    ("Accept",          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    ("Accept-Language", "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7"),
    ("Accept-Encoding", "gzip, deflate"),
    ("Connection",      "keep-alive"),
]


# ─── Утиліти ─────────────────────────────────────────────────────

def _unescape(text):
    """Декодує всі HTML entities включно з &#x...; та &amp; тощо."""
    return _html_mod.unescape(text).replace("\xa0", " ").strip()


def _extract_text(fragment):
    """Витягує чистий текст з HTML-фрагменту (без тегів)."""
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', fragment)).strip()


# ─── HTTP ────────────────────────────────────────────────────────

def _fetch_url(url):
    """Завантажує URL. Повертає (text, content_type)."""
    req = urllib.request.Request(url)
    for k, v in HEADERS:
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        ct  = resp.headers.get("Content-Type", "")
        raw = resp.read()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    charset = "utf-8"
    if "charset=" in ct:
        charset = ct.split("charset=")[-1].strip().split(";")[0].strip()
    return raw.decode(charset, errors="replace"), ct


# ─── БД ──────────────────────────────────────────────────────────

def _ensure_table():
    with get_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS news_cache (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT,
            link       TEXT UNIQUE,
            date       TEXT,
            image      TEXT DEFAULT '',
            fetched_at REAL)""")
        try:
            conn.execute("ALTER TABLE news_cache ADD COLUMN image TEXT DEFAULT ''")
        except Exception:
            pass


def _is_fresh():
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT MAX(fetched_at) FROM news_cache").fetchone()
        return row and row[0] and (time.time() - row[0]) < CACHE_TTL
    except Exception:
        return False


def _save(items):
    if not items:
        return
    with get_connection() as conn:
        conn.execute("DELETE FROM news_cache")
        for it in items:
            conn.execute(
                "INSERT OR IGNORE INTO news_cache "
                "(title, link, date, image, fetched_at) VALUES (?,?,?,?,?)",
                (it.get("title", ""), it.get("link", ""),
                 it.get("date", ""),  it.get("image", ""), time.time()))


def _get_cached():
    try:
        with get_connection() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM news_cache ORDER BY id LIMIT 30").fetchall()]
    except Exception:
        return []


# ─── RSS-парсинг ─────────────────────────────────────────────────

def _parse_rss(text, base):
    """Парсить RSS 2.0 та Atom."""
    items, seen = [], set()
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    media_ns = "http://search.yahoo.com/mrss/"
    atom_ns  = "http://www.w3.org/2005/Atom"

    channel = root.find("channel")
    if channel is not None:
        for item in channel.findall("item")[:25]:
            title = _unescape(item.findtext("title") or "")
            link  = (item.findtext("link") or "").strip()
            date  = (item.findtext("pubDate") or "")[:16].strip()
            image = ""
            enc = item.find("enclosure")
            if enc is not None and "image" in (enc.get("type") or ""):
                image = enc.get("url", "")
            med = item.find(f"{{{media_ns}}}thumbnail")
            if not image and med is not None:
                image = med.get("url", "")
            if len(title) < 5 or not link:
                continue
            if not link.startswith("http"):
                link = base + link
            if link in seen:
                continue
            seen.add(link)
            items.append({"title": title[:150], "link": link,
                          "date": date, "image": image})
        if items:
            return items

    for entry in root.findall(f"{{{atom_ns}}}entry")[:25]:
        title   = _unescape(entry.findtext(f"{{{atom_ns}}}title") or "")
        link_el = (entry.find(f"{{{atom_ns}}}link[@rel='alternate']")
                   or entry.find(f"{{{atom_ns}}}link"))
        link = (link_el.get("href", "") if link_el is not None else "").strip()
        date = (entry.findtext(f"{{{atom_ns}}}updated")
                or entry.findtext(f"{{{atom_ns}}}published") or "")[:10]
        if len(title) < 5 or not link:
            continue
        if not link.startswith("http"):
            link = base + link
        if link in seen:
            continue
        seen.add(link)
        items.append({"title": title[:150], "link": link, "date": date, "image": ""})

    return items


# ─── HTML-парсинг ────────────────────────────────────────────────

def _parse_html(html_text, base):
    """
    Парсить HTML сторінку новин chnu.edu.ua.
    На сайті структура: <h3>ЗАГОЛОВОК</h3> ... <a href="/novyny/...">Читати далі</a>
    Стратегія 0: знаходимо "Читати далі" → беремо останній h2/h3/h4 перед ним.
    Стратегії 1-3: fallback.
    """
    NON_NEWS = ["korysni", "posylannya", "kontakt", "kerivnytstvo",
                "struktura", "pro-universytet", "statut", "zvity",
                "naukovi-vydannya", "biblioteka"]

    clean = re.sub(r'<(nav|header|footer)[^>]*>.*?</\1>', ' ', html_text,
                   flags=re.IGNORECASE | re.DOTALL)

    items, seen = [], set()

    def _is_news_link(href):
        if not href:
            return False
        full = (base + href) if href.startswith("/") else (href if href.startswith("http") else None)
        if not full:
            return False
        if "/novyny/" not in full:
            return False
        path = full.replace(base, "").rstrip("/")
        segs = [s for s in path.split("/") if s]
        if len(segs) < 3:
            return False
        if any(skip in full.lower() for skip in NON_NEWS):
            return False
        return full

    # ── Стратегія 0: "Читати далі" → заголовок перед ним ─────────
    read_more_pat = re.compile(
        r'href=["\']([^"\'> ]+)["\'][^>]*>\s*(?:Читати далі|Read more|Детальніше)\s*</a>',
        re.IGNORECASE
    )
    for rm in read_more_pat.finditer(clean):
        full = _is_news_link(rm.group(1))
        if not full or full in seen:
            continue
        # Беремо 4000 символів ДО цього посилання
        before = clean[max(0, rm.start() - 4000): rm.start()]
        # Беремо ОСТАННІЙ h2/h3/h4 перед посиланням
        title = ""
        for hm in re.finditer(r'<h[234][^>]*>(.*?)</h[234]>', before,
                               re.IGNORECASE | re.DOTALL):
            t = _unescape(_extract_text(hm.group(1)))
            if 8 <= len(t) <= 200:
                title = t   # перезаписуємо — нас цікавить останній
        if not title:
            continue
        seen.add(full)
        items.append({"title": title[:150], "link": full, "date": "", "image": ""})
        if len(items) >= 20:
            return items

    if items:
        return items

    # ── Стратегія 1: картки article/div.views-row/div.node ────────
    card_pat = re.compile(
        r'<(?:article|div)[^>]*class=["\'][^"\']*(?:views-row|node|news|card|article)[^"\']*["\'][^>]*>'
        r'(.*?)'
        r'</(?:article|div)>',
        re.IGNORECASE | re.DOTALL
    )
    for card_m in card_pat.finditer(clean):
        card_html = card_m.group(1)
        title = ""
        for hm in re.finditer(r'<h[234][^>]*>(.*?)</h[234]>', card_html,
                               re.IGNORECASE | re.DOTALL):
            t = _unescape(_extract_text(hm.group(1)))
            if 8 <= len(t) <= 200:
                title = t
                break
        if not title:
            continue
        link = ""
        for lm in re.finditer(r'href=["\']([^"\'> ]+)["\']', card_html, re.IGNORECASE):
            full = _is_news_link(lm.group(1))
            if full and full not in seen:
                link = full
                break
        if not link:
            continue
        seen.add(link)
        items.append({"title": title[:150], "link": link, "date": "", "image": ""})
        if len(items) >= 20:
            return items

    # ── Стратегія 2: h2/h3 що містить <a href="/novyny/..."> ──────
    if len(items) < 3:
        for m in re.finditer(
            r'<h[234][^>]*>.*?<a[^>]+href=["\']([^"\'> ]+)["\'][^>]*>(.*?)</a>.*?</h[234]>',
            clean, re.IGNORECASE | re.DOTALL
        ):
            full = _is_news_link(m.group(1))
            if not full or full in seen:
                continue
            title = _unescape(_extract_text(m.group(2)))
            if len(title) < 8 or len(title) > 200:
                continue
            seen.add(full)
            items.append({"title": title[:150], "link": full, "date": "", "image": ""})
            if len(items) >= 20:
                break

    # ── Стратегія 3: будь-яке посилання з довгим текстом ─────────
    if len(items) < 3:
        skip_texts = ["читати далі", "read more", "детальніше", "більше", "→", ">>"]
        for m in re.finditer(
            r'<a[^>]+href=["\']([^"\'> ]+)["\'][^>]*>(.*?)</a>',
            clean, re.IGNORECASE | re.DOTALL
        ):
            full = _is_news_link(m.group(1))
            if not full or full in seen:
                continue
            title = _unescape(_extract_text(m.group(2)))
            if len(title) < 15 or len(title) > 200:
                continue
            if any(s in title.lower() for s in skip_texts):
                continue
            seen.add(full)
            items.append({"title": title[:150], "link": full, "date": "", "image": ""})
            if len(items) >= 20:
                break

    return items


# ─── Головна функція ─────────────────────────────────────────────

def fetch_news(force=False):
    """Повертає список новин ЧНУ. Порядок: RSS → HTML → кеш."""
    _ensure_table()

    if not force and _is_fresh():
        cached = _get_cached()
        if cached:
            return cached

    for url in RSS_URLS:
        try:
            text, ct = _fetch_url(url)
            if "html" in ct.lower() and "<channel" not in text and "<feed" not in text:
                continue
            items = _parse_rss(text, BASE)
            if len(items) >= 3:
                print(f"[news] RSS OK: {url} → {len(items)} новин")
                _save(items)
                return items
        except urllib.error.HTTPError as e:
            print(f"[news] {url} → HTTP {e.code}")
        except Exception as e:
            print(f"[news] {url} → {e}")

    for url in HTML_URLS:
        try:
            text, ct = _fetch_url(url)
            items = _parse_html(text, BASE)
            if len(items) >= 3:
                print(f"[news] HTML OK: {url} → {len(items)} новин")
                _save(items)
                return items
            else:
                print(f"[news] HTML {url} → знайдено {len(items)} (замало)")
        except urllib.error.HTTPError as e:
            print(f"[news] HTML {url} → HTTP {e.code}")
        except Exception as e:
            print(f"[news] HTML {url} → {e}")

    cached = _get_cached()
    print(f"[news] Повертаю кеш: {len(cached)} новин")
    return cached


def debug_fetch():
    """Детальна діагностика для /api/news-debug."""
    results = []
    for url in RSS_URLS + HTML_URLS:
        entry = {"url": url, "ok": False}
        try:
            text, ct = _fetch_url(url)
            entry["status"]       = 200
            entry["content_type"] = ct
            entry["size"]         = len(text)
            entry["has_rss"]      = "<channel>" in text or "<feed" in text
            entry["has_novyny"]   = "/novyny/" in text
            entry["preview"]      = text[:200]
            items = _parse_rss(text, BASE) if entry["has_rss"] else _parse_html(text, BASE)
            entry["parsed_items"] = len(items)
            entry["ok"]           = len(items) >= 3
            if items:
                entry["sample_title"] = items[0].get("title", "")
                entry["sample_link"]  = items[0].get("link", "")
        except urllib.error.HTTPError as e:
            entry["error"]  = f"HTTP {e.code}: {e.reason}"
            entry["status"] = e.code
        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {e}"
        results.append(entry)
    return results
