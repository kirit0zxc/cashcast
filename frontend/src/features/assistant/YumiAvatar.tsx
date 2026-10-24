import { Component, lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { Aura } from "../../ui/Aura";

// 3D-Юми (VRM). three.js и модель грузятся отдельным чанком только здесь.
// Модель — автор Ymi, используется с его разрешения для проекта команды; см. vendor/mascot/README.md.
const Mascot = lazy(() => import("../../vendor/mascot/react.js").then(m => ({ default: m.Mascot })));

type Mood = "idle" | "thinking" | "success" | "error";

// Маскот — украшение: любая ошибка WebGL/загрузки показывает обычную ауру, а не роняет чат.
class Fallback extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <Aura tone="assistant" cell={4} /> : this.props.children; }
}

const narrow = () => typeof window !== "undefined" && window.matchMedia("(max-width: 700px)").matches;

export function YumiAvatar({ mood }: { mood: Mood }) {
  // На телефоне 3D (≈2,4 МБ) не грузим без спроса.
  const [enabled, setEnabled] = useState(() => !narrow());
  useEffect(() => {
    if (!enabled) return;
    // Ядро тоже грузим лениво: иначе three.js попадает в общий бандл кабинета.
    void import("../../vendor/mascot/index.js")
      .then(m => m.getMascot().setState(mood))
      .catch(() => { /* маскот не должен мешать чату */ });
  }, [mood, enabled]);
  if (!enabled) return <div className="yumi-avatar off">
    <Aura tone="assistant" cell={4} />
    <button type="button" className="ghost" onClick={() => setEnabled(true)}>Показать Юми</button>
  </div>;
  return <div className="yumi-avatar">
    <Fallback>
      <Suspense fallback={<Aura tone="assistant" cell={4} />}>
        <Mascot renderer={{ assetsBase: "/mascot/", fit: "portrait" }} className="yumi-canvas" />
      </Suspense>
    </Fallback>
  </div>;
}
