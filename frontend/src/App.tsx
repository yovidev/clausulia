import { useState } from "react";
import { ChatPanel } from "./components/ChatPanel";
import { DocumentsPanel } from "./components/DocumentsPanel";
import { SourceDrawer } from "./components/SourceDrawer";

export function App() {
  const [openChunk, setOpenChunk] = useState<string | null>(null);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Clausulia</h1>
        <span className="muted">Preguntas con citas sobre contratos de proveedores</span>
      </header>
      <main className="layout">
        <DocumentsPanel />
        <ChatPanel onOpenSource={setOpenChunk} />
      </main>
      <SourceDrawer chunkId={openChunk} onClose={() => setOpenChunk(null)} />
    </div>
  );
}
