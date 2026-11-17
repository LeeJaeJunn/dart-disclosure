import { Link, NavLink, Route, Routes } from "react-router";
import "./App.css";
import ChatPage from "./pages/ChatPage";
import CompaniesPage from "./pages/CompaniesPage";
import CompanyPage from "./pages/CompanyPage";

function App() {
  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <Link className="site-title" to="/">
            국내 기업 공시정보 기반 질의응답
          </Link>
          <nav className="nav">
            <NavLink to="/" end>
              기업 목록
            </NavLink>
            <NavLink to="/qa">공시 Q&A</NavLink>
          </nav>
        </div>
      </header>

      <Routes>
        <Route path="/" element={<CompaniesPage />} />
        <Route path="/qa" element={<ChatPage />} />
        <Route path="/company/:corpCode" element={<CompanyPage />} />
      </Routes>
    </>
  );
}

export default App;
