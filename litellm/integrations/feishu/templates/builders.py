from typing import Any, Dict, List, Optional


def _kv_row(left: str, right: str) -> List[Dict[str, Any]]:
    return [
        {"tag": "text", "text": f"{left}"},
        {"tag": "text", "text": f"{right}"},
    ]


def _section_header(text: str) -> List[List[Dict[str, Any]]]:
    return [[{"tag": "text", "text": f"{text}"}]]


def _rows_from_list(items: List[str]) -> List[List[Dict[str, Any]]]:
    rows: List[List[Dict[str, Any]]] = []
    for it in items:
        rows.append([{"tag": "text", "text": it}])
    return rows


def build_generic_post(
    *,
    title: str,
    level: Optional[str] = None,
    timestamp: Optional[str] = None,
    message_lines: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    content: List[List[Dict[str, Any]]] = []

    # 级别/时间
    meta_line: List[Dict[str, Any]] = []
    if level:
        meta_line.append({"tag": "text", "text": f"级别：{level}  "})
    if timestamp:
        meta_line.append({"tag": "text", "text": f"时间：{timestamp}"})
    if meta_line:
        content.append(meta_line)

    # 正文消息
    if message_lines:
        content += _rows_from_list(message_lines)

    # 元数据
    if metadata:
        content += _section_header("告警元数据")
        for k, v in metadata.items():
            content.append([{"tag": "text", "text": f"{k}：{v}"}])

    # 代理地址
    if proxy_url:
        content += _section_header("代理地址")
        content.append([{"tag": "text", "text": proxy_url}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content or [[{"tag": "text", "text": ""}]],
                }
            }
        },
    }


def build_spend_reports(
    *,
    period_start: str,
    period_end: str,
    days: int,
    level: str,
    timestamp: str,
    team_spend: Optional[List[Dict[str, Any]]] = None,
    tag_spend: Optional[List[Dict[str, Any]]] = None,
    proxy_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    title = f"💸 支出报告（{period_start} - {period_end}，{days}天）"
    content: List[List[Dict[str, Any]]] = []

    # 顶部信息
    content.append(
        [
            {"tag": "text", "text": f"级别：{level}  "},
            {"tag": "text", "text": f"时间：{timestamp}"},
        ]
    )

    # 团队支出
    content += _section_header("团队支出汇总")
    if team_spend:
        for row in team_spend:
            team = row.get("team_alias") or row.get("team") or "未分配"
            spend = row.get("total_spend")
            content.append([{"tag": "text", "text": f"团队：{team} ｜ 支出：${spend}"}])
    else:
        content.append([{"tag": "text", "text": "无团队支出数据"}])

    # 标签支出
    content += _section_header("标签支出汇总")
    if tag_spend:
        for row in tag_spend:
            tag = (
                row.get("individual_request_tag")
                or row.get("tag")
                or row.get("name")
                or "未分配"
            )
            spend = row.get("total_spend")
            content.append([{"tag": "text", "text": f"标签：{tag} ｜ 支出：${spend}"}])
    else:
        content.append([{"tag": "text", "text": "无标签支出数据"}])

    # 元数据（可选）
    if metadata:
        content += _section_header("告警元数据")
        for k, v in metadata.items():
            content.append([{"tag": "text", "text": f"{k}：{v}"}])

    # 代理地址（可选）
    if proxy_url:
        content += _section_header("代理地址")
        content.append([{"tag": "text", "text": proxy_url}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content,
                }
            }
        },
    }


