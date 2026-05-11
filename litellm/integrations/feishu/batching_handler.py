"""
处理批处理+向飞书发送Httpx Post请求
飞书警报每10秒发送一次，或者当事件大于X个事件时发送一次
"""

from typing import TYPE_CHECKING, Any

from litellm._logging import verbose_proxy_logger

if TYPE_CHECKING:
    from .feishu_alerting import FeishuAlerting as _FeishuAlerting

    FeishuAlertingType = _FeishuAlerting
else:
    FeishuAlertingType = Any


def squash_payloads(queue):
    squashed = {}
    if len(queue) == 0:
        return squashed
    if len(queue) == 1:
        return {"key": {"item": queue[0], "count": 1}}

    for item in queue:
        url = item["url"]
        alert_type = item["alert_type"]
        _key = (url, alert_type)

        if _key in squashed:
            squashed[_key]["count"] += 1
            # Merge the payloads

        else:
            squashed[_key] = {"item": item, "count": 1}

    return squashed


def _print_alerting_payload_warning(
    payload: dict, feishuAlertingInstance: FeishuAlertingType
):
    """
    Print the payload to the console when
    feishuAlertingInstance.alerting_args.log_to_console is True

    Relevant issue: https://github.com/BerriAI/litellm/issues/7372
    """
    if feishuAlertingInstance.alerting_args.log_to_console is True:
        verbose_proxy_logger.warning(payload)


async def send_to_webhook(feishuAlertingInstance: FeishuAlertingType, item, count):
    """
    向飞书webhook发送单个告警
    """
    import json

    payload = item.get("payload", {})
    try:
        if count > 1:
             # 飞书消息格式
            if isinstance(payload, dict) and "content" in payload and isinstance(payload["content"], dict) and "text" in payload["content"]:
                payload["content"]["text"] = f"[Num Alerts: {count}]\n\n{payload['content']['text']}"


        response = await feishuAlertingInstance.async_http_handler.post(
            url=item["url"],
            headers=item["headers"],
            data=json.dumps(payload),
        )
        if response.status_code != 200:
            verbose_proxy_logger.debug(
                f"Error sending feishu alert to url={item['url']}. Error={response.text}"
            )
    except Exception as e:
        verbose_proxy_logger.debug(f"Error sending feishu alert: {str(e)}")
    finally:
        _print_alerting_payload_warning(
            payload, feishuAlertingInstance=feishuAlertingInstance
        )
