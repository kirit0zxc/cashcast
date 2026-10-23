# comparison-v1

Согласовано A-006 / B-012 (ACK на origin/agents/b-analytics a9eb0ad).
GET `/api/v1/forecasts/{scenario_id}/comparison` сравнивает успешный сценарий с
его успешной исходной базой. Доступ только члену компании; чужой ID — 404.
Базовый прогон без base_forecast_id — 409 not_a_scenario. Незавершённый расчёт —
409 forecast_not_ready. Несовпадение company/account/as_of/horizon/data_version/
model_version/seed или дат точек — 409 incompatible_forecasts.

Ответ: base_forecast_id, scenario_forecast_id, as_of, horizon_days, model_version,
points[{point_date,base_balance_p50_minor,scenario_balance_p50_minor,delta_balance_minor}],
risk{base:RiskOut,scenario:RiskOut}. delta = scenario − base, деньги в копейках.
Никакой записи в БД и пересчёта базы при сравнении нет.

API сценария проверяет обязательные поля и существование цели в сохранённом входе
до постановки job; неподдерживаемое изменение — 422 invalid_scenario. Вложенные
сценарии остаются запрещены. seed можно изменить, но такой результат не считается
парным сравнением и comparison вернёт 409. Минимальный UI предлагает дополнительный
расход; все четыре согласованных вида доступны в API.
