"""
크롤러 기반 클래스 및 Post 데이터 모델

새 사이트 추가 방법:
  1. 이 파일의 BaseCrawler 를 상속받는 클래스를 crawlers/ 폴더에 새 파일로 작성
  2. fetch_post_list() 와 fetch_post_content() 구현
  3. crawlers/__init__.py 의 CRAWLER_REGISTRY 에 등록
  4. config/sources.json 에 "crawler_type": "등록한_키" 로 소스 추가
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


@dataclass
class Post:
    """수집된 기사 한 건을 나타내는 데이터 모델."""
    id: str           # 기사 고유 식별자 (URL 해시 또는 게시글 번호)
    title: str        # 기사 제목
    url: str          # 기사 원문 URL
    category: str = ""              # 카테고리 (없으면 빈 문자열)
    comment_count: str = "0"        # 댓글 수 (RSS 소스는 항상 "0")
    content: str = ""               # 기사 본문
    published_at: object = None     # 기사 발행 시각 (datetime, 없으면 None)


class BaseCrawler(ABC):
    """모든 크롤러의 공통 기반 클래스."""

    # 봇 감지 우회를 위한 브라우저 수준 HTTP 헤더
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    # 요청 간 기본 대기 시간 (서버 부하 방지)
    REQUEST_DELAY = 2.0

    def __init__(self, config: dict):
        self.config = config
        self._session = requests.Session()
        self._session.headers.update(self.HEADERS)

    @abstractmethod
    def fetch_post_list(self) -> list[Post]:
        """소스에서 기사 목록을 수집합니다."""

    @abstractmethod
    def fetch_post_content(self, url: str) -> str:
        """개별 기사 URL에서 본문 텍스트를 추출합니다.
        RSS 크롤러처럼 본문이 이미 있는 경우 빈 문자열을 반환합니다."""

    def _get(self, url: str, timeout: int = 20) -> requests.Response | None:
        """GET 요청 헬퍼. 실패 시 None 반환."""
        try:
            response = self._session.get(url, timeout=timeout)
            logger.info(f"GET {url} → HTTP {response.status_code}")
            response.raise_for_status()
            time.sleep(self.REQUEST_DELAY)
            return response
        except requests.HTTPError as e:
            logger.error(f"GET 실패 (HTTP {e.response.status_code}): {url}")
            return None
        except requests.RequestException as e:
            logger.error(f"GET 실패 ({type(e).__name__}): {url}")
            return None
