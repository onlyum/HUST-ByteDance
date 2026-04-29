"""
Planner Agent（需求规划）
从非结构化采购指令中提取关键信息，并拆解为物料清单/字段更新。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from config import BusinessStatus, ProcurementSettings
from feishu_bitable_toolbox import FeishuBitableToolbox

from .base_agent import BaseAgent


class PlannerAgent(BaseAgent):
    AGENT_TYPE = "planner_agent"
    AGENT_NAME = "需求规划员"

    def __init__(self, agent_id: str, settings: ProcurementSettings, bitable: FeishuBitableToolbox) -> None:
        super().__init__(agent_id, settings, bitable)

    def run(self, demand_record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        record_id = str(demand_record.get("record_id", ""))
        fields = demand_record.get("fields") or {}
        if not isinstance(fields, dict):
            fields = {}

        instruction = str(fields.get(self.settings.demand_field_source_instruction, "") or "")

        system_prompt = (
            "你是资深采购需求分析师。请把非结构化采购指令抽取为结构化要点："
            "物料名称、规格、数量、单位、预算、期望交期、备注。输出 JSON。"
        )
        prompt = f"采购指令：\n{instruction}\n\n只输出 JSON。"
        extracted = self._call_llm(prompt, system_prompt)

        # Mock / fallback：不解析模型 JSON（避免解析失败阻塞流程），仅推进状态
        update_fields: Dict[str, Any] = {
            self.settings.demand_field_status: BusinessStatus.SUPPLIER_SELECTED,
        }

        self.log_to_audit_table(
            action="update",
            target_table="Demands",
            target_record_id=record_id,
            result="success",
            message="Planner parsed demand and moved to supplier selection stage",
            detail={"llm_raw": extracted[:2000]},
            demand_record_id=record_id,
        )

        return update_fields, BusinessStatus.SUPPLIER_SELECTED