def build_budget_alert(
    *,
    event_name: str,
    entity_type: str,
    spend: float,
    max_budget: Optional[float] = None,
    soft_budget: Optional[float] = None,
    projected_exceeded_date: Optional[str] = None,
    projected_spend: Optional[float] = None,
    alias: Optional[str] = None,
    token: Optional[str] = None,
    user_email: Optional[str] = None,
    team_alias: Optional[str] = None,
    organization_id: Optional[str] = None,
    timestamp: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    title = f"预算告警 - {event_name}"
    content: List[List[Dict[str, Any]]] = []

    # 顶部基本信息
    top_line: List[Dict[str, Any]] = []
    if timestamp:
        top_line.append({"tag": "text", "text": f"时间：{timestamp}"})
    if entity_type:
        top_line.append({"tag": "text", "text": f" 实体：{entity_type}"})
    if top_line:
        content.append(top_line)

    # 身份信息
    identity_lines: List[str] = []
    if alias:
        identity_lines.append(f"别名：{alias}")
    if team_alias:
        identity_lines.append(f"团队：{team_alias}")
    if user_email:
        identity_lines.append(f"邮箱：{user_email}")
    if token:
        identity_lines.append(f"令牌：{token}")
    if organization_id:
        identity_lines.append(f"组织：{organization_id}")
    if identity_lines:
        content += _section_header("实体信息")
        content += _rows_from_list(identity_lines)

    # 预算数据
    budget_lines: List[str] = [f"当前支出：${spend}"]
    if max_budget is not None:
        budget_lines.append(f"最大预算：${max_budget}")
    if soft_budget is not None:
        budget_lines.append(f"软预算：${soft_budget}")
    if projected_spend is not None:
        budget_lines.append(f"预测支出：${projected_spend}")
    if projected_exceeded_date:
        budget_lines.append(f"预计超限日期：{projected_exceeded_date}")
    content += _section_header("预算数据")
    content += _rows_from_list(budget_lines)

    # 代理地址
    if proxy_url:
        content += _section_header("代理地址")
        content.append([{"tag": "text", "text": proxy_url}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content,
                }
            }
        },
    }


def build_outage_alert(
    *,
    severity: str,
    scope: str,
    key_name: str,
    provider: str,
    api_base: Optional[str],
    errors_text: str,
    last_check_seconds: float,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    title = f"⚠️ {severity} 宕机告警"
    content: List[List[Dict[str, Any]]] = []

    # 顶部
    top_line: List[Dict[str, Any]] = []
    if timestamp:
        top_line.append({"tag": "text", "text": f"时间：{timestamp}"})
    content.append(top_line or [{"tag": "text", "text": ""}])

    # 概要
    content += _section_header("概览")
    content.append([{"tag": "text", "text": f"范围：{scope}"}])
    content.append([{"tag": "text", "text": f"名称：{key_name}"}])
    content.append([{"tag": "text", "text": f"提供商：{provider}"}])
    if api_base:
        content.append([{"tag": "text", "text": f"API Base：{api_base}"}])

    # 错误分布
    content += _section_header("错误分布")
    for ln in [ln for ln in errors_text.split("\n") if ln.strip()]:
        content.append([{"tag": "text", "text": ln}])

    content += _section_header("最近检查")
    content.append([{"tag": "text", "text": f"{round(last_check_seconds, 2)} 秒前"}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content,
                }
            }
        },
    }


