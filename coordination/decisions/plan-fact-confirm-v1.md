# plan-fact-confirm-v1 · предложение A017, ACK B ожидается

POST /api/v1/companies/{company_id}/plan-fact/confirm, cookie/member/CSRF.
Body: {account_id:UUID,planned_event_id:UUID,transaction_id:UUID,
matched_amount_minor:int1..9e15}. Только сегодняшнийUTCсрез; историческийas_of
вbodyнепринимается. Ответ200 — существующий PlanFactOut текущегоaccount/today.

Под accountFORUPDATE: оба объекта принадлежат компании/счёту, RUB, одинаковое
направление, известны/проведены ксегодня. Подтверждается только текущаяпара
proposal изтогоже matcher, сумма<=proposalamount и обоихдоступныхостатков.
Нельзя произвольно связать пару вне нынешних правил matcher. Несуществующие/чужие404,
устаревшийproposal409proposal_stale; остатки/конфликтсуммы409allocation_conflict.

Сохраняется confirmed/methodmanual; суммауменьшаетremaining иставитpaid/partially_paid.
confirmed-allocationbudget учитывает другие оплаты этойжеоперацией. Одинexisting
confirmedpair с тойжесуммой — идемпотентный200 безвторойзаписи; другаясумма409.
Подтверждение одной альтернативы делает другиепредложения устаревшими; двойной
allocation при двух параллельныхвызовах невозможен. Историюнепереписываем, rejected
пока не добавляем. Purematcher/общиеDTO не меняются. РеализацияHTTP/DB уAпослеACK.
