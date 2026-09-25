import httpx
import pytest

from jobradar.models import Job
from jobradar.notify import build_digest, send_telegram


def job(i, score, status="new", company="G", verdict=None):
    return Job(id=f"g:{i}", company=company, title=f"Role {i}", url=f"https://g/{i}", location_class="nyc",
               status=status, score=score, rank_score=float(score), verdict=verdict)


def test_build_digest_lists_top_and_hot():
    jobs = [job(1, 90), job(2, 70, status="open"), job(3, 95, verdict="applied"), job(4, 50)]
    text = build_digest("2026-09-02", jobs, "https://x.github.io/", hot=85, top_n=2)
    assert text.startswith("job-radar 2026-09-02: 3 open, 2 new")
    assert "🔥 1 at 85+: Role 1 (G, 90)" in text
    assert "1. 90 Role 1" in text and "2. 70 Role 2" in text and "Role 4" not in text and "Role 3" not in text
    assert text.rstrip().endswith("https://x.github.io/")


def test_send_telegram_posts_message():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url); seen["json"] = request.read()
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    out = send_telegram("hi", "TOKEN", "123", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["ok"] and seen["url"] == "https://api.telegram.org/botTOKEN/sendMessage" and b'"chat_id": "123"' in seen["json"] or b'"chat_id":"123"' in seen["json"]


def test_send_telegram_raises_on_error():
    def handler(request):
        return httpx.Response(200, json={"ok": False, "description": "bad token"})

    with pytest.raises(RuntimeError, match="bad token"):
        send_telegram("hi", "T", "1", client=httpx.Client(transport=httpx.MockTransport(handler)))
