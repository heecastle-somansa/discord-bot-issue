"""
Discord Webhook 전송 모듈

모든 소스에서 동일한 embed 양식을 사용합니다:

┌──────────────────────────────────────────────┐
│ 🎮 게임메카              ← 소스 아이콘 + 이름  │
│                                              │
│ 기사 제목 (클릭 시 원문 이동)  ← title + url  │
│                                              │
│ 게임명: ...                                  │
│ 플랫폼: ...                  ← Groq 요약     │
│ 한줄평: ...                                  │
│ 요약: ...                                    │
│                                              │
│ 게임메카 · 2026-04-15 10:00  ← footer        │
└──────────────────────────────────────────────┘
"""

import logging
import os
import time
from datetime import datetime, timezone

import requests

from crawlers.base import Post

logger = logging.getLogger(__name__)

# Discord embed는 한 번에 최대 10개까지 전송 가능
DISCORD_CHUNK_SIZE = 10


def build_embed(post: Post, summary: str, source: dict) -> dict:
    """소스와 기사 정보로 Discord embed 딕셔너리를 생성합니다."""
    source_name = source.get("name", "이슈봇")
    source_icon = source.get("icon", "📌")
    color = source.get("color", 0x5865F2)
    homepage = source.get("homepage", source.get("url", ""))

    description = summary or "_(요약을 가져오지 못했습니다. 원문을 확인해 주세요.)_"
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return {
        "author": {
            "name": f"{source_icon}  {source_name}",
            "url": homepage,
        },
        "title": post.title,
        "url": post.url,
        "description": description,
        "color": color,
        "footer": {
            "text": f"{source_name}  ·  {now_utc}",
        },
    }


def post_to_discord(embeds: list[dict]) -> bool:
    """Discord Webhook으로 embed 목록을 전송합니다. 성공 여부를 반환합니다."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        logger.error("DISCORD_WEBHOOK_URL 환경 변수가 설정되지 않았습니다.")
        return False

    success = True
    for i in range(0, len(embeds), DISCORD_CHUNK_SIZE):
        chunk = embeds[i: i + DISCORD_CHUNK_SIZE]
        payload = {
            "username": "게임 이슈봇",
            "embeds": chunk,
        }
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if response.status_code in (200, 204):
                logger.info(f"Discord 전송 성공: {len(chunk)}개 embed")
            else:
                logger.error(f"Discord 전송 실패: HTTP {response.status_code} / {response.text[:200]}")
                success = False
        except requests.RequestException as e:
            logger.error(f"Discord 요청 오류: {e}")
            success = False

        time.sleep(1)

    return success
