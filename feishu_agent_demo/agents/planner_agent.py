"""
Planner Agent（需求规划）
从非结构化采购指令中提取关键信息，并拆解为物料清单/字段更新。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from config import TABLE_IDS, BusinessStatus, ProcurementSettings
from feishu_bitable_toolbox import FeishuBitableToolbox

from .base_agent import BaseAgent

# 与 script/sqlinit.py 中 Demands 单选选项对齐（用于校验 / 兜底）
_DEMAND_CATEGORY_OPTIONS = ("原材料", "辅料", "包装", "备品备件", "设备", "服务", "其他")
_DEMAND_DEPARTMENT_OPTIONS = ("研发", "生产", "采购", "运营", "财务", "行政", "其他")
_DEMAND_UOM_OPTIONS = ("件", "个", "台", "套", "箱", "kg", "g", "m", "㎡", "L", "其他")
_DEMAND_CURRENCY_OPTIONS = ("CNY", "USD", "EUR", "HKD", "JPY")
_DEMAND_PRIORITY_OPTIONS = ("P0", "P1", "P2", "P3")

# Business_Rules.target_action 中允许写入合并逻辑层的键（空格则用 condition_value 填同一键）
_RULE_MERGE_KEYS = frozenset(
    {
        "requester",
        "department",
        "category",
        "priority",
        "currency",
        "remark",
        "item_name",
        "spec",
    }
)


class PlannerAgent(BaseAgent):
    AGENT_TYPE = "planner_agent"
    AGENT_NAME = "需求规划员"

    def __init__(self, agent_id: str, settings: ProcurementSettings, bitable: FeishuBitableToolbox) -> None:
        super().__init__(agent_id, settings, bitable)

    def _allocate_demand_code(self) -> str:
        prefix = (self.settings.demand_code_prefix or "DEM").strip().strip("-") or "DEM"
        tail = int(time.time() * 1000) % 10000
        return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{tail:04d}"

    @staticmethod
    def _rule_cell_text(val: Any) -> str:
        if val in (None, ""):
            return ""
        if isinstance(val, str):
            return val.strip()
        if isinstance(val, dict):
            t = val.get("text")
            if isinstance(t, str):
                return t.strip()
        return str(val).strip()

    @staticmethod
    def _rule_row_is_active(fields: Dict[str, Any]) -> bool:
        raw = PlannerAgent._rule_cell_text(fields.get("is_active")).lower()
        return raw in ("true", "1", "yes", "是", "on", "active")

    def _load_active_business_rules(self) -> List[Dict[str, Any]]:
        tid = str(TABLE_IDS.get("business_rules") or "").strip()
        if not tid:
            return []
        try:
            rows = self.bitable.get_records(
                app_token=self.settings.bitable_app_token,
                table_id=tid,
                fields=["rule_type", "condition_key", "condition_value", "target_action", "is_active"],
                max_pages=3,
            )
        except Exception as exc:
            self.logger.warning("读取 Business_Rules 失败，跳过规则映射: %s", exc)
            return []
        out: List[Dict[str, Any]] = []
        for rec in rows or []:
            if not isinstance(rec, dict):
                continue
            fld = rec.get("fields")
            if not isinstance(fld, dict):
                continue
            if self._rule_row_is_active(fld):
                out.append(fld)
        return out

    @staticmethod
    def _parse_rule_target_action(ta: str) -> Dict[str, str]:
        actions: Dict[str, str] = {}
        for part in re.split(r"[;\n]+", ta or ""):
            p = part.strip()
            if not p or "=" not in p:
                continue
            k, v = p.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and k in _RULE_MERGE_KEYS:
                actions[k] = v
        return actions

    def _apply_business_rules_to_merged(self, merged: Dict[str, Any], user_text: str) -> None:
        """
        TABLE_ID_BUSINESS_RULES 已配置且 is_active=true 时：
        - condition_key 为 always / 空 / *：视为全量匹配，只填补 merged 中空字段；
        - when_text_contains / contains / 包含：user_text 含 condition_value 时应用 target_action。
        target_action 示例：requester=李四;department=生产
        """
        rules = self._load_active_business_rules()
        if not rules:
            return
        ut = user_text or ""
        for fld in rules:
            ck = self._rule_cell_text(fld.get("condition_key")).lower()
            cv = self._rule_cell_text(fld.get("condition_value"))
            ta = self._rule_cell_text(fld.get("target_action"))
            if not ta:
                continue
            matched = ck in ("always", "全部", "*", "") or ck in ("when_text_contains", "contains", "包含") and bool(cv and cv in ut)
            if not matched and cv and cv in ut:
                matched = True
            if not matched:
                continue
            for key, val in self._parse_rule_target_action(ta).items():
                if merged.get(key) in (None, ""):
                    merged[key] = val

    def _prescreen_budget_before_debate(
        self,
        *,
        instruction: str,
        merged: Dict[str, Any],
        fields: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """
        阶段② 内部预审：按 Business_Rules 校验预算（TABLE_ID_BUSINESS_RULES + is_active=true）。
        - condition_key=max_budget_cny / budget_cap_cny / 预算上限：condition_value 为上限金额（CNY）；
        - target_action 可写 max_budget_cny=50000；
        - when_text_contains：仅当需求原文含子串时套用该条；
        - category_is：condition_value 为品类时仅对该品类生效。
        """
        budget = self._coerce_number(merged.get("budget_amount"))
        if budget is None:
            budget = self._coerce_number(fields.get(self.settings.demand_field_budget_amount))
        if budget is None:
            return True, ""

        rules = self._load_active_business_rules()
        if not rules:
            return True, ""
        ut = instruction or ""
        cat_picked = self._pick_enum(
            str(merged.get("category") or fields.get(self.settings.demand_field_category) or ""),
            _DEMAND_CATEGORY_OPTIONS,
        )

        for fld in rules:
            ck_raw = self._rule_cell_text(fld.get("condition_key"))
            ck = ck_raw.lower()
            cv = self._rule_cell_text(fld.get("condition_value"))
            ta = self._rule_cell_text(fld.get("target_action"))

            if ck in ("when_text_contains", "contains", "包含"):
                if not cv or cv not in ut:
                    continue
            elif ck in ("category_is", "category_equals", "品类"):
                pv = self._pick_enum(cv, _DEMAND_CATEGORY_OPTIONS)
                if not cat_picked or pv != cat_picked:
                    continue
            elif ck in (
                "always",
                "全部",
                "*",
                "",
                "max_budget_cny",
                "budget_cap_cny",
                "global_budget_max",
                "预算上限",
            ):
                pass
            elif "budget" in ck or "预算" in ck_raw:
                pass
            else:
                continue

            cap: Optional[float] = None
            if cv and re.fullmatch(r"[\d.,]+", cv.replace(",", "")):
                try:
                    cap = float(cv.replace(",", ""))
                except ValueError:
                    cap = None
            if cap is None and ta:
                m = re.search(r"(?:max_budget_cny|prescreen_max_budget)\s*=\s*([\d.]+)", ta, re.I)
                if m:
                    cap = float(m.group(1))
            if cap is None:
                continue
            if budget > cap + 1e-6:
                return False, (
                    f"内部预审（Business_Rules）未通过：预算 {budget:g} 元超过上限 {cap:g} 元（{ck_raw or 'rule'}）。"
                )

        return True, ""

    def _apply_im_context_to_merged(self, merged: Dict[str, Any], im_context: Optional[Dict[str, Any]]) -> None:
        """飞书事件里若有发送者展示名，且模型未抽到 requester，则写入 requester。"""
        if not im_context:
            return
        name = str(im_context.get("sender_name") or "").strip()
        if name and merged.get("requester") in (None, ""):
            merged["requester"] = name

    def _reconcile_resolved_fields_after_rules(self, merged: Dict[str, Any]) -> None:
        """规则补字段后，刷新与 Bitable 单选对齐的 *_resolved 字段。"""
        if merged.get("category") not in (None, ""):
            picked = self._pick_enum(str(merged["category"]), _DEMAND_CATEGORY_OPTIONS)
            merged["category"] = picked
        if merged.get("department") not in (None, ""):
            merged["department"] = self._pick_enum(str(merged["department"]), _DEMAND_DEPARTMENT_OPTIONS)
        uom_raw = merged.get("unit")
        if uom_raw not in (None, ""):
            merged["uom_resolved"] = self._pick_enum(str(uom_raw), _DEMAND_UOM_OPTIONS)
        if merged.get("currency") not in (None, ""):
            merged["currency_resolved"] = self._pick_enum(str(merged["currency"]), _DEMAND_CURRENCY_OPTIONS)
        if merged.get("priority") not in (None, ""):
            merged["priority_resolved"] = self._pick_enum(str(merged["priority"]), _DEMAND_PRIORITY_OPTIONS)

    def _try_append_interaction_memory(
        self,
        *,
        user_text: str,
        demand_record_id: str,
        im_context: Optional[Dict[str, Any]],
    ) -> None:
        tid = str(TABLE_IDS.get("interaction_memory") or "").strip()
        if not tid:
            return
        ctx = im_context or {}
        mid = str(ctx.get("message_id") or "").strip() or f"im-{int(time.time() * 1000)}"
        fields: Dict[str, Any] = {
            "message_id": mid[:200],
            "chat_id": str(ctx.get("chat_id") or "")[:200],
            "user_id": str(ctx.get("open_id") or "")[:200],
            "related_record_id": demand_record_id,
            "summary": (user_text or "")[:1800],
            "last_interaction": int(time.time() * 1000),
        }
        try:
            self.bitable.add_record(
                app_token=self.settings.bitable_app_token,
                table_id=tid,
                fields=fields,
            )
            self.logger.info("已写入 Interaction_Memory: demand=%s message_id=%s", demand_record_id, mid[:32])
        except Exception as exc:
            self.logger.warning("写入 Interaction_Memory 失败（请核对表字段名/类型与 sqlinit 一致）: %s", exc)

    @staticmethod
    def _pick_enum(raw: str, options: Tuple[str, ...]) -> Optional[str]:
        s = (raw or "").strip()
        if not s:
            return None
        if s in options:
            return s
        for o in options:
            if o in s or s in o:
                return o
        return None

    @staticmethod
    def _coerce_number(val: Any) -> Optional[float]:
        if val in (None, ""):
            return None
        if isinstance(val, (int, float)):
            return float(val)
        try:
            return float(str(val).strip().replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _harvest_from_cn_text(text: str) -> Dict[str, Any]:
        """
        从中文采购句中做轻量抽取（不依赖 LLM，补 Mock/模型漏抽）。
        """
        out: Dict[str, Any] = {}
        t = (text or "").strip()
        if not t:
            return out

        m = re.search(r"品类[是为：:\s]*([\u4e00-\u9fff]{2,8})", t)
        if m:
            out["category"] = m.group(1).strip()

        m = re.search(r"部门[是为：:\s]*([\u4e00-\u9fff]{2,4})", t)
        if m:
            out["department"] = m.group(1).strip()

        m = re.search(r"规格[是为：:\s]*([^，,。\n]+?)(?=，|,|数量|总预算|预算|$)", t)
        if m:
            out["spec"] = m.group(1).strip()

        m = re.search(r"数量[是为：:\s]*(\d+(?:\.\d+)?)\s*([个件套台箱]+)?", t)
        if m:
            q = m.group(1)
            out["quantity"] = float(q) if "." in q else int(q)
            if m.group(2):
                u = m.group(2).strip()
                if u:
                    out["unit"] = u

        m = re.search(r"(?:总)?预算[是为：:\s]*(\d+(?:\.\d+)?)\s*元?", t)
        if m:
            b = m.group(1)
            out["budget_amount"] = float(b) if "." in b else int(b)

        m = re.search(r"采购\s*([^，,。\n规格数量]{2,40}?)(?=，|,|规格|数量|总预算|预算|$)", t)
        if m:
            name = m.group(1).strip()
            if name and len(name) >= 2:
                out["item_name"] = name

        m = re.search(r"(申请人|提单人|需求人)[是为：:\s]*([\u4e00-\u9fff\w·]{2,16})", t)
        if m:
            out["requester"] = m.group(2).strip()

        m = re.search(r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})", t)
        if m:
            out["expected_delivery"] = m.group(1).replace("年", "-").replace("月", "-").replace("/", "-")

        return out

    def _safe_parse_llm_json(self, llm_raw: str) -> Dict[str, Any]:
        raw = (llm_raw or "").strip()
        if not raw:
            return {}
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            # 尝试截取第一个 { ... } 块
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    obj = json.loads(raw[start : end + 1])
                    return obj if isinstance(obj, dict) else {}
                except Exception:
                    pass
        return {}

    def _merge_logical_fields(self, *, user_text: str, llm_raw: str) -> Dict[str, Any]:
        parsed = self._safe_parse_llm_json(llm_raw)
        harvest = self._harvest_from_cn_text(user_text)

        keys = (
            "item_name",
            "spec",
            "quantity",
            "unit",
            "budget_amount",
            "category",
            "department",
            "requester",
            "expected_delivery",
            "remark",
            "currency",
            "priority",
        )
        merged: Dict[str, Any] = {}
        for k in keys:
            pv, hv = parsed.get(k), harvest.get(k)
            v = pv if pv not in (None, "") else hv
            merged[k] = v

        # 品类：禁止把物料名误写入 category（仅接受枚举或可映射到枚举）
        cat_raw = merged.get("category")
        if cat_raw not in (None, ""):
            picked = self._pick_enum(str(cat_raw), _DEMAND_CATEGORY_OPTIONS)
            if picked is None:
                merged["category"] = None
            else:
                merged["category"] = picked
        if merged.get("category") in (None, "") and harvest.get("category"):
            merged["category"] = self._pick_enum(str(harvest["category"]), _DEMAND_CATEGORY_OPTIONS)

        if merged.get("department") not in (None, ""):
            dep = self._pick_enum(str(merged["department"]), _DEMAND_DEPARTMENT_OPTIONS)
            merged["department"] = dep
        if merged.get("department") in (None, "") and harvest.get("department"):
            merged["department"] = self._pick_enum(str(harvest["department"]), _DEMAND_DEPARTMENT_OPTIONS)

        uom_raw = merged.get("unit") or parsed.get("uom")
        if uom_raw not in (None, ""):
            merged["uom_resolved"] = self._pick_enum(str(uom_raw), _DEMAND_UOM_OPTIONS)
        elif harvest.get("unit"):
            merged["uom_resolved"] = self._pick_enum(str(harvest["unit"]), _DEMAND_UOM_OPTIONS)

        if merged.get("currency") not in (None, ""):
            cur = self._pick_enum(str(merged["currency"]), _DEMAND_CURRENCY_OPTIONS)
            merged["currency_resolved"] = cur
        if merged.get("priority") not in (None, ""):
            merged["priority_resolved"] = self._pick_enum(str(merged["priority"]), _DEMAND_PRIORITY_OPTIONS)

        qb = self._coerce_number(merged.get("quantity"))
        if qb is not None:
            merged["quantity"] = qb

        bb = self._coerce_number(merged.get("budget_amount"))
        if bb is not None:
            merged["budget_amount"] = bb

        return merged

    def _logical_to_bitable(self, merged: Dict[str, Any]) -> Dict[str, Any]:
        s = self.settings
        out: Dict[str, Any] = {}

        def put(col: str, val: Any) -> None:
            if val in (None, ""):
                return
            out[col] = val

        put(s.demand_field_item_name, merged.get("item_name"))
        put(s.demand_field_spec, merged.get("spec"))
        put(s.demand_field_quantity, merged.get("quantity"))
        put(s.demand_field_uom, merged.get("uom_resolved"))
        put(s.demand_field_budget_amount, merged.get("budget_amount"))
        put(s.demand_field_category, merged.get("category"))
        put(s.demand_field_department, merged.get("department"))
        put(s.demand_field_requester, merged.get("requester"))

        cur = merged.get("currency_resolved")
        if cur:
            put(s.demand_field_currency, cur)
        elif merged.get("budget_amount") not in (None, ""):
            put(s.demand_field_currency, "CNY")

        pr = merged.get("priority_resolved")
        if pr:
            put(s.demand_field_priority, pr)

        ed = merged.get("expected_delivery")
        if isinstance(ed, str) and re.match(r"^\d{4}-\d{1,2}-\d{1,2}", ed.strip()):
            # 飞书日期字段常为毫秒时间戳；此处保留字符串若 API 不接受再由租户改类型
            put(s.demand_field_need_by_date, ed.strip()[:10])

        rm = merged.get("remark")
        if rm not in (None, ""):
            # 无独立备注列时写入 notes 易覆盖；仅当配置列存在且与 item 不同时再写 — 这里若 notes 非配置项则跳过
            pass

        return out

    def parse_and_create(self, user_text: str, im_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        从 IM 文本中抽取结构化信息，并在 Demands 表创建一条待规划记录。
        im_context：飞书 WS 传入的 message_id / chat_id / open_id / sender_name，用于补 requester 与 Interaction_Memory。
        """
        clean_text = str(user_text or "").strip()
        if not clean_text:
            raise ValueError("用户输入为空，无法创建需求。")

        system_prompt = (
            "你是资深采购需求分析师。把用户采购文本抽取为一个 JSON 对象，键必须包含：\n"
            "item_name（物料名称）, spec（规格型号）, quantity（数字）, unit（单位，须为："
            f"{', '.join(_DEMAND_UOM_OPTIONS)} 之一）,\n"
            "budget_amount（数字，与「元」对应金额）, currency（"
            f"{', '.join(_DEMAND_CURRENCY_OPTIONS)}，可省略）,\n"
            "category（必须是：{cats} 之一，不可填物料名称）,\n"
            "department（必须是：{depts} 之一）,\n"
            "requester（申请人姓名，无则省略）, expected_delivery（期望交期 YYYY-MM-DD，模糊则省略）, remark（备注）。\n"
            "只输出 JSON，不要 Markdown。"
        ).format(cats="、".join(_DEMAND_CATEGORY_OPTIONS), depts="、".join(_DEMAND_DEPARTMENT_OPTIONS))

        prompt = f"用户输入：\n{clean_text}\n\n只输出 JSON。"
        llm_raw = self._call_llm(prompt, system_prompt)

        merged = self._merge_logical_fields(user_text=clean_text, llm_raw=llm_raw)
        self._apply_business_rules_to_merged(merged, clean_text)
        self._apply_im_context_to_merged(merged, im_context)
        self._reconcile_resolved_fields_after_rules(merged)
        extra = self._logical_to_bitable(merged)
        demand_code = self._allocate_demand_code()

        fields: Dict[str, Any] = {
            self.settings.demand_field_source_instruction: clean_text,
            self.settings.demand_field_status: BusinessStatus.DEMAND_PENDING,
            self.settings.demand_field_demand_code: demand_code,
            **extra,
        }

        record_id = self.bitable.add_record(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["demands"],
            fields=fields,
        )

        self._try_append_interaction_memory(
            user_text=clean_text,
            demand_record_id=record_id,
            im_context=im_context,
        )

        self.log_to_audit_table(
            action="create",
            target_table="Demands",
            target_record_id=record_id,
            result="success",
            message="Planner parsed IM text and created a pending demand record",
            detail={"user_text": clean_text, "merged": merged, "llm_raw": llm_raw[:2000]},
            demand_record_id=record_id,
        )

        return {
            "record_id": record_id,
            "status": BusinessStatus.DEMAND_PENDING,
            "demand_code": demand_code,
            "parsed": merged,
            # 供 IM 回复生成「用途/说明」等业务摘要（不落库字段名）
            "source_instruction": clean_text,
        }

    def run(self, demand_record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        record_id = str(demand_record.get("record_id", ""))
        fields = demand_record.get("fields") or {}
        if not isinstance(fields, dict):
            fields = {}

        instruction = str(fields.get(self.settings.demand_field_source_instruction, "") or "")

        system_prompt = (
            "你是资深采购需求分析师。把非结构化采购指令抽取为 JSON，键："
            "item_name, spec, quantity, unit, budget_amount, currency, category, department, "
            "requester, expected_delivery, remark。"
            f"category 只能是：{'、'.join(_DEMAND_CATEGORY_OPTIONS)}；"
            f"department 只能是：{'、'.join(_DEMAND_DEPARTMENT_OPTIONS)}。"
            "只输出 JSON。"
        )
        prompt = f"采购指令：\n{instruction}\n\n只输出 JSON。"
        extracted = self._call_llm(prompt, system_prompt)

        merged = self._merge_logical_fields(user_text=instruction, llm_raw=extracted)
        self._apply_business_rules_to_merged(merged, instruction)
        self._reconcile_resolved_fields_after_rules(merged)
        fill = self._logical_to_bitable(merged)
        existing_code = str(fields.get(self.settings.demand_field_demand_code, "") or "").strip()
        if not existing_code:
            fill[self.settings.demand_field_demand_code] = self._allocate_demand_code()

        prescreen_ok, block_msg = self._prescreen_budget_before_debate(
            instruction=instruction, merged=merged, fields=fields
        )
        if not prescreen_ok:
            prev_notes = str(fields.get("notes") or "")
            line = (block_msg or "预审未通过")[:600]
            merged_notes = (prev_notes + ("\n" if prev_notes else "") + line)[-1000:]
            blocked_update: Dict[str, Any] = {
                self.settings.demand_field_status: BusinessStatus.DEMAND_PENDING,
                **fill,
                "notes": merged_notes,
            }
            self.log_to_audit_table(
                action="update",
                target_table="Demands",
                target_record_id=record_id,
                result="fail",
                message="Planner prescreen blocked (Business_Rules budget)",
                detail={"llm_raw": extracted[:2000], "merged": merged, "reason": block_msg},
                demand_record_id=record_id,
            )
            return blocked_update, BusinessStatus.DEMAND_PENDING

        update_fields: Dict[str, Any] = {
            self.settings.demand_field_status: BusinessStatus.DEMAND_PENDING_DEBATE,
            **fill,
        }

        self.log_to_audit_table(
            action="update",
            target_table="Demands",
            target_record_id=record_id,
            result="success",
            message="Planner parsed demand and moved to pending debate (await run_audit_debate)",
            detail={"llm_raw": extracted[:2000], "merged": merged},
            demand_record_id=record_id,
        )

        return update_fields, BusinessStatus.DEMAND_PENDING_DEBATE
