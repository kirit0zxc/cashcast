import type { FaceKey } from './types.ts';
export type { FaceKey };
/**
 * Какая метка действует в момент time: последняя, чьё at уже наступило.
 * -1 — ни одной: действует основное выражение состояния.
 * Метки должны быть отсортированы по at.
 */
export declare function faceKeyAt(keys: readonly FaceKey[], time: number): number;
export declare const sortKeys: (keys: readonly FaceKey[]) => FaceKey[];
