import { useState } from "react";
import { Link, useParams } from "react-router";
import { formatDate, useApi, type Filing } from "../api";
import SummaryModal from "../components/SummaryModal";
import "./Filings.css";

// 기업 페이지: 기업 1곳의 저장 공시 목록 (최근 공시일 순)
function CompanyPage() {
  const { corpCode } = useParams();
  const {
    data: filings,
    error,
    loading,
  } = useApi<Filing[]>(`/companies/${corpCode}/filings`);
  // 요약 모달을 열어 둔 공시 (없으면 null)
  const [summaryOf, setSummaryOf] = useState<Filing | null>(null);

  // 기업명은 가장 최근 공시의 것을 쓴다 (기업 테이블이 없음)
  const corpName = filings?.[0]?.corp_name;

  return (
    <main className="page">
      <Link className="back" to="/">
        ← 기업 목록
      </Link>
      <h1>{corpName ?? corpCode}</h1>
      {corpName && <p className="sub">기업 고유번호 {corpCode}</p>}

      {loading && <p className="status">불러오는 중...</p>}
      {error && <p className="status error">불러오기 실패: {error}</p>}

      {filings && (
        <ul className="rows">
          {filings.map((f) => (
            <li key={f.rcept_no} className="row-with-action">
              {/* 공시를 누르면 DART 원문으로 이동 */}
              <a
                className="row"
                href={f.dart_url}
                target="_blank"
                rel="noreferrer"
              >
                <span className="row-main">
                  <strong>{f.report_nm}</strong>
                  <span className="sub">
                    <span className="tag">{f.report_type}</span>
                    접수번호 {f.rcept_no}
                  </span>
                </span>
                <span className="row-side">
                  <span>{formatDate(f.rcept_dt)}</span>
                  <span className="sub">DART 원문 ↗</span>
                </span>
              </a>
              {f.has_summary && (
                <button
                  className="summary-button"
                  onClick={() => setSummaryOf(f)}
                >
                  요약
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {summaryOf && (
        <SummaryModal
          rceptNo={summaryOf.rcept_no}
          reportNm={summaryOf.report_nm}
          onClose={() => setSummaryOf(null)}
        />
      )}
    </main>
  );
}

export default CompanyPage;
