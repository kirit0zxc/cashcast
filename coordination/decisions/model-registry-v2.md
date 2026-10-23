# model-registry-v2

Предложено B-014 в49ddb50, принято A-009. DTO archive-v1 не меняется.

- get_forecast_service(model_version: str | None = None): без аргумента текущий
  продуктовый default, с точной строкой — эта версия либо ValueError с причиной
  unsupported_model_version. Никакого исполнения неизвестной версии как default.
- get_supported_model_versions() -> tuple[str, ...], явный статический реестр.
- Новые математика/параметры/quality policy получают новый ID. Старый ID не меняет
  семантику молча. Смена default только отдельным READY с метриками/критериями.
- B реализует фабрику в своей области; A после READY передаёт run.model_version
  в worker, сохраняет проверку result.model_version. Неподдерживаемый job/scenario
  завершается явной ошибкой. Не импортировать реестр динамически по строке клиента.

ACK контракта не означает, что эта фабрика уже реализована или интегрирована.
