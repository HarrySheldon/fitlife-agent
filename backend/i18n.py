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
    "INTERNAL_ERROR": {
        "en-US": "The request could not be completed. Please try again.",
        "zh-CN": "请求未能完成，请稍后重试。",
    },
    "RUN_BUDGET_EXCEEDED": {
        "en-US": "The Agent run reached its usage limit.",
        "zh-CN": "Agent 运行已达到使用限额。",
    },
    "RUN_TIMED_OUT": {
        "en-US": "The Agent run timed out.",
        "zh-CN": "Agent 运行已超时。",
    },
    "RUN_CANCELLED": {
        "en-US": "The Agent run was cancelled.",
        "zh-CN": "Agent 运行已取消。",
    },
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
    "FOOD_NOT_VISIBLE": {
        "en-US": "The food was not found.",
        "zh-CN": "未找到该食物。",
    },
    "DRAFT_NOT_FOUND": {
        "en-US": "The meal draft was not found.",
        "zh-CN": "未找到该餐食草稿。",
    },
    "DRAFT_EXPIRED": {
        "en-US": "The meal draft has expired.",
        "zh-CN": "该餐食草稿已过期。",
    },
    "DRAFT_VERSION_CONFLICT": {
        "en-US": "The meal draft changed. Reload it and try again.",
        "zh-CN": "餐食草稿已发生变化，请重新加载后再试。",
    },
    "DRAFT_INCOMPLETE": {
        "en-US": "Add at least one complete food item before confirming.",
        "zh-CN": "确认前请至少添加一项完整食物。",
    },
    "DRAFT_VERSION_REQUIRED": {
        "en-US": "The meal draft version is required.",
        "zh-CN": "缺少餐食草稿版本。",
    },
    "DRAFT_VERSION_INVALID": {
        "en-US": "The meal draft version is invalid.",
        "zh-CN": "餐食草稿版本无效。",
    },
    "SMART_ENTRY_SELECTION_REQUIRED": {
        "en-US": "Select at least one entry before confirming.",
        "zh-CN": "\u786e\u8ba4\u524d\u8bf7\u81f3\u5c11\u9009\u62e9\u4e00\u6761\u8bb0\u5f55\u3002",
    },
    "SMART_ENTRY_DRAFT_INCOMPLETE": {
        "en-US": "Complete the selected entries before confirming.",
        "zh-CN": "\u786e\u8ba4\u524d\u8bf7\u8865\u5168\u6240\u9009\u8bb0\u5f55\u3002",
    },
    "SMART_ENTRY_AGENT_ESTIMATE_NOT_ACCEPTED": {
        "en-US": "Review and accept every AI estimate before confirming.",
        "zh-CN": "\u786e\u8ba4\u524d\u8bf7\u5ba1\u6838\u5e76\u63a5\u53d7\u6bcf\u9879 AI \u4f30\u7b97\u3002",
    },
    "SMART_ENTRY_CATALOG_NOT_VISIBLE": {
        "en-US": "A selected catalog item is unavailable.",
        "zh-CN": "\u6240\u9009\u76ee\u5f55\u6570\u636e\u4e0d\u53ef\u7528\u3002",
    },
    "SMART_ENTRY_CONFIRM_FAILED": {
        "en-US": "The entries could not be confirmed. The draft was preserved.",
        "zh-CN": "\u8bb0\u5f55\u786e\u8ba4\u5931\u8d25\uff0c\u8349\u7a3f\u5df2\u4fdd\u7559\u3002",
    },
    "SMART_ENTRY_DRAFT_CORRUPT": {
        "en-US": "The smart entry draft could not be read.",
        "zh-CN": "\u65e0\u6cd5\u8bfb\u53d6\u667a\u80fd\u8f93\u5165\u8349\u7a3f\u3002",
    },
    "LEGACY_AGENT_ENTRY_DEPRECATED": {
        "en-US": "Use the smart entry draft workflow for signed-in records.",
        "zh-CN": "\u767b\u5f55\u540e\u8bf7\u4f7f\u7528\u667a\u80fd\u8f93\u5165\u8349\u7a3f\u6d41\u7a0b\u3002",
    },
    "EXERCISE_NOT_VISIBLE": {
        "en-US": "The exercise was not found.",
        "zh-CN": "未找到该训练动作。",
    },
    "WORKOUT_DRAFT_NOT_FOUND": {
        "en-US": "The workout draft was not found.",
        "zh-CN": "未找到该训练草稿。",
    },
    "WORKOUT_DRAFT_EXPIRED": {
        "en-US": "The workout draft has expired.",
        "zh-CN": "该训练草稿已过期。",
    },
    "WORKOUT_DRAFT_VERSION_CONFLICT": {
        "en-US": "The workout draft changed. Reload it and try again.",
        "zh-CN": "训练草稿已发生变化，请重新加载后再试。",
    },
    "WORKOUT_DRAFT_INCOMPLETE": {
        "en-US": "Add at least one complete exercise before confirming.",
        "zh-CN": "确认前请至少添加一项完整训练。",
    },
    "WORKOUT_DRAFT_VERSION_REQUIRED": {
        "en-US": "The workout draft version is required.",
        "zh-CN": "缺少训练草稿版本。",
    },
    "WORKOUT_DRAFT_VERSION_INVALID": {
        "en-US": "The workout draft version is invalid.",
        "zh-CN": "训练草稿版本无效。",
    },
    "WORKOUT_PROFILE_REQUIRED": {
        "en-US": "Complete a body profile before recording training.",
        "zh-CN": "记录训练前请先完成身体档案。",
    },
    "EXERCISE_TYPE_MISMATCH": {
        "en-US": "The selected exercise type does not match this entry.",
        "zh-CN": "所选动作类型与当前记录不匹配。",
    },
    "WORKOUT_MET_REQUIRED": {
        "en-US": "A MET value or device calorie value is required.",
        "zh-CN": "需要 MET 值或设备消耗值。",
    },
    "WORKOUT_INTENSITY_REQUIRED": {
        "en-US": "Select an intensity when workout duration is provided.",
        "zh-CN": "填写训练时长时请选择训练强度。",
    },
    "WORKOUT_WEIGHT_REQUIRED": {
        "en-US": "Complete a valid body weight before estimating training.",
        "zh-CN": "估算训练消耗前请完善有效体重。",
    },
    "WORKOUT_DATE_INVALID": {
        "en-US": "Enter a valid workout date.",
        "zh-CN": "请输入有效的训练日期。",
    },
    "WORKOUT_DURATION_INVALID": {
        "en-US": "Enter a valid workout duration.",
        "zh-CN": "请输入有效的训练时长。",
    },
    "WORKOUT_INTENSITY_INVALID": {
        "en-US": "Select a valid workout intensity.",
        "zh-CN": "请选择有效的训练强度。",
    },
    "STRENGTH_SETS_REQUIRED": {
        "en-US": "Add at least one strength set.",
        "zh-CN": "请至少添加一组力量训练。",
    },
    "STRENGTH_SET_ORDER_INVALID": {
        "en-US": "Strength sets must be numbered in order from one.",
        "zh-CN": "力量训练组数必须从 1 开始连续编号。",
    },
    "STRENGTH_BODYWEIGHT_INVALID": {
        "en-US": "Bodyweight sets cannot include an external load.",
        "zh-CN": "自重训练组不能同时填写外部负重。",
    },
    "EXERCISE_SOURCE_INVALID": {
        "en-US": "Select one catalog exercise or enter one custom exercise.",
        "zh-CN": "请选择一个目录动作或填写一个自定义动作。",
    },
    "EXERCISE_TYPE_INVALID": {
        "en-US": "Select a valid exercise type.",
        "zh-CN": "请选择有效的训练类型。",
    },
    "EXERCISE_ALIAS_INVALID": {
        "en-US": "Enter valid exercise aliases.",
        "zh-CN": "请输入有效的动作别名。",
    },
    "EXERCISE_SECONDARY_MUSCLE_INVALID": {
        "en-US": "Enter valid secondary muscle names.",
        "zh-CN": "请输入有效的辅助肌群名称。",
    },
    "FOOD_NAME_REQUIRED": {
        "en-US": "Enter a food name.",
        "zh-CN": "请输入食物名称。",
    },
    "FOOD_BASIS_TYPE_INVALID": {
        "en-US": "Select a supported nutrition basis.",
        "zh-CN": "请选择支持的营养基准。",
    },
    "FOOD_BASIS_AMOUNT_INVALID": {
        "en-US": "Enter a valid nutrition basis amount.",
        "zh-CN": "请输入有效的营养基准数量。",
    },
    "FOOD_UNIT_REQUIRED": {
        "en-US": "Enter a food unit.",
        "zh-CN": "请输入食物单位。",
    },
    "FOOD_UNIT_INCOMPATIBLE": {
        "en-US": "The amount unit does not match the food basis.",
        "zh-CN": "份量单位与食物营养基准不匹配。",
    },
    "FOOD_NUTRIENT_INVALID": {
        "en-US": "Enter complete, non-negative nutrition values.",
        "zh-CN": "请输入完整且不小于零的营养数据。",
    },
    "FOOD_PORTION_AMOUNT_INVALID": {
        "en-US": "Enter a positive food amount.",
        "zh-CN": "请输入大于零的食物份量。",
    },
    "FOOD_NUTRIENT_SCALE_INVALID": {
        "en-US": "The nutrition values are too large to calculate.",
        "zh-CN": "营养数据过大，无法计算。",
    },
    "FOOD_PORTION_SCALE_INVALID": {
        "en-US": "The food amount is too large to calculate.",
        "zh-CN": "食物份量过大，无法计算。",
    },
    "MEAL_ITEM_SOURCE_INVALID": {
        "en-US": "Select one catalog food or enter one custom food.",
        "zh-CN": "请选择一个目录食物或输入一个自定义食物。",
    },
    "MEAL_DATE_INVALID": {
        "en-US": "Select a valid meal date.",
        "zh-CN": "请选择有效的餐食日期。",
    },
    "MEAL_NAME_REQUIRED": {
        "en-US": "Enter a meal name.",
        "zh-CN": "请输入餐食名称。",
    },
    "MEAL_NAME_TOO_LONG": {
        "en-US": "The meal name is too long.",
        "zh-CN": "餐食名称过长。",
    },
    "MEAL_TYPE_INVALID": {
        "en-US": "Select a supported meal type.",
        "zh-CN": "请选择支持的餐食类型。",
    },
    "MEAL_ENTRY_METHOD_INVALID": {
        "en-US": "This meal entry method is not supported.",
        "zh-CN": "不支持该餐食录入方式。",
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
        "en-US": "Secure credential storage is temporarily unavailable.",
        "zh-CN": "安全凭据存储暂时不可用。",
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
