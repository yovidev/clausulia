import { useQuery } from "@tanstack/react-query";
import { getChunk } from "../api";
import { ErrorNotice } from "./ErrorNotice";

interface Props {
  chunkId: string | null;
  onClose: () => void;
}

/** Panel lateral con el fragmento fuente completo de una cita. */
export function SourceDrawer({ chunkId, onClose }: Props) {
  const chunk = useQuery({
    queryKey: ["chunk", chunkId],
    queryFn: () => getChunk(chunkId as string),
    enabled: chunkId !== null,
    staleTime: Infinity, // un chunk no cambia mientras el documento siga listo
  });

  if (chunkId === null) return null;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" aria-label="Fragmento fuente">
        <header className="drawer-header">
          {chunk.data ? (
            <div>
              <strong>{chunk.data.filename}</strong>
              <div className="muted">
                Página {chunk.data.page_number} · fragmento {chunk.data.chunk_index + 1}
              </div>
            </div>
          ) : (
            <strong>Fragmento fuente</strong>
          )}
          <button type="button" className="secondary" onClick={onClose} aria-label="Cerrar">
            ✕
          </button>
        </header>
        {chunk.isPending && <p className="muted">Cargando fragmento…</p>}
        {chunk.isError && <ErrorNotice error={chunk.error} />}
        {chunk.data && <p className="source-text">{chunk.data.content}</p>}
      </aside>
    </>
  );
}
