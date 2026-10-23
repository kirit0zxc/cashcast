import { useEffect, useState } from "react";

// Минимальный каркас: проверяет доступность API через /api/v1/health.
// Диана строит поверх экраны imports / transactions / forecast / planning / scenarios.
export function App() {
  const [health, setHealth] = useState<string>("проверяем…");

  useEffect(() => {
    fetch("/api/v1/health")
      .then((r) => r.json())
      .then((d: { status: string }) => setHealth(d.status))
      .catch(() => setHealth("недоступен"));
  }, []);

  return (
    <main style={{ fontFamily: "Segoe UI, Arial, sans-serif", padding: 24 }}>
      <h1>CashCast</h1>
      <p>Прогноз денежного потока для малого бизнеса. Каркас фронтенда.</p>
      <p>
        Состояние API: <strong>{health}</strong>
      </p>
    </main>
  );
}
