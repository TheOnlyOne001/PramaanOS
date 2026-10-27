"""FastAPI app: API routers plus the static worker app, employer console and verify page."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import config, console, core_api, edge, passport, pay, seed, state, voice


@asynccontextmanager
async def lifespan(app: FastAPI):
    st = state.get()
    if config.AUTOSEED and st.conn.execute("SELECT COUNT(*) FROM workers").fetchone()[0] == 0:
        seed.seed_all(st)
    yield


app = FastAPI(title="Saakshi", description="Shared, tamper-evident work records", lifespan=lifespan)
for m in (core_api, pay, voice, passport, edge, console):
    app.include_router(m.router)

for name in ("worker", "console", "verify", "shared"):
    d = config.WEB / name
    d.mkdir(parents=True, exist_ok=True)
    app.mount(f"/{name}", StaticFiles(directory=str(d), html=True), name=name)


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Saakshi</title><style>body{font:16px system-ui;max-width:560px;margin:40px auto;padding:0 16px}
a{display:block;padding:14px;margin:10px 0;border:1px solid #ccc;border-radius:10px;text-decoration:none}</style>
<h1>Saakshi · சாட்சி</h1><p>Shared, tamper-evident work records.</p>
<a href="/worker/?w=W001">Worker app (Meena)</a><a href="/console/">Employer console</a>
<a href="/verify/">Verify a skill credential</a><a href="/docs">API docs</a>"""
