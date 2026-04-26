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
    table_id: str

    # 轮询与字段配置
    poll_interval_seconds: int
    title_field_name: str
    status_field_name: str
    output_field_name: str

    # 业务状态配置
    pending_status: str
    processing_status: str
    review_status: str
    failed_status: str

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
        table_id=_get_required_env("TABLE_ID"),
        poll_interval_seconds=_get_int_env("POLL_INTERVAL_SECONDS", default=10),
        title_field_name=os.getenv("TITLE_FIELD_NAME", "任务标题").strip() or "任务标题",
        status_field_name=os.getenv("STATUS_FIELD_NAME", "状态").strip() or "状态",
        output_field_name=os.getenv("OUTPUT_FIELD_NAME", "输出结果").strip() or "输出结果",
        pending_status=os.getenv("PENDING_STATUS", "待处理").strip() or "待处理",
        processing_status=os.getenv("PROCESSING_STATUS", "处理中").strip() or "处理中",
        review_status=os.getenv("REVIEW_STATUS", "待审核").strip() or "待审核",
        failed_status=os.getenv("FAILED_STATUS", "处理失败").strip() or "处理失败",
        use_mock_llm=_get_bool_env("USE_MOCK_LLM", default=True),
        llm_api_url=os.getenv("LLM_API_URL", "").strip(),
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        llm_model=os.getenv("LLM_MODEL", "mock-model").strip() or "mock-model",
        llm_timeout_seconds=_get_int_env("LLM_TIMEOUT_SECONDS", default=30),
    )
