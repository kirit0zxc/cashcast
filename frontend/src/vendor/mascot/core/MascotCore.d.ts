import { type VoiceOptions } from '../voice/Voice';
import type { TTSProvider } from '../voice/types';
import type { Listener, MascotRenderer, MascotState } from './types';
export interface MascotCoreOptions {
    /** С какого состояния начинаем. */
    initialState?: MascotState;
    /** Следить за курсором (в состояниях с followPointer). */
    trackPointer?: boolean;
    /** Диапазон между морганиями, мс. */
    blinkRange?: [number, number];
    /**
     * Меньше фонового движения: без микро-саккад. По умолчанию 'auto' —
     * по системной настройке prefers-reduced-motion.
     */
    reducedMotion?: boolean | 'auto';
    /** Писать переходы в консоль. */
    debug?: boolean;
    /** Настройки голоса; провайдера можно подменить позже. */
    voice?: VoiceOptions;
}
/**
 * Мозг маскота. Ничего не знает про three.js, DOM трогает только
 * ради слушателя курсора. Всю картинку рисует renderer.
 *
 * Состояния и их таймеры живут независимо от картинки: Юми может быть
 * свёрнута, а пайплайн — слать события. Когда картинка вернётся, она
 * покажет актуальное состояние, а не давно прошедшую радость.
 */
export declare class MascotCore {
    private renderer;
    /** Рендерер, который ещё грузится. */
    private pendingRenderer;
    /** Клип, который играет текущее состояние, и последний выбранный из списка. */
    private stateClip;
    private lastPicked;
    private opts;
    private listeners;
    private state;
    private resetTimer;
    private blinkTimer;
    private saccadeTimer;
    /** Куда смотрит, -1..1. Складывается из курсора и микро-саккад. */
    private pointer;
    private saccade;
    private disposed;
    private container;
    private onPointerMove?;
    /** Окно, где сейчас Юми: курсор и кадры берём у него. */
    private win;
    /** Окно, на которое повешен слушатель курсора, — снимать надо с него же. */
    private pointerWin;
    /** Выбор пользователя «без звука». */
    private muted;
    /** Голос заглушён приложением (например, окно закрыто) — выбор пользователя не трогаем. */
    private suppressed;
    /** Последняя позиция курсора; пересчитываем раз в кадр, не на каждое событие. */
    private lastPointer;
    private gazeFrame;
    private voice;
    /** Куда вернуться, когда Юми договорит. */
    private stateBeforeSpeech;
    constructor(options?: MascotCoreOptions);
    /**
     * Речь началась или кончилась.
     *
     * На время реплики тело уходит в speaking, а потом возвращается:
     * в зацикленное состояние (Юми думала — думает дальше) или в покой,
     * если до реплики был разовый жест — повторять его второй раз странно.
     */
    private onSpeaking;
    attach(renderer: MascotRenderer, container: HTMLElement): Promise<void>;
    /**
     * Отсоединить рендерер и остановить всё, что работает на картинку.
     * Состояние и его таймер не трогаем — они живут и без картинки.
     *
     * С аргументом — только если подключён именно он: так размонтирование
     * старого компонента не снесёт рендерер, который уже поставил новый.
     */
    detach(renderer?: MascotRenderer): void;
    /**
     * Главная точка входа: сюда шлёт события пайплайн.
     *
     * Плавность перехода: opts.fadeMs (разово) → таблица переходов
     * для пары «прошлое→новое» → fadeMs состояния → 280 мс.
     */
    setState(next: MascotState, opts?: {
        fadeMs?: number;
    }): void;
    getState(): MascotState;
    /** Прямой доступ к рендереру — нужен песочнице и отладке. */
    getRenderer(): MascotRenderer | null;
    /**
     * Разовый жест поверх текущего состояния — например, кивок из правила
     * моста { state, clip }. Считается клипом состояния: если оно уходит
     * в покой «по концу клипа», конец этого жеста его и завершит.
     */
    playGesture(clip: string): void;
    /** Таймер возврата в покой — работает и без картинки. */
    private armReset;
    /** Показать состояние на картинке, если она есть. */
    private showState;
    /** Петля покоя — куда возвращаются разовые жесты. */
    private idleClip;
    /** Клип для состояния; из списка — случайный, но не тот же, что в прошлый раз. */
    private pickClip;
    /** Рендерер доиграл разовый клип. */
    private onClipEnd;
    /** Произнести реплику: голос, липсинк, кивки и возврат в прежнее состояние. */
    say(text: string): void;
    /** Без звука (выбор пользователя): реплики только текстом; текущая речь обрывается. */
    setMuted(muted: boolean): void;
    get isMuted(): boolean;
    /**
     * Заглушить голос по решению приложения — например, пока окно Юми
     * закрыто. Выбор пользователя «без звука» при этом не меняется.
     */
    setVoiceSuppressed(suppressed: boolean): void;
    /** Оборвать речь на полуслове. */
    hush(): void;
    /**
     * Подменить источник голоса — например, на бэкендовый TTS.
     * Лицо и тело об этом не узнают.
     */
    setVoiceProvider(provider: TTSProvider): void;
    /** Голос, темп и высота тона. */
    setVoiceOptions(next: {
        voiceName?: string;
        rate?: number;
        pitch?: number;
    }): void;
    get isSpeaking(): boolean;
    /** Раскрытие рта 0..1. Сюда пишет липсинк. */
    setMouth(openness: number): void;
    /** Моргание, саккады, курсор. Повторный запуск ничего не удваивает. */
    private startLife;
    private stopLife;
    private scheduleBlink;
    /**
     * Микро-саккады: глаз никогда не стоит идеально ровно.
     * Без них взгляд выглядит стеклянным, с ними — живым.
     */
    private scheduleSaccade;
    private startPointerTracking;
    /**
     * Взгляд считается от головы Юми, а не от центра окна: если она
     * сидит в углу, то должна смотреть на курсор, а не мимо него.
     * Масштаб — полэкрана: курсор у края окна даёт полный поворот.
     */
    private updatePointerGaze;
    private containerCenter;
    /** Поставить взгляд вручную, если курсор не нужен (trackPointer: false). */
    lookAt(x: number, y: number): void;
    /**
     * Куда смотреть. За курсором — только в состояниях с followPointer
     * (по умолчанию это покой); в остальных — в камеру, с саккадами.
     * Сглаживание в рендерере делает возврат взгляда плавным. Взгляд,
     * поставленный вручную через lookAt, действует всегда.
     */
    private pushGaze;
    /** Возвращает отписку. Тип void — чтобы годилась как cleanup в useEffect. */
    on(fn: Listener): () => void;
    private emit;
    dispose(): void;
}
/** Плавность перехода в клип состояния, если у него не задана своя. */
export declare const DEFAULT_FADE_MS = 280;
