import assert from "node:assert/strict";
import { test } from "node:test";
import { minorToInput, money, rublesToMinor } from "../src/shared/money.ts";

// Node24 читает этот чистый TS-модуль без нового test framework и транспилятора.
test("допустимые большие суммы сохраняют каждую копейку и знак", () => {
  assert.equal(money(8_999_999_999_999_999), "89 999 999 999 999,99 ₽");
  assert.equal(money(-8_999_999_999_999_999), "-89 999 999 999 999,99 ₽");
  assert.equal(money(9_000_000_000_000_000), "90 000 000 000 000,00 ₽");
});

test("нулевой остаток отличается от неизвестного, копейки сохраняют минус", () => {
  assert.equal(money(0), "0,00 ₽");
  assert.equal(money(null), "нет данных");
  assert.equal(money(1), "0,01 ₽");
  assert.equal(money(-1), "-0,01 ₽");
  assert.equal(money(-100), "-1,00 ₽");
});

test("непредставимое целое нельзя выдавать за точную сумму", () => {
  for (const value of [Number.MAX_SAFE_INTEGER + 1, 0.5, NaN, Infinity]) {
    assert.equal(money(value), "нет точного значения");
  }
});

test("ввод рублевой границы точен, лишние знаки и превышение отвергаются", () => {
  assert.equal(rublesToMinor("89999999999999,99"), 8_999_999_999_999_999);
  assert.equal(rublesToMinor("90000000000000.00"), 9_000_000_000_000_000);
  assert.equal(rublesToMinor("0,01"), 1);
  for (const value of ["90000000000000.01", "1.234", "1e9", "0", "-1", "Infinity"]) {
    assert.throws(() => rublesToMinor(value));
  }
});

test("сумма плана возвращается в поле ввода без потери копеек", () => {
  assert.equal(minorToInput(123456), "1234,56");
  assert.equal(minorToInput(5), "0,05");
  assert.equal(rublesToMinor(minorToInput(900000000000001)), 900000000000001);
});
