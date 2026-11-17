import { Link } from "react-router";
import { formatDate, useApi, type Company } from "../api";
import "./Filings.css";

// 기업 목록 페이지 (메인): 공시가 저장된 기업 목록
function CompaniesPage() {
  const { data: companies, error, loading } = useApi<Company[]>("/companies");

  return (
    <main className="page">
      <h1>기업 목록</h1>

      {loading && <p className="status">불러오는 중...</p>}
      {error && <p className="status error">불러오기 실패: {error}</p>}
      {companies?.length === 0 && (
        <p className="status">저장된 공시가 없습니다.</p>
      )}

      {companies && companies.length > 0 && (
        <ul className="rows">
          {companies.map((c) => (
            <li key={c.corp_code}>
              <Link className="row" to={`/company/${c.corp_code}`}>
                <span className="row-main">
                  <strong>{c.corp_name}</strong>
                  <span className="sub">{c.corp_code}</span>
                </span>
                <span className="row-side">
                  <span>공시 {c.filing_count}건</span>
                  <span className="sub">
                    최근 {formatDate(c.latest_rcept_dt)}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

export default CompaniesPage;
