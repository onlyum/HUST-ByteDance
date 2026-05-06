"""
Agent基类模块（供应链版）
定义所有采购 Agent 的标准接口和通用能力：
- LLM 调用（可 Mock）
- 跨表数据聚合（供应商上下文）
- 统一审计日志落库（强制子类在 Bitable 操作后记录）
"""

import json
import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# tenacity before_sleep 无 self，单独 logger
_llm_retry_logger = logging.getLogger(f"{__name__}.llm_retry")


def _before_llm_http_sleep(retry_state: object) -> None:
    """超时/连接失败后、指数退避等待前打一条日志。"""
    try:
        exc = retry_state.outcome.exception()  # type: ignore[union-attr]
        na = retry_state.next_action  # type: ignore[union-attr]
        sleep_s = float(getattr(na, "sleep", 0) or 0)
    except Exception:
        exc, sleep_s = None, 0.0
    _llm_retry_logger.warning(
        "LLM HTTP 失败，约 %.0fs 后自动重试（tenacity：含首次最多 3 次请求）: %s",
        sleep_s,
        exc,
    )

from config import TABLE_IDS, BusinessStatus, ProcurementSettings
from feishu_bitable_toolbox import FeishuBitableToolbox


class BaseAgent:
    """
    Agent基类，所有业务Agent都必须继承此类
    定义了统一的接口规范和通用能力
    """
    
    # Agent类型标识，子类必须重写
    AGENT_TYPE = "base"
    # Agent名称，子类必须重写
    AGENT_NAME = "基础Agent"
    
    def __init__(self, agent_id: str, settings: ProcurementSettings, bitable: FeishuBitableToolbox):
        """
        初始化Agent
        :param agent_id: Agent唯一标识
        :param settings: 全局配置对象
        """
        self.agent_id = agent_id
        self.settings = settings
        self.bitable = bitable
        self.use_mock = settings.use_mock_llm
        
        # 初始化日志
        self.logger = logging.getLogger(f"{self.AGENT_TYPE}_{agent_id}")
        self.logger.info(f"{self.AGENT_NAME} 初始化完成，ID: {agent_id}")

    def run(self, *args, **kwargs) -> Tuple[Dict[str, Any], str]:
        """
        执行任务的统一入口，子类必须实现
        返回: (处理结果数据, 下一步状态)
        """
        raise NotImplementedError(f"Agent {self.AGENT_NAME} 必须实现run方法")

    # -----------------------
    # Audit log (强制规范入口)
    # -----------------------
    def log_to_audit_table(
        self,
        *,
        action: str,
        target_table: str,
        target_record_id: str,
        result: str,
        message: str,
        detail: Optional[Dict[str, Any]] = None,
        demand_record_id: Optional[str] = None,
        supplier_record_id: Optional[str] = None,
        order_record_id: Optional[str] = None,
    ) -> None:
        """
        统一把 Agent 行为写入 Audit_Logs 表。
        约束：所有子类在完成任何 Bitable 写操作后都应调用本方法。
        """
        fields: Dict[str, Any] = {
            "log_id": f"{self.AGENT_TYPE}-{int(time.time() * 1000)}",
            "timestamp": int(time.time() * 1000),
            "agent_name": self.AGENT_TYPE,
            "action": action,
            "target_table": target_table,
            "target_record_id": target_record_id,
            "result": result,
            "message": message,
            "detail_json": json.dumps(detail or {}, ensure_ascii=False),
        }

        # 可选关联字段（如果你的 Logs 表建了这些 link 字段）
        if demand_record_id:
            fields["demand"] = demand_record_id
        if supplier_record_id:
            fields["supplier"] = supplier_record_id
        if order_record_id:
            fields["order"] = order_record_id

        try:
            self.bitable.add_record(
                app_token=self.settings.bitable_app_token,
                table_id=TABLE_IDS["logs"],
                fields=fields,
                link_fields=[k for k in ("demand", "supplier", "order") if k in fields],
            )
        except Exception as exc:
            # 审计日志不应阻塞主流程
            self.logger.warning(f"写入审计日志失败: {exc}")

    # -----------------------
    # Cross-table aggregation
    # -----------------------
    def get_supplier_context(self, supplier_record_id: str, *, max_orders_scan_pages: int = 5) -> Dict[str, Any]:
        """
        给 Sourcing/Auditor 一键汇总供应商画像：
        - 基础信息：credit_score / main_business / status 等
        - 历史表现：基于 Orders 表的简单聚合（可继续扩展）
        """
        supplier = self.bitable.get_record(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["suppliers"],
            record_id=supplier_record_id,
        )
        supplier_fields = supplier.get("fields") if isinstance(supplier, dict) else {}
        if not isinstance(supplier_fields, dict):
            supplier_fields = {}

        # 历史表现（扫描 Orders，按 supplier link 匹配）
        total_orders = 0
        abnormal_orders = 0
        for rec in self.bitable.iter_records(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["orders"],
            fields=["supplier", "logistics_status"],
            max_pages=max_orders_scan_pages,
        ):
            f = rec.get("fields") or {}
            if not isinstance(f, dict):
                continue
            supplier_link = f.get("supplier")
            linked_ids: Iterable[str] = []
            if isinstance(supplier_link, list):
                linked_ids = [x.get("record_id") for x in supplier_link if isinstance(x, dict) and isinstance(x.get("record_id"), str)]
            if supplier_record_id not in set(linked_ids):
                continue

            total_orders += 1
            if f.get("logistics_status") == "异常":
                abnormal_orders += 1

        return {
            "supplier_record_id": supplier_record_id,
            "credit_score": supplier_fields.get("credit_score"),
            "main_business": supplier_fields.get("main_business"),
            "status": supplier_fields.get("status"),
            "history": {
                "total_orders": total_orders,
                "abnormal_orders": abnormal_orders,
                "abnormal_rate": (abnormal_orders / total_orders) if total_orders else 0.0,
            },
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(
            (
                requests.exceptions.ConnectTimeout,
                requests.exceptions.ReadTimeout,
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            )
        ),
        before_sleep=_before_llm_http_sleep,
        reraise=True,
    )
    def _llm_http_post_json(self, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
        """HTTP 调用；连接超时 + 读超时；超时/连接错误由 tenacity 重试。"""
        timeout = (self.settings.llm_connect_timeout_seconds, self.settings.llm_timeout_seconds)
        self.logger.info(
            "LLM HTTP: 发起 POST（connect=%ss read=%ss）%s",
            timeout[0],
            timeout[1],
            f" → {self.settings.llm_api_url[:56]}…" if len(self.settings.llm_api_url) > 56 else f" → {self.settings.llm_api_url}",
        )
        response = requests.post(
            self.settings.llm_api_url,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("LLM response is not a JSON object")
        return body

    def _call_llm(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        *,
        http_fail_use_mock: bool = True,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        response_format_json_object: bool = False,
    ) -> str:
        """
        统一调用大模型接口。
        :param http_fail_use_mock: 为 False 时，重试后仍失败则抛出异常，由业务层降级。
        """
        if self.use_mock:
            return self._mock_llm_response(prompt)

        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": 0.7 if temperature is None else float(temperature),
            "max_tokens": 2000 if max_tokens is None else int(max_tokens),
        }
        if response_format_json_object and getattr(self.settings, "llm_json_mode", False):
            payload["response_format"] = {"type": "json_object"}

        try:
            self.logger.info(
                "开始调用大模型，prompt长度: %s（读超时 %ss；连接/读超时类错误自动重试：共最多 3 次请求，即失败后最多再试 2 次）",
                len(prompt),
                self.settings.llm_timeout_seconds,
            )
            start_time = time.time()
            result = self._llm_http_post_json(headers, payload)
            choices = result.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ValueError("LLM response missing choices")
            msg0 = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = msg0.get("content") if isinstance(msg0, dict) else None
            if not isinstance(content, str):
                content = str(content or "")
            elapsed = time.time() - start_time
            self.logger.info("大模型调用完成，耗时: %.2fs", elapsed)
            return content.strip()
        except Exception as e:
            self.logger.error("调用大模型失败：%s", e)
            if http_fail_use_mock:
                return self._mock_llm_response(prompt)
            raise

    def _mock_llm_response(self, prompt: str) -> str:
        """
        Mock大模型响应，用于演示流程和降级处理
        """
        time.sleep(1)  # 模拟模型调用耗时
        mock_response = f"[{self.AGENT_NAME} Mock响应] 已处理请求：{prompt[:50]}..."
        self.logger.debug(f"返回Mock响应: {mock_response}")
        return mock_response
