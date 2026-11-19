"""근거 준비와 검증 (LLM 호출 없음).

- excerpt(): 긴 목차 섹션을 글자 예산 안으로 줄인다 (키워드가 들어간 문단 우선, 실패하면 앞부분)
- verify_evidence(): LLM이 낸 근거 인용문의 숫자가 원문에 있는지 확인한다
- unverified_table_numbers(): LLM이 만든 표의 숫자 중 원문에 없는 것을 찾는다
"""

import re

PIECE_CHARS = 3000  # 발췌할 때 문단(표) 1개의 최대 글자
MIN_EXCERPT_RATIO = 0.3  # 키워드 발췌가 예산의 30% 미만이면 키워드가 본문과 안 맞은 것 → 앞부분으로 대신

_QUOTE_NUM = re.compile(r"\d[\d,.]*\d|\d")  # 인용문 속 숫자
_TABLE_NUM = re.compile(r"\d[\d,]*\.?\d*")  # 표 속 숫자


def excerpt(page: str, keywords: list[str], limit: int) -> tuple[str, bool]:
    """page를 limit 글자 안으로 줄인다. (결과, 잘렸는지)"""
    if len(page) <= limit:
        return page, False
    text = _keyword_excerpt(page, keywords, limit)
    if len(text) < limit * MIN_EXCERPT_RATIO:
        text = _head_excerpt(page, limit)
    return text, True


def _keyword_excerpt(page: str, keywords: list[str], limit: int) -> str:
    """키워드가 많이 들어간 문단(표)부터 고르고, 고른 문단의 바로 앞 문단(소제목·단위)도 함께 넣는다.
    원래 순서를 유지한다."""
    parts = page.split("\n\n")
    terms = [re.sub(r"\s+", "", k).lower() for k in keywords if k.strip()]
    score = [sum(t in re.sub(r"\s+", "", p.lower()) for t in terms) for p in parts]
    keep = {0}  # 첫 문단은 목차 제목
    for i in sorted(range(len(parts)), key=lambda i: -score[i]):
        if score[i] == 0:
            break
        keep |= {i - 1, i} if i > 0 else {i}
        if sum(min(len(parts[j]), PIECE_CHARS) for j in keep) > limit:
            keep.discard(i)
            break
    out: list[str] = []
    used = 0
    for j in sorted(keep):
        piece = parts[j] if len(parts[j]) <= PIECE_CHARS else parts[j][:PIECE_CHARS] + " …(표 일부 생략)"
        if used + len(piece) > limit:
            break
        out.append(piece)
        used += len(piece)
    if len(out) <= 1:  # 제목만 남음 = 키워드가 맞지 않음
        return ""
    return "\n\n".join(out) + f"\n\n(※ 긴 섹션이라 관련 부분만 발췌: {used:,}/{len(page):,}자)"


def _head_excerpt(page: str, limit: int) -> str:
    """앞부분을 문단 단위로 limit 안에서 자른다."""
    out: list[str] = []
    used = 0
    for p in page.split("\n\n"):
        if used + len(p) > limit:
            if not out:  # 첫 문단이 예산보다 길면 잘라서라도 넣는다
                out.append(p[:limit])
                used = len(out[0])
            break
        out.append(p)
        used += len(p) + 2
    return "\n\n".join(out) + f"\n\n(※ 긴 섹션이라 앞부분만 사용: {used:,}/{len(page):,}자)"


def verify_evidence(quote: str, source_text: str | None) -> list[str]:
    """근거 1건의 문제 목록. 비어 있으면 검증 통과.
    source_text가 None이면 LLM이 받지 않은 chunk_id를 쓴 것이다."""
    if source_text is None:
        return ["조회하지 않은 chunk_id"]
    missing = [n for n in _QUOTE_NUM.findall(quote) if n not in source_text]
    return [f"원문에 없는 숫자: {missing[:5]}"] if missing else []


def unverified_table_numbers(table_markdown: str, texts: list[str]) -> list[str]:
    """표 안의 숫자 중 근거 원문 어디에도 없는 것. 콤마 유무는 같은 숫자로 보고,
    연도·기수처럼 짧은 숫자(3자리 미만)는 건너뛴다."""
    if not table_markdown.strip():
        return []
    hay = "\n".join(texts)
    hay_no_comma = hay.replace(",", "")
    out: list[str] = []
    for raw in _TABLE_NUM.findall(table_markdown):
        n = raw.rstrip(".,")
        if len(n.replace(",", "").replace(".", "")) < 3:
            continue
        if n in hay or n.replace(",", "") in hay_no_comma:
            continue
        out.append(n)
    return list(dict.fromkeys(out))
