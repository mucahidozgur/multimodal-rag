"use client";

import { useCallback, useState, type DragEvent } from "react";

import { api, type Document } from "@/lib/api";

interface PDFUploadProps {
  onCreated: (doc: Document) => void;
}

type Phase = "idle" | "uploading" | "parsing" | "indexing" | "done";

const PHASE_LABELS: Record<Phase, string> = {
  idle: "PDF seçin veya sürükleyin",
  uploading: "Yükleniyor...",
  parsing: "Parse ediliyor...",
  indexing: "Indexleniyor...",
  done: "Tamamlandı",
};

export default function PDFUpload({ onCreated }: PDFUploadProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFile = useCallback(
    async (file: File | undefined | null) => {
      if (!file || phase !== "idle") {
        return;
      }
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        setError("Lütfen bir PDF dosyası seçin");
        return;
      }
      setError(null);
      try {
        // 1) Yükle → doküman oluştur (file_path set edilir)
        setPhase("uploading");
        const doc = await api.uploadPdf(file);
        // 2) Index → multi-modal akış (parse + text/table/image embed)
        setPhase("parsing");
        await api.indexDocument(doc.id);
        setPhase("indexing");
        onCreated(doc);
      } catch (err) {
        setError((err as Error).message);
        setPhase("idle");
      }
    },
    [onCreated, phase]
  );

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    void handleFile(e.dataTransfer.files?.[0]);
  }

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => document.getElementById("pdf-file-input")?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
          dragging
            ? "border-emerald-400 bg-emerald-500/10"
            : "border-slate-600 hover:border-slate-500 hover:bg-slate-900/40"
        }`}
      >
        <span className="text-4xl">📄</span>
        <p className="text-sm text-slate-300">{PHASE_LABELS[phase]}</p>
        {phase === "idle" && (
          <p className="text-xs text-slate-500">
            .pdf dosyası — metin, tablo ve grafikler ayrı ayrı indexlenir
          </p>
        )}
        {(phase === "uploading" || phase === "parsing" || phase === "indexing") && (
          <div className="h-1.5 w-48 overflow-hidden rounded-full bg-slate-700">
            <div
              className={`h-full animate-pulse rounded-full bg-gradient-to-r from-indigo-500 to-emerald-400 ${
                phase === "uploading"
                  ? "w-1/3"
                  : phase === "parsing"
                    ? "w-2/3"
                    : "w-full"
              }`}
            />
          </div>
        )}
      </div>
      <input
        id="pdf-file-input"
        type="file"
        accept=".pdf"
        className="hidden"
        onChange={(e) => void handleFile(e.target.files?.[0])}
      />
      {error && (
        <p className="mt-2 rounded-md bg-red-950/60 p-2 text-sm text-red-400">{error}</p>
      )}
    </div>
  );
}
