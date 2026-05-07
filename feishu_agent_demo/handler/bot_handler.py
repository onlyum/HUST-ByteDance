from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.planner_agent import PlannerAgent
from agents.sourcing_auditor import SourcingAuditorAgent
from config import BusinessStatus, TABLE_IDS, load_settings
from feishu_bitable_toolbox import FeishuBitableToolbox


logger = logging.getLogger(__name__)


class BotHandler:
    """处理 IM 消息并驱动 Planner 入库。"""

    def __init__(self, toolbox: FeishuBitableToolbox) -> None:
        self.settings = load_settings()
        self.planner = PlannerAgent("planner-im-1", self.settings, toolbox)
        self.auditor = SourcingAuditorAgent("auditor-im-1", self.settings, toolbox)

    def _extract_text(self, content: str) -> str:
        """
        飞书 IM message.content 是 JSON 字符串，文本一般在 text 字段。
        """
        raw = str(content or "").strip()
        if not raw:
            return ""
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                text = payload.get("text")
                if isinstance(text, str):
                    return text.strip()
        except Exception:
            pass
        return raw

    def _classify_intent(self, user_text: str) -> str:
        """
        LLM 路由：只输出 A/B/C
        A=采购申请，B=信息查询，C=闲聊
        """
        text = str(user_text or "").strip()
        if not text:
            return "C"

        system_prompt = (
            "你是意图路由器，只输出一个字母 A/B/C。\n"
            "A：用户**明确在提交采购/物料需求**（要买什么、数量预算交期、请帮忙下单等）。\n"
            "B：用户要**查库**（查供应商、订单、日志、统计、列出记录等）。\n"
            "C：**其余全部**归为 C——包括闲聊、常识、翻译、写短文/邮件、"
            "**写代码/脚本**、数学计算、与采购无关的技术问题等；不要只因「和采购无关」就强行归 A。\n"
            "仅输出 A 或 B 或 C，不要解释。"
        )
        prompt = f'用户说："{text}"\n只返回 A/B/C。'
        raw = self.planner._call_llm(prompt, system_prompt).strip()
        normalized = raw.replace('"', "").replace("'", "").strip().upper()
        if normalized in {"A", "B", "C"}:
            return normalized

        # 兜底：关键词规则（宁 C 勿错 A，避免把写代码/闲聊误判成采购申请）
        tech_general = ("python", "脚本", "代码", "编程", "函数", "import ", "def ", "javascript", "java", "sql")
        tl = text.lower()
        if any(k in text for k in ("写一段", "写一个", "生成代码", "示例代码")) or any(
            k in tl for k in tech_general
        ):
            return "C"
        command_keywords = ("查询", "列出", "查看", "统计", "订单", "供应商", "日志")
        if any(k in text for k in command_keywords):
            return "B"
        procurement_keywords = ("采购", "买", "下单", "预算", "交期", "供应商", "数量", "物料", "询价", "招标")
        if any(k in text for k in procurement_keywords):
            return "A"
        return "C"

    def _extract_query(self, user_text: str) -> Dict[str, Any]:
        """
        对 B 类查询抽取结构化参数。
        """
        system_prompt = (
            "你是查询参数提取器。"
            "把用户查询抽取成 JSON："
            '{"target":"suppliers|orders|logs","keyword":"","limit":3}。'
            "仅输出 JSON。"
        )
        prompt = f"用户查询：{user_text}"
        raw = self.planner._call_llm(prompt, system_prompt).strip()
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                target = str(data.get("target", "suppliers")).strip().lower()
                if target not in {"suppliers", "orders", "logs"}:
                    target = "suppliers"
                keyword = str(data.get("keyword", "") or "").strip()
                try:
                    limit = int(data.get("limit", 3))
                except Exception:
                    limit = 3
                return {"target": target, "keyword": keyword, "limit": max(1, min(limit, 5))}
        except Exception:
            pass
        return {"target": "suppliers", "keyword": "", "limit": 3}

    def _query_records(self, *, target: str, keyword: str, limit: int) -> List[Dict[str, Any]]:
        table_id = TABLE_IDS[target]
        rows: List[Dict[str, Any]] = []
        for rec in self.planner.bitable.iter_records(
            app_token=self.settings.bitable_app_token,
            table_id=table_id,
            max_pages=3,
        ):
            rows.append(rec)
            if len(rows) >= 30:
                break

        if keyword:
            k = keyword.lower()
            rows = [r for r in rows if k in json.dumps(r.get("fields", {}), ensure_ascii=False).lower()]
        return rows[:limit]

    def _build_query_card(self, target: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        title_map = {"suppliers": "供应商查询结果", "orders": "订单查询结果", "logs": "日志查询结果"}
        lines: List[str] = []

        def _fmt_ts(value: Any) -> str:
            try:
                ts = int(value)
                if ts > 10_000_000_000:
                    ts = ts // 1000
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            except Exception:
                return str(value)

        def _pick(fields: Dict[str, Any], *keys: str) -> str:
            for key in keys:
                v = fields.get(key)
                if v not in (None, "", [], {}):
                    return str(v)
            return "-"

        if not records:
            lines = ["未查询到匹配记录。"]
        else:
            for idx, rec in enumerate(records, start=1):
                fields = rec.get("fields") or {}
                if not isinstance(fields, dict):
                    fields = {}

                if target == "suppliers":
                    name = _pick(fields, "contact_name", "name", "supplier_name")
                    phone = _pick(fields, "contact_phone", "phone", "mobile")
                    email = _pick(fields, "contact_email", "email")
                    status = _pick(fields, "status")
                    created = fields.get("created_at")
                    created_text = _fmt_ts(created) if created not in (None, "") else "-"
                    lines.append(
                        f"**{idx}. {name}**\n"
                        f"电话：`{phone}` ｜ 邮箱：`{email}`\n"
                        f"状态：{status} ｜ 创建时间：{created_text}"
                    )
                    continue

                if target == "orders":
                    order_no = _pick(fields, "order_id", "order_no", "id")
                    logistics = _pick(fields, "logistics_status", "status")
                    supplier = _pick(fields, "supplier_name", "supplier")
                    demand = _pick(fields, "demand_name", "demand")
                    lines.append(
                        f"**{idx}. 订单 {order_no}**\n"
                        f"物流状态：{logistics}\n"
                        f"供应商：{supplier} ｜ 关联需求：{demand}"
                    )
                    continue

                # logs or fallback
                action = _pick(fields, "action")
                result = _pick(fields, "result", "status")
                message = _pick(fields, "message")
                ts = fields.get("timestamp")
                ts_text = _fmt_ts(ts) if ts not in (None, "") else "-"
                lines.append(
                    f"**{idx}. {action}**\n"
                    f"结果：{result} ｜ 时间：{ts_text}\n"
                    f"说明：{message}"
                )

        card = {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title_map.get(target, "查询结果")}},
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}],
        }
        return card

    def _resolve_demand_ref_to_record_id(self, ref: str) -> str:
        """
        将用户输入的需求标识解析为 Demands 表记录 ID（内部使用）。
        - 以 recv 开头：飞书多维表格记录 ID。
        - 否则：按 demand_code（如 DEM-20260426-01）精确匹配。
        """
        key = (ref or "").strip()
        if not key:
            raise ValueError("需求标识为空")
        if key.startswith("recv"):
            return key

        code_field = self.settings.demand_field_demand_code
        app_token = self.settings.bitable_app_token
        table_id = TABLE_IDS["demands"]

        safe_filter = '"' not in key and "\\" not in key
        if safe_filter:
            try:
                filter_formula = f'CurrentValue.[{code_field}] = "{key}"'
                for rec in self.planner.bitable.iter_records(
                    app_token=app_token,
                    table_id=table_id,
                    filter_formula=filter_formula,
                    fields=[code_field],
                    max_pages=3,
                ):
                    rid = rec.get("record_id")
                    if isinstance(rid, str) and rid.startswith("recv"):
                        return rid
            except Exception as exc:
                logger.warning("按 %s 过滤查询需求失败，改为全表扫描: %s", code_field, exc)

        for rec in self.planner.bitable.iter_records(
            app_token=app_token,
            table_id=table_id,
            fields=[code_field],
            max_pages=25,
        ):
            fields = rec.get("fields") if isinstance(rec.get("fields"), dict) else {}
            if str(fields.get(code_field, "") or "").strip() != key:
                continue
            rid = rec.get("record_id")
            if isinstance(rid, str) and rid.startswith("recv"):
                return rid

        raise ValueError(f'未找到编号为「{key}」的采购需求，请核对单号后重试。')

    def _im_delivery_kwargs(self, im_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """飞书会话 chat_id：群聊为群 ID，单聊为二人会话 ID；用于审批卡片与机器人回复同源投递。"""
        chat = str((im_context or {}).get("chat_id") or "").strip()
        if chat:
            return {"im_receive_id": chat, "im_receive_id_type": "chat_id"}
        return {}

    def _procurement_intent_reply(self, result: Dict[str, Any]) -> str:
        """采购申请（意图 A）成功后的 IM 正文：业务列表摘要 + 流程说明，避免底层实现术语。"""
        dcode = str(result.get("demand_code") or "").strip()
        parsed_raw = result.get("parsed")
        parsed: Dict[str, Any] = parsed_raw if isinstance(parsed_raw, dict) else {}
        instruction = str(result.get("source_instruction") or "").strip()

        item = str(parsed.get("item_name") or "").strip()
        spec = str(parsed.get("spec") or "").strip()
        qty_val = parsed.get("quantity")
        uom = str(parsed.get("uom_resolved") or parsed.get("unit") or "").strip()
        budget_val = parsed.get("budget_amount")
        cur = str(parsed.get("currency_resolved") or parsed.get("currency") or "").strip() or "CNY"
        remark = str(parsed.get("remark") or "").strip()
        purpose = remark if remark else instruction
        if len(purpose) > 300:
            purpose = purpose[:300].rstrip() + "…"

        if not item:
            item = "（已保存原文，随流程继续整理）"
        mat = f"• **物料**：{item}"
        if spec:
            mat += f"（规格：{spec}）"

        if qty_val not in (None, ""):
            if isinstance(qty_val, float) and qty_val.is_integer():
                qstr = str(int(qty_val))
            elif isinstance(qty_val, int):
                qstr = str(qty_val)
            else:
                qstr = str(qty_val)
            qty_line = f"• **数量**：{qstr}" + (f" {uom}" if uom else "")
        else:
            qty_line = "• **数量**：待补充（以您发来的说明为准）"

        if budget_val not in (None, ""):
            if isinstance(budget_val, float) and budget_val.is_integer():
                bstr = str(int(budget_val))
            elif isinstance(budget_val, int):
                bstr = str(budget_val)
            else:
                bstr = str(budget_val)
            budget_line = f"• **预算**：{bstr} {cur}"
        else:
            budget_line = "• **预算**：待补充（以您发来的说明为准）"

        purpose_line = f"• **用途 / 说明**：{purpose if purpose else '见本次对话原文。'}"

        header = f"单号 **{dcode}**" if dcode else "需求已登记"
        summary = "\n".join([mat, qty_line, budget_line, purpose_line])

        qcdsr_flow = (
            "接下来系统将自动排队处理本单，**AI 审计官** 将基于 **QCDSR** 对候选供应商做 **比价与博弈分析**；"
            "完成后会按配置推送审批卡片，**您无需再发「触发审批」**。"
        )
        if dcode:
            manual_flow = (
                f"接下来请在流程就绪后发送一行 **`触发审批 {dcode}`**（或直接发 **`{dcode}`**），"
                "以启动 **AI 审计官** 的 **QCDSR 比价博弈** 与后续审批。"
            )
        else:
            manual_flow = (
                "接下来请在流程就绪后发送 **触发审批** 并附上 **本单需求编号**，"
                "以启动 **AI 审计官** 的 **QCDSR 比价博弈** 与后续审批。"
            )

        next_step = qcdsr_flow if self.settings.auto_run_audit_debate else manual_flow

        return (
            f"{header}\n\n"
            "已为您登记本次采购申请，关键信息如下，请核对：\n"
            f"{summary}\n\n"
            f"{next_step}"
        )

    def handle_message(self, message_content: str, im_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        user_text = self._extract_text(message_content)
        if not user_text:
            return {"reply": "收到空消息，未创建需求。"}

        # 指令：触发审批/审批 + 需求编号；也支持整行仅 DEM-xxx 或 recv…（内部解析）
        stripped = user_text.strip()
        ref: str | None = None
        for prefix in ("触发审批", "审批"):
            if stripped.startswith(prefix):
                ref = stripped[len(prefix) :].strip()
                break
        if ref is None:
            if re.fullmatch(r"(?i)DEM-[A-Z0-9_-]+", stripped):
                ref = stripped
            elif re.fullmatch(r"recv[a-zA-Z0-9]+", stripped) and len(stripped) >= 12:
                ref = stripped

        if ref is not None:
            if not ref:
                return {
                    "reply": (
                        "请提供本单 **需求编号**，例如：\n"
                        "• `触发审批 DEM-20260426-01`\n"
                        "• 或直接发送一行 `DEM-20260426-01`"
                    )
                }
            try:
                record_id = self._resolve_demand_ref_to_record_id(ref)
                demand_rec = self.planner.bitable.get_record(
                    app_token=self.settings.bitable_app_token,
                    table_id=TABLE_IDS["demands"],
                    record_id=record_id,
                )
                fld = demand_rec.get("fields") if isinstance(demand_rec, dict) else {}
                if not isinstance(fld, dict):
                    fld = {}
                st = str(fld.get(self.settings.demand_field_status, "") or "").strip()

                resend_statuses = {
                    BusinessStatus.DEMAND_PENDING_APPROVAL,
                    BusinessStatus.DEMAND_PENDING_APPROVAL_SUPERVISOR,
                    BusinessStatus.DEMAND_PENDING_APPROVAL_LOGISTICS,
                    BusinessStatus.DEMAND_PENDING_PURCHASE_CONFIRM,
                    "待下单确认",
                }
                if st in resend_statuses:
                    logger.info(
                        "触发审批: demand=%s 状态=%s，重发当前环节卡片 record_id=%s",
                        ref,
                        st,
                        record_id,
                    )
                    _ok, msg = self.auditor.resend_approval_card(record_id)
                    code = str(fld.get(self.settings.demand_field_demand_code) or "").strip() or ref
                    return {"reply": f"单号 **{code}**：{msg}"}

                logger.info(
                    "触发审批: demand=%s → record_id=%s（辩论在 IM 后台线程执行）",
                    ref,
                    record_id,
                )
                _update_fields, _st, skip_reason = self.auditor.run_audit_debate(
                    record_id, **self._im_delivery_kwargs(im_context)
                )
                code = str(fld.get(self.settings.demand_field_demand_code) or "").strip() or ref
                if skip_reason == "no_candidate_suppliers":
                    return {
                        "reply": (
                            f"单号 **{code}**：当前**没有可用的候选供应商**，AI 审计官无法启动 QCDSR 比价。\n"
                            "请在需求中**关联推荐供应商**，或调整**品类**与供应商表中**主营业务**标签一致后，再发「触发审批」。"
                            "（系统已在需求备注中留下说明。）"
                        )
                    }
                if skip_reason == "debate_aborted_no_supplier":
                    return {
                        "reply": (
                            f"单号 **{code}**：比价流程异常结束，**未能确定供应商**。\n"
                            "请检查候选供应商数据或在表中人工指定推荐后，再试「触发审批」。"
                        )
                    }
                pending_hint = (
                    "主管 → 采购对接 → 运输确认 → 生成订单"
                    if self.settings.multi_stage_approval
                    else "审批通过后将生成订单"
                )
                return {
                    "reply": (
                        f"单号 **{code}** 已受理。\n"
                        "• **AI 审计官** 正在基于 **QCDSR** 对候选供应商做 **比价与博弈分析**；完成后将按配置推送审批卡片。\n"
                        f"• 后续流程：**{pending_hint}**（各环节负责人将收到待办）。"
                    )
                }
            except Exception as exc:
                logger.exception("触发审批失败: %s", exc)
                return {"reply": f"触发审批失败：{exc}"}

        intent = self._classify_intent(user_text)
        logger.info("消息意图分类: %s | text=%s", intent, user_text[:120])

        if intent == "A":
            result = self.planner.parse_and_create(user_text, im_context=im_context)
            dcode = str(result.get("demand_code") or "").strip()
            logger.info("IM需求已入库 record_id=%s demand_code=%s", result.get("record_id"), dcode or "(空)")
            rid = result.get("record_id")
            reply = self._procurement_intent_reply(result)
            return {"reply": reply, "record_id": rid, "demand_code": dcode or None}

        if intent == "B":
            query = self._extract_query(user_text)
            rows = self._query_records(target=query["target"], keyword=query["keyword"], limit=query["limit"])
            target_cn = {"suppliers": "供应商", "orders": "订单", "logs": "运行日志"}
            label = target_cn.get(query["target"], "数据")
            return {
                "reply": f"已按您的条件查询 **{label}**，共 **{len(rows)}** 条，详情见下方卡片。",
                "msg_type": "interactive",
                "content": self._build_query_card(query["target"], rows),
            }

        if intent == "C":
            model_keywords = ("什么模型", "用的什么ai", "用的什么模型", "你现在用的ai")
            if any(k in user_text.lower() for k in model_keywords):
                return {"reply": f"我当前调用的模型是：{self.settings.llm_model}。"}

            system_prompt = (
                "你部署在飞书里的企业助手，**默认熟悉采购**，但应对用户保持友好、专业，**不要拒绝**与采购无关的合理请求。\n"
                "- 用户要写代码/脚本、算题、翻译、常识问答等：正常作答，代码可用 markdown 代码块，保持简洁可运行。\n"
                "- 用户问采购：可说明支持需求录入、供应商协同、订单跟踪、触发审批等。\n"
                "- 禁止再说「只支持采购、不支持 Python」这类生硬拒答；最多在回答末尾用一句话轻量提醒采购能力即可。\n"
                "使用中文为主。"
            )
            prompt = f"用户消息：{user_text}"
            answer = self.planner._call_llm(
                prompt,
                system_prompt,
                max_tokens=min(4096, max(1024, len(user_text) * 2 + 512)),
            ).strip()
            if not answer:
                answer = "我在呢。你可以发采购需求、查供应商/订单，或继续问我别的问题。"
            return {"reply": answer[:8000]}

        return {"reply": "我暂时无法识别你的意图，请尝试描述采购需求或查询对象。"}

