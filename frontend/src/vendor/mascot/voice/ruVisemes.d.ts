import type { SpeechAccent, VisemeStep } from './types';
export interface SpeechPlan {
    steps: VisemeStep[];
    accents: SpeechAccent[];
    totalMs: number;
}
/**
 * Превращает текст в раскладку рта и акцентов.
 *
 * Тайминг здесь оценочный: точных длительностей фонем браузер не даёт.
 * Зато каждый шаг помнит свой индекс в тексте, и когда синтезатор
 * сообщает границу слова, раскладка подтягивается к реальной речи —
 * так расхождение не накапливается до конца фразы.
 */
export declare function planSpeech(text: string, rate?: number): SpeechPlan;
