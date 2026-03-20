import aiosqlite
import os

DB_PATH = "bot_database.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # جدول المستخدمين
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # جدول الكتب المرفوعة
        await db.execute("""
            CREATE TABLE IF NOT EXISTS books (
                book_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                file_id TEXT,
                file_name TEXT,
                content_text TEXT,
                chapters_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        
        # جدول الأبواب المستخرجة
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chapters (
                chapter_id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER,
                chapter_title TEXT,
                chapter_content TEXT,
                summary TEXT,
                questions_json TEXT,
                FOREIGN KEY (book_id) REFERENCES books (book_id)
            )
        """)
        
        await db.commit()

async def add_user(user_id, username, full_name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
            (user_id, username, full_name)
        )
        await db.commit()

async def save_book(user_id, file_id, file_name, content_text):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO books (user_id, file_id, file_name, content_text) VALUES (?, ?, ?, ?)",
            (user_id, file_id, file_name, content_text)
        )
        book_id = cursor.lastrowid
        await db.commit()
        return book_id

async def update_book_chapters(book_id, chapters_json):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE books SET chapters_json = ? WHERE book_id = ?",
            (chapters_json, book_id)
        )
        await db.commit()

async def add_chapter(book_id, title, content):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO chapters (book_id, chapter_title, chapter_content) VALUES (?, ?, ?)",
            (book_id, title, content)
        )
        chapter_id = cursor.lastrowid
        await db.commit()
        return chapter_id

async def get_chapters(book_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chapter_id, chapter_title FROM chapters WHERE book_id = ?", (book_id,)) as cursor:
            return await cursor.fetchall()

async def get_chapter_details(chapter_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chapter_title, chapter_content, summary, questions_json FROM chapters WHERE chapter_id = ?", (chapter_id,)) as cursor:
            return await cursor.fetchone()

async def update_chapter_summary(chapter_id, summary):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE chapters SET summary = ? WHERE chapter_id = ?", (summary, chapter_id))
        await db.commit()

async def update_chapter_questions(chapter_id, questions_json):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE chapters SET questions_json = ? WHERE chapter_id = ?", (questions_json, chapter_id))
        await db.commit()
