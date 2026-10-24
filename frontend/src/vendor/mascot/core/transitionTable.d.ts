import { type ChainStep } from './transitions';
/** Плавность переходов «из→в», мс. Сохранённые в файле плюс заданные на лету. */
export declare const TRANSITIONS: Record<string, number>;
/** Сохранённые в песочнице цепочки. */
export declare const CHAINS: Record<string, ChainStep[]>;
/** Плавность перехода из from в to, если она есть в таблице. */
export declare function transitionFade(from: string, to: string): number | undefined;
/**
 * Задать плавность для пары на лету, без файла:
 *   defineTransition('thinking', 'success', 600);
 */
export declare function defineTransition(from: string, to: string, fadeMs: number): void;
export declare function removeTransition(from: string, to: string): void;
