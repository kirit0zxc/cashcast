import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { navigate } from "../../app/router";
import { CashCastApi, money, type ObligationPreview } from "../../shared/api";
import { useCompanyCanWrite } from "../../shared/company-permissions";
import { dmy, Leaders } from "../../ui/Blank";

type Provider = "bank" | "onec" | "tax";
interface Source { id: Provider; label: string; mode: "demo"; description: string }
interface ExternalPreview extends ObligationPreview {
  provider_id: Provider; mode: "demo"; skipped_settled: number; preview_truncated: boolean;
  documents: { source_ref: string; label: string; document_kind: string; direction: "in" | "out";
    amount_minor: number; due_date: string; available_at: string; category: string | null; provenance: string }[];
}

// Подключения пока демонстрационные; preview и запись планов идут в настоящий API.
export function ExternalSources({ api, companyId, accountId, onChanged }: {
  api: CashCastApi; companyId: string; accountId: string; onChanged: () => Promise<void>;
}) {
  const canWrite = useCompanyCanWrite();
  const sources = useQuery({ queryKey: ["external-sources", companyId], queryFn: ({ signal }) =>
    api.request<{ items: Source[]; warning: string }>(`/companies/${companyId}/external-sources`, { signal }) });
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ExternalPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refreshError, setRefreshError] = useState("");
  const [committed, setCommitted] = useState<{ inserted: number; skipped_existing: number } | null>(null);

  function reset() { setPreview(null); setCommitted(null); setError(""); setRefreshError(""); }
  async function load(provider: "bank" | "onec") {
    if (!canWrite || busy) return;
    reset(); setBusy(true);
    try {
      setPreview(await api.post<ExternalPreview>(`/companies/${companyId}/external-sources/${provider}/preview`, {
        account_id: accountId,
      }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Источник недоступен"); }
    finally { setBusy(false); }
  }
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!canWrite || !file || busy) return;
    reset(); setBusy(true);
    try {
      const body = new FormData(); body.set("file", file); body.set("account_id", accountId);
      setPreview(await api.request<ExternalPreview>(`/companies/${companyId}/external-tax-imports`, {
        method: "POST", body,
      }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Ошибка проверки файла"); }
    finally { setBusy(false); }
  }
  async function commit() {
    if (!canWrite || !preview || busy || preview.status === "committed") return;
    setBusy(true); setError("");
    try {
      const result = await api.post<{ inserted: number; skipped_existing: number }>(
        `/obligation-imports/${preview.import_id}/commit`);
      setCommitted(result);
      // Ошибка обновления кабинета не отменяет уже сохранённые обязательства.
      try { await onChanged(); }
      catch { setRefreshError("Платежи сохранены. Не удалось обновить кабинет: откройте планы и запустите прогноз."); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Ошибка импорта"); }
    finally { setBusy(false); }
  }

  if (!canWrite) return null;
  return <>
    <section className="panel dash">
      <div className="panel-head"><h2>Банк, 1С и налоговые документы</h2><span className="chip">Демо-режим</span></div>
      <p className="note">{sources.data?.warning ?? "Только тестовые данные. Связи с банком, базой 1С и ФНС нет."}
        {" "}После подтверждения они станут настоящими плановыми платежами выбранного счёта.</p>
      <p>Демонабор от 24.10.2026. Суммы и сроки вымышлены. Банковские операции не создаются,
        деньги не переводятся, налоги автоматически не рассчитываются.</p>
      {sources.isPending && <p role="status">Получаем источники…</p>}
      {sources.error && <p role="alert">{sources.error.message}</p>}
      <div className="external-source-grid">
        {sources.data?.items.filter(s => s.id !== "tax").map(source => <section className="panel flat" key={source.id}>
          <span className="label">Демонстрационный источник</span><h3>{source.label}</h3>
          <p>{source.description}</p>
          <button type="button" disabled={busy} onClick={() => void load(source.id as "bank" | "onec")}>
            Получить демоданные {source.label === "Банк" ? "банка" : "1С"}</button>
        </section>)}
      </div>
    </section>
    <section className="panel">
      <span className="label">Загрузка файла · демо-ФНС</span><h2>Налоговые обязательства</h2>
      <p>Скачайте пример, проверьте суммы и сроки и загрузите его. Оплаченные и отменённые строки
        не создают новых платежей. Ранее загруженные планы закрываются отдельно через сверку оплат.
        Форматы официальных XML/PDF ФНС пока не поддерживаются.</p>
      <a href={`/api/v1/companies/${companyId}/external-tax-template`} download>Скачать демо-файл налогов (CSV)</a>
      <form className="upload" onSubmit={upload}>
        <label>Демо-файл налоговых обязательств<input type="file" accept=".csv,text/csv" disabled={busy}
          onChange={e => { setFile(e.target.files?.[0] ?? null); reset(); }} /></label>
        <button disabled={busy || !file}>Проверить налоговый файл</button>
      </form>
      <details><summary>Что должно быть в файле</summary>
        <p>UTF-8, разделитель «;». Колонки: id, tax_name, amount, due_date, available_at, tax_regime, status.
          Сумма — положительное число рублей с точкой, даты — ГГГГ-ММ-ДД. Статусы: due (к уплате),
          paid (оплачен), cancelled (отменён). ID документа сохраняйте при повторной загрузке.</p>
        <p>Дата available_at — когда документ стал известен. Сальдо ЕНС само по себе не является
          будущим платёжным поручением; нужны известная сумма и срок отдельного обязательства.</p>
      </details>
    </section>
    {preview && <section className="panel" aria-label="Проверка внешних данных">
      <span className="label">Демо · до подтверждения планы не меняются</span><h2>Проверьте будущие платежи</h2>
      <Leaders testId="external-preview" rows={[
        ["Платежей к проверке", preview.total_rows], ["Корректных", preview.valid_count],
        ["Ошибок", preview.error_count], ["Оплаченных и отменённых пропущено", preview.skipped_settled],
      ]} />
      {preview.documents.length > 0 && <div className="scroll"><table aria-label="Документы внешнего источника">
        <thead><tr><th>Документ и источник</th><th>Дата платежа</th><th>Известен с</th><th>Движение</th><th>Сумма</th></tr></thead>
        <tbody>{preview.documents.map(doc => <tr key={doc.source_ref}>
          <td><b>{doc.label}</b><small>{doc.provenance}</small></td><td>{dmy(doc.due_date)}</td>
          <td>{dmy(doc.available_at)}</td><td>{doc.direction === "in" ? "Поступление" : "Расход"}</td>
          <td className="num">{money(doc.amount_minor)}</td></tr>)}</tbody>
      </table></div>}
      {preview.preview_truncated && <p>Показаны первые 20 платежей. При подтверждении проверяются и сохраняются все корректные строки.</p>}
      {!preview.valid_count && !preview.error_count && <p role="status">Все строки оплачены или отменены.
        Новых обязательств для добавления нет.</p>}
      {preview.sample_errors.length > 0 && <div role="alert"><b>Исправьте ошибки: весь импорт заблокирован.</b>
        <ul>{preview.sample_errors.map((e, i) => <li key={i}>Строка {e.row}, {e.field}: {e.code}</li>)}</ul></div>}
      {preview.status === "committed" && <p role="status">Этот набор уже импортирован. Новые платежи не добавлены,
        оплаты и ручные изменения сохранены.</p>}
      <div className="row"><button type="button" disabled={busy || preview.error_count > 0 || !preview.valid_count
        || preview.status === "committed" || !!committed} onClick={() => void commit()}>Добавить в план и обновить прогноз</button>
        <button type="button" className="ghost" disabled={busy} onClick={reset}>Закрыть проверку</button></div>
      {committed && <div className="done"><p role="status">Добавлено внешних платежей: {committed.inserted}.
        Уже существовали: {committed.skipped_existing}. Прогноз обновляется автоматически.</p>
        <button type="button" onClick={() => navigate("/payments")}>Открыть плановые платежи</button></div>}
    </section>}
    {busy && <p role="status">Обрабатываем внешние данные…</p>}
    {error && <p role="alert">{error}</p>}
    {refreshError && <p role="alert">{refreshError}</p>}
  </>;
}
