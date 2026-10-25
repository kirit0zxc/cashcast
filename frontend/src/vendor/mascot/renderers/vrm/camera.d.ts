/**
 * Настройки камеры: как Юми стоит в кадре.
 *
 * Значения по умолчанию можно поменять в песочнице (вкладка «Камера») —
 * они сохраняются в camera.json рядом и попадают во все сборки.
 * Приложение всё равно может переопределить их опциями рендерера.
 *
 * Модуль без DOM и three: им же dev-сервер проверяет то, что сохраняет
 * песочница.
 */
export interface CameraSettings {
    /**
     * Что показываем:
     *  full     — вся фигура целиком
     *  half     — от бёдер вверх
     *  portrait — от груди вверх
     */
    fit: 'full' | 'half' | 'portrait';
    /** Воздух по краям кадра, доля от размера. 0.08 — восемь процентов. */
    margin: number;
    /** Крупность: больше единицы — ближе. */
    zoom: number;
    /** Сдвиг Юми в кадре по горизонтали, в метрах. Плюс — вправо. */
    offsetX: number;
    /** Сдвиг по вертикали, в метрах. Плюс — выше. */
    offsetY: number;
    /** Поворот камеры вокруг Юми, градусы. Плюс — заходим справа. */
    yaw: number;
    /** Наклон камеры, градусы. Плюс — смотрим сверху. */
    pitch: number;
    /** Угол обзора по вертикали, градусы. Меньше — плоский «телевик». */
    fov: number;
}
export declare const CAMERA_DEFAULTS: Readonly<CameraSettings>;
/** Допустимые пределы — их же используют ползунки песочницы. */
export declare const CAMERA_LIMITS: {
    readonly margin: readonly [0, 0.5];
    readonly zoom: readonly [0.3, 4];
    readonly offsetX: readonly [-1, 1];
    readonly offsetY: readonly [-1, 1];
    readonly yaw: readonly [-180, 180];
    readonly pitch: readonly [-60, 60];
    readonly fov: readonly [10, 60];
};
/**
 * Взять из чего угодно только годные настройки, зажав их в пределы.
 * Неизвестное и битое отбрасывается — остаются значения по умолчанию.
 */
export declare function parseCamera(raw: unknown): Partial<CameraSettings>;
/** Только то, что отличается от base, — для короткой записи в файл и код. */
export declare function cameraDiff(settings: CameraSettings, base?: Readonly<CameraSettings>): Partial<CameraSettings>;
