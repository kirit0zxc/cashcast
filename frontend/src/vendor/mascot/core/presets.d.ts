import type { StateSpec, VrmExpression } from './types.ts';
/**
 * Свои состояния, собранные в студии: выражение лица + клип + свет.
 * Хранятся в presets.json рядом с этим файлом и попадают в сборку.
 *
 * Модуль без DOM: им же dev-сервер проверяет то, что сохраняет студия.
 */
export type Presets = Record<string, StateSpec>;
export declare const EXPRESSIONS: readonly VrmExpression[];
export declare const isPresetName: (name: string) => boolean;
/**
 * Привести что угодно к StateSpec или вернуть null.
 *
 * Файл правят руками и через студию; битая запись не должна ронять
 * маскота — она просто пропускается.
 */
export declare function toStateSpec(raw: unknown): StateSpec | null;
/** Разобрать весь файл: битые и неправильно названные записи отбрасываются. */
export declare function parsePresets(raw: unknown): Presets;
