import type { NormalizedPayload } from './types';
/**
 * Оборачивает любые входные данные в безопасный доступ.
 *
 * Главное требование к фронту маскота: что бы ни прислал бэкенд —
 * null, строку вместо объекта, недогруженный JSON, — приложение
 * не должно падать. Здесь всё приводится к типу или к запасному
 * значению, без исключений наружу.
 */
export declare function normalize(raw: unknown): NormalizedPayload;
/** Имя события и полезная нагрузка, вытащенные из чего угодно. */
export interface ParsedEvent {
    name: string;
    payload: unknown;
}
/**
 * Приводит сообщение к паре «имя события + данные».
 *
 * Разные бэкенды называют поле по-разному: type, event, name, action.
 * Вместо того чтобы требовать один формат, разбираем все
 * распространённые — интеграция не должна упираться в соглашение
 * об имени поля.
 */
export declare function parseEvent(input: unknown): ParsedEvent | null;
