import * as THREE from 'three';
/**
 * Вырезать из клипа отрезок [start, end] секунд и сдвинуть его к нулю.
 *
 * Ключевые кадры редко попадают ровно на границы, поэтому значения на
 * границах вычисляются интерполяцией той же дорожки (для поворотов —
 * сферической). Иначе в первом кадре поза дёрнулась бы к ближайшему
 * ключу.
 */
export declare function trimClip(clip: THREE.AnimationClip, start: number, end: number): THREE.AnimationClip;
