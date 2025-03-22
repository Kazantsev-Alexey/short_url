from fastapi import FastAPI, HTTPException, Request, Body, Header, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional
import psycopg2
import datetime
import shortuuid
import os
import redis

def get_redis():
    return redis.Redis(
        host=os.getenv("REDIS_HOST"),
        port=int(os.getenv("REDIS_PORT")),
        password=os.getenv("REDIS_PASSWORD"),
        ssl=True,
        decode_responses=True
    )

DATABASE_URL = os.getenv("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True

app = FastAPI()


with conn.cursor() as cur:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS urls (
            id SERIAL PRIMARY KEY,
            original_url TEXT NOT NULL UNIQUE,
            short_code TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            visit_count INTEGER NOT NULL DEFAULT 0,
            last_accessed TIMESTAMP,
            user_id INTEGER
        );
    """)

with conn.cursor() as cur:
    # Создаём таблицу пользователей
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        );
    """)


class RegisterRequest(BaseModel):
    username: str
    password: str

class ShortenRequest(BaseModel):
    url: HttpUrl
    custom_alias: str = None
    expires_at: datetime.datetime = None
    username: str = None

class UpdateRequest(BaseModel):
    new_url: HttpUrl

def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    try:
        username, password = authorization.split(":")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Authorization format")
    
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username = %s AND password = %s", (username, password))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return {"id": row[0], "username": username}
    
@app.post("/register")
def register(data: RegisterRequest):
    with conn.cursor() as cur:
        try:
            cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (data.username, data.password))
        except psycopg2.errors.UniqueViolation:
            raise HTTPException(status_code=400, detail="Username already taken")
    return {"message": "User registered successfully"}

@app.post("/links/shorten")
# определяем хост с помощью Request
def shorten_url(data: ShortenRequest, request: Request):
    # добавляем генерацию короткого кода, если алиас не передан
    
    user_id = None
    if data.username:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (data.username,))
            res = cur.fetchone()
            if not res:
                raise HTTPException(status_code=404, detail="User not found")
            user_id = res[0]

    short_code = data.custom_alias or shortuuid.uuid()[:6] 
    with conn.cursor() as cur:
        # проверяем на дубликат алиаса 
        cur.execute("SELECT 1 FROM urls WHERE short_code = %s", (short_code,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Alias already taken")
        
        # пробуем вставить запись, но если такая ссылка уже есть, возвращаем по ней запись
        try:
            cur.execute(
                "INSERT INTO urls (original_url, short_code, expires_at, user_id) VALUES (%s, %s, %s, %s)",
                (str(data.url), short_code, data.expires_at, user_id)
            )
        except psycopg2.errors.UniqueViolation:
            with conn.cursor() as cur2:
                cur2.execute(
                    "SELECT original_url, short_code FROM urls WHERE original_url = %s ORDER BY created_at DESC",
                    (str(data.url),)
                )
                rows = cur2.fetchall()

            base_url = str(request.base_url)
            return [
                {
                    "original_url": row[0],
                    "short_url": f"{base_url}{row[1]}"
                }
                for row in rows
            ]

    base_url = str(request.base_url)
    return {"short_url": f"{base_url}{short_code}"}

@app.get("/{short_code}")
# перенаправляем на нужный адрес
def redirect(short_code: str):
    # смотрим кэш и обновляем стату посещаемости
    r = get_redis() # обновляем редис
    cached_url = r.get(short_code)
    if cached_url:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE urls SET visit_count = visit_count + 1, last_accessed = %s
                WHERE short_code = %s
            """, (datetime.datetime.now(datetime.timezone.utc), short_code))
        return RedirectResponse(url=cached_url)

    # если в кэше нет, берем из бд и обновляем стату посещаемости
    with conn.cursor() as cur:
        cur.execute("SELECT original_url, expires_at FROM urls WHERE short_code = %s", (short_code,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="URL not found")

        original_url, expires_at = row
        if expires_at:
            expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
            if expires_at < datetime.datetime.now(datetime.timezone.utc):
                raise HTTPException(status_code=410, detail="URL expired")

        cur.execute("""
            UPDATE urls SET visit_count = visit_count + 1, last_accessed = %s
            WHERE short_code = %s
        """, (datetime.datetime.now(datetime.timezone.utc), short_code))

        r.setex(short_code, 3600, original_url)
        return RedirectResponse(url=original_url)

@app.get("/links/{short_code}/stats")
# выведем содержимое для кода 
def stats(short_code: str):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT original_url, created_at, visit_count, last_accessed, expires_at
            FROM urls WHERE short_code = %s
        """, (short_code,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="URL not found")

        return {
            "original_url": row[0],
            "created_at": row[1],
            "visit_count": row[2],
            "last_accessed": row[3],
            "expires_at": row[4]
        }
    

@app.get("/links/search")
# аналогично со stats, только ищем по оригинальной ссылке и возвращаем код
def search(original_url: str):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT short_code, created_at, visit_count, last_accessed, expires_at
               FROM urls WHERE original_url = %s ORDER BY created_at DESC;
        """, (original_url,)
        )
        rows = cur.fetchall()
    return [
        {
            "short_code": row[0],
            "created_at": row[1],
            "visit_count": row[2],
            "last_accessed": row[3],
            "expires_at": row[4]
        }
        for row in rows
    ]

@app.put("/links/{short_code}")
# обновляем ссылку с проверкой авторизации
def update(short_code: str, data: UpdateRequest, user=Depends(get_current_user)):
    r = get_redis()
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM urls WHERE short_code = %s", (short_code,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="URL not found")
        if row[0] != user["id"]:
            raise HTTPException(status_code=403, detail="You don't have permission to update this link")

        cur.execute("UPDATE urls SET original_url = %s WHERE short_code = %s", (str(data.new_url), short_code))
        r.delete(short_code)
        return {"message": "URL has been updated successfully"}
    
@app.delete("/links/{short_code}")
# удаляем ссылку с проверкой авторизации
def delete(short_code: str, user=Depends(get_current_user)):
    r = get_redis()
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM urls WHERE short_code = %s", (short_code,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"URL not found for {short_code}")
        if row[0] != user["id"]:
            raise HTTPException(status_code=403, detail="You don't have permission to delete this link")

        cur.execute("DELETE FROM urls WHERE short_code = %s", (short_code,))
        r.delete(short_code)
        return {"message": f"Code {short_code} has been deleted successfully"}
