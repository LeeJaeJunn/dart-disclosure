// 백엔드 API 호출과 응답 타입. /api/* 는 Vite 프록시가 FastAPI(8000)로 전달한다.
import { useEffect, useState } from "react";

// 공시가 저장된 기업 1곳 (GET /companies)
export type Company = {
  corp_code: string;
  corp_name: string;
  filing_count: number;
  latest_rcept_dt: string; // YYYYMMDD
};

// 저장된 공시 1건 (GET /companies/{corp_code}/filings)
export type Filing = {
  rcept_no: string;
  corp_code: string;
  corp_name: string;
  report_nm: string;
  report_type: string;
  period: string;
  rcept_dt: string; // YYYYMMDD
  is_latest: boolean;
  dart_url: string;
  has_summary: boolean; // 요약이 있는지 여부
};

// 공시 1건의 요약 (GET /filings/{rcept_no}/summary)
export type SummarySource = {
  section_path: string; // 원문 위치 (목차 경로)
  quote: string; // 근거 원문 발췌
};

export type SummarySection = {
  id: string;
  title: string;
  headline: string; // 한 줄 결론
  overview: string; // 원문에서 확인한 사실
  interpretation: string[]; // LLM 해석
  watch: string[]; // 지켜볼 항목
  table_markdown: string; // 섹션 표 (없으면 "")
  sources: SummarySource[];
};

export type FilingSummary = {
  rcept_no: string;
  corp_name: string;
  report_nm: string;
  rcept_dt: string; // YYYYMMDD
  dart_url: string;
  title: string;
  model: string;
  created_at: string; // ISO 8601
  sections: SummarySection[];
};

// 질의응답 (POST /qa/ask)
export type AskRequest = {
  question: string;
  top_k?: number; // 생략하면 5
};

// 답변 근거 1건. 답변 본문의 [n]과 n이 대응한다.
export type AskSource = {
  n: number;
  chunk_id: string;
  rcept_no: string; // 접수번호
  corp_name: string;
  report_nm: string; // 공시명
  rcept_dt: string; // YYYYMMDD
  section_path: string; // 원문 위치 (목차 경로)
  quote: string; // 근거 원문 발췌
  dart_url: string;
};

export type AskResponse = {
  type: "general" | "disclosure"; // general: 공시 검색 없이 답한 일반 대화
  answer: string;
  sources: AskSource[];
  search_args: Record<string, unknown> | null; // LLM이 정한 검색 조건 (확인용)
};

export async function ask(req: AskRequest): Promise<AskResponse> {
  const res = await fetch("/api/qa/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : null;
    throw new Error(detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<AskResponse>;
}

type FetchState<T> ={ data: T | null; error: string | null; loading: boolean };

// path의 JSON을 가져온다. path가 바뀌면 다시 가져온다.
export function useApi<T>(path: string): FetchState<T> {
  const [result, setResult] = useState<{
    path: string;
    data: T | null;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api${path}`)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.detail ?? `${res.status} ${res.statusText}`);
        }
        return res.json() as Promise<T>;
      })
      .then((data) => {
        if (!cancelled) setResult({ path, data, error: null });
      })
      .catch((err: Error) => {
        if (!cancelled) setResult({ path, data: null, error: err.message });
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  // 이전 path의 결과는 쓰지 않는다 (기업을 바꿨을 때 이전 기업 공시가 잠깐 보이지 않게)
  if (result?.path !== path) return { data: null, error: null, loading: true };
  return { data: result.data, error: result.error, loading: false };
}

// 20240312 → 2024.03.12
export function formatDate(yyyymmdd: string): string {
  if (!/^\d{8}$/.test(yyyymmdd)) return yyyymmdd;
  return `${yyyymmdd.slice(0, 4)}.${yyyymmdd.slice(4, 6)}.${yyyymmdd.slice(6)}`;
}
