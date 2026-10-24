import type { TTSHandlers, TTSProvider } from './types';
export interface VoiceInfo {
    name: string;
    lang: string;
    local: boolean;
    isDefault: boolean;
}
/**
 * Голос средствами браузера. Бесплатно, офлайн, работает сразу.
 *
 * Ограничение, которое определяет всю конструкцию липсинка: Chrome
 * проигрывает синтезированную речь мимо Web Audio, поэтому звук
 * нельзя проанализировать. Зато приходят события границ слов.
 */
/**
 * Голоса, которые берём в первую очередь, по убыванию — подстрока имени.
 * Ирина (Microsoft Irina, Windows) — выбранный голос Юми. Её нет на Mac,
 * Linux и телефонах; там подбор идёт по качеству среди русских голосов.
 */
export declare const DEFAULT_PREFERRED_VOICES: readonly string[];
type BrowserTTSOptions = {
    lang?: string;
    rate?: number;
    pitch?: number;
    /** Точное имя голоса — важнее всех предпочтений. */
    voiceName?: string;
    /** Подстроки имён голосов по приоритету; по умолчанию — Ирина. */
    prefer?: readonly string[];
};
/** Минимум, по которому выбирается голос: есть и у системного голоса, и у VoiceInfo. */
type VoiceLike = {
    name: string;
    lang: string;
    default?: boolean;
};
export declare class BrowserTTS implements TTSProvider {
    readonly name = "browser";
    readonly hasBoundaries = true;
    private opts;
    private lastCancelAt;
    /** Растёт на каждой отмене: реплика, ждавшая паузы, понимает, что её отменили. */
    private generation;
    /** Завершить текущую реплику: снять её таймеры и отпустить промис. */
    private finishCurrent;
    constructor(opts?: BrowserTTSOptions);
    static isAvailable(): boolean;
    /**
     * Список голосов приходит асинхронно.
     *
     * При первом обращении getVoices() почти всегда пуст, и если
     * спросить его синхронно, окажется что голосов «нет» — хотя через
     * мгновение они появятся. Это самая частая причина немой первой фразы.
     */
    static loadVoices(timeoutMs?: number): Promise<SpeechSynthesisVoice[]>;
    /** Что доступно в системе — для диагностики. */
    static list(): Promise<VoiceInfo[]>;
    /** Поменять голос и тембр на лету. */
    setOptions(next: Partial<typeof this.opts>): void;
    getOptions(): {
        lang?: string;
        rate?: number;
        pitch?: number;
        /** Точное имя голоса — важнее всех предпочтений. */
        voiceName?: string;
        /** Подстроки имён голосов по приоритету; по умолчанию — Ирина. */
        prefer?: readonly string[];
    };
    /**
     * Насколько голос подходит Юми.
     *
     * Сначала — предпочтённые (по умолчанию Ирина). Дальше — по качеству:
     * нейросетевые голоса (Google, «Natural»/«Neural») живее системных
     * SAPI, которые узнаются по «роботности» с первых слов.
     */
    private static score;
    /**
     * Выбрать голос из списка: точное имя → предпочтённые → лучший на
     * нужном языке → любой. Им же пользуется песочница, чтобы показать
     * в списке тот голос, которым Юми и заговорит.
     */
    static choose<V extends VoiceLike>(voices: readonly V[], { lang, voiceName, prefer }?: BrowserTTSOptions): V | null;
    private pick;
    speak(text: string, handlers: TTSHandlers): Promise<void>;
    cancel(): void;
}
export {};
