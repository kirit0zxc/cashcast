const currency = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB" });

// Деление Number на100 теряет копейку у больших сумм; обе части считаем целыми.
export function money(minor: number | null): string {
  if (minor === null) return "нет данных";
  if (!Number.isSafeInteger(minor)) return "нет точного значения";
  const value = BigInt(minor);
  const whole = value / 100n;
  const fraction = (value < 0n ? -value : value) % 100n;
  // -0 нужен локализатору для отрицательного остатка меньше одного рубля.
  const signedWhole = whole === 0n && minor < 0 ? -0 : whole;
  return currency.formatToParts(signedWhole).map(part =>
    part.type === "fraction" ? fraction.toString().padStart(2, "0") : part.value,
  ).join("");
}

// Десятичная строка превращается в копейки до отправки; лишние знаки не округляем.
export function rublesToMinor(value: string): number {
  if (!/^\d+([.,]\d{1,2})?$/.test(value)) throw new Error("Введите сумму с точностью до копеек");
  const [whole, fraction = ""] = value.replace(",", ".").split(".");
  const minor = Number(whole) * 100 + Number((fraction + "00").slice(0, 2));
  if (!Number.isSafeInteger(minor) || minor <= 0 || minor > 9_000_000_000_000_000) {
    throw new Error("Сумма вне допустимого диапазона");
  }
  return minor;
}

// Копейки → строка для поля ввода («1234,56»), без форматирования разрядов.
export function minorToInput(minor: number): string {
  const value = BigInt(minor);
  return `${value / 100n},${(value % 100n).toString().padStart(2, "0")}`;
}
