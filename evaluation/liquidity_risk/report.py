"""Сводка завершённых опытов и архив локального резерва без исходных выписок."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
BASE = "a92bd5013b5b5d7e5008157815160b67fd762edf"
FOLDERS = ("fallback-model-v1", "liquidity-risk-v2", "recall-policy-v3", "net-quantiles-v4",
           "chronos-v5", "risk-scale-v6", "chronos-alert-v7")


class ResearchReport:
    @staticmethod
    def read(folder):
        return json.loads((ROOT / "data/raw" / folder / "results.json").read_text(encoding="utf-8"))

    @classmethod
    def make(cls):
        points = []
        phases = ("validation", "retrospective_development", "retrospective_other_companies")
        for folder, candidate in (("fallback-model-v1", "direct_depth6"),
                                  ("net-quantiles-v4", "net6_uniform"), ("chronos-v5", "chronos")):
            report = cls.read(folder)
            for phase in phases:
                scores = report[phase].get("scores", report[phase])
                current, challenger = scores["current"]["30"], scores[candidate]["30"]
                points.append({"model": candidate, "phase": phase, "windows": challenger["windows"],
                               "mae_rub": challenger["mae_rub"], "mse_rub2": challenger["mse_rub2"],
                               "rmse_rub": challenger["rmse_rub"], "current_mae_rub": current["mae_rub"],
                               "improvement_pct": 100 * (1 - challenger["mae_rub"] / current["mae_rub"])})
        warnings = cls.read("chronos-alert-v7")
        counts = {name: {key: sum(warnings[phase][name][key] for phase in phases[1:])
                         for key in ("tp", "fp", "fn", "tn", "n")}
                  for name in ("candidate", "current")}
        for item in counts.values():
            tp, fp, fn, tn = (item[k] for k in ("tp", "fp", "fn", "tn"))
            item.update(accuracy=(tp+tn)/item["n"], precision=tp/(tp+fp), recall=tp/(tp+fn),
                        f1=2*tp/(2*tp+fp+fn))
        result = {"base_commit": BASE, "production_activated": False, "release_allowed": False,
                  "independent_control_received": False, "points": points,
                  "late_warning_common_windows": counts, "positive_windows": 4, "positive_companies": 3,
                  "early_warning_gate_passed": warnings["selection"]["feasible"],
                  "tests": {"research_unique": 39, "existing_analytics": 77, "artifact_checks": 13},
                  "notes": ["Поздние периоды уже изучались; это ретроспектива, не слепой контроль.",
                            "Наборы пригодных окон различаются между экспериментами; сравнения внутри одного опыта парные.",
                            "Chronos/net-quantile исследуют остатки; скопированные диагностические потоки не являются их прогнозом.",
                            "4 положительных окна относятся к 3 компаниям, а не 4 независимым компаниям."]}
        (ROOT / "journal/ROUND2-SUMMARY.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        table = []
        names = {"validation": "Выбор модели", "retrospective_development": "Поздние даты",
                 "retrospective_other_companies": "Другие компании"}
        for row in points:
            table.append(f"| {row['model']} | {names[row['phase']]} ({row['windows']}) | {row['mae_rub']:,.0f} | {row['rmse_rub']:,.0f} | {row['improvement_pct']:+.2f}% |")
        text = """# CashCast — итоги семи локальных экспериментов

Лучший ориентир по средней ошибке остатка — **Chronos-2**. На периодах выбора
MAE меньше текущей модели на 21.0%, на поздних периодах — на 11.85%, на отдельной
группе компаний — на 0.93%. Это не «точность 99%»: MAE измеряет ошибку в рублях.
На других компаниях RMSE выросла с 4.79 до 5.25 млн рублей: крупные промахи стали тяжелее.

Рабочая модель сайта не заменена. Все исследования локальны; commits/push/PR/deploy
не выполнялись. Сравнение готово к запуску по инструкции [ROUND2-RUNBOOK.md](ROUND2-RUNBOOK.md).

