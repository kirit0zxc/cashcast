import type { MascotCore } from '../core/MascotCore';
import type { BridgeOptions, BridgeRules, WrapFetchOptions } from './types';
/**
 * Мост между пайплайном и маскотом.
 *
 * Весь смысл в том, чтобы подключение сводилось к таблице, а не
 * к правкам кода в десяти местах. Бэкенд шлёт события как умеет,
 * мост приводит их к общему виду и смотрит в таблицу.
 *
 * Отдельное требование: что бы ни пришло, приложение не падает.
 * Любое исключение внутри обработки гасится здесь и дальше не идёт.
 */
export declare class MascotBridge {
    private core;
    private rules;
    private opts;
    /** -Infinity: иначе события в первые throttleMs после загрузки страницы откладывались бы. */
    private lastAt;
    private cleanups;
    /** Реакция, отложенная throttle'ом: последняя всегда доходит. */
    private deferred;
    private deferTimer;
    /** Сколько запросов через wrapFetch сейчас в полёте. */
    private inFlight;
    /** Итоги текущей волны запросов. */
    private batch;
    constructor(core: MascotCore, rules: BridgeRules, options?: BridgeOptions);
    /** Добавить или переопределить правила на лету. */
    extend(rules: BridgeRules): void;
    /** Основной вход: имя события и произвольные данные. */
    handle(name: string, payload?: unknown): void;
    /** Принять «сырое» сообщение, из которого ещё надо достать имя. */
    handleRaw(input: unknown): void;
    private dispatch;
    /** Исполнить готовую реакцию. Жест — часть состояния, а не обход ядра. */
    private apply;
    /**
     * Разворачивает функции-реакции до конкретного действия.
     *
     * Функция может вернуть другую функцию — это удобно для общих
     * правил, но зациклиться на этом не хочется, поэтому глубина
     * ограничена.
     */
    private resolve;
    private applyState;
    /**
     * Подписаться и вернуть отписку только от этого источника.
     * dispose() снимает все подписки моста разом.
     */
    private subscribe;
    /** Любой EventTarget: window, document, свой эмиттер. */
    listen(target: EventTarget, events: string[]): () => void;
    /** WebSocket: каждое сообщение разбирается автоматически. */
    listenWebSocket(ws: WebSocket): () => void;
    /** Server-Sent Events — так был устроен стрим в прошлой Yumi. */
    listenEventSource(es: EventSource, namedEvents?: string[]): () => void;
    /**
     * Обёртка над fetch: запрос сам переводит Юми в thinking,
     * а ответ — в success или error.
     *
     * Это самый дешёвый способ интеграции: одна строка подмены,
     * и маскот уже отражает происходящее, без единого вызова руками.
     * Собственные файлы Юми грузит мимо этой обёртки.
     */
    wrapFetch(base?: typeof fetch, options?: WrapFetchOptions): typeof fetch;
    /** Запрос вернулся — подводим итог волны, когда вернулся последний. */
    private settle;
    dispose(): void;
}
