/** Режим окна: открыто на странице, свёрнуто во вкладку, закрыто. */
export type WindowMode = 'open' | 'minimized' | 'closed';
export type WindowFit = 'full' | 'half' | 'portrait';
export interface Placement {
    /** Желаемое положение. На экране окно может стоять ближе к краю, если экран уже. */
    x: number;
    y: number;
    mode: WindowMode;
    muted: boolean;
    /** Кадр, выбранный в меню «Вид»; не задан — кадр по умолчанию. */
    fit?: WindowFit;
}
export interface Size {
    width: number;
    height: number;
}
/**
 * Где стоит окно Юми и в каком оно режиме.
 *
 * Положение запоминается в localStorage — это удобство конкретного
 * пользователя, а не данные: если хранилище недоступно (приватный
 * режим, запрет сайта), окно просто открывается на месте по умолчанию.
 */
export declare class WindowPlacement {
    private readonly key;
    private readonly storage;
    constructor(key?: string, storage?: Storage | null);
    /**
     * Положение по умолчанию: слева внизу. На узком экране окно сразу
     * свёрнуто — там оно закрыло бы половину интерфейса.
     */
    initial(viewport: Size, window: Size): Placement;
    load(viewport: Size, window: Size): Placement;
    save(p: Placement): void;
    /** Окно целиком в экране: заголовок всегда можно схватить. */
    clamp(p: {
        x: number;
        y: number;
    }, viewport: Size, window: Size): {
        x: number;
        y: number;
    };
}
