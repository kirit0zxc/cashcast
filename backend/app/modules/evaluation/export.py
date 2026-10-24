"""Автономный HTML для чек-поинта: только экранированные агрегаты и SVG."""

from html import escape


class EvaluationExport:
    @staticmethod
    def number(value):
        return "—" if value is None else f"{value:.6g}"

    @classmethod
    def chart(cls, points):
        if not points:
            return "<p>Нет рассчитанных точек.</p>"
        values = [
            p[key]
            for p in points
            for key in ("balance_p10_minor", "balance_p90_minor", "actual_balance_minor")
            if p[key] is not None
        ]
        low, high = min([0, *values]), max([0, *values])
        span = max(high - low, 1)

        def x(index):
            return 75 + index * 760 / max(1, len(points) - 1)

        def y(value):
            return 230 - (value - low) * 205 / span

        paths = []
        for key, color, dash in (
            ("balance_p10_minor", "#a3b9cf", "5 4"),
            ("balance_p90_minor", "#a3b9cf", "5 4"),
            ("balance_p50_minor", "#1762bd", "none"),
            ("actual_balance_minor", "#bb4a24", "none"),
        ):
            segments, current = [], []
            for index, point in enumerate(points):
                if point[key] is None:
                    if current:
                        segments.append(current)
                    current = []
                else:
                    current.append(f"{x(index):.2f},{y(point[key]):.2f}")
                    paths.append(f'<circle cx="{x(index):.2f}" cy="{y(point[key]):.2f}" r="2" fill="{color}"/>')
            if current:
                segments.append(current)
            paths.extend(
                f'<polyline points="{" ".join(segment)}" fill="none" stroke="{color}" '
                f'stroke-width="2" stroke-dasharray="{dash}"/>'
                for segment in segments
            )
        return (
            f'<svg viewBox="0 0 900 280" role="img" aria-label="Прогноз и факт остатка в рублях">'
            f'<line x1="75" x2="835" y1="{y(0):.2f}" y2="{y(0):.2f}" stroke="#aaa"/>'
            f'<text x="0" y="25">{cls.number(high / 100)} ₽</text>'
            f'<text x="0" y="230">{cls.number(low / 100)} ₽</text>'
            + "".join(paths)
            + f'<text x="75" y="260">{escape(points[0]["date"])}</text>'
            f'<text x="755" y="260">{escape(points[-1]["date"])}</text></svg>'
            "<p>Синий — прогноз p50; оранжевый — факт; пунктир — p10/p90. Пропуски факта не соединяются.</p>"
        )

    @classmethod
    def html(cls, report):
        parts = [
            '<!doctype html><html lang="ru"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>CashCast · Проверка качества</title><style>"
            "body{font:16px/1.6 system-ui;margin:40px auto;max-width:1100px;"
            "padding:0 24px;color:#152c30;background:#fafaf6}"
            "section{background:white;border:1px solid #d8dfd8;padding:24px;margin:24px 0;border-radius:12px}"
            "table{border-collapse:collapse;width:100%;font-size:14px}"
            "th,td{border-bottom:1px solid #ddd;padding:8px;text-align:left}"
            "code{overflow-wrap:anywhere}svg{width:100%;height:auto}small{color:#58666a}.scroll{overflow:auto}"
            "@media print{section{break-inside:avoid}body{margin:0}}</style><body><h1>CashCast · Проверка качества</h1>"
        ]
        parts.append(
            f"<p>Модель: <b>{escape(report['model_version'])}</b>. Валюта RUB. "
            "MAE/RMSE — рубли, MSE — рубли². Вероятности не откалиброваны.</p>"
            f"<p>Нормализованный набор SHA-256: <code>{escape(report['dataset_sha256'])}</code></p>"
        )
        if report.get("source_sha256"):
            parts.append(
                f"<p>SHA-256 исходного файла (передан импортёром): <code>{escape(report['source_sha256'])}</code></p>"
            )
        parts.append("<section><h2>Настройки и границы проверки</h2><ul>")
        parts.extend(f"<li>{escape(key)}: {escape(str(value))}</li>" for key, value in report["config"].items())
        parts.append(
            "</ul><p>Только история операций; планы исключены. "
            "Все результаты относятся к этому счёту и этим окнам.</p></section>"
        )
        parts.append(
            "<section><h2>Ошибка денежных величин</h2><table><tr><th>Величина</th><th>Дней</th>"
            "<th>MAE ₽</th><th>MSE ₽²</th><th>RMSE ₽</th></tr>"
        )
        for key, title in (("balance", "Остаток"), ("inflow", "Поступления"), ("outflow", "Списания")):
            row = report["regression"][key]
            parts.append(
                f"<tr><td>{title}</td><td>{row['n']}</td>"
                + "".join(
                    f'<td title="{escape(row[name]["unavailable_reason"] or "")}">{cls.number(row[name]["value"])}</td>'
                    for name in ("mae", "mse", "rmse")
                )
                + "</tr>"
            )
        parts.append(
            "</table><p>Эмпирическое покрытие p10–p90: "
            f"{cls.number(report['interval_coverage']['value'])} (доля).</p></section>"
        )
        for key, title in (
            ("daily_median_negative", "Ежедневный минус по медиане"),
            ("daily_probability_negative", "Ежедневный минус по вероятности"),
            ("horizon_new_gap", "Новый минус за весь горизонт"),
        ):
            group = report[key]
            c = group["confusion_matrix"]
            parts.append(
                f"<section><h2>{title}</h2><p>Случаев: {group['n']}; порог: {group['threshold']}.</p>"
                "<table><tr><th>Факт / прогноз</th><th>Минус</th><th>Нет минуса</th></tr>"
                f"<tr><th>Минус</th><td>TP {c['tp']}</td><td>FN {c['fn']}</td></tr>"
                f"<tr><th>Нет минуса</th><td>FP {c['fp']}</td><td>TN {c['tn']}</td></tr></table><ul>"
            )
            parts.extend(
                f"<li>{escape(name)}: {cls.number(metric['value'])} "
                f"<small>{escape(metric['unavailable_reason'] or '')}</small></li>"
                for name, metric in group["metrics"].items()
            )
            parts.append("</ul></section>")
        for window in report["windows"]:
            parts.append(f"<section><h2>Окно {window['index']}: срез {escape(window['as_of'])}</h2>")
            if window["status"] == "skipped":
                parts.append(f"<p>Пропущено: {escape(window['reason'])}</p></section>")
                continue
            parts.append(cls.chart(window["points"]))
            parts.append(
                f"<p>Вероятность минуса за горизонт: {cls.number(window['probability_any_negative'])} (доля).</p>"
            )
            parts.append("<ul>" + "".join(f"<li>{escape(w)}</li>" for w in window["warnings"]) + "</ul>")
            parts.append(
                '<div class="scroll"><table><tr><th>Дата</th><th>Прогноз ₽</th><th>Факт ₽</th>'
                '<th>Источник факта</th><th>P(минус)</th></tr>'
            )
            for point in window["points"]:
                actual = point["actual_balance_minor"]
                parts.append(
                    f"<tr><td>{escape(point['date'])}</td><td>{cls.number(point['balance_p50_minor'] / 100)}</td>"
                    f"<td>{cls.number(actual / 100 if actual is not None else None)}</td>"
                    f"<td>{escape(point['balance_source'])}</td><td>{cls.number(point['probability_negative'])}</td></tr>"
                )
            parts.append("</table></div></section>")
        parts.append(
            "<section><h2>Пошаговый журнал</h2><ol>"
            + "".join(f"<li><b>{escape(item['step'])}</b>: {escape(item['message'])}</li>" for item in report["trace"])
            + "</ol></section>"
        )
        parts.append(
            "<section><h2>Ограничения</h2><ul>"
            + "".join(f"<li>{escape(item)}</li>" for item in report["limitations"])
            + "</ul></section></body></html>"
        )
        return "".join(parts)
