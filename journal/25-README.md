# Исследовательское дополнение риска25 к пакету18

Не production. На858зависимых ретроспективных окнах:TP10/FP67/FN1/TN780,
противTP10/FP71/FN1/TN776 у21. Нового независимого контроля нет;
95%paired company bootstrap измененияFP:[-15,+4.025], пересекает0.
Небольшой выигрыш не подтверждает устойчивое превосходство;18/21 сохранить.

Нужен исходный SHA-проверенный пакет `cashcast-local-candidate-v18` из release
`model-research-handoff-20261025`. Его код и веса это дополнение не изменяет.
Табличное и Chronos окружения — `research_handoff/requirements-*.txt` веткиB.
Веса25 и исполняемый код закреплены `manifest.json`. Нет выписок или обучающих признаков.

Из каталога дополнения, используя абсолютные пути:

```powershell
$env:HF_HUB_OFFLINE='1'
& <tabular-python> predict.py --snapshot <input.json> --manifest manifest.json --base-manifest <package18/manifest.json> --tabular-python <tabular-python> --chronos-python <chronos-python> --output <output.json>
```

Input: существующий ForecastInputCodec JSON,30дней без явных планов/сценария/recurrences.
Формат и synthetic-пример — в пакете18. Недоступный baseline или отсутствие
причинного checkpoint возвращают явный `risk_extension.status=unavailable`.
Модель выбирается только с training_cutoff<=as_of; задержка указана staleness_days.
Обновление после августа2026 автоматически не выполняется.

Риск:18 OR crossfit_score>=.025; `probability_any_negative=null`, raw score не является
калиброванной вероятностью. Точка, потоки и согласованный сценарий остаются от18.
Разделение: sha256(account_id)[0]%5==0 даёт среднее5моделей; иначе используется модель,
исключившая группу sha256(account_id)[1]%5. Те же правила использованы в оценке.

Исходный split/model selection зафиксированы до поздней проверки. Строки обучения
имеют as_of+37<=training_cutoff, heldout-компании всегда исключены. Равный суммарный
вес компаний уменьшает повторный учёт окон, но не создаёт независимые наблюдения.
Полные результаты, протокол и аудит обучения находятся в reports/.
