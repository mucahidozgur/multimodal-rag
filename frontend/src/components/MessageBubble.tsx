"use client";

import { useState } from "react";

import type { ChatSource, VerificationData } from "@/lib/api";

export interface CitationTarget {
  documentId: string;
  pageNumber: number;
  bbox: number[] | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string; // streaming sırasında güncellenir
  sources?: ChatSource[]; // assistant mesajları için
  verification?: VerificationData; // Faz 5: citation doğrulaması
  intent?: string; // agent modu için
  error?: string; // hata varsa
  done?: boolean; // stream bitti mi
}

interface MessageBubbleProps {
  message: Message;
  onCitationClick?: (citation: CitationTarget) => void;
}

export default function MessageBubble({ message, onCitationClick }: MessageBubbleProps) {
  const [sourcesOpen, setSourcesOpen] = useState(false);

  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-indigo-500 px-4 py-2 text-white">
          {message.content}
        </div>
      </div>
    );
  }

  function citationChip(label: string, citation: CitationTarget | null, key: string) {
    if (!citation || !onCitationClick) {
      return (
        <span key={key} className="text-slate-400">
          {label}
        </span>
      );
    }
    return (
      <button
        key={key}
        onClick={() => onCitationClick(citation)}
        className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300 hover:bg-emerald-500/20"
        title="PDF'te konuma git"
      >
        📄 {label}
      </button>
    );
  }

  const verificationSources =
    message.verification?.sources.filter((s) => s.document_id && s.page_number) ?? [];

  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-2xl border border-slate-700 bg-slate-800/80 px-4 py-3">
        {message.intent && (
          <span className="mb-2 inline-block rounded-full bg-slate-700 px-2 py-0.5 text-xs text-slate-300">
            intent: {message.intent}
          </span>
        )}
        <div className="text-slate-100">
          {message.content.split("\n").map((line, i) => (
            <p key={i}>{line}</p>
          ))}
        </div>
        {message.sources && message.sources.length > 0 && (
          <div className="mt-2">
            <button
              onClick={() => setSourcesOpen((open) => !open)}
              className="text-sm text-slate-400 hover:text-slate-200"
            >
              📎 Kaynaklar ({message.sources.length})
            </button>
            {sourcesOpen && (
              <ul className="mt-1 space-y-1 text-sm text-slate-300">
                {message.sources.map((source, i) => {
                  const label =
                    source.page_number != null
                      ? `${source.document_title} — sayfa ${source.page_number}`
                      : `${source.document_title} — benzerlik ${source.similarity.toFixed(2)}`;
                  return (
                    <li key={i}>
                      {citationChip(
                        label,
                        source.document_id && source.page_number != null
                          ? {
                              documentId: source.document_id,
                              pageNumber: source.page_number,
                              bbox: source.bbox,
                            }
                          : null,
                        `s-${i}`
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
        {message.verification && (
          <div className="mt-2 rounded-md bg-slate-900/60 p-2 text-xs">
            <p className="font-medium text-slate-300">
              {message.verification.verified
                ? "✅ Tüm cümleler kaynaklarla destekleniyor"
                : "⚠️ Bazı cümleler kaynaklarla desteklenmiyor"}
              {" · "}doğruluk {message.verification.faithfulness.toFixed(2)}
            </p>
            {message.verification.unsupported.length > 0 && (
              <ul className="mt-1 list-inside list-disc text-red-400">
                {message.verification.unsupported.map((sentence, i) => (
                  <li key={i}>{sentence}</li>
                ))}
              </ul>
            )}
            {verificationSources.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {verificationSources.map((source, i) =>
                  citationChip(
                    `${source.document_title ?? "Doküman"} — sayfa ${source.page_number}`,
                    {
                      documentId: source.document_id!,
                      pageNumber: source.page_number!,
                      bbox: source.bbox,
                    },
                    `v-${i}`
                  )
                )}
              </div>
            )}
          </div>
        )}
        {message.error && <p className="mt-2 text-sm text-red-400">{message.error}</p>}
        {!message.done && (
          <div className="mt-1 text-right">
            <span className="animate-pulse text-emerald-400">▍</span>
          </div>
        )}
      </div>
    </div>
  );
}
