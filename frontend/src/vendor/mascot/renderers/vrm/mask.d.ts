import type { ClipMask } from '../../core/clips';
/**
 * Пропускать ли дорожку при заданной маске.
 *
 * Юми всегда в кадре по грудь, ноги не видны никогда. Выбрасывая их,
 * мы и экономим, и снимаем конфликт: низ остаётся за процедурной
 * анимацией, а клип управляет только тем, что видно.
 */
export declare function keepTrack(vrmBoneName: string, property: string, mask: ClipMask): boolean;