def build_new_model_added(
    *,
    model_name: str,
    base_model: Optional[str],
    model_info: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    title = "🚅 新增模型"
    content: List[List[Dict[str, Any]]] = []

    def _fmt_bool(val: Any) -> str:
        try:
            return "是" if bool(val) else "否"
        except Exception:
            return str(val)

    def _fmt_cost(val: Any) -> str:
        # 将数字格式化为科学计数或固定小数；保留原样若非数字
        try:
            f = float(val)
            # 保留原有科学计数法风格（如 3e-06），但统一前缀为 $/token
            return f"${val}/token"
        except Exception:
            return str(val)

    # 顶部
    top_line: List[Dict[str, Any]] = []
    if timestamp:
        top_line.append({"tag": "text", "text": f"时间：{timestamp}"})
    content.append(top_line or [{"tag": "text", "text": ""}])

    # 基本信息
    content += _section_header("基本信息")
    content.append([{"tag": "text", "text": f"模型名：{model_name}"}])
    if base_model:
        content.append([{"tag": "text", "text": f"基础模型：{base_model}"}])

    # 分类提取
    info = dict(model_info or {})
    provider = info.pop("litellm_provider", None)
    mode = info.pop("mode", None)

    input_cost = info.pop("input_cost_per_token", None)
    output_cost = info.pop("output_cost_per_token", None)
    input_cost_batches = info.pop("input_cost_per_token_batches", None)
    output_cost_batches = info.pop("output_cost_per_token_batches", None)

    max_input_tokens = info.pop("max_input_tokens", None)
    max_output_tokens = info.pop("max_output_tokens", None)
    max_tokens = info.pop("max_tokens", None)

    supports_system_messages = info.pop("supports_system_messages", None)
    supports_tool_choice = info.pop("supports_tool_choice", None)

    # 提供方与模式
    if provider or mode:
        content += _section_header("提供方与模式")
        if provider:
            content.append([{"tag": "text", "text": f"提供方：{provider}"}])
        if mode:
            content.append([{"tag": "text", "text": f"模式：{mode}"}])

    # 令牌上限
    if any(v is not None for v in [max_input_tokens, max_output_tokens, max_tokens]):
        content += _section_header("令牌上限")
        if max_input_tokens is not None:
            content.append([{"tag": "text", "text": f"最大输入令牌：{max_input_tokens}"}])
        if max_output_tokens is not None:
            content.append([{"tag": "text", "text": f"最大输出令牌：{max_output_tokens}"}])
        if max_tokens is not None:
            content.append([{"tag": "text", "text": f"最大令牌：{max_tokens}"}])

    # 成本（每 token）
    if input_cost is not None or output_cost is not None:
        content += _section_header("成本（每 token）")
        if input_cost is not None:
            content.append([{"tag": "text", "text": f"输入：{_fmt_cost(input_cost)}"}])
        if output_cost is not None:
            content.append([{"tag": "text", "text": f"输出：{_fmt_cost(output_cost)}"}])

    # 批量成本（每 token）
    if input_cost_batches is not None or output_cost_batches is not None:
        content += _section_header("批量成本（每 token）")
        if input_cost_batches is not None:
            content.append([
                {"tag": "text", "text": f"输入（批量）：{_fmt_cost(input_cost_batches)}"}
            ])
        if output_cost_batches is not None:
            content.append([
                {"tag": "text", "text": f"输出（批量）：{_fmt_cost(output_cost_batches)}"}
            ])

    # 支持能力
    if supports_system_messages is not None or supports_tool_choice is not None:
        content += _section_header("支持能力")
        if supports_system_messages is not None:
            content.append([
                {"tag": "text", "text": f"系统消息：{_fmt_bool(supports_system_messages)}"}
            ])
        if supports_tool_choice is not None:
            content.append([
                {"tag": "text", "text": f"工具选择：{_fmt_bool(supports_tool_choice)}"}
            ])

    # 其他信息（未分类的字段）
    if info:
        content += _section_header("其他信息")
        for k, v in info.items():
            content.append([{"tag": "text", "text": f"{k}：{v}"}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content,
                }
            }
        },
    }


def build_llm_too_slow(
    *,
    observed_seconds: float,
    threshold_seconds: float,
    model: str,
    api_base: Optional[str],
    message_excerpt: Optional[str] = None,
    deployment_latencies_text: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    title = "🐢 LLM 响应过慢"
    content: List[List[Dict[str, Any]]] = []

    # 顶部
    top_line: List[Dict[str, Any]] = []
    if timestamp:
        top_line.append({"tag": "text", "text": f"时间：{timestamp}"})
    content.append(top_line or [{"tag": "text", "text": ""}])

    content += _section_header("阈值与观测")
    content.append([{"tag": "text", "text": f"观测响应时间：{round(observed_seconds, 2)}s"}])
    content.append([{"tag": "text", "text": f"告警阈值：{round(threshold_seconds, 2)}s"}])

    content += _section_header("请求信息")
    content.append([{"tag": "text", "text": f"模型：{model}"}])
    if api_base:
        content.append([{"tag": "text", "text": f"API Base：{api_base}"}])
    if message_excerpt:
        content.append([{"tag": "text", "text": f"消息片段：{message_excerpt}"}])

    if deployment_latencies_text:
        content += _section_header("可用部署延迟")
        for ln in [ln for ln in deployment_latencies_text.split("\n") if ln.strip()]:
            content.append([{"tag": "text", "text": ln}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content,
                }
            }
        },
    }


