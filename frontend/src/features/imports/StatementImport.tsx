import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { CashCastApi, type Commit, type Preview } from "../../shared/api";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import { navigate } from "../../app/router";
import { Leaders, Stepper, dmy } from "../../ui/Blank";

// Сервер возвращает согласованный mapping; пользователь может поправить его до загрузки.
export function StatementImport({ api, companyId, accountId, onCommit }: {
  api: CashCastApi; companyId: string; accountId: string; onCommit: (lastDate: string | null) => void;
}) {
  const canWrite = useCompanyCanWrite();
  const [file, setFile] = useState<File | null>(null);
  const [customMapping, setMapping] = useState<string | null>(null);
  const presets = useQuery({ queryKey: ["import-presets"], enabled: canWrite, queryFn: ({ signal }) =>
    api.request<{ items: { id: string; mapping: Record<string, unknown> }[] }>("/import-presets", { signal }) });
  const preset = presets.data?.items.find(p => p.id === "participants-v1");
  const mapping = customMapping ?? JSON.stringify(preset?.mapping ?? {}, null, 2);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [commit, setCommit] = useState<Commit | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!canWrite || !file) return;
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
    if (!canWrite || !preview) return; setBusy(true); setError("");
    try {
      setCommit(await api.post<Commit>(`/imports/${preview.import_id}/commit`));
      onCommit(preview.period_end);
    } catch (error) { setError(error instanceof Error ? error.message : "Ошибка импорта"); }
    finally { setBusy(false); }
  }
  if (!canWrite) return null;
  const step = commit ? 3 : preview ? 2 : file ? 1 : 0;
  return <section className="panel">
    <Stepper steps={["Выбрать файл", "Проверить данные", "Подтвердить импорт", "Готово"]} current={step} />
    <h2>История денежных операций</h2>
    <p>Одна выписка — один счёт: statements/Cxxx.csv. Сводный файл нескольких компаний сюда не загружайте.
      CSV с разделителем «;», UTF-8 с BOM, русские направления.</p>
    <form onSubmit={upload} className="upload">
      <label>CSV-файл<input type="file" accept=".csv,text/csv" disabled={busy}
        onChange={e => { setFile(e.target.files?.[0] ?? null); setPreview(null); setCommit(null); }} /></label>
      <details><summary>Соответствие колонок</summary>
        <p>Шаблон participants-v1 с сервера. Меняйте, только если колонки файла названы иначе.</p>
        <textarea aria-label="Соответствие колонок" rows={13} value={mapping} disabled={busy}
          onChange={e => { setMapping(e.target.value); setPreview(null); setCommit(null); }} />
      </details>
      <button disabled={!file || !accountId || busy || !preset}>Проверить файл</button>
    </form>
    {presets.error && <p role="alert">Не удалось получить настройки CSV: {presets.error.message}</p>}
    {preview && <div className="check">
      <span className="label">Предварительная проверка · {file?.name}</span>
      <Leaders testId="statement-preview" rows={[
        ["Строк в файле", preview.total_rows],
        ["Ошибок", preview.error_count],
        ["Повторов внутри файла", preview.duplicate_in_file],
        ["Период", `${preview.period_start ? dmy(preview.period_start) : "—"} — ${preview.period_end ? dmy(preview.period_end) : "—"}`],
      ]} />
      {preview.reused && <p className="note">Этот файл уже загружали. Повторное подтверждение не добавит операции заново.</p>}
      {preview.sample_errors.length > 0 && <div className="errors" role="alert"><b>Ошибки в строках — импорт недоступен</b>
        <ul>{preview.sample_errors.map((e, i) => <li key={i}>Строка {e.row}, {e.field}: {e.message}</li>)}</ul></div>}
      <div className="row">
        <button onClick={() => void confirm()} disabled={busy || preview.error_count > 0 || !!commit}>Подтвердить импорт</button>
      </div>
    </div>}
    {commit && <div className="done">
      <p role="status">Результат сохранённого импорта. Добавлено: {commit.inserted}. Уже существовали: {commit.skipped_existing}.</p>
      <p>При повторном подтверждении возвращается та же сводка; операции заново не добавляются.</p>
      <p>Прогноз пересчитывается автоматически на конец периода выписки.</p>
      <div className="row">
        <button type="button" onClick={() => navigate("/operations")}>Открыть операции</button>
        <button type="button" className="ghost" onClick={() => navigate("/forecast")}>Открыть прогноз</button>
      </div>
    </div>}
    {busy && <p role="status">Обрабатываем…</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
