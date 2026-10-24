import * as THREE from 'three';
import { type VRM } from '@pixiv/three-vrm';
import type { ClipSpec } from '../../core/clips';
/** Забыть разобранный файл, чтобы перечитать его с диска (песочница). */
export declare function forgetClip(url: string): void;
/** Грузит .vrma и привязывает к скелету модели. */
export declare function loadClip(spec: ClipSpec, vrm: VRM): Promise<THREE.AnimationClip | null>;
