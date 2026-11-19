"""기업분석 보고서(company_analysis)의 섹션 정의.

섹션마다 읽을 공시 목차를 정해 두고, 그 목차의 section 청크만 읽어 LLM이 요약한다 (검색·임베딩 없음).

    patterns      section_path에 이 글자가 들어간 section 청크를 읽는다.
                  하위 목차도 함께 잡힌다 (예: "IV. 이사의 경영진단" → IV 아래 1~6).
    keywords      긴 목차를 줄일 때 이 단어가 들어간 문단을 고른다 (본문에 실제로 나오는 단어).
    instruction   이 섹션에서 다룰 내용. 공통 형식(특징 → 데이터 → 해석)은 prompts.SECTION_SYSTEM.
    table         True면 데이터 표를 반드시 요구한다.
    report_types  이 섹션을 만들 공시 종류. 비우면 전부.
    summary       True면 공시 대신 다른 섹션의 결과만 읽고 "한눈에 보기"를 쓴다 (마지막에 생성).

근거가 없는 섹션(예: 분기보고서의 경영진단)은 status가 no_evidence가 되어 화면에서 빠진다.
"""

from dataclasses import dataclass, field

TEMPLATE_ID = "company_analysis"
TEMPLATE_TITLE = "기업분석 보고서"

PAGE_CHARS = 7000  # 목차 섹션 1개당 LLM에 넣는 최대 글자
MAX_PAGES = 8  # 보고서 섹션 1개가 읽는 목차 섹션 수 상한
CONTEXT_CHARS = 22000  # 보고서 섹션 1개의 근거 총량 상한


@dataclass(frozen=True)
class SectionSpec:
    id: str
    title: str
    instruction: str
    patterns: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    table: bool = False
    report_types: list[str] = field(default_factory=list)
    summary: bool = False


SECTIONS: list[SectionSpec] = [
    SectionSpec(
        id="summary",
        title="한눈에 보기",
        summary=True,
        instruction="보고서 전체에서 이 기업의 가장 두드러진 특징 3~4가지를 잇고, 투자자가 점검할 포인트를 정리한다.",
    ),
    SectionSpec(
        id="overview",
        title="사업 구조",
        patterns=["사업의 개요", "주요 제품 및 서비스"],
        keywords=["사업 개요", "사업 부문", "주력 사업", "사업 구조", "주요 제품", "제품별", "매출 비중", "서비스별"],
        instruction=(
            "무엇으로 돈을 버는 회사인지, 사업부문과 주력 제품의 구성과 비중이 특징이다. "
            "매출 총액·이익 같은 실적 숫자는 '실적' 섹션에서 다루므로 쓰지 않는다. 비중(%)과 제품 구성만 쓴다."
        ),
    ),
    SectionSpec(
        id="financials",
        title="실적",
        patterns=["1. 요약재무정보"],
        keywords=["매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계", "연결", "요약"],
        table=True,
        instruction=(
            "성장과 수익성이 어떤 모습인지가 특징이다. 요약연결재무정보 기준(없으면 별도임을 밝힘)으로 매출액, 영업이익, "
            "당기순이익, 자산총계, 부채총계, 자본총계를 표로 보여준다. 표는 항목을 행, 기간(기수)을 열로 둔다. "
            "해석에서 증감 배수, 영업이익률, 부채비율 등을 반올림해 제시한다."
        ),
    ),
    SectionSpec(
        id="sales",
        title="판매와 수주",
        patterns=["매출 및 수주상황"],
        keywords=["수주", "판매 실적", "지역별 매출", "부문별 매출", "판매경로", "수출", "내수"],
        instruction=(
            "어디에 어떻게 파는지(부문·지역·판매경로)와 수주 상황이 특징이다. 매출 총액은 '실적' 섹션에서 다루므로 "
            "반복하지 않고, 구성·경로·수주잔고처럼 이 섹션에만 있는 내용을 쓴다."
        ),
    ),
    SectionSpec(
        id="operations",
        title="생산과 원가",
        patterns=["원재료 및 생산설비"],
        keywords=["원재료", "생산능력", "가동률", "생산설비", "설비투자", "CAPA"],
        instruction="생산능력·가동률, 주요 원재료와 가격 변동 요인, 설비투자 규모가 특징이다. 단위가 없는 표는 확인할 점에 적는다.",
    ),
    SectionSpec(
        id="risk",
        title="리스크",
        patterns=["위험관리 및 파생거래", "2. 우발부채 등에 관한 사항"],
        keywords=["환율", "금리", "이자율", "파생", "위험관리", "헤지", "소송", "우발부채", "채무보증", "약정"],
        instruction=(
            "가장 중요한 위험 2~3가지만 고른다(예: 환율 민감도, 금리, 우발부채·소송·지급보증). "
            "모든 통화·항목을 나열하지 말고 영향이 큰 것만 표로 보여준다."
        ),
    ),
    SectionSpec(
        id="management",
        title="경영진 시각",
        patterns=["IV. 이사의 경영진단"],
        # 섹션 이름(경영진단·분석의견)이 아니라 본문에 나오는 단어로 발췌해야 내용이 잡힌다
        keywords=["개요", "매출", "영업이익", "영업손실", "실적", "재무", "부채비율", "전망", "투자", "시장", "증가", "감소", "사업부문"],
        report_types=["사업보고서"],  # 반기·분기보고서는 이 항목을 기재하지 않는다
        instruction="경영진이 설명하는 실적 변동 원인, 사업 전망, 중점 추진 사항이 특징이다.",
    ),
    SectionSpec(
        id="shareholders",
        title="주주와 배당",
        patterns=["VII. 주주에 관한 사항", "6. 배당에 관한 사항"],
        keywords=["최대주주", "특수관계인", "지분율", "5% 이상", "소액주주", "배당", "배당금", "배당성향", "주당배당"],
        instruction="지배구조(최대주주·주요 주주 지분)와 주주환원(주당배당금·배당성향·배당정책)이 특징이다.",
    ),
]


def sections_for(report_type: str) -> list[SectionSpec]:
    """이 공시 종류의 보고서에 들어가는 섹션 (report_types로 제한된 섹션은 해당 종류에만)."""
    return [spec for spec in SECTIONS if not spec.report_types or report_type in spec.report_types]
