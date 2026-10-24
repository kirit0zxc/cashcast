"""Ограниченный HTTPS-клиент OpenRouter без логирования ключей, сообщений и ответов провайдера."""

import json
import urllib.error
import urllib.request

from app.core.config import Settings
from app.core.errors import AppError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # Не передаём Authorization другому адресу по перенаправлению.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OpenRouterClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def complete(self, messages: list[dict], tools: list[dict], timeout: float) -> dict:
        secret = self.settings.openrouter_api_key.get_secret_value()
        if not secret:
            raise AppError(503, "assistant_not_configured", "Ассистент ещё не подключён на сервере")
        payload = {
            "model": self.settings.assistant_model, "messages": messages, "tools": tools,
            "tool_choice": "auto" if tools else "none", "parallel_tool_calls": False, "max_tokens": 2500,
            "reasoning": {"effort": "low"},
            "provider": {"require_parameters": True, "data_collection": "deny",
                         "max_price": {"prompt": 0.5, "completion": 1.5}},
        }
        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions", data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json",
                     "X-Title": "CashCast"}, method="POST",
        )
        try:
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(request, timeout=min(timeout, 20)) as response:
                raw = response.read(512 * 1024 + 1)
            if len(raw) > 512 * 1024:
                raise ValueError
            result = json.loads(raw)
            message = result["choices"][0]["message"]
            if not isinstance(message, dict):
                raise ValueError
            return message
        except urllib.error.HTTPError as exc:
            code = "assistant_rate_limit" if exc.code == 429 else "assistant_provider_unavailable"
            raise AppError(503, code, "Провайдер ассистента недоступен. Попробуйте позже") from None
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            raise AppError(503, "assistant_provider_unavailable", "Не удалось получить ответ ассистента") from None
