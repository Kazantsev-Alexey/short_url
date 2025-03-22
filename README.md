### URL Shortener API

В проекте представле сервис, работающий на FastAPI, который позволяет сокращать ссылки, смотреть статистику по ним и работает с подключением БД postgres и системы кэширования Redis.

---

### Доступные эндопинты API

1. POST   - `/register`                 - Регистрация нового пользователя
2. POST   - `/links/shorten`            - Создание короткой ссылки (с опц. алиасом
3. GET    - `/{short_code}`             - Переход по короткой ссылке
4. GET    - `/links/{short_code}/stats` - Получение статистики по ссылке
5. GET    - `/links/search`             - Поиск ссылки по оригинальному URL
6. PUT    - `/links/{short_code}`       - Обновление оригинального URL (авторизация)
7. DELETE - `/links/{short_code}`       - Удаление ссылки (авторизация)

---

### Примеры запросов

#### Регистрация

curl -X POST https://short-url-uhgn.onrender.com/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alexey", "password": "1234"}'

#### Создание ссылки
  curl -X POST https://short-url-uhgn.onrender.com/links/shorten \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://youtube.com",
    "custom_alias": "yt",
    "username": "username"
  }'

#### Просмотр статистики
curl https://short-url-uhgn.onrender.com/links/yt/stats

#### Удаление записи
curl -X DELETE https://short-url-uhgn.onrender.com/links/yt \
  -H "Authorization: user:pass"

---

#### Описание БД
#### Таблица users
id       -  SERIAL

username - TEXT

password - TEXT

#### Таблица urls

id            -  SERIAL

original_url  -  TEXT

short_code    -  TEXT

created_at    -  TIMESTAMP (UTC)

expires_at    -  TIMESTAMP (UTC)

visit_count   -  INTEGER

last_accessed -  TIMESTAMP (UTC)

created_at    -  TIMESTAMP (UTC)

created_at    -  TIMESTAMP (UTC)

user_id       -  INTEGER (Foreign key -> users)




