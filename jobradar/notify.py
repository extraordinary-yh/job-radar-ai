"""Daily digest to Telegram (bot token + chat id from the environment or .env)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from .models import Job


def build_digest(date: str, jobs: list[Job], pages_url: str, hot: int = 85, top_n: int = 5) -> str:
    visible = [j for j in jobs if not j.excluded and not j.hidden and j.verdict != "applied"]
    visible.sort(key=lambda j: (-j.rank_score, j.company))
    new = [j for j in visible if j.status == "new"]
    lines = [f"job-radar {date}: {len(visible)} open, {len(new)} new"]
    fire = [j for j in visible if j.score >= hot]
    if fire:
        lines.append(f"🔥 {len(fire)} at {hot}+: " + "; ".join(f"{j.title} ({j.company}, {j.score})" for j in fire[:3]))
    for i, j in enumerate(visible[:top_n], 1):
        tag = " · new" if j.status == "new" else ""
        lines.append(f"{i}. {j.score} {j.title} — {j.company}, {j.location_class.replace('_', ' ')}{tag}\n{j.url}")
    if pages_url:
        lines.append(pages_url)
    return "\n".join(lines)


def send_telegram(text: str, token: str, chat_id: str, client: httpx.Client | None = None) -> dict[str, Any]:
    client = client or httpx.Client(timeout=30)
    r = client.post(f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True})
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"telegram: {data}")
    return data


def telegram_credentials() -> tuple[str, str]:
    return os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