def build_daily_reports(
    *,
    timestamp: Optional[str],
    top_failed: Optional[List[Dict[str, Any]]] = None,
    top_slowest: Optional[List[Dict[str, Any]]] = None,
    next_run_in_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    title = "📈 每日性能报告"
    content: List[List[Dict[str, Any]]] = []

    # 顶部
    top_line: List[Dict[str, Any]] = []
    if timestamp:
        top_line.append({"tag": "text", "text": f"时间：{timestamp}"})
    content.append(top_line or [{"tag": "text", "text": ""}])

    # 失败最多部署
    content += _section_header("❗️ 失败请求最多的部署 Top 5")
    if top_failed:
        for i, item in enumerate(top_failed, start=1):
            name = item.get("deployment_name", "")
            count = item.get("count", 0)
            api_base = item.get("api_base", "")
            content.append([
                {"tag": "text", "text": f"{i}. 部署：{name} ｜ 失败数：{count} ｜ API Base：{api_base}"}
            ])
    else:
        content.append([{"tag": "text", "text": "无数据"}])

    # 最慢部署
    content += _section_header("😅 最慢的部署 Top 5（按输出令牌延迟）")
    if top_slowest:
        for i, item in enumerate(top_slowest, start=1):
            name = item.get("deployment_name", "")
            latency = item.get("latency", 0)
            api_base = item.get("api_base", "")
            content.append([
                {"tag": "text", "text": f"{i}. 部署：{name} ｜ 延迟：{latency}s/token ｜ API Base：{api_base}"}
            ])
    else:
        content.append([{"tag": "text", "text": "无数据"}])

    if next_run_in_seconds is not None:
        content += _section_header("下次运行间隔")
        content.append([
            {"tag": "text", "text": f"{round(float(next_run_in_seconds), 2)} 秒后"}
        ])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content,
                }
            }
        },
    }


def build_failed_tracking_spend(
    *,
    failing_model: str,
    error_message: str,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    title = "📉 费用跟踪失败"
    content: List[List[Dict[str, Any]]] = []

    # 顶部
    top_line: List[Dict[str, Any]] = []
    if timestamp:
        top_line.append({"tag": "text", "text": f"时间：{timestamp}"})
    content.append(top_line or [{"tag": "text", "text": ""}])

    content += _section_header("详情")
    content.append([{"tag": "text", "text": f"失败模型：{failing_model}"}])
    content.append([{"tag": "text", "text": f"错误信息：{error_message}"}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content,
                }
            }
        },
    }


def build_fallback_report(
    *,
    fallback_text: str,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    title = "🔁 回退统计"
    content: List[List[Dict[str, Any]]] = []

    # 顶部
    top_line: List[Dict[str, Any]] = []
    if timestamp:
        top_line.append({"tag": "text", "text": f"时间：{timestamp}"})
    content.append(top_line or [{"tag": "text", "text": ""}])

    content += _section_header("统计信息")
    for ln in [ln for ln in fallback_text.split("\n") if ln.strip()]:
        content.append([{"tag": "text", "text": ln}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content,
                }
            }
        },
    }


def build_management_event(
    *,
    event_name: str,
    created_by: Optional[Dict[str, Any]] = None,
    args: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    title = "🛠️ 管理事件通知"
    content: List[List[Dict[str, Any]]] = []

    # 顶部
    top_line: List[Dict[str, Any]] = []
    if timestamp:
        top_line.append({"tag": "text", "text": f"时间：{timestamp}"})
    content.append(top_line or [{"tag": "text", "text": ""}])

    content += _section_header("事件")
    content.append([{"tag": "text", "text": event_name}])

    # 执行人信息
    if created_by:
        content += _section_header("执行人")
        for k, v in created_by.items():
            content.append([{"tag": "text", "text": f"{k}：{v}"}])

    # 传入参数
    if args:
        content += _section_header("参数")
        for k, v in args.items():
            content.append([{"tag": "text", "text": f"{k}：{v}"}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content,
                }
            }
        },
    }


