/**
 * Отдельное окно поверх всех окон для Юми.
 *
 * Окно живёт в том же JS-контексте, что и страница: ядро, состояние и
 * подписки общие, второй копии Юми нет. Открыть можно только из
 * обработчика клика — так требует браузер.
 */
export declare class PipWindow {
    private win;
    private readonly onClosed;
    constructor(onClosed: () => void);
    static supported(): boolean;
    get window(): Window | null;
    open(size: {
        width: number;
        height: number;
    }, font?: boolean, nonce?: string): Promise<Window | null>;
    close(): void;
}
