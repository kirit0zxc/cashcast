import { type ClipMask } from '../../core/clips';
import type { FaceKey, GlowSpec, MascotRenderer, VrmExpression } from '../../core/types';
import { type CameraSettings } from './camera';
import { type ClipCameras } from './clipCameras';
export interface VrmRendererOptions extends Partial<CameraSettings> {
    /**
     * Откуда грузить модель и клипы. Относительные пути из реестра
     * клипов и modelUrl считаются от этой папки.
     *   '/static/mascot/'                       — приложение не в корне
     *   chrome.runtime.getURL('mascot/')        — расширение
     *   'https://cdn.example.com/yumi/'         — CDN
     */
    assetsBase?: string;
    /** Путь к модели; относительный — от assetsBase. */
    modelUrl?: string;
    /** Насколько охотно голова поворачивается за курсором, 0..1. */
    headFollow?: number;
    /**
     * Развести плечи наружу, в градусах.
     *
     * Анимации Mixamo рассчитаны на обычный торс, а худи у VRoid
     * заметно шире — без этого руки в покое тонут в одежде.
     */
    armSpread?: number;
    background?: boolean;
    /**
     * Меньше фонового движения: без покачивания корпуса и пульсации
     * свечения. Клипы состояний играют как обычно — они несут смысл.
     * 'auto' — по системной настройке prefers-reduced-motion.
     */
    reducedMotion?: boolean | 'auto';
}
type ClipRange = readonly [number, number];
export declare const clipOf: (key: string) => string;
export declare class VrmRenderer implements MascotRenderer {
    private opts;
    private scene;
    private camera;
    private gl;
    /**
     * Время прошлого кадра. Свой счётчик, а не THREE.Timer: Timer появился
     * в ядре three недавно, а пакет совместим и с более старыми версиями.
     */
    private lastTick;
    /** Контейнер не виден (свёрнут, прокручен, display: none) — не рисуем. */
    private offscreen;
    private visibility;
    /** Контекст WebGL потерян — не рисуем, пока браузер его не вернёт. */
    private contextLost;
    private vrm;
    private mixer;
    private container;
    private resizeObserver;
    private frame;
    private elapsed;
    private actions;
    private pending;
    private current;
    private currentName;
    /** Для обрезанных клипов: где отрезок в исходном клипе и его полная длина. */
    private clipMeta;
    /** Последний запрошенный клип — только он имеет право включиться. */
    private wantedName;
    /** Номер последнего запроса клипа: переключает только он. */
    private requestSeq;
    /** Зацикленный клип, к которому возвращаемся после разового жеста. */
    private baseName;
    private disposed;
    private expressionTarget;
    /** Основное выражение состояния — действует вне дорожки. */
    private baseExpression;
    private faceTrack;
    /** Какая метка сейчас применена: -1 — основное выражение, -2 — пересчитать. */
    private faceIndex;
    private expressionNow;
    private gazeTarget;
    private gazeNow;
    private lookAtAnchor;
    /**
     * Габариты модели в позе покоя, замеренные один раз при загрузке.
     * Если мерить по текущей позе, кадр дрожал бы вместе с анимацией.
     */
    private bounds;
    /** Точка взгляда «прямо в камеру» и оси камеры — от них считается взгляд. */
    private gazeBase;
    private camRight;
    private camUp;
    private gazePoint;
    /** Куда сейчас смотрит камера — её lookAt. */
    private camTarget;
    /** Цель плавного переезда камеры (смена клипа со своим кадром); null — стоим. */
    private camGoal;
    /** Каким набором настроек камера расставлена — чтобы не переезжать без нужды. */
    private camKey;
    private tmpVec;
    private blinkValue;
    private blinkUntil;
    private blinkDuration;
    /** Целевые и текущие веса пяти визем. */
    private visemeTarget;
    private visemeNow;
    private speaking;
    /** Короткие акценты речи: кивки, брови, паузы. */
    private accents;
    /** Мгновенная подмешка выражения поверх базовой эмоции. */
    private accentExpr;
    private armSpread;
    /** Окно, в котором живёт контейнер, — от него кадры и размеры. */
    private win;
    private reducedMotion;
    /**
     * Позы костей до того, как мы добавили процедурную поправку.
     *
     * Микшер перезаписывает только те кости, для которых в текущем клипе
     * есть дорожка. Для остальных наш `+=` копился бы кадр за кадром и
     * раскручивал кость — поэтому каждый кадр сначала откатываем добавку.
     */
    private offsetBases;
    private glow;
    private glowColor;
    private rimMaterials;
    constructor(options?: VrmRendererOptions);
    /** Подобрать разведение плеч на лету, в градусах. */
    setArmSpread(deg: number): void;
    getArmSpread(): number;
    init(container: HTMLElement): Promise<void>;
    /**
     * Не рисовать, пока контейнер не виден: Юми прокручена за экран,
     * окно свёрнуто или спрятано. Иначе она жгла бы 60 кадров в секунду
     * впустую — на ноутбуке это заметно по батарее.
     */
    private watchVisibility;
    private setupLights;
    private loadModel;
    /** Находим MToon-материалы: у них есть встроенный параметрический rim. */
    private collectRimMaterials;
    /**
     * Вписываем модель в кадр по её реальным габаритам.
     *
     * Так не нужно подбирать расстояние вручную: поменяется причёска,
     * обувь или пропорции — камера пересчитает сама.
     */
    /** Замерить габариты модели — один раз, в позе покоя. */
    private measure;
    /**
     * Вписываем модель в кадр по её реальным габаритам.
     *
     * Так не нужно подбирать расстояние вручную: поменяется причёска,
     * обувь или пропорции — камера пересчитает сама. Поверх — настройки
     * кадра: крупность, сдвиг, поворот и наклон вокруг Юми.
     */
    private frameCamera;
    /** Применить положение, взгляд и угол обзора камеры. */
    private applyCameraPose;
    /** Шаг плавного переезда камеры к кадру нового клипа. */
    private moveCamera;
    /**
     * Сменился клип (или он остановлен) — переехать к его кадру, если тот
     * отличается от текущего. Правку кадров клипов из другого рендерера
     * на странице этот рендерер увидит при следующей смене клипа.
     */
    private followClipCamera;
    /**
     * Для диагностики: сколько секунд анимации отрисовано и рисуется ли
     * Юми сейчас (не на паузе из-за невидимости или потери контекста).
     */
    stats(): {
        elapsed: number;
        drawing: boolean;
    };
    /** Имя текущего клипа, как его знают состояния и файл кадров клипов. */
    private clipName;
    /** Кадр с учётом своего кадра текущего клипа — то, что сейчас на экране. */
    getEffectiveCamera(): CameraSettings;
    /** Свой кадр клипа (только отличия от общего) или null. */
    getClipCamera(clip: string): Partial<CameraSettings> | null;
    /** Все клипы со своим кадром. */
    getClipCameras(): ClipCameras;
    /**
     * Задать или убрать свой кадр клипа на лету. Если клип сейчас играет,
     * кадр применяется сразу — это нужно для настройки ползунками.
     */
    setClipCamera(clip: string, camera: Partial<CameraSettings> | null): void;
    /** Текущие настройки общего кадра. */
    getCamera(): CameraSettings;
    /** Поменять кадр на лету; значения зажимаются в допустимые пределы. */
    setCamera(patch: Partial<CameraSettings>): void;
    private resize;
    setExpression(name: VrmExpression, weight: number): void;
    setFaceTrack(clip: string | null, keys: readonly FaceKey[] | null): void;
    /** Целевое выражение; к нему лицо подтягивается плавно в applyExpressions. */
    private targetExpression;
    /**
     * Лицо по дорожке: пока играет клип дорожки, берём метку по его
     * времени, иначе основное выражение. Цели меняем только при смене
     * метки — сглаживание в applyExpressions делает переход мягким.
     */
    private applyFaceTrack;
    /** Что играет сейчас: имя, время, длина, пауза. */
    private offsetOf;
    /**
     * Что играет сейчас. Время и длина — в шкале исходного клипа:
     * у обрезанного клипа start..end — играющий отрезок внутри duration.
     */
    getClipState(): {
        name: string;
        time: number;
        duration: number;
        start: number;
        end: number;
        paused: boolean;
    } | null;
    /** Остановить или продолжить текущий клип — поза и лицо замирают на месте. */
    setClipPaused(paused: boolean): void;
    /** Перемотать текущий клип; на паузе поза обновится в следующем кадре. */
    seekClip(time: number): void;
    setGaze(x: number, y: number): void;
    /** Совместимость: одиночное раскрытие рта мапим на «аа». */
    setMouth(openness: number): void;
    /** Полный набор визем — сюда пишет липсинк. */
    setVisemes(weights: Record<string, number>): void;
    /**
     * Речь идёт или нет.
     *
     * Пока Юми говорит, эмоция приглушается: happy и sad у VRoid
     * сами деформируют рот, и на полной силе они забивают виземы —
     * получается шевеление губ вместо артикуляции.
     */
    setSpeaking(active: boolean): void;
    /** Короткий акцент: кивок на точке, брови на вопросе, пауза. */
    accent(kind: 'nod' | 'question' | 'pause' | 'emphasis'): void;
    blink(durationMs?: number): void;
    setGlow(spec: GlowSpec): void;
    playClip(name: string, opts?: {
        loop?: boolean;
        fadeMs?: number;
        mask?: ClipMask;
        range?: ClipRange;
        returnTo?: string;
    }): void;
    /**
     * Запомнить, что хотим играть, и включить, когда клип загрузится.
     *
     * Клипы грузятся с разной скоростью: без этой проверки медленный
     * клип, запрошенный раньше, перебил бы тот, что попросили позже.
     * Сверяется номер запроса, а не только имя: при перезагрузке файла
     * два запроса одного клипа могут завершиться в обратном порядке, и
     * устаревший не должен перезапустить клип со своими loop и fade.
     */
    private request;
    /** Разовый жест доигран — возвращаемся в зацикленный фон, а не замираем. */
    onClipEnd: ((name: string) => void) | null;
    private onClipFinished;
    /**
     * Проиграть файл напрямую, в обход реестра состояний.
     * Нужно для песочницы: бросила файл в папку — сразу проверила.
     */
    playFile(url: string, opts?: {
        mask?: ClipMask;
        loop?: boolean;
        reload?: boolean;
    }): void;
    /**
     * Сбросить разобранный файл, чтобы перечитать его с диска заново.
     * Если он сейчас играл — клипа больше нет, камера возвращается к
     * общему кадру.
     */
    forgetFile(url: string): void;
    private dropFile;
    stopClip(fadeMs?: number): void;
    capabilities(): {
        clips: string[];
        expressions: string[];
    };
    private onContextLost;
    private onContextRestored;
    /**
     * Где на экране голова — в координатах окна.
     *
     * По ней ядро считает взгляд: Юми может сидеть в углу, и смотреть
     * она должна на курсор относительно себя, а не центра окна.
     */
    getHeadScreenPosition(): {
        x: number;
        y: number;
    } | null;
    dispose(): void;
    private ensureClip;
    /**
     * Убрать прошлые обрезки того же клипа. Пока в студии двигают границы,
     * каждая правка — новое действие; без уборки они копились бы в микшере.
     */
    private evictVariants;
    private switchTo;
    private loop;
    /** Вернуть кости в состояние, в котором их оставил клип. */
    private restoreOffsets;
    /** Добавить поворот к кости, запомнив исходное значение. */
    private addRotation;
    /**
     * Отводим плечи наружу поверх клипа.
     *
     * Правка аддитивная: клип продолжает управлять рукой как задумано,
     * мы лишь сдвигаем её по дуге настолько, чтобы она вышла из ткани.
     * Руки в T-позе смотрят вдоль X, так что поворот вокруг Z
     * поднимает их — для правой руки знак зеркальный.
     */
    private applyArmSpread;
    /** Дыхание и лёгкое покачивание — то, чего не дают клипы. */
    private applyBreathing;
    /** Голова мягко доворачивается за курсором поверх клипа. */
    private applyHeadFollow;
    /**
     * Кивки и наклоны на знаках препинания.
     *
     * Говорящая голова, которая не двигается, выглядит мёртвой,
     * а равномерное покачивание — механическим. Привязка к пунктуации
     * даёт движение там, где его ждёт слушатель.
     */
    private applyAccents;
    private applyExpressions;
    private applyGlow;
    /**
     * Rim light берём не шейдерным хаком, а встроенным параметрическим
     * римом MToon — он штатный, анимируется и не ломается при обновлениях.
     */
    private pulseGlow;
}
export {};
