import { type CSSProperties } from 'react';
import type { MascotCore } from '../core/MascotCore';
import type { VrmRendererOptions } from '../renderers/vrm/VrmRenderer';
export interface MascotProps {
    /** По умолчанию берётся общий экземпляр, см. getMascot(). */
    core?: MascotCore;
    renderer?: VrmRendererOptions;
    className?: string;
    style?: CSSProperties;
}
export declare function Mascot({ core, renderer, className, style }: MascotProps): import("react").JSX.Element;
