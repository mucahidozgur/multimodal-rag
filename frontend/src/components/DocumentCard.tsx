import { formatDate } from "@/lib/format";
import type { DocumentListItem } from "@/lib/api";

interface DocumentCardProps {
  document: DocumentListItem;
  onDelete: (id: string) => void;
  onIndex: (id: string) => void;
  onView: (id: string) => void;
}

export default function DocumentCard({ document, onDelete, onIndex, onView }: DocumentCardProps) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/60 p-4 shadow-lg transition-colors hover:border-slate-600">
      <div className="mb-2 flex items-start justify-between gap-4">
        <h3 className="text-lg font-semibold text-white">{document.title}</h3>
        <span className="shrink-0 text-sm text-slate-400">
          {formatDate(document.created_at)}
        </span>
      </div>
      <p className="mb-3 line-clamp-2 text-slate-300">
        {document.file_path ? "📄 PDF dokümanı" : document.content_preview}
      </p>
      <div className="flex items-center gap-4">
        <button
          onClick={() => onIndex(document.id)}
          className="rounded-md border border-indigo-500/60 px-3 py-1 text-sm text-indigo-300 hover:bg-indigo-500/10"
        >
          Index
        </button>
        {document.file_path && (
          <button
            onClick={() => onView(document.id)}
            className="rounded-md border border-slate-600 px-3 py-1 text-sm text-slate-300 hover:bg-slate-700"
          >
            Görüntüle
          </button>
        )}
        <button
          onClick={() => onDelete(document.id)}
          className="text-sm text-red-400 hover:underline"
        >
          Sil
        </button>
      </div>
    </div>
  );
}
