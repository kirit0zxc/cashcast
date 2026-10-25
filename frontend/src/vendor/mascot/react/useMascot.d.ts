import type { MascotCore } from '../core/MascotCore';
import type { MascotState } from '../core/types';
/**
 * Управление маскотом из компонента + текущее состояние для UI.
 * По умолчанию — общий экземпляр, см. getMascot().
 */
export declare function useMascot(coreOverride?: MascotCore): {
    core: MascotCore;
    set: (s: MascotState) => void;
    say: (text: string) => void;
    hush: () => void;
    setMuted: (m: boolean) => void;
    setVoiceOptions: (o: {
        voiceName?: string;
        rate?: number;
        pitch?: number;
    }) => void;
    lookAt: (x: number, y: number) => void;
    state: MascotState;
    ready: boolean;
    bubble: string | null;
    speaking: boolean;
    muted: boolean;
};
