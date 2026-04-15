"""
게임 이슈/추천 뉴스봇 — 메인 진입점
GitHub Actions 에서 `python bot.py` 로 실행됩니다.

실행 흐름:
  1. config/sources.json 에서 활성화된 소스 목록 로드
  2. 각 소스별로 RSS 피드 수집
  3. 시간 필터: 최근 N시간(기본 7h) 이내 발행된 기사만 처리
  4. 중복 제거: seen_posts.json 에 기록된 기사 제외
  5. 키워드 필터 → Groq AI 요약
  6. Discord Webhook 으로 embed 전송
  7. 처리된 기사 ID를 seen_posts.json 에 저장 (중복 방지)
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from crawlers import CRAWLER_REGISTRY
from discord_poster import build_embed, post_to_discord
from summarizer import filter_and_summarize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

SOURCES_FILE = Path("config/sources.json")
SEEN_FILE = Path("seen_posts.json")


def load_sources() -> list[dict]:
    """sources.json 에서 enabled=true 인 소스만 반환합니다."""
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    return [s for s in data["sources"] if s.get("enabled", True)]


def load_seen() -> dict[str, list[str]]:
    """seen_posts.json 을 로드합니다. 파일이 없으면 빈 딕셔너리를 반환합니다."""
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            pass
    return {}


def save_seen(seen: dict[str, list[str]]) -> None:
    """처리된 기사 ID 목록을 seen_posts.json 에 저장합니다."""
    SEEN_FILE.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run() -> None:
    logger.info("=" * 60)
    logger.info("게임 이슈봇 실행 시작")

    sources = load_sources()
    seen = load_seen()
    all_embeds: list[dict] = []
    updated_seen = {k: list(v) for k, v in seen.items()}

    for source in sources:
        source_id = source["id"]
        crawler_cls = CRAWLER_REGISTRY.get(source.get("crawler_type", ""))

        if not crawler_cls:
            logger.warning(f"[{source_id}] 알 수 없는 crawler_type — 건너뜁니다.")
            continue

        logger.info(f"[{source_id}] 수집 시작: {source['url']}")

        crawler = crawler_cls(source)
        posts = crawler.fetch_post_list()

        # ── 시간 기반 필터: 최근 N시간 이내 발행된 기사만 처리 ──
        # 6시간마다 실행 기준, lookback_hours 기본값 7 (약간의 여유분 포함)
        lookback_hours: int = source.get("lookback_hours", 7)
        cutoff: datetime = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        time_filtered: list = []
        for p in posts:
            if p.published_at is None:
                # 발행 시각 정보가 없으면 통과 (안전하게 포함)
                time_filtered.append(p)
            elif p.published_at >= cutoff:
                time_filtered.append(p)
            else:
                logger.debug(
                    f"[{source_id}] 시간 필터 제외 "
                    f"({p.published_at.strftime('%Y-%m-%d %H:%M UTC')}): {p.title[:40]}"
                )
        logger.info(
            f"[{source_id}] 시간 필터({lookback_hours}h) 후: "
            f"{len(posts)}개 → {len(time_filtered)}개 (기준: {cutoff.strftime('%Y-%m-%d %H:%M UTC')})"
        )

        # ── 중복 제거: seen_posts.json 기준 ──
        seen_ids: set[str] = set(updated_seen.get(source_id, []))
        max_per_run: int = source.get("max_posts_per_run", 5)
        new_posts = [p for p in time_filtered if p.id not in seen_ids][:max_per_run]

        if not new_posts:
            logger.info(f"[{source_id}] 신규 기사 없음")
            continue

        logger.info(f"[{source_id}] 신규 기사 {len(new_posts)}개 → 필터링 및 요약")

        for post in new_posts:
            if not post.content:
                post.content = crawler.fetch_post_content(post.url)

            summary = filter_and_summarize(post, source)
            seen_ids.add(post.id)  # 필터 제외 기사도 다음 실행에서 재처리하지 않음

            if summary is None:
                continue

            all_embeds.append(build_embed(post, summary, source))
            time.sleep(1)

        updated_seen[source_id] = list(seen_ids)

    if not all_embeds:
        logger.info("전송할 기사 없음 — 종료")
        save_seen(updated_seen)
        return

    logger.info(f"Discord 전송 시작: 총 {len(all_embeds)}개")
    success = post_to_discord(all_embeds)

    if success:
        save_seen(updated_seen)
        logger.info("seen_posts.json 저장 완료")
    else:
        # 전송 실패 시 seen 저장 안 함 → 다음 실행 때 재시도
        logger.error("Discord 전송 실패 — 다음 실행 시 재시도됩니다.")

    logger.info("게임 이슈봇 실행 종료")
    logger.info("=" * 60)


if __name__ == "__main__":
    run()
