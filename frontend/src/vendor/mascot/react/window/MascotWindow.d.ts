import type { MascotCore } from '../../core/MascotCore';
import type { VrmRendererOptions } from '../../renderers/vrm/VrmRenderer';
import { type MenuSection } from './MenuBar';
export interface MascotWindowProps {
    /** По умолчанию — общий экземпляр, см. getMascot(). */
    core?: MascotCore;
    /** Подпись в заголовке. */
    title?: string;
    /**
     * Меню. Массив заменяет стандартное, функция получает стандартное
     * и возвращает своё — так удобно добавить раздел, не теряя готовых.
     */
    menu?: MenuSection[] | ((defaults: MenuSection[]) => MenuSection[]);
    renderer?: VrmRendererOptions;
    /** Ключ, под которым запоминается положение окна. */
    storageKey?: string;
    /**
     * Пиксельный шрифт с Google Fonts. false — не грузить (свой шрифт
     * задаётся через --yumi-font): нужно при строгой CSP или если
     * приложение не хочет внешних запросов.
     */
    font?: boolean;
    /** nonce для вставляемого <style> — при CSP со style-src 'nonce-…'. */
    nonce?: string;
    /**
     * Фон сцены. По умолчанию — комната с экранами (bg/room.webp в папке
     * ассетов), строка — свой адрес картинки (относительный — от
     * assetsBase), false — без фона.
     */
    backdrop?: boolean | string;
    /** Клик по Юми. По умолчанию она здоровается. */
    onMascotClick?: (core: MascotCore) => void;
}
/**
 * Юми в ретро-окне поверх интерфейса.
 *
 * Заголовок перетаскивается; «–» сворачивает во вкладку у левого края,
 * «□» выносит в отдельное окно поверх всех окон (Chromium), «X» прячет
 * до узкой вкладки. Положение, режим, кадр и «без звука» запоминаются.
 *
 * Окно рендерится порталом в document.body: transform или filter у
 * предков в приложении не сдвинут и не обрежут его.
 */
export declare function MascotWindow({ core: coreProp, title, menu, renderer, storageKey, font, nonce, backdrop, onMascotClick, }: MascotWindowProps): import("react").JSX.Element;
