import type { SpeechAccent, TTSProvider, VisemeWeights } from './types';
export interface VoiceSink {
    /** Текущие веса визем, каждый кадр речи. */
    visemes(weights: VisemeWeights): void;
    /** Короткий акцент: кивок, брови на вопросе, пауза. */
    accent(kind: SpeechAccent['kind']): void;
    /** Речь началась или закончилась. */
    speaking(active: boolean): void;
}
export interface VoiceOptions {
    provider?: TTSProvider;
    rate?: number;
    /** Насколько широко открывается рот, 0..1. */
    mouthGain?: number;
}
/**
 * Голос и мимика речи.
 *
 * Раскладка рта считается из текста заранее, а события границ слов
 * от синтезатора подтягивают её к реальному произношению. Если
 * провайдер отдаёт звук (бэкендовый TTS), включается анализ
 * амплитуды и спектра и вытесняет текстовую раскладку.
 */
export declare class Voice {
    private provider;
    private audio;
    private sink;
    private plan;
    private startedAt;
    /** Сдвиг раскладки, накопленный из событий границ слов. */
    private driftMs;
    private firedAccents;
    /**
     * Номер текущей реплики. Колбэки провайдера от вытесненной реплики
     * приходят с опозданием, и без этой сверки onEnd старой фразы
     * закрыл бы рот новой.
     */
    private seq;
    private frame;
    private win;
    private rate;
    private gain;
    constructor(opts?: VoiceOptions);
    setSink(sink: VoiceSink): void;
    /**
     * Чьими кадрами считать липсинк. Юми в отдельном окне говорит, пока
     * главная вкладка скрыта, — кадры главного окна в это время стоят.
     */
    setFrameSource(win: Window): void;
    /** Настроить тембр текущего провайдера, если он это умеет. */
    setVoiceOptions(next: {
        voiceName?: string;
        rate?: number;
        pitch?: number;
    }): void;
    /**
     * Подменить источник голоса. Идущая реплика обрывается здесь же:
     * контракт не обязывает провайдера присылать onEnd при отмене, и без
     * этого Юми осталась бы «говорящей». Номер реплики сдвигается так же,
     * как в cancel(): колбэки старого провайдера больше не считаются своими.
     */
    setProvider(provider: TTSProvider): void;
    get isSpeaking(): boolean;
    say(text: string): Promise<void>;
    cancel(): void;
    /** Остановить только свою часть: раскладку рта и цикл кадров. */
    private stopLocal;
    private stop;
    /**
     * Синтезатор дошёл до слова — подвинуть раскладку туда же.
     *
     * Без этого расхождение копится: оценка длительности по символам
     * всегда немного врёт, и к концу длинной фразы рот уходит вперёд
     * или отстаёт на полслова.
     */
    private resync;
    private tick;
    private fireAccents;
}
