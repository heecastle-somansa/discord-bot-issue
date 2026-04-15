"""
게임 이슈/추천 기사 필터링 + Groq AI 요약

이 봇의 목적:
  - 신규 출시가 아닌, 입소문을 타거나 재조명되는 게임 관련 기사 포스팅
  - 재밌는 게임 추천, 숨겨진 명작 발굴, 화제작 리뷰 등

처리 흐름:
  1. 키워드 필터  — API 호출 없이 관련 없는 기사를 먼저 제거
  2. Groq 요약    — 통과한 기사만 AI로 요약

키워드 필터 설계 기준:
  - INCLUDE: 추천/화제/명작/리뷰/입소문 등 게임 이슈성 키워드
  - EXCLUDE: 신규 출시/사전예약 등 신작 관련 키워드 (discord-bot-newgame 봇 담당)
             해킹/논란/서비스종료 등 부정적 이슈
             인터뷰/행사/콜라보 등 게임 내용과 무관한 기사
"""

import logging
import os
import time

from groq import Groq

from crawlers.base import Post

logger = logging.getLogger(__name__)

# ── 포함 키워드: 하나라도 제목에 있으면 AI 요약 대상 ─────────────────────
# 게임 추천·화제·재조명 관련
INCLUDE_KEYWORDS = [
    # 추천·인기
    "추천", "강추", "필수", "해볼만한", "해봐야",
    # 입소문·화제
    "입소문", "화제", "화제작", "화제의", "주목",
    # 재조명·명작
    "재조명", "명작", "숨겨진", "숨작", "레전드", "역대급", "역대",
    "갓겜", "꿀잼", "재미", "재밌", "완성도",
    # 리뷰·평가
    "리뷰", "평가", "평점", "호평", "극찬", "메타크리틱", "오픈크리틱",
    "GOTY", "올해의 게임",
    # 트렌드·랭킹
    "인기 급상승", "스팀 인기", "스팀차트", "판매 1위", "판매순위",
    "동접", "동시접속",
    # 할인·무료
    "무료", "할인", "게임패스", "플러스", "에픽 무료",
    # 재발견·복귀
    "다시 해보", "재발견", "복귀", "귀환", "컴백",
]

# ── 제외 키워드: 하나라도 제목에 있으면 무조건 제외 ──────────────────────
EXCLUDE_KEYWORDS = [
    # 신작 출시 (discord-bot-newgame 봇 담당)
    "신작", "정식 출시", "정식출시", "정식 발매", "정식발매",
    "사전예약", "사전 예약", "출시 예정", "발매 예정", "출시일",
    "얼리 액세스", "앞서 해보기", "사전 다운로드",
    # 부정적 이슈
    "해킹", "유출", "논란", "서비스 종료", "개인정보",
    "피싱", "사기", "소송", "폐쇄", "폐업",
    # 업계 이슈 (게임 내용 무관)
    "인터뷰", "행사", "채용", "인수", "합병", "상장",
    "실적", "매출", "분기", "연간",
    # 기타 잡음
    "루머", "유언비어", "추측",
]

# ── Groq 설정 ─────────────────────────────────────────────────────────────
MODEL = "llama-3.3-70b-versatile"
MAX_RETRIES = 2
RETRY_DELAY = 30
INTER_REQUEST_DELAY = 3

_client = None


def _get_client() -> Groq:
    """Groq 클라이언트를 초기화합니다 (최초 1회)."""
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise EnvironmentError("GROQ_API_KEY 환경 변수가 설정되지 않았습니다.")
        _client = Groq(api_key=api_key)
        logger.info(f"Groq 클라이언트 초기화 완료 (모델: {MODEL})")
    return _client


def _call_groq(prompt: str) -> str:
    """Groq API를 호출합니다. 한도 초과 시 최대 MAX_RETRIES 번 재시도합니다."""
    for attempt in range(MAX_RETRIES):
        try:
            client = _get_client()
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            err = str(e)
            if "429" in err or "rate" in err.lower():
                wait = RETRY_DELAY * (attempt + 1)
                logger.warning(f"Groq 한도 — {wait}초 후 재시도 ({attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
            else:
                logger.error(f"Groq 오류: {e}")
                return ""

    logger.error("Groq 최대 재시도 초과")
    return ""


def _keyword_match(title: str, content: str) -> bool:
    """제목·본문 기준으로 게임 이슈/추천 기사인지 판단합니다."""
    title_lower = title.lower()

    # 제외 키워드가 제목에 있으면 즉시 탈락
    if any(kw in title_lower for kw in EXCLUDE_KEYWORDS):
        return False

    # 포함 키워드가 제목에 있으면 통과
    if any(kw.lower() in title_lower for kw in INCLUDE_KEYWORDS):
        return True

    # 제목에 없어도 본문 앞부분에 강한 추천·화제 키워드가 있으면 통과
    strong_keywords = ["강력 추천", "명작", "갓겜", "입소문", "화제", "재조명"]
    content_preview = content[:300].lower()
    return any(kw in content_preview for kw in strong_keywords)


def filter_and_summarize(post: Post, source: dict) -> str | None:
    """
    기사를 필터링하고 요약합니다.
    - 게임 이슈/추천 관련 → AI 요약문 반환
    - 관련 없음           → None 반환 (Discord에 올리지 않음)
    - AI 실패             → 본문 앞부분으로 대체 반환
    """
    if not _keyword_match(post.title, post.content):
        logger.info(f"[필터 제외] {post.title[:50]}")
        return None

    logger.info(f"[필터 통과] {post.title[:50]}")

    body = post.content[:1500] if post.content else "(본문 없음)"
    prompt = f"""다음 게임 기사를 읽고, 이 게임을 해볼 만한지 판단해서 요약해 주세요.

제목: {post.title}
본문: {body}

아래 형식으로 작성하세요 (이모지 금지, ~습니다 체):
게임명: (게임 이름)
플랫폼: (PC / 모바일 / 콘솔 / 멀티플랫폼 중 해당, 모르면 미상)
한줄평: (왜 화제인지 또는 왜 추천받는지 한 줄 요약)
요약: (기사 핵심 내용 2~3줄. 어떤 점이 재밌는지, 왜 입소문이 났는지 중심으로)"""

    time.sleep(INTER_REQUEST_DELAY)
    result = _call_groq(prompt)

    if not result:
        logger.warning(f"AI 실패 — 본문으로 대체: {post.title[:40]}")
        return post.content[:300].strip() or "(요약 없음 — 원문 링크를 확인해 주세요)"

    return result
