import { useState } from "react";
import { Bot, Database, FolderKanban, MessageSquare, Settings, type LucideIcon } from "lucide-react";

import { ChatPage } from "./pages/ChatPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { MemoryPage } from "./pages/MemoryPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { SettingsPage } from "./pages/SettingsPage";

type PageKey = "chat" | "documents" | "memory" | "projects" | "settings";

const navItems: Array<{ key: PageKey; label: string; icon: LucideIcon }> = [
  { key: "chat", label: "问答", icon: MessageSquare },
  { key: "documents", label: "资料库", icon: Database },
  { key: "memory", label: "记忆", icon: Bot },
  { key: "projects", label: "项目", icon: FolderKanban },
  { key: "settings", label: "设置", icon: Settings },
];

export function App() {
  const [page, setPage] = useState<PageKey>("settings");

  const renderPage = () => {
    switch (page) {
      case "chat":
        return <ChatPage />;
      case "documents":
        return <DocumentsPage />;
      case "memory":
        return <MemoryPage />;
      case "projects":
        return <ProjectsPage />;
      case "settings":
        return <SettingsPage />;
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">WM</div>
          <div>
            <strong>WorkMemory</strong>
            <span>本地知识库</span>
          </div>
        </div>
        <nav className="nav-list" aria-label="主导航">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                className={page === item.key ? "nav-item active" : "nav-item"}
                type="button"
                onClick={() => setPage(item.key)}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>
      <main className="main-view">{renderPage()}</main>
    </div>
  );
}
