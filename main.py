from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
from telethon import TelegramClient, events
from telethon.tl.types import Document
from bs4 import BeautifulSoup
from pathlib import Path
import asyncio

# ==== НАСТРОЙКИ ====
API_ID = 29212970
API_HASH = "a7a9d0feedcc6de6837b2c3026a6e33a"
SESSION_NAME = "session"
TARGET_BOT = "@userbox_100_bot"
HTML_FILE = Path("report.html")

# ==== TELETHON КЛИЕНТ ====
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    print("✅ Telethon client запущен")
    yield
    await client.disconnect()
    print("❎ Telethon client остановлен")

app = FastAPI(lifespan=lifespan)

# ==== Pydantic-модель для POST ====
class SearchRequest(BaseModel):
    query: str
    user_id: int

# ==== Парсинг HTML ====
def parse_html_report(html_content: str) -> tuple[str, int]:
    soup = BeautifulSoup(html_content, 'lxml')
    result = []

    for block in soup.select('.accordion-content'):
        header = block.find_previous('span')
        title = header.text.strip() if header else "Раздел"
        result.append(f'{title}')
        for row in block.select('.row'):
            key_tag = row.find('strong')
            val_tag = row.find('span')
            if key_tag and val_tag:
                key = key_tag.text.strip(':')
                val = val_tag.text.strip()
                result.append(f'├ {key}: {val}')
        result.append('└' + '─' * 20)

    text = '\n'.join(result)
    count = text.count('└────────────────────')
    return text, count

# ==== Единая логика ====
async def perform_search(query: str) -> dict:
    html_received = asyncio.Event()

    async def on_message(event):
        if event.document and isinstance(event.document, Document):
            if event.file.name.endswith('.html'):
                await client.download_media(event.message, file=HTML_FILE)
                html_received.set()

    client.add_event_handler(on_message, events.NewMessage(from_users=TARGET_BOT))
    await client.send_message(TARGET_BOT, query)

    try:
        await asyncio.wait_for(html_received.wait(), timeout=25)

        if not HTML_FILE.exists() or HTML_FILE.stat().st_size < 100:
            raise HTTPException(status_code=500, detail="⚠️ Полученный отчёт пуст или повреждён.")

        with open(HTML_FILE, encoding="utf-8") as f:
            html = f.read()

        parsed, count = parse_html_report(html)
        return {"parsed": parsed, "count": count}

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="⏳ Бот не прислал ответ.")
    finally:
        client.remove_event_handler(on_message, events.NewMessage(from_users=TARGET_BOT))

# ==== GET /search ====
@app.get("/search")
async def search_get(query: str = Query(..., description="Поисковый запрос")):
    return await perform_search(query)

# ==== POST /search ====
@app.post("/search")
async def search_post(data: SearchRequest):
    return await perform_search(data.query)
