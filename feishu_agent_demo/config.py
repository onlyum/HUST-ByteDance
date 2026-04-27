"""
配置加载模块。

本文件专门负责：
1. 从 .env 文件读取环境变量；
2. 对关键配置做基础校验；
3. 将零散的环境变量整理为一个结构化的 Settings 对象。

这样做的好处是：
1. 主程序不用到处写 os.getenv()；
2. 飞书密钥、表格 token 等敏感配置不会被硬编码到业务代码里；
3. 如果后续要扩展配置项，只需要改这里即可。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# 以当前文件所在目录作为项目根目录，便于稳定地定位 .env 文件。
BASE_DIR = Path(__file__).resolve().parent

# 显式加载项目目录下的 .env 文件。
# 如果 .env 不存在，load_dotenv 不会报错，但后续缺失变量时我们会主动抛异常。
load_dotenv(BASE_DIR / ".env")


def _get_required_env(name: str) -> str:
    """
    读取一个必填环境变量。

    如果变量为空，立刻抛出带中文提示的异常，方便使用者快速定位配置问题。
    """
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(
            f"缺少必填环境变量：{name}。"
            f"请先参考 .env.example 创建 .env，并填写正确的配置。"
        )
    return value


def _get_int_env(name: str, default: int) -> int:
    """
    读取整数类型环境变量。

    例如轮询间隔、请求超时时间这类配置，适合统一从这里解析。
    """
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是整数，当前值为：{raw_value}") from exc


def _get_bool_env(name: str, default: bool) -> bool:
    """
    读取布尔类型环境变量。

    支持常见写法：true/false、1/0、yes/no、y/n。
    """
    raw_value = os.getenv(name, "").strip().lower()
    if not raw_value:
        return default

    if raw_value in {"1", "true", "yes", "y", "on"}:
        return True
    if raw_value in {"0", "false", "no", "n", "off"}:
        return False

    raise ValueError(f"环境变量 {name} 必须是布尔值，当前值为：{raw_value}")


@dataclass(frozen=True)
class Settings:
    """
    项目运行配置对象。

    frozen=True 表示创建后不可修改，能减少运行时被误改配置的风险。
    """

    # 飞书开放平台应用凭证
    feishu_app_id: str
    feishu_app_secret: str

    # 多维表格定位信息
    bitable_app_token: str
    task_table_id: str  # 选题任务表ID
    content_table_id: str  # 内容数据表ID

    # 轮询配置
    poll_interval_seconds: int

    # 任务表字段配置
    task_field_task_id: str
    task_field_title: str
    task_field_requirement: str
    task_field_content_type: str
    task_field_priority: str
    task_field_status: str
    task_field_creator_agent: str
    task_field_auditor_agent: str
    task_field_publisher_agent: str
    task_field_created_at: str
    task_field_deadline: str
    task_field_final_score: str

    # 内容表字段配置
    content_field_content_id: str
    content_field_task_id: str
    content_field_writer_agent: str
    content_field_content_text: str
    content_field_audit_result: str
    content_field_audit_comment: str
    content_field_audit_time: str
    content_field_publish_url: str
    content_field_publish_time: str
    content_field_view_count: str
    content_field_quality_score: str

    # 业务状态配置
    task_status_pending_assign: str
    task_status_pending_write: str
    task_status_pending_audit: str
    task_status_pending_publish: str
    task_status_completed: str
    task_status_rejected: str

    # 审核结果配置
    audit_result_pass: str
    audit_result_reject: str
    audit_result_modify_pass: str

    # 大模型配置
    use_mock_llm: bool
    llm_api_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: int


def load_settings() -> Settings:
    """
    统一加载并返回项目配置。

    主程序只需要调用一次这个函数，就能拿到完整的运行参数。
    """
    return Settings(
        feishu_app_id=_get_required_env("FEISHU_APP_ID"),
        feishu_app_secret=_get_required_env("FEISHU_APP_SECRET"),
        bitable_app_token=_get_required_env("BITABLE_APP_TOKEN"),
        task_table_id=_get_required_env("TASK_TABLE_ID"),
        content_table_id=_get_required_env("CONTENT_TABLE_ID"),
        poll_interval_seconds=_get_int_env("POLL_INTERVAL_SECONDS", default=10),
        
        # 任务表字段配置
        task_field_task_id=os.getenv("TASK_FIELD_TASK_ID", "task_id").strip() or "task_id",
        task_field_title=os.getenv("TASK_FIELD_TITLE", "task_title").strip() or "task_title",
        task_field_requirement=os.getenv("TASK_FIELD_REQUIREMENT", "task_requirement").strip() or "task_requirement",
        task_field_content_type=os.getenv("TASK_FIELD_CONTENT_TYPE", "content_type").strip() or "content_type",
        task_field_priority=os.getenv("TASK_FIELD_PRIORITY", "priority").strip() or "priority",
        task_field_status=os.getenv("TASK_FIELD_STATUS", "task_status").strip() or "task_status",
        task_field_creator_agent=os.getenv("TASK_FIELD_CREATOR_AGENT", "creator_agent").strip() or "creator_agent",
        task_field_auditor_agent=os.getenv("TASK_FIELD_AUDITOR_AGENT", "auditor_agent").strip() or "auditor_agent",
        task_field_publisher_agent=os.getenv("TASK_FIELD_PUBLISHER_AGENT", "publisher_agent").strip() or "publisher_agent",
        task_field_created_at=os.getenv("TASK_FIELD_CREATED_AT", "created_at").strip() or "created_at",
        task_field_deadline=os.getenv("TASK_FIELD_DEADLINE", "deadline").strip() or "deadline",
        task_field_final_score=os.getenv("TASK_FIELD_FINAL_SCORE", "final_score").strip() or "final_score",
        
        # 内容表字段配置
        content_field_content_id=os.getenv("CONTENT_FIELD_CONTENT_ID", "content_id").strip() or "content_id",
        content_field_task_id=os.getenv("CONTENT_FIELD_TASK_ID", "task_id").strip() or "task_id",
        content_field_writer_agent=os.getenv("CONTENT_FIELD_WRITER_AGENT", "writer_agent").strip() or "writer_agent",
        content_field_content_text=os.getenv("CONTENT_FIELD_CONTENT_TEXT", "content_text").strip() or "content_text",
        content_field_audit_result=os.getenv("CONTENT_FIELD_AUDIT_RESULT", "audit_result").strip() or "audit_result",
        content_field_audit_comment=os.getenv("CONTENT_FIELD_AUDIT_COMMENT", "audit_comment").strip() or "audit_comment",
        content_field_audit_time=os.getenv("CONTENT_FIELD_AUDIT_TIME", "audit_time").strip() or "audit_time",
        content_field_publish_url=os.getenv("CONTENT_FIELD_PUBLISH_URL", "publish_url").strip() or "publish_url",
        content_field_publish_time=os.getenv("CONTENT_FIELD_PUBLISH_TIME", "publish_time").strip() or "publish_time",
        content_field_view_count=os.getenv("CONTENT_FIELD_VIEW_COUNT", "view_count").strip() or "view_count",
        content_field_quality_score=os.getenv("CONTENT_FIELD_QUALITY_SCORE", "quality_score").strip() or "quality_score",
        
        # 业务状态配置
        task_status_pending_assign=os.getenv("TASK_STATUS_PENDING_ASSIGN", "待分配").strip() or "待分配",
        task_status_pending_write=os.getenv("TASK_STATUS_PENDING_WRITE", "待创作").strip() or "待创作",
        task_status_pending_audit=os.getenv("TASK_STATUS_PENDING_AUDIT", "待审核").strip() or "待审核",
        task_status_pending_publish=os.getenv("TASK_STATUS_PENDING_PUBLISH", "待发布").strip() or "待发布",
        task_status_completed=os.getenv("TASK_STATUS_COMPLETED", "已完成").strip() or "已完成",
        task_status_rejected=os.getenv("TASK_STATUS_REJECTED", "已驳回").strip() or "已驳回",
        
        # 审核结果配置
        audit_result_pass=os.getenv("AUDIT_RESULT_PASS", "通过").strip() or "通过",
        audit_result_reject=os.getenv("AUDIT_RESULT_REJECT", "驳回").strip() or "驳回",
        audit_result_modify_pass=os.getenv("AUDIT_RESULT_MODIFY_PASS", "修改后通过").strip() or "修改后通过",
        
        use_mock_llm=_get_bool_env("USE_MOCK_LLM", default=True),
        llm_api_url=os.getenv("LLM_API_URL", "").strip(),
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        llm_model=os.getenv("LLM_MODEL", "mock-model").strip() or "mock-model",
        llm_timeout_seconds=_get_int_env("LLM_TIMEOUT_SECONDS", default=30),
    )
