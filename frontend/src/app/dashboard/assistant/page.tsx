"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import DocumentSelector from "@/components/DocumentSelector";
import MessageBubble, { type CitationTarget, type Message } from "@/components/MessageBubble";
import { api, type DocumentListItem, type VerificationData } from "@/lib/api";
import { streamSSE } from "@/lib/sse";
import { uuid } from "@/lib/uuid";

// react-pdf tarayıcı API'lerine dayanır; SSR'da render edilmez.
const PDFViewer = dynamic(() => import("@/components/PDFViewer"), { ssr: false });

const EXAMPLE_QUESTIONS = ["Python nedir?", "Toplantı notlarını özetle", "Yapılacakları çıkar"];

export default function AssistantPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [mode, setMode] = useState<"chat" | "agent">("chat");
  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [viewer, setViewer] = useState<CitationTarget | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    api
      .listDocuments(100, 0)
      .then((r) => setDocuments(r.items))
      .catch(console.error);
  }, []);

  function updateMessage(id: string, patch: Partial<Message>) {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));
  }

  async function handleSend() {
    if (!input.trim() || streaming) return;
    const query = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { id: uuid(), role: "user", content: query }]);

    const assistantId = uuid();
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", content: "", done: false },
    ]);
    setStreaming(true);

    try {
      const path = mode === "chat" ? "/api/ai/chat" : "/api/ai/agent";
      const body = {
        query,
        top_k: 5,
        document_ids: selectedIds.length > 0 ? selectedIds : undefined,
      };
      for await (const ev of streamSSE(path, body)) {
        const data = JSON.parse(ev.data);
        if (ev.event === "intent") {
          updateMessage(assistantId, { intent: data.intent });
        } else if (ev.event === "sources") {
          updateMessage(assistantId, { sources: data });
        } else if (ev.event === "verification") {
          // Faz 5: citation doğrulaması (sources + page + bbox) → tıklanabilir.
          updateMessage(assistantId, { verification: data as VerificationData });
        } else if (ev.event === "token") {
          // content'e ekle
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + data.text } : m
            )
          );
        } else if (ev.event === "error") {
          updateMessage(assistantId, { error: data.message });
        } else if (ev.event === "done") {
          updateMessage(assistantId, { done: true });
        }
      }
    } catch (e) {
      updateMessage(assistantId, { error: (e as Error).message, done: true });
    } finally {
      setStreaming(false);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }

  return (
    <div className="flex h-[calc(100vh-6.5rem)] flex-col">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">AI Asistan</h1>
        {/* Segmented control: Chat / Agent */}
        <div className="flex rounded-lg border border-slate-700 bg-slate-900/60 p-1">
          {(["chat", "agent"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`rounded-md px-4 py-1 text-sm transition-colors ${
                mode === m
                  ? "bg-gradient-to-r from-indigo-500 to-indigo-400 text-white shadow"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              {m === "chat" ? "Chat" : "Agent"}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-1 flex-col overflow-hidden rounded-lg border border-slate-700 bg-slate-900/40">
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {messages.length === 0 ? (
            <div className="flex min-h-full flex-col items-center justify-center gap-3 text-center">
              <span className="text-5xl">💬</span>
              <p className="text-slate-400">Dokümanlarınız hakkında soru sorun</p>
              <div className="flex flex-wrap justify-center gap-2">
                {EXAMPLE_QUESTIONS.map((question) => (
                  <button
                    key={question}
                    onClick={() => setInput(question)}
                    className="rounded-full border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800"
                  >
                    {question}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((message) => (
              <MessageBubble
                key={message.id}
                message={message}
                onCitationClick={(citation) => setViewer(citation)}
              />
            ))
          )}
          <div ref={bottomRef} />
        </div>

        <div className="border-t border-slate-700 p-4">
          <div className="mb-2">
            <DocumentSelector
              documents={documents}
              selectedIds={selectedIds}
              onChange={setSelectedIds}
              mode={mode}
            />
          </div>
          <div className="flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={streaming}
              rows={2}
              placeholder="Sorunuzu yazın... (Enter: gönder, Shift+Enter: yeni satır)"
              className="flex-1 resize-none rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none disabled:bg-slate-900"
            />
            <button
              onClick={() => void handleSend()}
              disabled={streaming || !input.trim()}
              className="rounded-md bg-gradient-to-r from-indigo-500 to-emerald-500 px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              Gönder
            </button>
          </div>
          {mode === "agent" && selectedIds.length === 0 && (
            <p className="mt-2 text-sm text-amber-400">
              ⚠️ Özet/aksiyon/karşılaştırma için önce yukarıdan doküman seçin
            </p>
          )}
          {streaming && <p className="mt-2 text-sm text-slate-500">Yanıt yazıyor...</p>}
        </div>
      </div>

      {viewer && (
        <PDFViewer
          documentId={viewer.documentId}
          initialPage={viewer.pageNumber}
          bbox={viewer.bbox}
          onClose={() => setViewer(null)}
        />
      )}

      <p className="mt-2 text-xs text-slate-600">
        Chat: dokümanlarınız hakkında soru sorun. Agent: özet/aksiyon/karşılaştırma da yapabilir.
      </p>
    </div>
  );
}
