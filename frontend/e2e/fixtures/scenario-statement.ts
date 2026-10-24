// Одна согласованная синтетическая история для сценариев и сверки, без повторных операций.
export function scenarioStatement() {
  const today = new Date().toISOString().slice(0, 10);
  const lines = ["operation_id;operation_date;amount;direction;counterparty_name;counterparty_inn;payment_purpose;balance_eod"];
  for (let offset = 70; offset >= 0; offset--) {
    const day = new Date(Date.parse(today) - offset * 86400000).toISOString().slice(0, 10);
    const index = Date.parse(day) / 86400000;
    const rent = index % 7 === 1;
    const balance = 2_000_000 + index * 5000 - Math.floor((index + 6) / 7) * 7777;
    lines.push(`scenario-income-${day};${day};50.00;Поступление;Клиент;e2e-scenario-revenue;Выручка;${((balance + (rent ? 7777 : 0)) / 100).toFixed(2)}`);
    if (rent) {
      lines.push(`scenario-rent-${day};${day};77.77;Списание;Арендодатель;e2e-scenario-rent;Аренда;${(balance / 100).toFixed(2)}`);
    }
  }
  return { today, rowCount: lines.length - 1, buffer: Buffer.from(`\ufeff${lines.join("\n")}\n`) };
}
