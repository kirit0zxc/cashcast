/**
 * Метка, которой мост помечает свою обёртку над fetch: по ней
 * загрузчик находит настоящий fetch под ней.
 */
export declare const ORIGINAL_FETCH: unique symbol;
export declare function fetchBuffer(url: string): Promise<ArrayBuffer>;
/** Папка файла — от неё GLTF ищет внешние текстуры и буферы. */
export declare const baseOf: (url: string) => string;
/**
 * Собрать адрес ассета.
 *
 * Относительные пути считаются от assetsBase, поэтому приложение,
 * живущее не в корне домена, или расширение (chrome.runtime.getURL)
 * меняют одну настройку, а не реестр клипов.
 */
export declare function resolveAsset(url: string, base: string): string;
