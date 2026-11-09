"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
import { Document, Page, pdfjs } from "react-pdf";

import { api, getToken } from "@/lib/api";

pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs"; // prebuild ile public/'e kopyalanır

interface PDFViewerProps {
  documentId: string;
  initialPage?: number;
  /** [x0, top, x1, bottom] — PDF nokta birimi (72 dpi). */
  bbox?: number[] | null;
  onClose: () => void;
}

export default function PDFViewer({
  documentId,
  initialPage = 1,
  bbox,
  onClose,
}: PDFViewerProps) {
  const [numPages, setNumPages] = useState(0);
  const [pageNumber, setPageNumber] = useState(initialPage);
  const [pageSize, setPageSize] = useState<{ width: number; height: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);

  // Görüntüleme genişliğini konteynere göre ölç (bbox oranlaması için gerekli).
  useEffect(() => {
    const el = containerRef.current;
    if (!el) {
      return;
    }
    const observer = new ResizeObserver(() => setContainerWidth(el.clientWidth));
    observer.observe(el);
    setContainerWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);

  function onDocumentLoad(pdf: PDFDocumentProxy) {
    setNumPages(pdf.numPages);
    setPageNumber(Math.min(Math.max(initialPage, 1), pdf.numPages));
  }

  function onPageLoad(pdfPage: PDFPageProxy) {
    const viewport = pdfPage.getViewport({ scale: 1 });
    setPageSize({ width: viewport.width, height: viewport.height });
  }

  // bbox overlay: PDF koordinatları (72dpi) → render boyutuna oranla.
  const scale = pageSize && containerWidth ? containerWidth / pageSize.width : 0;
  const overlay = bbox && scale ? {
    left: bbox[0] * scale,
    top: bbox[1] * scale,
    width: (bbox[2] - bbox[0]) * scale,
    height: (bbox[3] - bbox[1]) * scale,
  } : null;

  const token = getToken();

  // react-pdf, file/options prop'larının kimliği değişince dokümanı YENİDEN
  // yükler; her render'da yeni obje üretmek "yükle → state → render → yeniden
  // yükle" döngüsüne sokar. Nesneleri bir kez üretip sabitle.
  const fileSource = useMemo(() => ({ url: api.documentFileUrl(documentId) }), [documentId]);
  const docOptions = useMemo(
    () => ({ httpHeaders: token ? { Authorization: `Bearer ${token}` } : undefined }),
    [token]
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="flex h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg border border-slate-700 bg-slate-800 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
          <h2 className="text-lg font-semibold text-white">PDF Görüntüleyici</h2>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-sm text-slate-300">
              <button
                onClick={() => setPageNumber((p) => Math.max(1, p - 1))}
                disabled={pageNumber <= 1}
                className="rounded-md border border-slate-600 px-2 py-1 hover:bg-slate-700 disabled:opacity-50"
              >
                ←
              </button>
              <span>
                Sayfa {pageNumber} / {numPages || "…"}
              </span>
              <button
                onClick={() => setPageNumber((p) => Math.min(numPages, p + 1))}
                disabled={pageNumber >= numPages}
                className="rounded-md border border-slate-600 px-2 py-1 hover:bg-slate-700 disabled:opacity-50"
              >
                →
              </button>
            </div>
            <button
              onClick={onClose}
              className="rounded-md border border-slate-600 px-3 py-1 text-sm text-slate-300 hover:bg-slate-700"
            >
              Kapat
            </button>
          </div>
        </div>

        <div ref={containerRef} className="flex-1 overflow-auto bg-slate-900/60 p-4">
          <Document
            file={fileSource}
            options={docOptions}
            onLoadSuccess={onDocumentLoad}
            onLoadError={(err) => setError(`PDF yüklenemedi: ${(err as Error).message}`)}
            loading={<p className="p-4 text-sm text-slate-400">PDF yükleniyor...</p>}
            error={<p className="p-4 text-sm text-red-400">PDF yüklenemedi</p>}
            className="mx-auto flex flex-col items-center"
          >
            <div className="relative">
              <Page
                pageNumber={pageNumber}
                width={containerWidth || undefined}
                onLoadSuccess={onPageLoad}
                renderTextLayer={false}
                renderAnnotationLayer={false}
                loading={<p className="p-4 text-sm text-slate-400">Sayfa yükleniyor...</p>}
              />
              {overlay && (
                <div
                  className="pointer-events-none absolute rounded-sm border-2 border-orange-400 bg-yellow-300/40"
                  style={{
                    left: overlay.left,
                    top: overlay.top,
                    width: overlay.width,
                    height: overlay.height,
                  }}
                  title={`Sayfa ${pageNumber} — bbox: [${bbox!.map((v) => v.toFixed(0)).join(", ")}]`}
                />
              )}
            </div>
          </Document>
          {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
        </div>
      </div>
    </div>
  );
}
