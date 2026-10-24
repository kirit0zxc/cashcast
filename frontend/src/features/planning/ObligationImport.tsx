import { useState, type FormEvent } from "react";
import { CashCastApi, type ObligationPreview } from "../../shared/api";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import { navigate } from "../../app/router";
import { Leaders, Stepper } from "../../ui/Blank";

// Отдельный preview сохраняет известное происхождение; commit запрещён при любой ошибке.
export function ObligationImport({ api, companyId, accountId, onChanged }: {
  api: CashCastApi; companyId: string; accountId: string; onChanged: () => Promise<void>;
}) {
  const canWrite = useCompanyCanWrite();
  const [file, setFile] = useState<File | null>(null);
  const [sourceName, setSourceName] = useState("invoices");
  const [preview, setPreview] = useState<ObligationPreview | null>(null);
  const [committed, setCommitted] = useState<{ inserted: number; skipped_existing: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function resetPreview() { setPreview(null); setCommitted(null); setError(""); }
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!canWrite || !file) return;
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
    if (!canWrite || !preview) return;
    setBusy(true); setError("");
    try {
      setCommitted(await api.post(`/obligation-imports/${preview.import_id}/commit`));
      await onChanged();
    } catch (error) { setError(error instanceof Error ? error.message : "Ошибка импорта обязательств"); }
    finally { setBusy(false); }
  }
  if (!canWrite) return null;
  const step = committed ? 3 : preview ? 2 : file ? 1 : 0;
  return <section className="panel">
    <Stepper steps={["Выбрать файл", "Проверить данные", "Подтвердить импорт", "Готово"]} current={step} />
    <h2>Будущие поступления и расходы</h2>
    <p>Загрузите файл со счетами, налогами и другими будущими платежами — они появятся в «Плановых платежах».</p>
    <details><summary>Формат файла (для специалистов)</summary>
      <p>CSV, UTF-8, разделитель «;». Колонки: id, counterparty_ref, direction, amount, currency, due_date,
        available_at, kind, provenance; tax_regime необязателен. Даты — ГГГГ-ММ-ДД, суммы — в рублях.</p>
      <p>available_at — дата, когда документ стал известен; проверяем её по текущему дню UTC.</p>
      <p>Название источника и внешний id должны сохраняться при повторной загрузке документа.</p>
    </details>
    <form onSubmit={upload} className="upload">
      <div className="row">
        <label>Источник обязательств<input required maxLength={40} disabled={busy} value={sourceName}
          onChange={e => { setSourceName(e.target.value); resetPreview(); }} /></label>
        <label>CSV счетов и обязательств<input type="file" accept=".csv,text/csv" disabled={busy}
          onChange={e => { setFile(e.target.files?.[0] ?? null); resetPreview(); }} /></label>
      </div>
      <button disabled={busy || !file}>Проверить обязательства</button>
    </form>
    {preview && <div className="check">
      <span className="label">Предварительная проверка · {file?.name}</span>
      <Leaders testId="obligation-preview" rows={[
        ["Обязательств в файле", preview.total_rows],
        ["Корректных", preview.valid_count],
        ["Ошибок", preview.error_count],
      ]} />
      {preview.reused && <p className="note">Этот файл уже загружали. Повторное подтверждение не создаст дубли.</p>}
      {preview.sample_errors.length > 0 && <div className="errors" role="alert"><b>Ошибки в строках — импорт недоступен</b>
        <ul>{preview.sample_errors.map((e, i) => <li key={i}>Строка {e.row}, {e.field}: {e.code}</li>)}</ul></div>}
      <div className="row">
        <button disabled={busy || preview.error_count > 0 || !!committed} onClick={() => void commit()}>
          Подтвердить обязательства</button>
      </div>
    </div>}
    {committed && <div className="done">
      <p role="status">Обязательств добавлено: {committed.inserted}.
        Уже существовали: {committed.skipped_existing}. Прогноз обновляется автоматически.</p>
      <div className="row"><button type="button" onClick={() => navigate("/payments")}>Открыть платежи</button></div>
    </div>}
    {busy && <p role="status">Обрабатываем обязательства…</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
