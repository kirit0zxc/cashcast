import type { VisemeWeights } from './types';
/**
 * Липсинк по реальному звуку — для случая, когда голос приходит
 * с бэкенда отдельным аудио.
 *
 * Громкость даёт раскрытие рта, спектральный центроид — форму:
 * низкий центр тяжести спектра соответствует округлым «о/у»,
 * высокий — растянутым «и/е». Это приближение, но на глаз
 * работает заметно лучше, чем просто открывать рот по громкости.
 */
export declare class AudioLipSync {
    private analyser;
    private source;
    private freq;
    private time;
    attach(node: AudioNode, ctx: AudioContext): void;
    /** Отключиться от звука, иначе анализаторы копятся в графе контекста. */
    detach(): void;
    get active(): boolean;
    /** Текущие веса визем; пустой объект — тишина. */
    sample(): VisemeWeights;
}
