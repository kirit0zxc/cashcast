/** Картинка фона по умолчанию — относительно assetsBase. */
export declare const DEFAULT_BACKDROP = "bg/room.webp";
/**
 * Адрес картинки фона из пропа backdrop: true — картинка по умолчанию из
 * папки ассетов, строка — свой адрес (относительный — тоже от assetsBase,
 * как модель и клипы), false — без фона.
 */
export declare function backdropUrl(backdrop: boolean | string, assetsBase?: string): string | null;
/**
 * Значение для background-image. Кавычки, обратный слэш и переводы строк
 * экранируются: иначе адрес с ними сделал бы правило недействительным,
 * и фон молча пропал бы.
 */
export declare function cssUrl(url: string): string;
