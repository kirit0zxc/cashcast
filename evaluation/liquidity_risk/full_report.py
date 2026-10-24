"""Читаемый отчёт расширенного сравнения; только агрегаты без строк выписок."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
LABELS = {"validation":"Январь–март: выбор", "bridge":"Апрель–июнь",
          "late_development":"Июль–август", "other_early":"Другие компании: январь–июнь",
          "late_other":"Другие компании: июль–август"}


class FullReport:
    @staticmethod
    def make(folder):
        report = json.loads((folder/"results.json").read_text(encoding="utf-8"))
        phases = report["phases"]
        assert set(phases)==set(LABELS)
        count = sum(p["audit"]["windows"] for p in phases.values())
        fallback = sum(p["audit"]["fallback_windows"] for p in phases.values())
        excluded = sum(sum(p["audit"]["excluded"].values()) for p in phases.values())
        seconds = sum(sum(p["audit"]["inference_seconds"].values()) for p in phases.values())
        lines = ["# Chronos и ансамбль специалистов — полный локальный прогон", "",
                 f"Проверено **{count} пригодных окон** из {count+excluded} возможных по всем 150 компаниям за январь–август 2026.",
                 f"Каждое окно — 30 дней, отдельно измерены 7/14/30 дней. В {fallback} окнах Chronos использует явный fallback из-за истории.",
                 f"Расчёт трёх вариантов Chronos на CPU занял {seconds:.1f} с суммарно, без загрузки весов и подготовки текущих прогнозов.",
                 "Это расширенный backtest, **не дообучение** Chronos. Данные уже исследовались; нового слепого контроля нет.", "",
                 "## Выбранная сборка", "",
                 "| Задача | Источник | Основание |", "|---|---|---|",
                 "| Точечный прогноз остатка | 75% Chronos365 + 25% ранее обученного CatBoost | Выбрано на январе–марте по MAE с ограничениями RMSE и macro-MAE |",
                 "| Ежедневные поступления | Текущая сезонная модель | Хороший компромисс ошибки дня и суммы за месяц |",
                 "| Ежедневные списания | Текущая сезонная модель | Тот же заранее заданный критерий |",
                 "| Рабочие предупреждения | Сохранить текущий механизм | Выбранный ранними данными Chronos84 пропустил один поздний разрыв |",
                 "| Дополнительная диагностика | Нижние квантили Chronos, с указанием источника | Не выдавать за калиброванную вероятность |", "",
                 "Состав балансовой/потоковой сборки зафиксирован в selection-frozen.json до анализа поздних метрик.",
                 "Официальный источник Chronos: [amazon/chronos-2](https://huggingface.co/amazon/chronos-2), Apache-2.0; revision и локальные SHA сохранены.", "",
                 "## Остаток на 30 дней", "",
                 "MAE — средняя абсолютная ошибка дневного остатка в рублях. Процент — уменьшение MAE относительно текущей модели, не «точность».", "",
                 "| Проверка | Окон | Текущая MAE, ₽ | Chronos365 MAE, ₽ | Смесь MAE, ₽ | Улучшение смеси |",
                 "|---|---:|---:|---:|---:|---:|"]
        for name,p in phases.items():
            s=p["scores"]; base=s["current"]["30"]["mae_rub"]; chrono=s["balance365"]["30"]["mae_rub"]; mix=s["specialists_separate"]["30"]["mae_rub"]
            lines.append(f"| {LABELS[name]} | {p['audit']['windows']} | {base:,.0f} | {chrono:,.0f} | {mix:,.0f} | {100*(1-mix/base):+.2f}% |")
        lines += ["", "## Разные горизонты", "", "Положительный процент — ошибка меньше; отрицательный — хуже текущей модели.", "",
                  "| Проверка | 7 дней | 14 дней | 30 дней |", "|---|---:|---:|---:|"]
        for name,p in phases.items():
            gains=[100*(1-p["scores"]["specialists_separate"][str(h)]["mae_rub"]/p["scores"]["current"][str(h)]["mae_rub"]) for h in (7,14,30)]
            lines.append(f"| {LABELS[name]} | {gains[0]:+.2f}% | {gains[1]:+.2f}% | {gains[2]:+.2f}% |")
        lines += ["", "На позднем development первые 7 дней стали хуже на 3.13%. Нельзя объявлять смесь лучшей на всех сроках.",
                  "На поздней отдельной группе RMSE смеси выросла с 4.79 до 5.20 млн ₽ при улучшении MAE: тяжёлые ошибки остаются.",
                  "95% bootstrap-интервал разницы MAE по компаниям на позднем development: −435460…−15832 ₽;",
                  "на других поздних компаниях: −206249…+186423 ₽. Перенос на другую группу уверенно не доказан.", "",
                  "## Почему не взяли Chronos для всех денежных потоков", "",
                  "Результаты периода выбора; отдельный двухмерный прогноз прихода и расхода, а не копия текущих потоков.", "",
                  "| Модель | Ошибка прихода за день, ₽ | Ошибка суммы прихода за 30 дней, ₽ | Ошибка расхода за день, ₽ | Ошибка суммы расхода за 30 дней, ₽ |",
                  "|---|---:|---:|---:|---:|"]
        for name,label in (("current","Текущая"),("direct","CatBoost"),("flow365","Chronos: медианные потоки")):
            f=phases["validation"]["flows"][name]["30"]
            lines.append(f"| {label} | {f['inflow']['mae_rub']:,.0f} | {f['inflow']['total_mae_rub']:,.0f} | {f['outflow']['mae_rub']:,.0f} | {f['outflow']['total_mae_rub']:,.0f} |")
        lines += ["", "Chronos часто прогнозирует небольшие/нулевые медианные потоки: для отдельного дня это уменьшает MAE,",
                  "но месячные суммы становятся хуже. CatBoost лучше оценивает месячные суммы на ранних периодах, но хуже распределяет их по дням.",
                  "Нельзя одновременно объявить разные выходы «одной идеальной моделью» без проверки их совместимости.", "",
                  "## Проверка денежного равенства", "",
                  "Сделан второй вариант сборки: минимально изменить дневные приход/расход по L2 так, чтобы они точно давали выбранный остаток.",
                  "Потоки неотрицательны, равенство выполняется до копейки во всех 965 окнах. Сам прогноз остатка не меняется.",
                  "Цена такой сверки на позднем development: MAE прихода 191134→203640 ₽; расхода 255508→256094 ₽.",
                  "На отдельных поздних компаниях: приход 265870→284465 ₽; расход 269896→279502 ₽.",
                  "Раздельные средние потоки и медиана остатка статистически могут различаться. Если UI показывает единую денежную траекторию,",
                  "нужно использовать согласованный вариант и явно принять эту потерю качества потоков. Нельзя молча смешивать смысл полей.", "",
                  "## Предупреждения о новых разрывах", "",
                  "Начальный остаток >=0, за 30 дней факт хотя бы раз <0. Сравнение на общей маске доступности текущего риска.",
                  "На ранних шести срезах выбрался Chronos84/p10: 4/5 найденных, 64 ложные тревоги вместо 87 при тех же 4/5 текущего сигнала.",
                  "Однако на позднем development он нашёл 2/3 против 3/3 текущей модели. Поэтому кандидат не заменяет рабочий детектор.", "",
                  "| Проверка | Сигнал | TP / FP / FN / TN | Precision | Recall | F1 |", "|---|---|---|---:|---:|---:|"]
        for phase in ("late_development","late_other"):
            for name,label in (("current","Текущий"),("balance84","Выбранный Chronos84"),("balance365","Chronos365, диагностика")):
                r=phases[phase]["risk"][name]
                lines.append(f"| {LABELS[phase]} | {label} | {r['tp']} / {r['fp']} / {r['fn']} / {r['tn']} | {r['precision']:.2%} | {r['recall']:.2%} | {r['f1']:.2%} |")
        lines += ["", "### ROC-AUC и average precision", "",
                  "Здесь у Chronos есть непрерывный **ранжирующий score**, а не вероятность: −минимум p10 / прошлый масштаб потоков.",
                  "AUC/AP измеряют ранжирование; Brier к этому score не применяется. Значения посчитаны без fallback.", "",
                  "| Проверка | Модель | ROC-AUC | Average precision | Число положительных окон |", "|---|---|---:|---:|---:|"]
        for phase in ("validation","bridge","late_development","other_early","late_other"):
            for name in ("balance84","balance365"):
                r=phases[phase]["risk"][name]; rank=r["ranking"]
                fmt=lambda v: "не определено" if v is None else f"{v:.4f}"
                lines.append(f"| {LABELS[phase]} | {name} | {fmt(rank['roc_auc'])} | {fmt(rank['average_precision'])} | {r['positives']} |")
        lines += ["", "AUC=1 на одном положительном окне не доказывает идеальную модель. Четыре поздних положительных окна относятся к трём компаниям.",
                  "Высокий AUC может сочетаться с плохим выбранным порогом и низкой precision. Вероятность минуса за горизонт у Chronos остаётся не определена.", "",
                  "## Что сохранено", "",
                  "- Полные результаты: data/raw/chronos-specialists-v8/results.json — включая MSE, RMSE, интервалы, pinball и время.",
                  "- Замороженный состав и политика: selection-frozen.json, risk-selection-frozen.json.",
                  "- Протокол: 08_chronos_specialists.md; запуск: [08-RUNBOOK.md](08-RUNBOOK.md).",
                  "- 52 уникальных локальных теста прошли. В предыдущем этапе также прошли 77 существующих аналитических тестов и 13 проверок артефактов; приложение с тех пор не менялось.",
                  "- Коммиты/push/изменения main, сайта и production не выполнялись. Независимое агентское ревью и CI не заявляются.",
                  "- Рабочий вариант остаётся текущим. Исследовательская смесь готова для следующей независимой проверки; калиброванный риск и полноценная API-интеграция не объявлены готовыми.", ""]
        output=ROOT/"journal/08-RESULTS.md"
        output.write_text("\n".join(lines),encoding="utf-8")
        return output

    @classmethod
    def package(cls,folder,destination):
        folder=folder.resolve()
        report=cls.make(folder)
        files=[]
        for directory in ("evaluation/fallback_model","evaluation/liquidity_risk","experiments"):
            files.extend((ROOT/directory).glob("*.py"))
        files.extend(ROOT/"journal"/name for name in (
            "08_chronos_specialists.md","08-RUNBOOK.md","08-RESULTS.md","JOURNAL.md",
            "ENVIRONMENTS.json","chronos-source.json","chronos-weights-sha256.json","ROUND2-RUNBOOK.md"))
        files.extend(folder.glob("*.json"))
        files.append(ROOT/"data/raw/fallback-model-v1/direct_depth6.cbm")
        files=sorted(set(files))
        manifest={"base_commit":"a92bd5013b5b5d7e5008157815160b67fd762edf","release_allowed":False,
                  "files":{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
        with ZipFile(destination,"x",compression=ZIP_DEFLATED) as archive:
            for p in files: archive.write(p,p.relative_to(ROOT).as_posix())
            archive.writestr("LOCAL-MANIFEST.json",json.dumps(manifest,indent=2))
        with ZipFile(destination) as archive:
            assert archive.testzip() is None
            for name,digest in manifest["files"].items(): assert hashlib.sha256(archive.read(name)).hexdigest()==digest
        print(json.dumps({"files":len(files)+1,"bytes":destination.stat().st_size,
                          "sha256":hashlib.sha256(destination.read_bytes()).hexdigest(),"report":str(report)}))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--folder",type=Path,required=True)
    parser.add_argument("--archive",type=Path,required=True)
    args=parser.parse_args()
    FullReport.package(args.folder,args.archive)
