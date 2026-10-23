import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { CashCastApi, type Commit, type Preview } from "../../shared/api";

// Сервер возвращает согласованный mapping; пользователь может поправить его до загрузки.
export function StatementImport({ api, companyId, accountId, onCommit }: {
  api: CashCastApi; companyId: string; accountId: string; onCommit: (lastDate: string | null) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [customMapping, setMapping] = useState<string | null>(null);
  const presets = useQuery({ queryKey: ["import-presets"], queryFn: ({ signal }) =>
    api.request<{ items: { id: string; mapping: Record<string, unknown> }[] }>("/import-presets", { signal }) });
  const preset = presets.data?.items.find(p => p.id === "participants-v1");
  const mapping = customMapping ?? JSON.stringify(preset?.mapping ?? {}, null, 2);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [commit, setCommit] = useState<Commit | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file) return;
    setBusy(true); setError(""); setPreview(null); setCommit(null);
    try {
      const form = new FormData();
      form.set("file", file); form.set("account_id", accountId);
      form.set("mapping", JSON.stringify(JSON.parse(mapping)));
      setPreview(await api.request<Preview>(`/companies/${companyId}/imports`, { method: "POST", body: form }));
    } catch (error) { setError(error instanceof Error ? error.message : "Ошибка загрузки"); }
    finally { setBusy(false); }
  }
  async function confirm() {
    if (!preview) return; setBusy(true); setError("");
    try {
      setCommit(await api.post<Commit>(`/imports/${preview.import_id}/commit`));
      onCommit(preview.period_end);
    } catch (error) { setError(error instanceof Error ? error.message : "Ошибка импорта"); }
    finally { setBusy(false); }
  }
  return <section className="panel"><h2>1. Импорт выписки</h2>
    <p>Выберите одну выписку statements/Cxxx.csv. Сводный файл нескольких компаний сюда не загружайте.</p>
    <form onSubmit={upload}>
      <label>CSV-файл<input type="file" accept=".csv,text/csv" disabled={busy}
        onChange={e => { setFile(e.target.files?.[0] ?? null); setPreview(null); setCommit(null); }} /></label>
      <details><summary>Соответствие колонок</summary>
        <textarea aria-label="Соответствие колонок" rows={13} value={mapping} disabled={busy}
          onChange={e => { setMapping(e.target.value); setPreview(null); setCommit(null); }} />
      </details><button disabled={!file || !accountId || busy || !preset}>Проверить файл</button>
    </form>
    {presets.error && <p role="alert">Не удалось получить настройки CSV: {presets.error.message}</p>}
    {preview && <div><p>Строк: {preview.total_rows}. Ошибок: {preview.error_count}.
      Повторов внутри: {preview.duplicate_in_file}.</p>
      <p>Период: {preview.period_start ?? "—"} — {preview.period_end ?? "—"}.
        {preview.reused && " Этот файл уже загружали."}</p>
      {preview.sample_errors.length > 0 && <ul>{preview.sample_errors.map((e, i) =>
        <li key={i}>Строка {e.row}, {e.field}: {e.message}</li>)}</ul>}
      <button onClick={() => void confirm()} disabled={busy || preview.error_count > 0 || !!commit}>Подтвердить импорт</button>
    </div>}
    {commit && <p role="status">Добавлено: {commit.inserted}. Уже существовали: {commit.skipped_existing}.</p>}
    {busy && <p role="status">Обрабатываем…</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
