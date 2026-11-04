import io
import json
import logging
import zipfile
from pathlib import PurePosixPath
from typing import Literal
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, ConfigDict

from src.config import settings

BASE_URL = "https://opendart.fss.or.kr/api"
STATUS_OK = "000"
STATUS_NO_DATA = "013"

# httpx는 INFO 로그에 요청 URL을 남기는데, DART는 API 키를 쿼리로 받는다.
logging.getLogger("httpx").setLevel(logging.WARNING)


class DartApiError(RuntimeError):
    pass


class CorpCode(BaseModel):
    corp_code: str
    corp_name: str
    stock_code: str | None  # 비상장사는 None


# 공시 목록 검색 조건. page_no, page_count는 fetch_disclosures가 처리한다.
class DisclosureQuery(BaseModel):
    corp_code: str | None = None  # 고유번호(8자리). 삼성전자: 00126380
    bgn_de: str | None = None  # YYYYMMDD, 기본값: end_de. corp_code 없으면 기간 3개월 제한
    end_de: str | None = None  # YYYYMMDD, 기본값: 당일
    last_reprt_at: Literal["Y", "N"] | None = None  # 최종보고서만 검색 여부, 기본값: N
    # A: 정기공시, B: 주요사항보고, C: 발행공시, D: 지분공시, E: 기타공시,
    # F: 외부감사관련, G: 펀드공시, H: 자산유동화, I: 거래소공시, J: 공정위공시
    pblntf_ty: Literal["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"] | None = None
    pblntf_detail_ty: str | None = None  # 공시상세유형(4자리), 예: A001(사업보고서)
    corp_cls: Literal["Y", "K", "N", "E"] | None = None  # 유가, 코스닥, 코넥스, 기타
    sort: Literal["date", "crp", "rpt"] | None = None  # 접수일자, 회사명, 보고서명. 기본값: date
    sort_mth: Literal["asc", "desc"] | None = None  # 기본값: desc


class Disclosure(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    rcept_no: str
    report_nm: str
    rcept_dt: str
    corp_code: str
    corp_name: str
    corp_cls: str
    flr_nm: str
    rm: str


# 공시 원문을 구성하는 파일 하나. 사업보고서는 본문 외에 감사보고서 파일이 함께 온다.
class DisclosureFile(BaseModel):
    file_name: str
    content: str


# 기업 고유번호 목록
async def fetch_corp_codes() -> list[CorpCode]:
    content = await _get("corpCode.xml")
    files = _read_zip(content)
    return _parse_corp_codes(files[min(files)])


# 공시 목록. 날짜를 생략하면 당일 공시만 조회된다.
async def fetch_disclosures(query: DisclosureQuery) -> list[Disclosure]:
    disclosures: list[Disclosure] = []
    page_no = 1
    while True:
        content = await _get(
            "list.json",
            **query.model_dump(exclude_none=True),
            page_no=page_no,
            page_count=100,
        )
        data = json.loads(content)
        if data["status"] == STATUS_NO_DATA:
            return disclosures
        if data["status"] != STATUS_OK:
            raise DartApiError(f"DART 오류 {data['status']}: {data['message']}")
        disclosures += [Disclosure(**item) for item in data["list"]]
        if page_no >= data["total_page"]:
            return disclosures
        page_no += 1


# 공시 원문 파일 목록. 본문 파일({rcept_no}.xml)이 맨 앞에 온다.
async def fetch_document(rcept_no: str) -> list[DisclosureFile]:
    content = await _get("document.xml", rcept_no=rcept_no)
    files = _read_zip(content)
    return [
        DisclosureFile(file_name=name, content=_decode(files[name]))
        for name in sorted(files)
    ]


# DART에 HTTP 요청
async def _get(path: str, **params: str | int) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                f"{BASE_URL}/{path}",
                params={"crtfc_key": settings.opendart_api_key, **params},
            )
            response.raise_for_status()
    except httpx.HTTPError as e:
        # 원본 예외 메시지에는 API 키가 포함된 URL이 들어갈 수 있어 연결하지 않는다.
        raise DartApiError(f"DART 요청 실패: {path} ({type(e).__name__})") from None
    return response.content


# ZIP 응답의 압축을 풀어 {파일명: 내용}으로 반환
def _read_zip(content: bytes) -> dict[str, bytes]:
    # DART는 오류도 HTTP 200으로, zip 대신 status와 message가 담긴 XML로 응답한다.
    if not zipfile.is_zipfile(io.BytesIO(content)):
        root = ElementTree.fromstring(content)
        raise DartApiError(
            f"DART 오류 {root.findtext('status')}: {root.findtext('message')}"
        )
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        # 오래된 공시는 파일명이 "/"로 시작하기도 해서 경로를 제거한다.
        return {PurePosixPath(name).name: z.read(name) for name in z.namelist()}


# 파일 내용을 문자열로 변환. 오래된 공시는 UTF-8이 아닐 수 있다.
def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp949", errors="replace")


# 기업 목록 XML을 CorpCode 리스트로 변환
def _parse_corp_codes(xml: bytes) -> list[CorpCode]:
    return [
        CorpCode(
            corp_code=item.findtext("corp_code", "").strip(),
            corp_name=item.findtext("corp_name", "").strip(),
            stock_code=item.findtext("stock_code", "").strip() or None,
        )
        for item in ElementTree.fromstring(xml).iter("list")
    ]
