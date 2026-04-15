"""
범용 RSS/Atom 피드 크롤러
crawler_type: "rss"

RSS는 사이트가 공식으로 제공하는 데이터 형식으로,
Cloudflare 등 봇 차단 없이 안정적으로 수집할 수 있습니다.
기사 본문이 피드에 포함되어 있어 별도 페이지 접속이 필요 없습니다.

sources.json 의 "url" 필드에 RSS 피드 URL을 입력하면 됩니다.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from .base import BaseCrawler, Post

logger = logging.getLogger(__name__)

# RSS/Atom 표준 XML 네임스페이스
_NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",  # 본문 전문
    "atom":    "http://www.w3.org/2005/Atom",               # Atom 피드
    "dc":      "http://purl.org/dc/elements/1.1/",          # Dublin Core (카테고리 등)
}


def _find_text(el, *paths: str, ns: dict = _NS) -> str:
    """여러 경로를 순서대로 시도해 첫 번째로 찾은 텍스트를 반환합니다."""
    for path in paths:
        node = el.find(path, ns)
        if node is not None and node.text:
            return node.text.strip()
    return ""


def _strip_html(text: str) -> str:
    """HTML 태그를 제거하고 연속 공백을 정리합니다."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _make_id(url: str) -> str:
    """URL 을 MD5 해싱해 16자리 고유 ID를 생성합니다."""
    return hashlib.md5(url.encode()).hexdigest()[:16]


def _parse_pubdate(item) -> datetime | None:
    """RSS <pubDate> 또는 Atom <published> 를 UTC datetime 으로 파싱합니다."""
    raw = (
        _find_text(item, "pubDate")
        or _find_text(item, "atom:published", ns=_NS)
        or _find_text(item, "dc:date")
    )
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        return dt.astimezone(timezone.utc)
    except Exception:
        try:
            # ISO 8601 형식 (Atom 등)
            raw_clean = raw.replace("Z", "+00:00")
            return datetime.fromisoformat(raw_clean).astimezone(timezone.utc)
        except Exception:
            return None


class RssCrawler(BaseCrawler):
    """범용 RSS/Atom 피드 크롤러. crawler_type: "rss" """

    MAX_CONTENT = 3000  # 본문 최대 길이 (토큰 절약)

    def fetch_post_list(self) -> list[Post]:
        """RSS 피드를 파싱해 Post 목록을 반환합니다."""
        response = self._get(self.config["url"])
        if not response:
            logger.error(f"[{self.config['id']}] RSS 요청 실패: {self.config['url']}")
            return []

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            logger.error(f"[{self.config['id']}] RSS XML 파싱 실패: {e}")
            return []

        # RSS 2.0: <item>, Atom: <entry>
        items = root.findall(".//item") or root.findall(".//atom:entry", _NS)
        posts: list[Post] = []

        for item in items:
            # 링크 추출: <link> 텍스트 → <guid> → Atom <link href="...">
            link = _find_text(item, "link", "guid")
            if not link or not link.startswith("http"):
                link_el = item.find("link")
                if link_el is not None:
                    link = link_el.get("href", "")
            if not link:
                continue

            title = _find_text(item, "title")
            category = _find_text(item, "category", "dc:subject")

            # 본문 우선순위: content:encoded (전문) > description (요약)
            raw_content = (
                _find_text(item, "content:encoded")
                or _find_text(item, "description")
            )
            content = _strip_html(raw_content)[: self.MAX_CONTENT]

            posts.append(Post(
                id=_make_id(link),
                title=title,
                url=link,
                category=category,
                content=content,
                published_at=_parse_pubdate(item),
            ))

        logger.info(f"[{self.config['id']}] RSS {len(posts)}개 수집")
        return posts

    def fetch_post_content(self, url: str) -> str:
        """RSS 본문은 fetch_post_list 에서 이미 수집되므로 별도 요청 없음."""
        return ""
