'''
告警模型定义

定义了如 BaseOutageModel、OutageModel、ProviderRegionOutageModel 等 TypedDict，用于描述模型或区域的故障告警信息（如告警次数、是否已发送、最后更新时间等）。
告警参数配置

通过 FeishuAlertingArgsEnum 和 FeishuAlertingArgs，定义了告警相关的参数（如告警频率、检查间隔、TTL、阈值等），支持通过环境变量或默认值配置。
枚举类型与常量

定义了多种枚举类型，如 FeishuAlertingCacheKeys（缓存键）、AlertType（告警类型），以及一些常量（如 logo 链接、支持邮箱、阈值等）。
部署监控指标

DeploymentMetrics 用于描述单个部署的监控指标（如失败请求、延迟等），便于日常报告和监控。
默认告警类型

DEFAULT_ALERT_TYPES 指定了系统默认关注的告警类型列表。
悬挂请求数据结构

HangingRequestData 用于描述"悬挂请求"的详细信息，便于追踪和告警

'''

import os
from datetime import datetime as dt
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Set

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from litellm.types.utils import LiteLLMPydanticObjectBase

from litellm.proxy._types import AlertType

Feishu_ALERTING_THRESHOLD_5_PERCENT = 0.05
Feishu_ALERTING_THRESHOLD_15_PERCENT = 0.15
MAX_OLDEST_HANGING_REQUESTS_TO_CHECK = 20
HANGING_ALERT_BUFFER_TIME_SECONDS = 60


class BaseOutageModel(TypedDict):
    alerts: List[int]
    minor_alert_sent: bool
    major_alert_sent: bool
    last_updated_at: float


class OutageModel(BaseOutageModel):
    model_id: str


class ProviderRegionOutageModel(BaseOutageModel):
    provider_region_id: str
    deployment_ids: Set[str]


# 邮件头使用此 logo URL，如果更改，请发送测试邮件以验证其在邮件中的显示效果
LITELLM_LOGO_URL = "https://litellm-listing.s3.amazonaws.com/litellm_logo.png"
LITELLM_SUPPORT_CONTACT = "support@berri.ai"


class FeishuAlertingArgsEnum(Enum):
    daily_report_frequency = 12 * 60 * 60
    report_check_interval = 5 * 60
    budget_alert_ttl = 24 * 60 * 60
    outage_alert_ttl = 1 * 60
    region_outage_alert_ttl = 1 * 60
    minor_outage_alert_threshold = 1 * 5
    major_outage_alert_threshold = 1 * 10
    max_outage_alert_list_size = 1 * 10


class FeishuAlertingArgs(LiteLLMPydanticObjectBase):
    # 告警参数配置
    daily_report_frequency: int = Field(
        default=int(
            os.getenv(
                "Feishu_DAILY_REPORT_FREQUENCY",
                int(FeishuAlertingArgsEnum.daily_report_frequency.value),
            )
        ),
        description="Frequency of receiving deployment latency/failure reports. Default is 12hours. Value is in seconds.",
    )
    report_check_interval: int = Field(
        default=FeishuAlertingArgsEnum.report_check_interval.value,
        description="Frequency of checking cache if report should be sent. Background process. Default is once per hour. Value is in seconds.",
    )  # 5 minutes
    budget_alert_ttl: int = Field(
        default=FeishuAlertingArgsEnum.budget_alert_ttl.value,
        description="Cache ttl for budgets alerts. Prevents spamming same alert, each time budget is crossed. Value is in seconds.",
    )  # 24 hours
    outage_alert_ttl: int = Field(
        default=FeishuAlertingArgsEnum.outage_alert_ttl.value,
        description="Cache ttl for model outage alerts. Sets time-window for errors. Default is 1 minute. Value is in seconds.",
    )  # 1 minute ttl
    region_outage_alert_ttl: int = Field(
        default=FeishuAlertingArgsEnum.region_outage_alert_ttl.value,
        description="Cache ttl for provider-region based outage alerts. Alert sent if 2+ models in same region report errors. Sets time-window for errors. Default is 1 minute. Value is in seconds.",
    )  # 1 minute ttl
    minor_outage_alert_threshold: int = Field(
        default=FeishuAlertingArgsEnum.minor_outage_alert_threshold.value,
        description="The number of errors that count as a model/region minor outage. ('400' error code is not counted).",
    )
    major_outage_alert_threshold: int = Field(
        default=FeishuAlertingArgsEnum.major_outage_alert_threshold.value,
        description="The number of errors that countas a model/region major outage. ('400' error code is not counted).",
    )
    max_outage_alert_list_size: int = Field(
        default=FeishuAlertingArgsEnum.max_outage_alert_list_size.value,
        description="Maximum number of errors to store in cache. For a given model/region. Prevents memory leaks.",
    )  # prevent memory leak
    log_to_console: bool = Field(
        default=False,
        description="If true, the alerting payload will be printed to the console.",
    )


class DeploymentMetrics(LiteLLMPydanticObjectBase):
    """
    Metrics per deployment, stored in cache

    Used for daily reporting
    """

    id: str
    """id of deployment in router model list"""

    failed_request: bool
    """did it fail the request?"""

    latency_per_output_token: Optional[float]
    """latency/output token of deployment"""

    updated_at: dt
    """Current time of deployment being updated"""


class FeishuAlertingCacheKeys(Enum):
    """
    Enum for deployment daily metrics keys - {deployment_id}:{enum}
    """

    failed_requests_key = "failed_requests_daily_metrics"
    latency_key = "latency_daily_metrics"
    report_sent_key = "daily_metrics_report_sent"



DEFAULT_ALERT_TYPES: List[AlertType] = [
    # LLM related alerts
    AlertType.llm_exceptions,
    AlertType.llm_too_slow,
    AlertType.llm_requests_hanging,
    # Budget and spend alerts
    AlertType.budget_alerts,
    AlertType.spend_reports,
    AlertType.failed_tracking_spend,
    # Database alerts
    AlertType.db_exceptions,
    # Report alerts
    AlertType.daily_reports,
    # Deployment alerts
    AlertType.cooldown_deployment,
    AlertType.new_model_added,
    # Outage alerts
    AlertType.outage_alerts,
    AlertType.region_outage_alerts,
    # Fallback alerts
    AlertType.fallback_reports,
    # Management Events (Virtual Keys / Teams / Internal Users)
    AlertType.new_virtual_key_created,
    AlertType.virtual_key_updated,
    AlertType.virtual_key_deleted,
    AlertType.new_team_created,
    AlertType.team_updated,
    AlertType.team_deleted,
    AlertType.new_internal_user_created,
    AlertType.internal_user_updated,
    AlertType.internal_user_deleted,
]


class HangingRequestData(BaseModel):
    request_id: str
    model: str
    api_base: Optional[str] = None
    key_alias: Optional[str] = None
    team_alias: Optional[str] = None
    alerting_metadata: Optional[dict] = None
