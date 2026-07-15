from __future__ import annotations

import re
from collections.abc import Iterable

from fastapi import Request

from backend.config import get_settings
from backend.domain.user_preferences import AppLanguage
from backend.infrastructure.settings.file_user_preferences_repository import (
    FileUserPreferencesRepository,
)
from backend.schemas import AuthenticatedUser
from backend.tools.auth_store import user_from_token


DEFAULT_LANGUAGE: AppLanguage = "en-US"
SUPPORTED_LANGUAGES: tuple[AppLanguage, ...] = (DEFAULT_LANGUAGE, "zh-CN")
QUALITY_VALUE_PATTERN = re.compile(r"(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)\Z")

PUBLIC_MESSAGES: dict[str, dict[AppLanguage, str]] = {
    "INVALID_UPLOAD_FILE": {
        "en-US": "Only CSV files are supported.",
        "zh-CN": "仅支持 CSV 文件。",
    },
    "UPLOAD_SAVED": {"en-US": "Upload saved.", "zh-CN": "上传已保存。"},
    "AUTH_INVALID_CREDENTIALS": {
        "en-US": "Invalid account or password.",
        "zh-CN": "账号或密码无效。",
    },
    "AUTH_REQUIRED": {
        "en-US": "Authentication is required.",
        "zh-CN": "需要登录后才能继续。",
    },
    "AUTH_TOKEN_INVALID": {
        "en-US": "The session is invalid or has expired.",
        "zh-CN": "登录状态无效或已过期。",
    },
    "AUTH_IDENTIFIER_EXISTS": {
        "en-US": "That account identifier is already registered.",
        "zh-CN": "该账号标识已被注册。",
    },
    "VALIDATION_ERROR": {
        "en-US": "Check the submitted fields and try again.",
        "zh-CN": "请检查提交的字段后重试。",
    },
    "AUTH_REGISTERED": {"en-US": "Registered.", "zh-CN": "注册成功。"},
    "AUTH_LOGGED_IN": {"en-US": "Logged in.", "zh-CN": "登录成功。"},
    "PREFERENCES_SAVED": {"en-US": "Preferences saved.", "zh-CN": "偏好设置已保存。"},
    "MODEL_SETTINGS_SAVED": {"en-US": "Model settings saved.", "zh-CN": "模型设置已保存。"},
    "API_KEY_CLEARED": {"en-US": "API key cleared.", "zh-CN": "API 密钥已清除。"},
    "MODEL_CONNECTION_VERIFIED": {"en-US": "Model connection verified.", "zh-CN": "模型连接验证成功。"},
    "PROFILE_SAVED": {"en-US": "Profile saved.", "zh-CN": "个人资料已保存。"},
    "MEAL_SAVED": {"en-US": "Meal saved.", "zh-CN": "餐食已保存。"},
    "WORKOUT_SAVED": {"en-US": "Workout saved.", "zh-CN": "训练已保存。"},
    "ENTRY_PARSED": {"en-US": "Entry parsed.", "zh-CN": "记录已解析。"},
    "AI_NOT_CONFIGURED": {
        "en-US": "Configure and enable a model connection before using Agent features.",
        "zh-CN": "请先配置并启用模型连接，再使用 Agent 功能。",
    },
    "AI_DISABLED": {
        "en-US": "Enable the saved model connection before using Agent features.",
        "zh-CN": "请先启用已保存的模型连接，再使用 Agent 功能。",
    },
    "CREDENTIAL_STORE_UNAVAILABLE": {
        "en-US": "Secure credential storage is unavailable. Configure SETTINGS_ENCRYPTION_KEY.",
        "zh-CN": "安全凭据存储不可用，请配置 SETTINGS_ENCRYPTION_KEY。",
    },
    "INVALID_MODEL_ENDPOINT": {
        "en-US": "The custom model endpoint is not allowed by the server security policy.",
        "zh-CN": "服务器安全策略不允许使用该自定义模型端点。",
    },
    "MODEL_TIMEOUT": {
        "en-US": "The model did not respond before the request timed out.",
        "zh-CN": "模型未能在请求超时前响应。",
    },
    "MODEL_AUTH_FAILED": {
        "en-US": "The model provider rejected the configured credentials.",
        "zh-CN": "模型提供商拒绝了已配置的凭据。",
    },
    "MODEL_NOT_FOUND": {
        "en-US": "The configured model could not be found.",
        "zh-CN": "找不到已配置的模型。",
    },
    "MODEL_RATE_LIMITED": {
        "en-US": "The model provider rate limit was reached.",
        "zh-CN": "已达到模型提供商的速率限制。",
    },
    "MODEL_PROTOCOL_ERROR": {
        "en-US": "The model provider returned an invalid or unsupported response.",
        "zh-CN": "模型提供商返回了无效或不受支持的响应。",
    },
}


def translate_public_message(key: str, language: AppLanguage, fallback: str = "") -> str:
    messages = PUBLIC_MESSAGES.get(key)
    if messages is None:
        return fallback
    return messages.get(language, messages[DEFAULT_LANGUAGE])


def language_from_accept_language(value: str | None) -> AppLanguage:
    preferences: list[tuple[str, float, int]] = []
    for index, item in enumerate((value or "").split(",")):
        tag, *parameters = (part.strip() for part in item.split(";"))
        quality = _quality(parameters)
        if quality is None:
            continue
        preferences.append((tag, quality, index))

    ranked: list[tuple[float, int, int, AppLanguage]] = []
    for language_index, language in enumerate(SUPPORTED_LANGUAGES):
        matches = [
            (specificity, quality, -index)
            for tag, quality, index in preferences
            if (specificity := _match_specificity(tag, language)) is not None
        ]
        if not matches:
            continue
        _, quality, negative_index = max(matches)
        if quality > 0:
            ranked.append((quality, negative_index, -language_index, language))

    return max(ranked)[3] if ranked else DEFAULT_LANGUAGE


def language_for_request(
    request: Request,
    user: AuthenticatedUser | None = None,
) -> AppLanguage:
    authenticated = user or _user_from_request(request)
    if authenticated is not None:
        repository = FileUserPreferencesRepository(get_settings().data_dir)
        preferences = repository.get(authenticated.user_id)
        return preferences.language if preferences is not None else DEFAULT_LANGUAGE
    return language_from_accept_language(request.headers.get("accept-language"))


def message_for_request(
    key: str,
    request: Request,
    user: AuthenticatedUser | None = None,
    fallback: str = "",
) -> str:
    return translate_public_message(key, language_for_request(request, user), fallback)


def _quality(parameters: Iterable[str]) -> float | None:
    for parameter in parameters:
        name, _, raw_value = parameter.partition("=")
        if name.lower() == "q":
            if QUALITY_VALUE_PATTERN.fullmatch(raw_value) is None:
                return None
            return float(raw_value)
    return 1


def _match_specificity(tag: str, language: AppLanguage) -> int | None:
    if tag == "*":
        return 0
    if _supported_language(tag) != language:
        return None
    return tag.count("-") + 1


def _supported_language(tag: str) -> AppLanguage | None:
    lowered = tag.lower()
    if lowered == "zh" or lowered.startswith("zh-"):
        return "zh-CN"
    if lowered == "en" or lowered.startswith("en-"):
        return "en-US"
    return None


def _user_from_request(request: Request) -> AuthenticatedUser | None:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return user_from_token(token)
