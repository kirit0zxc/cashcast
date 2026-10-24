import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent } from "react";
import { CashCastApi, type Transaction } from "../../shared/api";
import { useCompanyCanWrite } from "../../shared/company-permissions";

// Значения существующего Category из OpenAPI; подписи не меняют серверный словарь.
const categories = {
  sales: "Выручка", purchases: "Закупки", payroll: "Зарплата", rent: "Аренда",
  tax: "Налоги", fees: "Комиссии", loan: "Кредит", transfer: "Собственный перевод", other: "Прочее",
};

export function CategoryEditor({ api, transaction, companyId, accountId, onChanged }: {
  api: CashCastApi; transaction: Transaction; companyId: string; accountId: string;
  onChanged: () => void;
}) {
  const canWrite = useCompanyCanWrite();
  const cache = useQueryClient();
  const mutation = useMutation({
    mutationFn: (category: string) => api.patch<Transaction>(`/transactions/${transaction.id}/category`, { category }),
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey: ["transactions", companyId, accountId] });
      onChanged();
    },
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (canWrite) mutation.mutate(String(new FormData(event.currentTarget).get("category")));
  }
  const category = transaction.category;
  return <>
    <span data-testid="transaction-category">{category ? categories[category as keyof typeof categories] ?? category : "Не определена"}</span>
    <small>{transaction.category_source === "manual" ? "Выбрано вами"
      : transaction.category_source === "auto" ? "Определено автоматически" : "Источник не указан"}</small>
    {canWrite && <details><summary>Изменить категорию</summary><form onSubmit={submit}>
      <label>Новая категория<select name="category" key={category} defaultValue={category ?? "other"}
        disabled={mutation.isPending} onChange={() => mutation.reset()}>
        {Object.entries(categories).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <button disabled={mutation.isPending}>Сохранить категорию</button>
    </form></details>}
    {mutation.error && <p role="alert">{mutation.error.message}</p>}
    {mutation.isSuccess && <p role="status">Категория сохранена. Новый прогноз запрашивается автоматически.</p>}
  </>;
}
