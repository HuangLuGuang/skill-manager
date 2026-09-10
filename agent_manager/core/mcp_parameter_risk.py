from __future__ import annotations

import re


_PARAMETER_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("command_execution", re.compile(r"(?i)(?:^|\s)(command|cmd|shell|script|code)(?:$|\s)|命令|脚本")),
    ("filesystem_path", re.compile(r"(?i)(?:^|\s)(path|file|filename|directory|dir)(?:$|\s)|文件|目录|路径")),
    ("external_destination", re.compile(r"(?i)(?:^|\s)(url|uri|endpoint|webhook|host|email|recipient|destination)(?:$|\s)|地址|收件人|目标")),
    ("financial", re.compile(r"(?i)(?:^|\s)(amount|account|iban|wallet|card|currency)(?:$|\s)|金额|账户|卡号|钱包")),
    ("credential", re.compile(r"(?i)(?:^|\s)(token|secret|password|credential|api\s?key)(?:$|\s)|令牌|密钥|密码|凭据")),
)

_DIRECT_QUERY_EXECUTION_NAMES = {"sql", "statement", "sql statement", "database query"}
_CONDITIONAL_QUERY_NAMES = {"query", "raw query", "query expression"}
_QUERY_EXECUTION_CONTEXT = re.compile(
    r"(?i)(?:\bsql\b|\bdatabase\b|\bdb\b|\bstatement\b|\bexecute\b|\bexecution\b|数据库|执行语句|查询数据库)"
)
_SEARCH_QUERY_CONTEXT = re.compile(
    r"(?i)(?:\bsearch\s+quer(?:y|ies)\b|\bsearch\s+terms?\b|\bfilter\s+query\b|搜索关键词|搜索查询)"
)
_GRAPHQL_ONLY_CONTEXT = re.compile(r"(?i)\bgraphql\s+query\b")


def normalize_mcp_identifier(value: str) -> str:
    """Normalize camelCase and common JSON path separators into words."""
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value))
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    return re.sub(r"[._\-/:$\[\]]+", " ", text).strip()


def classify_mcp_parameter(
    name: str,
    *,
    description: str = "",
    parent_path: str = "",
) -> list[str]:
    """Classify a parameter using its name and explicit schema context.

    A generic ``query`` is not an execution signal by itself. It needs SQL,
    database, statement, or execution context, and common search/filter or
    GraphQL-only descriptions deliberately suppress that weak inference.
    """
    normalized_name = normalize_mcp_identifier(name).lower()
    normalized_description = normalize_mcp_identifier(description)
    normalized_parent = normalize_mcp_identifier(parent_path)
    # Parent paths are useful only as query execution context. Including them in
    # every category would repeat a parent ``urlMap`` signal on its ``type``,
    # ``description``, and ``additionalProperties`` descendants.
    combined = " ".join(value for value in (normalized_name, normalized_description) if value)

    categories = [category for category, pattern in _PARAMETER_RULES if pattern.search(combined)]

    if normalized_name in _DIRECT_QUERY_EXECUTION_NAMES:
        categories.append("query_execution")
    elif normalized_name in _CONDITIONAL_QUERY_NAMES:
        context = " ".join(value for value in (normalized_description, normalized_parent) if value)
        weak_search_context = bool(_SEARCH_QUERY_CONTEXT.search(context) or _GRAPHQL_ONLY_CONTEXT.search(context))
        if _QUERY_EXECUTION_CONTEXT.search(context) and not weak_search_context:
            categories.append("query_execution")

    return list(dict.fromkeys(categories))
