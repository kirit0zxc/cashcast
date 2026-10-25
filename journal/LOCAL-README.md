# Как проверить резерв локально

Это добавочный локальный пакет к CashCast main `a92bd50`. Не заменяет модель сайта и не предназначен для автоматического деплоя. Commit/push не выполнялись.

Рабочий каталог:
`C:/Users/kirito/Documents/Codex/2026-10-03/new-chat/work/cashcast-model-fallback`.

Окружение: Python3.12.14, CatBoost1.2.8, NumPy2.5.4, уже установленное отдельное `../cashcast-eval-env`. Дополнительные зависимости в backend не добавлены.

В PowerShell из рабочего каталога:

```powershell
$mlPython = '../cashcast-eval-env/Scripts/python.exe'
$datasetZip = '../../outputs/cashcast-datasets-2026-10-24/01-organizers/cashflow_dataset_participants.zip'

# Чистые тесты, без БД.
& $mlPython -m unittest evaluation.fallback_model.test_model -v

# Проверка весов, причинности и совместимости DTO на настоящем синтетическом наборе.
& $mlPython -m evaluation.fallback_model.verify_artifacts --zip $datasetZip --artifacts data/raw/fallback-model-v1

# Полное повторение обучения. Новый output сохраняет исходный результат.
& $mlPython experiments/01_direct_cashflow.py --zip $datasetZip --output data/raw/fallback-model-repeat
& $mlPython -m evaluation.fallback_model.uncertainty --output data/raw/fallback-model-repeat
```

Полный прогон использует CPU, не требует сервера и не обращается к БД. Повторные результаты не считаются новой независимой проверкой. Не изменять разбиение и параметры после просмотра поздних метрик без отдельного нового протокола.

Артефакты в `data/raw/fallback-model-v1`:

- `results.json` — все модели, периоды, горизонты, MAE/MSE/RMSE, ошибки потоков и point-матрицы.
- `probabilities.json` — вероятности, порог, матрицы, Accuracy/Precision/Recall/F1/F2/ROC-AUC/AP/Brier, reliability.
- `selection-frozen.json` — выбор по validation до поздней проверки.
- `release.json` — запрет выпуска и причины.
- `direct_depth6.cbm` — выбранные локальные веса; depth4 — проверенный альтернативный кандидат.
- `residual-paths.npz` —200траекторий ошибок прошлых прогнозов, не калиброванная гарантия.
- `verification.json` — результат проверки реальных артефактов.

Для разработчика, при уже подготовленном `ForecastInput`:

```python
import sys
from pathlib import Path
sys.path.insert(0, 'backend')  # Запуск из корня отдельной копии CashCast.
from evaluation.fallback_model.adapter import LocalFallbackService

# По умолчанию неподтверждённый кандидат блокируется и используется текущий движок.
service = LocalFallbackService(Path('data/raw/fallback-model-v1'))
result = service.run(snapshot)

# Только явное исследование: не подключать этим способом production worker.
research = LocalFallbackService(Path('data/raw/fallback-model-v1'), allow_unreleased=True)
candidate_result = research.run(snapshot)
```

В архив резерва включены только добавочные исходники, журнал, агрегированные отчёты и веса. Исходный датасет, снимки строк `.pickle`, секреты и виртуальное окружение не включаются. Скопировать добавочные файлы можно в отдельную копию указанного main; не накладывать вслепую на чужую рабочую ветку. Сырые финансовые данные не публиковать.
