import { MascotCore, type MascotCoreOptions } from './core/MascotCore';
/**
 * Общий экземпляр маскота.
 *
 * Нужен, чтобы дёргать Юми откуда угодно — из интерсептора axios,
 * из обработчика WebSocket, из любого модуля, — не протаскивая
 * пропсы через половину дерева компонентов.
 *
 * Опции применяются только при первом вызове: дальше экземпляр уже
 * создан, и молча проглотить новые настройки было бы хуже, чем сказать.
 */
export declare function getMascot(options?: MascotCoreOptions): MascotCore;
export declare function resetMascot(): void;
