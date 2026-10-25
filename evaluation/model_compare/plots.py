"""PNG-графики сравнения. Цвет закреплён за моделью, а не за её местом в рейтинге."""

from datetime import timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import FuncFormatter

SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
COLORS = {
    "Текущая 2.1-w84": "#2a78d6",
    "LightGBM v2": "#eb6834",
    "Ансамбль 2.1 + LightGBM v2": "#1baf7a",
    "Ансамбль persistence + LightGBM v2": "#e34948",
    "Persistence (остаток не меняется)": "#008300",
    "Baseline (повтор недели)": "#eda100",
    "Сезонный naive (месяц)": "#e87ba4",
    "Эталон 1.0-w84 (B4)": "#6250d6",
    "Новый разрыв: LightGBM": "#eb6834",
    "Новый разрыв: логистическая": "#1baf7a",
    "Новый разрыв: частота train": "#eda100",
    "LightGBM-классификатор": "#eb6834",
    "Логистическая регрессия": "#1baf7a",
    "LightGBM квантили минимума": "#e87ba4",
    "Константа (частота train)": "#eda100",
    "Persistence (знак остатка)": "#6250d6",
}
BLUES = LinearSegmentedColormap.from_list("blues", ["#f3f7fd", "#2a78d6", "#0d3d73"])
MILLIONS = FuncFormatter(lambda v, _: f"{v / 1e8:.1f}")  # копейки -> млн ₽

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10, "axes.titlesize": 11,
    "axes.titleweight": "bold", "legend.frameon": False, "lines.linewidth": 2,
})


def _save(fig, path, rect=None):
    fig.tight_layout(rect=rect)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path.name


def forecast_examples(examples, path, banded, flat):
    """Факт, медианы и интервалы p10–p90 моделей banded, плоские линии flat; holdout."""
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.2))
    for ax, item in zip(axes.ravel(), examples, strict=False):
        w = item["window"]
        past = [w.as_of - timedelta(days=59 - k) for k in range(60)]
        future = [w.as_of + timedelta(days=k + 1) for k in range(30)]
        ax.plot(past, w.bal[-60:], color=INK, linewidth=1.6, label="Факт до среза")
        ax.plot(future, w.truth[:, 2], color=INK, linewidth=2, linestyle=(0, (4, 2)), label="Факт после среза")
        for name in banded:
            p = item["predictions"][name]
            ax.fill_between(future, p["p10"], p["p90"], color=COLORS[name], alpha=0.14, linewidth=0)
            ax.plot(future, p["p50"], color=COLORS[name], label=f"{name}: p50 и p10–p90")
        for name in flat:
            ax.plot(future, item["predictions"][name]["p50"], color=COLORS[name], linestyle=(0, (2, 2)),
                    label=name)
        ax.axvline(w.as_of, color=INK_2, linewidth=1)
        ax.axhline(0, color=INK_2, linewidth=1, linestyle=":")
        ax.yaxis.set_major_formatter(MILLIONS)
        ax.set_ylabel("Остаток, млн ₽")
        ax.set_title(f"{w.company} · {item['reason']}")
        ax.tick_params(axis="x", labelrotation=25)
    handles, labels = axes.ravel()[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3)
    fig.suptitle("Прогноз остатка на 30 дней от среза 31.08.2026 (holdout)", fontweight="bold")
    return _save(fig, path, rect=(0, 0.07, 1, 1))


def mae_by_horizon(report, names, path):
    fig, ax = plt.subplots(figsize=(10, 5))
    days = np.arange(1, 31)
    ends = []
    for name in names:
        values = np.array(report[name]["balance_mae_by_day_rub"]) / 1e6
        ax.plot(days, values, color=COLORS[name], label=name)
        ends.append(values[-1])
    # Подписи концов линий разводятся по вертикали, чтобы близкие значения не слипались.
    gap = (max(ends) - min(ends) + 1e-9) * 0.04 + 0.05
    placed = []
    for value in sorted(ends):
        y = max(value, placed[-1] + gap) if placed else value
        placed.append(y)
        ax.annotate(f"{value:.2f}", (30, value), xytext=(31.2, y), textcoords="data",
                    va="center", fontsize=9, color=INK_2)
    ax.set_xlim(0, 33)
    ax.set_xlabel("День горизонта")
    ax.set_ylabel("MAE остатка, млн ₽")
    ax.set_title("Ошибка растёт к концу горизонта: MAE по дням, holdout сентябрь 2026")
    ax.legend(loc="upper left")
    return _save(fig, path)


