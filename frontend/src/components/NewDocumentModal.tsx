"use client";

import { useEffect, useState, type FormEvent } from "react";

import PDFUpload from "@/components/PDFUpload";
import { api, type Document } from "@/lib/api";

interface NewDocumentModalProps {
  onClose: () => void;
  onCreated: (doc: Document) => void;
}

export default function NewDocumentModal({ onClose, onCreated }: NewDocumentModalProps) {
  const [tab, setTab] = useState<"text" | "pdf">("text");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const doc = await api.createDocument({ title, content });
      onCreated(doc);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-lg bg-white p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-4 text-xl font-semibold">Yeni Doküman</h2>

        <div className="mb-4 flex rounded-md border border-gray-300 p-1">
          <button
            onClick={() => setTab("text")}
            className={`flex-1 rounded px-3 py-1 text-sm ${
              tab === "text" ? "bg-blue-600 text-white" : "text-gray-600 hover:bg-gray-100"
            }`}
          >
            Metin
          </button>
          <button
            onClick={() => setTab("pdf")}
            className={`flex-1 rounded px-3 py-1 text-sm ${
              tab === "pdf" ? "bg-blue-600 text-white" : "text-gray-600 hover:bg-gray-100"
            }`}
          >
            PDF Yükle
          </button>
        </div>

        {tab === "pdf" ? (
          <div className="space-y-4">
            <PDFUpload onCreated={onCreated} />
            <div className="flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="rounded-md border border-gray-300 px-4 py-2 text-sm hover:bg-gray-100"
              >
                Kapat
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="doc-title"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                Başlık
              </label>
              <input
                id="doc-title"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label
                htmlFor="doc-content"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                İçerik
              </label>
              <textarea
                id="doc-content"
                rows={10}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                required
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            {error && (
              <p className="rounded-md bg-red-50 p-2 text-sm text-red-600">{error}</p>
            )}
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={onClose}
                disabled={submitting}
                className="rounded-md border border-gray-300 px-4 py-2 text-sm hover:bg-gray-100 disabled:opacity-50"
              >
                İptal
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {submitting ? "Oluşturuluyor..." : "Oluştur"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
