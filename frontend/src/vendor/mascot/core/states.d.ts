import type { BuiltinState, MascotState, StateSpec } from './types';
/** Сколько грустить после ошибки, прежде чем вернуться в покой. */
export declare const ERROR_RESET_MS = 5000;
/**
 * Встроенные состояния. Словарь взят из Yumi 1.0 один в один,
 * чтобы существующий код, который шлёт эти имена, завёлся без правок.
 *
 * Поле action ссылается на имя клипа в реестре (см. clips.ts).
 * Клипа может не быть — тогда отыграет только мимика и свет.
 */
export declare const BUILTIN_STATES: Readonly<Record<BuiltinState, StateSpec>>;
/** Свои состояния из студии (presets.json). Одноимённые перекрывают встроенные. */
export declare const PRESETS: Record<string, StateSpec>;
/**
 * Все состояния, которые знает Юми: встроенные, пресеты и заданные на лету.
 *
 * Объект без прототипа: имя состояния может прийти из сети, и
 * 'constructor' или 'toString' не должны находиться как «состояния».
 */
export declare const STATES: Record<MascotState, StateSpec>;
/** Есть ли такое состояние — только своё поле, не унаследованное. */
export declare const hasState: (name: string) => boolean;
/**
 * Добавить или заменить состояние на лету — без правки файлов.
 *
 *   defineState('celebrate', { expression: 'happy', weight: 0.9,
 *     action: 'victory', resetAfterMs: 'clip', glow: { ... } });
 *   getMascot().setState('celebrate');
 */
export declare function defineState(name: string, spec: StateSpec): void;
/**
 * Убрать своё состояние — и заданное на лету, и пресет из файла.
 * Встроенное с тем же именем возвращается.
 */
export declare function removeState(name: string): void;