## Прогноз остатка

Горизонт 30 дней, MAE/RMSE по дневным остаткам. Положительный процент означает
уменьшение MAE относительно текущего `seasonal-estimated-2.1-w84` на тех же окнах.

| Модель | Проверка (число окон) | MAE, ₽ | RMSE, ₽ | Улучшение MAE |
|---|---|---:|---:|---:|
""" + "\n".join(table) + """

Chronos — [внешняя предобученная модель Amazon](https://huggingface.co/amazon/chronos-2),
120M параметров, Apache-2.0, закреплённый revision в chronos-source.json. Мы не обучали
её с нуля: использовали локальный zero-shot inference. CatBoost-кандидаты обучали сами
на прошлых данных организаторского набора, с целями до 2025-12-31.

Контекст Chronos: до 365 дней согласованной истории после последней несверки.
Данные позже даты прогноза исключаются; cross_learning=False. Ни одна выписка не
отправлялась во внешний модельный API. Дневной интервал p10–p90 накрыл факт в 76.0%
дней validation, 77.3% позднего development, 79.4% других компаний; номинал — 80%.
Покрытие считается по окнам с настоящим Chronos, без fallback.

Доверительные интервалы разницы MAE, bootstrap по компаниям:
- Поздние даты: −406456…+4395 ₽.
- Другие компании: −209524…+235955 ₽.
Оба включают ноль: статистически уверенного превосходства пока не доказали.

## Новые кассовые разрывы

Определение: начальный остаток неотрицателен, за следующие 30 дней хотя бы один
подтверждённый дневной остаток отрицателен. Это отдельная задача от прогноза p50.
Проверка медианы Chronos на пересечение нуля пропустила все 4 поздних новых разрыва.

Предупреждение по p10 нашло все 4 поздних положительных окна из 232 доступных,
относящиеся к 3 компаниям. Текущий сигнал bootstrap>=0.5 также нашёл все 4.

| Показатель на общей поздней выборке | Текущий сигнал | Предупреждение Chronos p10 |
|---|---:|---:|
| TP / FP / FN / TN | 4 / 45 / 0 / 183 | 4 / 29 / 0 / 199 |
| Accuracy | 80.60% | 87.50% |
| Precision | 8.16% | 12.12% |
| Recall | 100% (4/4) | 100% (4/4) |
| F1 | 15.09% | 21.62% |

**Это диагностический результат, не разрешение выпуска:** на ранних срезах p10
нашёл только 3/5 разрывов. Ни один квантиль из фиксированной сетки не прошёл условие
recall=100% при FPR<=25%; q=.1 был заранее обозначенной диагностикой при провале.
Высокая Accuracy при редких разрывах не означает хороший детектор.
ROC-AUC/вероятность горизонта для этого бинарного предупреждения не заявляются.
Дневные квантили не определяют вероятность хотя бы одного минуса за весь горизонт.

## Остальные проверенные подходы

1. Прямой CatBoost по накопленным поступлениям и списаниям: улучшает точку, но не риск.
2. Обучение требуемого резерва: 1916 ненулевых целей вместо 24 окон новых разрывов
   в обучении (эти 24 окна относятся лишь к 6 компаниям). Reserve4 улучшил отдельную
   группу, но пропустил 2/3 поздних development-разрыва. Выбранный на validation
   отдельный classifier пропустил все 4 поздних разрыва.
3. Среднее текущей оценки и reserve4: ранний recall 4/5; поздний development 1/3.
4. Медианный netflow CatBoost: слабее Chronos по MAE; полноценной вероятности не даёт.
5. Chronos-2: лучший точечный ориентир, ограничения выше.
6. Сдвиг logit текущей вероятности: Brier на позднем development 0.1281→0.0198,
   на других компаниях 0.1431→0.0234; постоянная частота лучше (0.0162/0.0197).
   Порог преобразован вместе со шкалой, поэтому тревоги и ROC-AUC не изменились.
   Калибровку не считаем подтверждённой. Нельзя заменить только общий риск и оставить
   противоречащие ему старые дневные вероятности.
7. Нижний квантиль Chronos: полезная дополнительная диагностика, ранний gate не пройден.

## Достоверность и воспроизводимость

Данные: синтетический организаторский ZIP, 222420 операций, 150 компаний,
2024-10-01—2026-09-30. SHA-256:
`e753802b7f7a2eecb7b5a558f9923b529e711c40fe431774750904b62ec79987`.
MoneyVis/Berka не подмешивались в новое обучение; розничные счета и иностранные
валюты не выдавались за данные российских МСП. Новых контрольных данных нет.

Параметры CatBoost выбирались на январе—марте 2026; риск-политики 03/06/07 используют
ранние срезы январь—июнь. Поздняя проверка — июль/август. У групп разные критерии
пригодности истории, поэтому ранние 476 и 499 окон нельзя смешивать как одну выборку.
У позднего сравнения предупреждений маска едина: 182+50 окон. Периоды уже многократно
изучались: называем их ретроспективными, а не независимым контролем.

Проверено: 39 уникальных локальных unit-тестов, 77 существующих аналитических тестов,
13 проверок весов/воспроизводимости. Выполнен реальный офлайн-запуск Chronos через CLI.
Предыдущий аудит импорта проверил 150 выписок/222420 операций. Продуктовые tracked-файлы
не менялись. Независимое агентское ревью и зелёный CI для этого локального пакета
не заявляются; push не разрешён и не выполнялся.

В архиве — добавочные исходники, веса CatBoost, агрегированные отчёты, протоколы,
синтетический пример и манифест SHA-256. Нет исходных выписок, приватных строковых
прогнозов, pickle, виртуальных сред, секретов и больших внешних весов Chronos.

## Практическое решение

Сохранить текущий детектор и подготовить Chronos как отдельное локальное сравнение.
Не активировать автоматически ни новую политику тревог, ни «откалиброванную» цифру.
На новом контроле зафиксировать модели до просмотра будущих ответов и измерить
ошибки остатка, precision/recall/F1 разрывов и качество вероятностей отдельно.
Без будущих фактов для нового файла честные метрики качества рассчитать нельзя.
"""
        path = ROOT / "journal/ROUND2-RESULTS.md"
        path.write_text(text, encoding="utf-8")
        return path

    @classmethod
    def package(cls, destination):
        report = cls.make()
        files = []
        for folder in ("evaluation/fallback_model", "evaluation/liquidity_risk", "experiments", "journal"):
            files.extend(p for p in (ROOT / folder).rglob("*") if p.is_file()
                         and "__pycache__" not in p.parts and p.suffix in {".py", ".md", ".json"})
        for folder in FOLDERS:
            files.extend(p for p in (ROOT / "data/raw" / folder).iterdir() if p.is_file()
                         and p.suffix in {".json", ".cbm", ".npz"} and not p.name.endswith("-rows.json"))
        for name in ("synthetic-snapshot.json", "comparison.json"):
            files.append(ROOT / "data/raw/local-comparison-demo" / name)
        files = sorted(set(files))
        manifest = {"base_commit": BASE, "release_allowed": False, "files": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
        destination.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(destination, "x", compression=ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, path.relative_to(ROOT).as_posix())
            archive.writestr("LOCAL-MANIFEST.json", json.dumps(manifest, indent=2))
        with ZipFile(destination) as archive:
            assert archive.testzip() is None
            for name, digest in manifest["files"].items():
                assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        print(json.dumps({"files": len(files)+1, "bytes": destination.stat().st_size,
                          "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                          "report": str(report), "archive": str(destination)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    ResearchReport.package(parser.parse_args().archive)
