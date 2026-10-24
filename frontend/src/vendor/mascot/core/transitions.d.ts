/**
 * Таблица переходов: плавность для конкретной пары «из → в».
 *
 * Подбирается в песочнице на вкладке «Цепочка» и хранится в
 * transitions.json рядом. Там же — сохранённые цепочки.
 *
 * Модуль без DOM: им же dev-сервер проверяет то, что сохраняет песочница.
 */
/** Один шаг цепочки. */
export interface ChainStep {
    kind: 'state' | 'clip';
    name: string;
    /** До конца клипа или фиксированное время. */
    mode: 'end' | 'secs';
    secs: number;
    /** Переход в шаг, мс; null — из таблицы, состояния или по умолчанию. */
    fadeMs: number | null;
}
export interface TransitionsFile {
    /** Ключ — «из→в», значение — плавность перехода в мс. */
    transitions: Record<string, number>;
    chains: Record<string, ChainStep[]>;
}
export declare const transitionKey: (from: string, to: string) => string;
export declare const splitTransitionKey: (key: string) => [string, string];
export declare const isChainName: (name: string) => boolean;
/** Разобрать файл; битое отбрасывается, ничего не бросает. */
export declare function parseTransitionsFile(raw: unknown): TransitionsFile;
