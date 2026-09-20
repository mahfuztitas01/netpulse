"""HTML page routes (server-rendered shell + JS-driven dashboard)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..deps import COOKIE_NAME

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["pages"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.cookies.get(COOKIE_NAME):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"app_name": "NetPulse"})


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    if not request.cookies.get(COOKIE_NAME):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "index.html", {"app_name": "NetPulse"})
