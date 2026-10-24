import { MascotBridge } from './bridge/MascotBridge';
import type { BridgeOptions, BridgeRules } from './bridge/types';
import type { MascotCoreOptions } from './core/MascotCore';
export interface ConnectOptions extends BridgeOptions {
    /** Свои правила поверх стандартных. */
    rules?: BridgeRules;
    /** Не подмешивать стандартную таблицу. */
    replaceRules?: boolean;
    core?: MascotCoreOptions;
}
/**
 * Один вызов для подключения маскота к пайплайну.
 *
 *   const bridge = connect();
 *   bridge.listenWebSocket(ws);
 *   window.fetch = bridge.wrapFetch();
 *
 * Дальше бэкенд может слать события как привык: мост разберёт
 * сообщение, найдёт реакцию в таблице и ничего не уронит, если
 * придёт что-то неожиданное.
 */
export declare function connect(options?: ConnectOptions): MascotBridge;
