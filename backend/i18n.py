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
REQUEST_LANGUAGE_STATE_KEY = "public_message_language"
QUALITY_VALUE_PATTERN = re.compile(r"(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)\Z")

PUBLIC_MESSAGES: dict[str, dict[AppLanguage, str]] = {
    "ACCOUNT_EXPORT_FAILED": {
        "en-US": "Account data could not be exported. Please try again.",
        "zh-CN": "无法导出账户数据，请重试。",
    },
    "ACCOUNT_DELETED": {
        "en-US": "Account deleted.",
        "zh-CN": "账户已删除。",
    },
    "ACCOUNT_DELETE_CONFIRMATION_INVALID": {
        "en-US": 'Enter "DELETE" to confirm account deletion.',
        "zh-CN": "请输入“DELETE”以确认删除账户。",
    },
    "ACCOUNT_DELETE_FAILED": {
        "en-US": "Account could not be deleted. Please try again.",
        "zh-CN": "无法删除账户，请重试。",
    },
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
    "ACCOUNT_PASSWORD_CHANGED": {
        "en-US": "Password changed.",
        "zh-CN": "密码已更新。",
    },
    "ACCOUNT_SESSIONS_REVOKED": {
        "en-US": "Other sessions revoked.",
        "zh-CN": "其他会话已撤销。",
    },
    "ACCOUNT_CURRENT_PASSWORD_INVALID": {
        "en-US": "The current password is incorrect.",
        "zh-CN": "当前密码不正确。",
    },
    "ACCOUNT_PASSWORD_POLICY": {
        "en-US": "The new password must be between 8 and 128 characters.",
        "zh-CN": "新密码长度必须为 8 到 128 个字符。",
    },
    "ACCOUNT_PASSWORD_UNCHANGED": {
        "en-US": "The new password must differ from the current password.",
        "zh-CN": "新密码必须与当前密码不同。",
    },
    "PREFERENCES_SAVED": {"en-US": "Preferences saved.", "zh-CN": "偏好设置已保存。"},
    "MODEL_SETTINGS_SAVED": {"en-US": "Model settings saved.", "zh-CN": "模型设置已保存。"},
    "API_KEY_CLEARED": {"en-US": "API key cleared.", "zh-CN": "API 密钥已清除。"},
    "MODEL_CONNECTION_VERIFIED": {"en-US": "Model connection verified.", "zh-CN": "模型连接验证成功。"},
    "PROFILE_SAVED": {"en-US": "Profile saved.", "zh-CN": "个人资料已保存。"},
    "PROFILE_VERSIONED_WRITE_REQUIRED": {
        "en-US": "Use the body profile or training personalization form for this change.",
        "zh-CN": "请通过身体档案或训练个性化表单完成此修改。",
    },
    "PROFILE_EFFECTIVE_FROM_CONFLICT": {
        "en-US": "A profile version already exists at that effective time. Try saving again.",
        "zh-CN": "该生效时间已存在档案版本，请重新保存。",
    },
    "GOAL_EFFECTIVE_FROM_CONFLICT": {
        "en-US": "A goal version already exists at that effective time. Try saving again.",
        "zh-CN": "该生效时间已存在目标版本，请重新保存。",
    },
    "TARGET_EFFECTIVE_FROM_CONFLICT": {
        "en-US": "A daily target version already exists at that effective time. Try confirming again.",
        "zh-CN": "该生效时间已存在每日目标版本，请重新确认。",
    },
    "PROFILE_TARGET_SETUP_INCOMPLETE": {
        "en-US": "Complete the body profile and overall goal before calculating targets.",
        "zh-CN": "请先完成身体档案和总体目标，再计算每日目标。",
    },
    "TARGET_CALCULATION_RESTRICTED": {
        "en-US": "Automatic target calculation is unavailable for this profile.",
        "zh-CN": "当前档案不支持自动计算每日目标。",
    },
    "TARGET_OUT_OF_RANGE": {
        "en-US": "One or more daily targets are outside the supported range.",
        "zh-CN": "一个或多个每日目标超出支持范围。",
    },
    "TARGET_PREVIEW_STALE": {
        "en-US": "The profile or goal changed. Calculate a new target preview.",
        "zh-CN": "档案或目标已变化，请重新计算目标预览。",
    },
    "TARGET_PREVIEW_INVALID": {
        "en-US": "The target preview is invalid. Calculate it again.",
        "zh-CN": "目标预览无效，请重新计算。",
    },
    "TARGET_PREVIEW_TOKEN_REQUIRED": {
        "en-US": "A target preview token is required.",
        "zh-CN": "缺少目标预览令牌。",
    },
    "TARGET_WARNING_ACKNOWLEDGEMENT_REQUIRED": {
        "en-US": "Review and acknowledge the target warnings before confirming.",
        "zh-CN": "确认前请查看并确认目标警告。",
    },
    "TARGET_COMPATIBILITY_WRITE_FAILED": {
        "en-US": "Targets were saved, but legacy views could not be updated. Retry the confirmation.",
        "zh-CN": "目标已保存，但旧版视图更新失败，请重试确认。",
    },
    "IDEMPOTENCY_KEY_REQUIRED": {
        "en-US": "A confirmation retry key is required.",
        "zh-CN": "缺少确认重试键。",
    },
    "INVALID_IDEMPOTENCY_KEY": {
        "en-US": "The confirmation retry key is invalid.",
        "zh-CN": "确认重试键无效。",
    },
    "IDEMPOTENCY_KEY_REUSED": {
        "en-US": "That confirmation retry key was already used for another request.",
        "zh-CN": "该确认重试键已用于其他请求。",
    },
    "IDEMPOTENCY_RESULT_NOT_FOUND": {
        "en-US": "The saved confirmation result could not be recovered. Calculate a new preview.",
        "zh-CN": "无法恢复已保存的确认结果，请重新计算目标预览。",
    },
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
    captured = getattr(request.state, REQUEST_LANGUAGE_STATE_KEY, None)
    if captured in SUPPORTED_LANGUAGES:
        return captured
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