def build_db_exception(
    *,
    level: Optional[str] = None,
    timestamp: Optional[str] = None,
    summary: Optional[str] = None,
    traceback_text: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    title = "🗄️ 数据库异常"
    content: List[List[Dict[str, Any]]] = []

    # 顶部
    meta_line: List[Dict[str, Any]] = []
    if level:
        meta_line.append({"tag": "text", "text": f"级别：{level}  "})
    if timestamp:
        meta_line.append({"tag": "text", "text": f"时间：{timestamp}"})
    if meta_line:
        content.append(meta_line)

    # 摘要
    if summary:
        content += _section_header("错误摘要")
        content.append([{"tag": "text", "text": summary}])

    # 追踪
    if traceback_text:
        content += _section_header("错误追踪")
        for ln in [ln for ln in traceback_text.split("\n") if ln.strip()]:
            content.append([{"tag": "text", "text": ln}])

    if proxy_url:
        content += _section_header("代理地址")
        content.append([{"tag": "text", "text": proxy_url}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content or [[{"tag": "text", "text": ""}]],
                }
            }
        },
    }


def build_hanging_request(
    *,
    threshold_seconds: float,
    model: str,
    api_base: Optional[str] = None,
    key_alias: Optional[str] = None,
    team_alias: Optional[str] = None,
    request_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    title = "⏳ 请求挂起告警"
    content: List[List[Dict[str, Any]]] = []

    # 顶部
    top_line: List[Dict[str, Any]] = []
    if timestamp:
        top_line.append({"tag": "text", "text": f"时间：{timestamp}"})
    content.append(top_line or [{"tag": "text", "text": ""}])

    content += _section_header("阈值")
    content.append([{"tag": "text", "text": f"已超时：{round(float(threshold_seconds), 2)}s+"}])

    content += _section_header("请求信息")
    content.append([{"tag": "text", "text": f"模型：{model}"}])
    if api_base:
        content.append([{"tag": "text", "text": f"API Base：{api_base}"}])
    if key_alias is not None:
        content.append([{"tag": "text", "text": f"Key 别名：{key_alias}"}])
    if team_alias is not None:
        content.append([{"tag": "text", "text": f"团队别名：{team_alias}"}])
    if request_id:
        content.append([{"tag": "text", "text": f"请求ID：{request_id}"}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content,
                }
            }
        },
    }


def build_llm_exception(
    *,
    level: Optional[str] = None,
    timestamp: Optional[str] = None,
    exception_text: Optional[str] = None,
    model: Optional[str] = None,
    api_base: Optional[str] = None,
    messages_excerpt: Optional[str] = None,
    key_alias: Optional[str] = None,
    team_alias: Optional[str] = None,
    model_group: Optional[str] = None,
    deployment: Optional[str] = None,
) -> Dict[str, Any]:
    title = "❌ LLM 异常"
    content: List[List[Dict[str, Any]]] = []

    # 顶部元信息
    meta_line: List[Dict[str, Any]] = []
    if level:
        meta_line.append({"tag": "text", "text": f"级别：{level}  "})
    if timestamp:
        meta_line.append({"tag": "text", "text": f"时间：{timestamp}"})
    if meta_line:
        content.append(meta_line)

    # 异常摘要
    if exception_text:
        content += _section_header("异常摘要")
        # 将长文本按行拆分，保持可读性
        for ln in [ln for ln in str(exception_text).split("\n") if ln.strip()]:
            content.append([{"tag": "text", "text": ln}])

    # 请求信息
    info_lines: List[str] = []
    if model:
        info_lines.append(f"模型：{model}")
    if api_base:
        info_lines.append(f"API Base：{api_base}")
    if messages_excerpt:
        info_lines.append(f"消息片段：{messages_excerpt}")
    if key_alias:
        info_lines.append(f"Key 别名：{key_alias}")
    if team_alias:
        info_lines.append(f"团队别名：{team_alias}")
    if model_group:
        info_lines.append(f"model_group：{model_group}")
    if deployment:
        info_lines.append(f"deployment：{deployment}")
    if info_lines:
        content += _section_header("请求信息")
        content += _rows_from_list(info_lines)

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content or [[{"tag": "text", "text": ""}]],
                }
            }
        },
    }
