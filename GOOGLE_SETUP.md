# Кроки для оновлення Google Cloud Console

Програма тепер використовує **Gmail API** замість IMAP. Треба зробити 2 речі в Google Cloud:

## 1. Увімкнути Gmail API

1. https://console.cloud.google.com → твій проект "MailSort"
2. Зліва **APIs & Services → Library**
3. Знайди **"Gmail API"** → натисни → **"Enable"**

## 2. Додати scope `gmail.modify` в OAuth Consent Screen

1. Зліва **APIs & Services → OAuth consent screen**
2. Натисни **"Edit app"** (або скрол вниз до Scopes)
3. **"Add or Remove Scopes"**
4. У списку знайди і додай:
   - `https://www.googleapis.com/auth/gmail.modify`
5. Save

## 3. Додай свою пошту як Test User (поки app не verified)

Поки додаток не пройшов Google verification, тільки Test Users можуть увійти:

1. **OAuth consent screen → Audience → Test users**
2. **+ ADD USERS**
3. Додай: `marusiak.vladyslav@chnu.edu.ua` (та інші email якщо треба)
4. Save

Без цього Google буде блокувати вхід для не-Test users з помилкою "Access blocked: MailSort has not completed the Google verification process".

## 4. Перевір Authorized redirect URIs

В **Credentials → твій OAuth Client → Authorized redirect URIs** має бути:

```
https://web-production-a436a.up.railway.app/auth/google/callback
```

(Це вже додано раніше, але про всяк випадок перевір.)

---

Після цих кроків кожен Test User зможе увійти через Google і програма автоматично читатиме його Gmail.
