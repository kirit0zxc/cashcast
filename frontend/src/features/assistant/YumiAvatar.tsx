import { Component, lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { Aura } from "../../ui/Aura";

// 3D-Юми (VRM). three.js и модель грузятся отдельным чанком.
// Модель — автор Ymi, используется с его разрешения для проекта команды; см. vendor/mascot/README.md.
const Mascot = lazy(() => import("../../vendor/mascot/react.js").then(m => ({ default: m.Mascot })));

export type YumiMood = "idle" | "thinking" | "success" | "error";

// Маскот — украшение: любая ошибка WebGL/загрузки показывает обычную ауру, а не роняет кабинет.
class Fallback extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <Aura tone="assistant" cell={4} /> : this.props.children; }
}

const narrow = () => typeof window !== "undefined" && window.matchMedia("(max-width: 700px)").matches;

// Аватар в карточке ассистента в меню. Ядро маскота — общий экземпляр,
// поэтому настроение задаёт чат (useYumiMood), а не меню.
export function YumiAvatar() {
  // На телефоне карточка крошечная, 3D (≈2,4 МБ) там не грузим.
  const [enabled] = useState(() => !narrow());
  if (!enabled) return <Aura tone="assistant" cell={4} />;
  return <div className="yumi-avatar">
    <Fallback>
      <Suspense fallback={<Aura tone="assistant" cell={4} />}>
        <Mascot renderer={{ assetsBase: "/mascot/", fit: "portrait" }} className="yumi-canvas" />
      </Suspense>
    </Fallback>
  </div>;
}

// Чат сообщает Юми, что происходит: думает, ответила, ошибка.
export function useYumiMood(mood: YumiMood) {
  useEffect(() => {
    if (narrow()) return;
    // Ядро тоже грузим лениво: иначе three.js попадает в общий бандл кабинета.
    void import("../../vendor/mascot/index.js")
      .then(m => m.getMascot().setState(mood))
      .catch(() => { /* маскот не должен мешать чату */ });
  }, [mood]);
}
