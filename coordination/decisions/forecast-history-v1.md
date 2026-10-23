# forecast-history-v1 · предложение A017, ACK B ожидается

GET /api/v1/companies/{company_id}/forecasts — только чтение, cookie-session/member.
Query: account_id UUID обязателен, limit default20/max100, cursor optional opaque.
Чужаякомпания/счёт404, неверныйcursor422invalid_cursor. Порядокcreated_at DESC,id DESC;
курсор включает дату/UUID и contextcompany/account, сменаcontext422. Новые записи
не дублируют/не пропускают прежние страницы; offset не используется.

Ответ: {items:[{id,account_id,as_of,horizon_days,status,model_version,data_version,seed,
base_forecast_id,created_at,error_code,job_id}],next_cursor:str|None}.
base_forecast_id/error_code/job_id nullable; status pending/running/succeeded/failed.
job_id — существующийforecastjob этогоrun (legacy безjobnull); не создаётся приGET.
Ни rawinput, ни текстисключения не возвращается. GET /forecasts/{id} по-прежнему
отдаёт сохранённый результат, GET /jobs/{job} — ожиданиеработы. ИзмененийpureDTOнет.
