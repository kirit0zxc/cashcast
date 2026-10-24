import { useState, type FormEvent } from "react";
import { CashCastApi, type ObligationPreview } from "../../shared/api";

// Отдельный preview сохраняет известное происхождение; commit запрещён при любой ошибке.
export function ObligationImport({ api, companyId, accountId, onChanged }: {
  api: CashCastApi; companyId: string; accountId: string; onChanged: () => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [sourceName, setSourceName] = useState("invoices");
  const [preview, setPreview] = useState<ObligationPreview | null>(null);
  const [committed, setCommitted] = useState<{ inserted: number; skipped_existing: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function resetPreview() { setPreview(null); setCommitted(null); setError(""); }
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file) return;
    setBusy(true); resetPreview();
    try {
      const form = new FormData();
      form.set("account_id", accountId); form.set("source_name", sourceName); form.set("file", file);
      setPreview(await api.request<ObligationPreview>(`/companies/${companyId}/obligation-imports`, {
        method: "POST", body: form,
      }));
    } catch (error) { setError(error instanceof Error ? error.message : "Ошибка проверки обязательств"); }
    finally { setBusy(false); }
  }
  async function commit() {
    if (!preview) return;
    setBusy(true); setError("");
    try {
      setCommitted(await api.post(`/obligation-imports/${preview.import_id}/commit`));
      await onChanged();
    } catch (error) { setError(error instanceof Error ? error.message : "Ошибка импорта обязательств"); }
    finally { setBusy(false); }
  }
  return <details><summary>Загрузить счета и обязательства из CSV</summary>
    <p>UTF-8, разделитель «;»: id, counterparty_ref, direction, amount, currency, due_date,
      available_at, kind, provenance; tax_regime необязателен. Даты — YYYY-MM-DD, суммы — рубли.</p>
    <p>available_at — дата, когда документ стал известен; проверяем её по текущему дню UTC.</p>
    <p>Название источника и внешний id должны сохраняться при повторной загрузке документа.</p>
    <form onSubmit={upload} className="row">
      <label>Источник обязательств<input required maxLength={40} disabled={busy} value={sourceName}
        onChange={e => { setSourceName(e.target.value); resetPreview(); }} /></label>
      <label>CSV счетов и обязательств<input type="file" accept=".csv,text/csv" disabled={busy}
        onChange={e => { setFile(e.target.files?.[0] ?? null); resetPreview(); }} /></label>
      <button disabled={busy || !file}>Проверить обязательства</button>
    </form>
    {preview && <><p>Обязательств проверено: {preview.total_rows}. Корректных: {preview.valid_count}.
      Ошибок: {preview.error_count}.{preview.reused && " Этот файл уже загружали."}</p>
      <ul>{preview.sample_errors.map((e, i) => <li key={i}>Строка {e.row}, {e.field}: {e.code}</li>)}</ul>
      <button disabled={busy || preview.error_count > 0 || !!committed} onClick={() => void commit()}>
        Подтвердить обязательства</button></>}
    {committed && <p role="status">Обязательств добавлено: {committed.inserted}.
      Уже существовали: {committed.skipped_existing}. Дата среза переключена на сегодня; прогноз обновляется автоматически.</p>}
    {busy && <p role="status">Обрабатываем обязательства…</p>}
    {error && <p role="alert">{error}</p>}
  </details>;
}