def mae_by_cutoff(per_cutoff, names, path):
    cutoffs = list(per_cutoff)
    fig, ax = plt.subplots(figsize=(11, 5))
    width = 0.8 / len(names)
    for i, name in enumerate(names):
        values = [per_cutoff[c][name]["balance"]["mae"] / 1e6 for c in cutoffs]
        x = np.arange(len(cutoffs)) + (i - (len(names) - 1) / 2) * width
        ax.bar(x, values, width=width * 0.92, color=COLORS[name], label=name)
    ax.set_xticks(np.arange(len(cutoffs)), [c + (" (holdout)" if i == len(cutoffs) - 1 else "")
                                             for i, c in enumerate(cutoffs)])
    ax.set_ylabel("MAE дневного остатка, млн ₽")
    ax.set_ylim(0, ax.get_ylim()[1] * 1.25)  # место под легенду над столбцами
    ax.set_title("MAE по срезам: 4 validation + holdout")
    ax.legend(ncol=3, loc="upper left")
    return _save(fig, path)


def confusion_grid(matrices, title, path):
    """matrices: [(подпись, {'tp','fp','fn','tn'})]."""
    columns = min(3, len(matrices))
    rows = int(np.ceil(len(matrices) / columns))
    fig, axes = plt.subplots(rows, columns, figsize=(4.2 * columns, 3.9 * rows), squeeze=False)
    for ax in axes.ravel()[len(matrices):]:
        ax.axis("off")
    for ax, (label, m) in zip(axes.ravel(), matrices, strict=False):
        grid = np.array([[m["tn"], m["fp"]], [m["fn"], m["tp"]]])
        ax.imshow(grid, cmap=BLUES, vmin=0, vmax=max(grid.max(), 1))
        ax.grid(False)
        for (r, c), value in np.ndenumerate(grid):
            dark = value > grid.max() * 0.55
            ax.text(c, r, f"{value}", ha="center", va="center", fontsize=13, fontweight="bold",
                    color="#ffffff" if dark else INK)
        ax.set_xticks([0, 1], ["Нет минуса", "Минус"])
        ax.set_yticks([0, 1], ["Нет минуса", "Минус"])
        ax.set_xlabel("Прогноз")
        ax.set_ylabel("Факт")
        ax.set_title(label, fontsize=10)
    fig.suptitle(title, fontweight="bold")
    return _save(fig, path)


def roc_pr(curves, path, title="holdout"):
    fig, (left, right) = plt.subplots(1, 2, figsize=(12, 5))
    for name, data in curves.items():
        roc = np.array(data["roc"])
        pr = np.array(data["pr"])
        # Точки уже содержат углы ступенек; отрезок между равными оценками — прямая.
        left.plot(roc[:, 0], roc[:, 1], color=COLORS[name], label=name)
        right.plot(pr[:, 0], pr[:, 1], color=COLORS[name], label=name, drawstyle="steps-pre")
    left.plot([0, 1], [0, 1], color=INK_2, linewidth=1, linestyle=":")
    prevalence = next(iter(curves.values()))["prevalence"]
    # Частота события: precision случайного ранжирования и уровень PR в конце кривой.
    right.axhline(prevalence, color=INK_2, linewidth=1, linestyle=":")
    right.annotate(f"частота события {prevalence:.3f}", (1, prevalence), xytext=(-4, 4), textcoords="offset points",
                   ha="right", fontsize=8, color=INK_2)
    left.set(xlabel="Доля ложных тревог (FPR)", ylabel="Полнота (TPR)", title=f"ROC, {title}")
    right.set(xlabel="Полнота (recall)", ylabel="Точность (precision)", title=f"Precision–Recall, {title}",
              ylim=(0, 1.05))
    left.legend(loc="center right", fontsize=8)
    return _save(fig, path)


def calibration(curves_by_phase, path):
    fig, axes = plt.subplots(1, len(curves_by_phase), figsize=(6 * len(curves_by_phase), 5), squeeze=False)
    for ax, (phase, curves) in zip(axes.ravel(), curves_by_phase.items(), strict=True):
        ax.plot([0, 1], [0, 1], color=INK_2, linewidth=1, linestyle=":", label="Идеальная калибровка")
        for name, data in curves.items():
            points = np.array(data["calibration"])
            if len(points):
                # Площадь точки пропорциональна числу окон в корзине; корзины не соединяются линией.
                ax.scatter(points[:, 0], points[:, 1], s=12 + 4 * np.sqrt(points[:, 2]) ** 2 / 2,
                           color=COLORS[name], alpha=0.75, edgecolor=SURFACE, linewidth=1, label=name)
                for x, y, n in points:
                    ax.annotate(f"{int(n)}", (x, y), xytext=(4, 3), textcoords="offset points", fontsize=7,
                                color=INK_2)
        ax.set(xlabel="Средняя предсказанная вероятность", ylabel="Наблюдаемая частота минуса",
               title=f"Калибровка, {phase}", xlim=(0, 1), ylim=(0, 1))
    axes.ravel()[0].legend(fontsize=8, loc="upper left")
    return _save(fig, path)
