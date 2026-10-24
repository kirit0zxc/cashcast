/** Пункт меню окна. */
export interface MenuItem {
    label: string;
    onSelect: () => void;
    /** Галочка слева: для переключателей и выбора одного из нескольких. */
    checked?: boolean;
    disabled?: boolean;
}
/** Раздел меню: «Вид», «Звук»… null в items — разделитель. */
export interface MenuSection {
    label: string;
    items: (MenuItem | null)[];
}
/**
 * Строка меню в духе старых окон: раздел открывается кликом, пока
 * один открыт — соседние открываются наведением. Закрывается кликом
 * мимо, Escape или выбором пункта.
 *
 * С клавиатуры: ←/→ — между разделами, ↓/Enter — открыть и перейти к
 * пунктам, ↑/↓ — по пунктам, Escape — закрыть и вернуть фокус разделу.
 */
export declare function MenuBar({ sections }: {
    sections: MenuSection[];
}): import("react").JSX.Element | null;
