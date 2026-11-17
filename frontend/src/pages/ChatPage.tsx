import { useState, type FormEvent } from "react";
import { ask, formatDate, type AskSource, type ChatTurn } from "../api";
import "./ChatPage.css";

type Message =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string; sources: AskSource[] }
  | { role: "error"; content: string };

function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || loading) return;

    // 지금까지의 대화를 함께 보낸다. 질문·답변 본문만 보내고 근거 목록은 뺀다.
    // 요청이 실패한 질문과 그 오류 메시지도 뺀다 (답 없는 질문이 기록에 남지 않게).
    const history: ChatTurn[] = messages.flatMap((m, i) =>
      m.role === "error" || (m.role === "user" && messages[i + 1]?.role === "error")
        ? []
        : [{ role: m.role, content: m.content }],
    );

    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setInput("");
    setLoading(true);

    try {
      const data = await ask({ question, history });
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.answer, sources: data.sources },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "error", content: `요청 실패: ${(err as Error).message}` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="chat">
      <h1>공시 Q&A</h1>

      <ul className="messages">
        {messages.map((m, i) => (
          <li key={i} className={`message ${m.role}`}>
            {m.content}
            {m.role === "assistant" && m.sources.length > 0 && (
              <Sources sources={m.sources} />
            )}
          </li>
        ))}
        {loading && <li className="message assistant">답변 생성 중...</li>}
      </ul>

      <form className="composer" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="질문을 입력하세요"
          disabled={loading}
        />
        <button type="submit" disabled={loading || !input.trim()}>
          전송
        </button>
      </form>
    </main>
  );
}

// 답변 아래 근거 목록. 번호는 답변 본문의 [n]과 같다.
function Sources({ sources }: { sources: AskSource[] }) {
  return (
    <ol className="sources">
      {sources.map((s) => (
        <li key={s.n}>
          <details>
            <summary>
              <span className="source-n">[{s.n}]</span>{" "}
              <a href={s.dart_url} target="_blank" rel="noreferrer">
                {s.corp_name} {s.report_nm}
              </a>{" "}
              <span className="source-meta">
                · {formatDate(s.rcept_dt)} · 접수번호 {s.rcept_no}
              </span>
              <span className="source-path">{s.section_path}</span>
            </summary>
            <blockquote>{s.quote}</blockquote>
          </details>
        </li>
      ))}
    </ol>
  );
}

export default ChatPage;
