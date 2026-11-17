import { useEffect, useRef } from "react";
import {
  formatDate,
  useApi,
  type FilingSummary,
  type SummarySection,
} from "../api";
import "./SummaryModal.css";

type Props = {
  rceptNo: string;
  reportNm: string; // 요약을 불러오는 동안 제목에 보여줄 공시명
  onClose: () => void;
};

// 공시 1건의 요약을 모달로 보여준다. Esc, 바깥 클릭, 닫기 버튼으로 닫는다.
function SummaryModal({ rceptNo, reportNm, onClose }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const {
    data: summary,
    error,
    loading,
  } = useApi<FilingSummary>(`/filings/${rceptNo}/summary`);

  useEffect(() => {
    // 정리(cleanup)에서 close()를 부르지 않는다. 개발 모드(StrictMode)는 effect를 두 번 실행하는데,
    // 그때 close 이벤트가 발생해 onClose가 불리면 모달이 열리자마자 닫힌다.
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  return (
    <dialog
      ref={dialogRef}
      className="summary-modal"
      onClose={onClose}
      onClick={(e) => {
        // 내용 바깥(배경)을 누르면 닫는다
        if (e.target === dialogRef.current) onClose();
      }}
    >
      <div className="summary-body">
        <header className="summary-header">
          <div>
            <h2>{summary ? summary.title : "공시 요약"}</h2>
            <p className="summary-meta">
              {summary
                ? `${summary.corp_name} · ${summary.report_nm} · 공시일 ${formatDate(summary.rcept_dt)} · 접수번호 ${summary.rcept_no}`
                : reportNm}
            </p>
          </div>
          <button className="summary-close" onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </header>

        {loading && <p className="summary-status">불러오는 중...</p>}
        {error && (
          <p className="summary-status error">불러오기 실패: {error}</p>
        )}

        {summary && (
          <>
            {summary.sections.map((s) => (
              <SectionView key={s.id} section={s} />
            ))}
            <footer className="summary-footer">
              <span>
                AI({summary.model})가 생성한 요약입니다. 정확한 내용은 원문을
                확인하세요.
              </span>
              <a href={summary.dart_url} target="_blank" rel="noreferrer">
                DART 원문 ↗
              </a>
            </footer>
          </>
        )}
      </div>
    </dialog>
  );
}

// 본문의 인용 번호 [n]을 지운다.
// 현재 데이터는 [n]이 근거 번호와 맞지 않아 그대로 두면 잘못된 근거를 가리킨다.
function stripCitations(text: string): string {
  return text.replace(/\s*\[\d+\]/g, "");
}

function SectionView({ section }: { section: SummarySection }) {
  return (
    <section className="summary-section">
      <h3>{section.title}</h3>
      <p className="headline">{section.headline}</p>
      <p>{stripCitations(section.overview)}</p>

      {section.table_markdown && (
        <MarkdownTable markdown={section.table_markdown} />
      )}

      {section.interpretation.length > 0 && (
        <LabeledList label="AI 해석" items={section.interpretation} />
      )}
      {section.watch.length > 0 && (
        <LabeledList label="지켜볼 항목" items={section.watch} />
      )}

      {section.sources.length > 0 && (
        <details className="sources">
          <summary>근거 {section.sources.length}건</summary>
          <ul>
            {section.sources.map((src, i) => (
              <li key={i}>
                <span className="source-path">{src.section_path}</span>
                <blockquote>{src.quote}</blockquote>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function LabeledList({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="labeled">
      <span className="label">{label}</span>
      <ul>
        {items.map((item, i) => (
          <li key={i}>{stripCitations(item)}</li>
        ))}
      </ul>
    </div>
  );
}

// "| a | b |" 한 줄을 셀 배열로 나눈다.
function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((cell) => cell.trim());
}

// 요약의 표(마크다운)를 그린다. 표 앞의 줄(예: "단위: 백만원 | 연결")은 캡션으로 보여준다.
// 형식: 캡션 줄 → 헤더 행 → 구분 행(|---|---:|) → 데이터 행
function MarkdownTable({ markdown }: { markdown: string }) {
  const lines = markdown.split("\n").filter((line) => line.trim() !== "");
  const tableStart = lines.findIndex((line) => line.trim().startsWith("|"));
  // 표 형식이 아니면 원문 그대로 보여준다
  if (tableStart === -1 || lines.length < tableStart + 2) {
    return <pre className="summary-table-raw">{markdown}</pre>;
  }

  const caption = lines.slice(0, tableStart).join(" ");
  const header = splitRow(lines[tableStart]);
  // 구분 행이 "---:"로 끝나면 오른쪽 정렬 (숫자 열)
  const rightAligned = splitRow(lines[tableStart + 1]).map((cell) =>
    cell.endsWith(":"),
  );
  const rows = lines.slice(tableStart + 2).map(splitRow);
  const align = (i: number) => (rightAligned[i] ? "num" : undefined);

  return (
    <div className="summary-table">
      {caption && <p className="caption">{caption}</p>}
      <table>
        <thead>
          <tr>
            {header.map((cell, i) => (
              <th key={i} className={align(i)}>
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>
              {row.map((cell, i) => (
                <td key={i} className={align(i)}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default SummaryModal;
