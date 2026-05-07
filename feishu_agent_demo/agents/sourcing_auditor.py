"""
Sourcing Auditor（选型审计/比价）
对候选供应商做资质审查与比价；run() 在「已选型」时创建订单；
run_audit_debate 完成辩论后仅将需求置为「待审批」并推送飞书卡片，不自动下单。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import lark_oapi as lark

from config import BusinessStatus, ProcurementSettings, TABLE_IDS
from feishu_bitable_toolbox import FeishuBitableToolbox

from .base_agent import BaseAgent


class SourcingAuditorAgent(BaseAgent):
    AGENT_TYPE = "sourcing_auditor"
    AGENT_NAME = "选型审计官"

    # Demands.notes 中展示给业务看的降级说明（须与产品话术一致）
    DEBATE_FALLBACK_AUDIT_NOTE = (
        "由于审计系统繁忙，已通过基础信用算法完成初选，请人工加强复核。"
    )
    # 写入 Demands.notes，避免编排器每 tick 重复发 IM
    NO_CANDIDATE_SUPPLIER_MARKER = "【寻源阻塞-已提示】"
    DEBATE_ABORT_NO_SUPPLIER_MARKER = "【比价异常-已提示】"

    def __init__(self, agent_id: str, settings: ProcurementSettings, bitable: FeishuBitableToolbox) -> None:
        super().__init__(agent_id, settings, bitable)
        self._im_client = (
            lark.Client.builder()
            .app_id(settings.feishu_app_id)
            .app_secret(settings.feishu_app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

    def get_im_chat_id_for_demand(self, demand_record_id: str) -> str:
        """
        从 Interaction_Memory 取该需求最近一次 IM 上下文的 chat_id。
        群聊与单聊在飞书中均有 chat_id，发消息时使用 receive_id_type=chat_id 即可回到同一会话。
        """
        tid = str(TABLE_IDS.get("interaction_memory") or "").strip()
        if not tid or not (demand_record_id or "").strip():
            return ""
        did = demand_record_id.strip()
        best_ts = -1
        best_chat = ""
        for rec in self.bitable.iter_records(
            app_token=self.settings.bitable_app_token,
            table_id=tid,
            fields=["related_record_id", "chat_id", "last_interaction"],
            max_pages=15,
        ):
            fields = rec.get("fields") if isinstance(rec.get("fields"), dict) else {}
            if not isinstance(fields, dict):
                continue
            if str(fields.get("related_record_id") or "").strip() != did:
                continue
            cid = str(fields.get("chat_id") or "").strip()
            if not cid:
                continue
            raw_ts = fields.get("last_interaction")
            ts = 0
            try:
                if isinstance(raw_ts, (int, float)):
                    ts = int(raw_ts)
                elif isinstance(raw_ts, str) and raw_ts.strip().isdigit():
                    ts = int(raw_ts.strip())
            except Exception:
                ts = 0
            if ts >= best_ts:
                best_ts = ts
                best_chat = cid
        return best_chat

    @staticmethod
    def _resolve_session_notify_target(
        im_receive_id: Optional[str],
        im_receive_id_type: Optional[str],
        memory_chat_id: Optional[str],
    ) -> Tuple[str, str]:
        """
        会话内说明类消息（如「无候选供应商」）：优先本条 IM 的会话，其次 Interaction_Memory 中的 chat_id。
        """
        explicit_id = (im_receive_id or "").strip()
        explicit_type = (im_receive_id_type or "").strip().lower()
        if explicit_id and explicit_type in ("chat_id", "open_id"):
            return explicit_id, explicit_type
        mem = (memory_chat_id or "").strip()
        if mem:
            return mem, "chat_id"
        return "", ""

    def _resolve_approval_card_delivery_target(
        self,
        personnel_open_id: str,
        memory_chat_id: Optional[str],
    ) -> Tuple[str, str]:
        """
        审批交互卡片：必须优先发给环节负责人（私聊 open_id）；仅当未配置审批人时，才用会话 chat_id 兜底（避免静默失败）。
        """
        oid = (personnel_open_id or "").strip()
        if oid:
            return oid, "open_id"
        mock = (self.settings.mock_personnel_feishu_open_id or "").strip()
        if mock:
            return mock, "open_id"
        mem = (memory_chat_id or "").strip()
        if mem:
            self.logger.warning(
                "审批人 open_id 未配置，审批卡片发往会话 chat_id（兜底），建议配置 Personnel 或 MOCK_PERSONNEL_FEISHU_OPEN_ID"
            )
            return mem, "chat_id"
        return "", ""

    def _append_demand_note_line(self, demand_record_id: str, line: str, *, max_len: int = 1200) -> None:
        try:
            dem = self.bitable.get_record(
                app_token=self.settings.bitable_app_token,
                table_id=TABLE_IDS["demands"],
                record_id=demand_record_id,
            )
            fld = dem.get("fields") if isinstance(dem, dict) else {}
            if not isinstance(fld, dict):
                fld = {}
            prev = str(fld.get("notes") or "").strip()
            if line in prev:
                return
            merged = (prev + ("\n" if prev else "") + line)[-max_len:]
            self.bitable.update_record(
                app_token=self.settings.bitable_app_token,
                table_id=TABLE_IDS["demands"],
                record_id=demand_record_id,
                fields={"notes": merged},
            )
        except Exception as exc:
            self.logger.warning("写入需求备注失败 demand=%s: %s", demand_record_id, exc)

    def _notify_im_debate_hint(
        self,
        demand_record_id: str,
        text: str,
        *,
        im_receive_id: Optional[str] = None,
        im_receive_id_type: Optional[str] = None,
    ) -> None:
        """在会话（群/单聊）中发一条说明；依赖 chat_id 或 Interaction_Memory。"""
        mem = self.get_im_chat_id_for_demand(demand_record_id)
        recv_id, recv_type = self._resolve_session_notify_target(
            im_receive_id,
            im_receive_id_type,
            mem,
        )
        if not recv_id:
            self.logger.info("无 IM 投递目标，跳过寻源提示 IM: demand=%s", demand_record_id)
            return
        ok = self._send_im_text(receive_id=recv_id, receive_id_type=recv_type, text=text[:3500])
        if ok:
            self.logger.info("已发送寻源/比价提示 IM（%s）", recv_type)

    @staticmethod
    def _single_select_text(val: Any) -> str:
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
    def _multi_select_texts(val: Any) -> List[str]:
        out: List[str] = []
        if val in (None, "", []):
            return out
        if isinstance(val, str):
            s = val.strip()
            return [s] if s else []
        if isinstance(val, list):
            for x in val:
                if isinstance(x, str) and x.strip():
                    out.append(x.strip())
                elif isinstance(x, dict):
                    t = x.get("text")
                    if isinstance(t, str) and t.strip():
                        out.append(t.strip())
            return out
        if isinstance(val, dict):
            t = val.get("text")
            if isinstance(t, str) and t.strip():
                return [t.strip()]
        return out

    @staticmethod
    def _link_field_record_ids(val: Any) -> List[str]:
        """
        解析「读记录」接口返回的关联字段（推荐供应商等）。
        飞书常见形态：{"type":18,"value":[{"record_id":"recv…","text":"…"}]}，而非顶层 list。
        """
        if val is None:
            return []

        if isinstance(val, dict):
            if "value" in val:
                return SourcingAuditorAgent._link_field_record_ids(val.get("value"))
            if isinstance(val.get("link_record_ids"), list):
                return [str(x).strip() for x in val["link_record_ids"] if isinstance(x, str) and str(x).strip()]
            if isinstance(val.get("record_ids"), list):
                return [str(x).strip() for x in val["record_ids"] if isinstance(x, str) and str(x).strip()]
            rid = val.get("record_id")
            if isinstance(rid, str) and rid.strip():
                return [rid.strip()]
            return []

        if isinstance(val, str):
            s = val.strip()
            return [s] if s else []

        if isinstance(val, list):
            out: List[str] = []
            for item in val:
                out.extend(SourcingAuditorAgent._link_field_record_ids(item))
            seen: set[str] = set()
            uniq: List[str] = []
            for x in out:
                if x not in seen:
                    seen.add(x)
                    uniq.append(x)
            return uniq

        return []

    @staticmethod
    def _first_linked_record_id(val: Any) -> str:
        """从 Demands 推荐供应商等多选关联字段中取第一条 record_id。"""
        ids = SourcingAuditorAgent._link_field_record_ids(val)
        return ids[0] if ids else ""

    def _role_is_supervisor_or_approver(self, role_val: Any) -> bool:
        text = self._single_select_text(role_val)
        if not text:
            return False
        return "主管" in text or "approver" in text.lower()

    def _role_is_logistics(self, role_val: Any) -> bool:
        text = self._single_select_text(role_val)
        if not text:
            return False
        tl = text.lower()
        return any(k in text for k in ("物流", "运输", "仓储", "关务")) or "logistics" in tl

    def _role_is_purchaser(self, role_val: Any) -> bool:
        text = self._single_select_text(role_val)
        if not text:
            return False
        tl = text.lower()
        return any(k in text for k in ("采购", "买手", "下单员")) or "purchaser" in tl or "buyer" in tl

    def _managed_matches_category(self, category: str, managed_raw: Any) -> bool:
        tokens = self._multi_select_texts(managed_raw)
        if "全品类" in tokens:
            return True
        cat = (category or "").strip()
        if not cat:
            return True
        if not tokens:
            return False
        for t in tokens:
            if t == cat or cat in t or t in cat:
                return True
        return False

    def _get_personnel_open_id_by_phase(self, category: str, phase: str) -> str:
        """
        按环节从 Personnel 匹配联系人（全品类 / 负责类别与 demand category 匹配）。
        phase: supervisor | purchaser | logistics
        """
        fallback = (self.settings.mock_personnel_feishu_open_id or "").strip()
        personnel_tid = str(TABLE_IDS.get("personnel") or "").strip()
        if not personnel_tid:
            self.logger.warning(
                "TABLE_ID_PERSONNEL 未配置，环节 %s 使用 MOCK_PERSONNEL_FEISHU_OPEN_ID 回退", phase
            )
            return fallback

        try:
            rows = self.bitable.get_records(
                app_token=self.settings.bitable_app_token,
                table_id=personnel_tid,
                fields=["role", "feishu_open_id", "managed_categories", "name"],
                max_pages=20,
            )
        except Exception as exc:
            self.logger.warning("读取 Personnel 表失败，使用 MOCK 回退: %s", exc)
            return fallback

        cat = (category or "").strip()

        def role_ok(role_f: Any) -> bool:
            if phase == "supervisor":
                return self._role_is_supervisor_or_approver(role_f)
            if phase == "logistics":
                return self._role_is_logistics(role_f)
            if phase == "purchaser":
                return self._role_is_purchaser(role_f)
            return self._role_is_supervisor_or_approver(role_f)

        label = {"supervisor": "主管/终审", "purchaser": "采购确认", "logistics": "运输审批"}.get(phase, phase)
        for rec in rows:
            if not isinstance(rec, dict):
                continue
            fields = rec.get("fields")
            if not isinstance(fields, dict):
                continue
            if not role_ok(fields.get("role")):
                continue
            if not self._managed_matches_category(cat, fields.get("managed_categories")):
                continue
            oid = str(fields.get("feishu_open_id") or "").strip()
            if oid:
                self.logger.info(
                    "匹配%s: name=%s open_id=%s category=%s",
                    label,
                    fields.get("name", ""),
                    oid,
                    cat or "(空)",
                )
                return oid

        self.logger.warning(
            "Personnel 中未找到「%s」联系人（category=%s），使用 MOCK_PERSONNEL_FEISHU_OPEN_ID 回退",
            label,
            cat or "(空)",
        )
        return fallback

    def _get_approver_open_id(self, category: str) -> str:
        """主管 / Approver 环节。"""
        return self._get_personnel_open_id_by_phase(category, "supervisor")

    def _build_interactive_approval_card(
        self,
        *,
        demand_record: Dict[str, Any],
        debate_decision: Dict[str, Any],
        phase: str = "legacy",
        liaison_markdown: str = "",
    ) -> Dict[str, Any]:
        demand_id = str(demand_record.get("record_id") or "")
        fields = demand_record.get("fields") if isinstance(demand_record.get("fields"), dict) else {}
        item_name = str(fields.get("item_name", "") or "")
        quantity = str(fields.get("quantity", "") or "")
        budget = str(fields.get(self.settings.demand_field_budget_amount, "") or "")
        supplier_name = str(debate_decision.get("supplier_name", "") or "")
        supplier_id = str(debate_decision.get("record_id", "") or "")
        reason = str(debate_decision.get("final_reason", "") or "")[:600]

        ph = (phase or "legacy").strip()
        if ph == "supervisor":
            title = "① 终审 · 选型与预算授权"
            ok_label, reject_label = "同意，交采购对接", "驳回"
        elif ph == "purchaser":
            title = "② 采购确认 · 供方/需求方对接"
            ok_label, reject_label = "确认对接完成，进入运输审批", "驳回"
        elif ph == "logistics":
            title = "③ 运输审批 · 发运安排"
            ok_label, reject_label = "同意发运并生成订单", "驳回"
        else:
            title = "采购方案待审批"
            ok_label, reject_label = "同意下单", "驳回重选"

        btn_value_base = {
            "action": "approve",
            "demand_id": demand_id,
            "supplier_id": supplier_id,
            "phase": ph,
        }
        btn_reject_base = {
            "action": "reject",
            "demand_id": demand_id,
            "supplier_id": supplier_id,
            "phase": ph,
        }

        elements: List[Dict[str, Any]] = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**物料名称**：{item_name}\n"
                        f"**数量**：{quantity}\n"
                        f"**预算**：{budget}\n"
                        f"**AI 推荐供应商**：{supplier_name}\n"
                    ),
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**寻源/辩论摘要**\n{reason}",
                },
            },
        ]
        if liaison_markdown.strip():
            elements.extend(
                [
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": liaison_markdown.strip()[:3500]},
                    },
                ]
            )
        elements.extend(
            [
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": f"🟢 {ok_label}"},
                            "type": "primary",
                            "value": {**btn_value_base, "action": "approve"},
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": f"🔴 {reject_label}"},
                            "type": "danger",
                            "value": {**btn_reject_base, "action": "reject"},
                        },
                    ],
                },
            ]
        )

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "orange",
                "title": {"tag": "plain_text", "content": f"🔴 {title}"},
            },
            "elements": elements,
        }

    def _liaison_markdown_for_purchaser(self, demand_fields: Dict[str, Any], supplier_record_id: str) -> str:
        """采购环节卡片补充：需求方与推荐供应商对接信息，便于采购对外联络。"""
        s = self.settings
        code = str(demand_fields.get(s.demand_field_demand_code, "") or "").strip()
        req = str(demand_fields.get(s.demand_field_requester, "") or "").strip()
        if isinstance(demand_fields.get(s.demand_field_requester), dict):
            req = str(demand_fields[s.demand_field_requester].get("text") or req)
        dept = str(demand_fields.get(s.demand_field_department, "") or "").strip()
        if isinstance(demand_fields.get(s.demand_field_department), dict):
            dept = str(demand_fields[s.demand_field_department].get("text") or dept)
        src = str(demand_fields.get(s.demand_field_source_instruction, "") or "").strip()[:400]

        lines = [
            "**需求方信息**",
            f"- 需求编号：`{code or '—'}`",
            f"- 申请人：{req or '—'}",
            f"- 部门：{dept or '—'}",
        ]
        if src:
            lines.append(f"- 原始申请摘要：{src}")

        lines.append("")
        lines.append("**推荐供应商对接**（请在 Suppliers 表维护联系人字段）")
        sid = (supplier_record_id or "").strip()
        if not sid:
            lines.append("- （无关联供应商 record_id）")
            return "\n".join(lines)
        try:
            sup = self.bitable.get_record(
                app_token=self.settings.bitable_app_token,
                table_id=TABLE_IDS["suppliers"],
                record_id=sid,
            )
            sf = sup.get("fields") if isinstance(sup, dict) else {}
            if not isinstance(sf, dict):
                sf = {}
            name = str(sf.get("supplier_name", "") or "").strip()
            cn = str(sf.get("contact_name", "") or "").strip()
            phone = str(sf.get("contact_phone", "") or "").strip()
            email = str(sf.get("contact_email", "") or "").strip()
            lines.append(f"- 供应商：{name or sid[:12]}…")
            lines.append(f"- 联系人：{cn or '—'}")
            lines.append(f"- 电话：{phone or '—'}")
            lines.append(f"- 邮箱：{email or '—'}")
        except Exception as exc:
            lines.append(f"- （读取供应商档案失败：{exc}）")
        return "\n".join(lines)

    def _send_interactive_card(
        self,
        *,
        receive_id: str,
        receive_id_type: str,
        card: Dict[str, Any],
    ) -> bool:
        rid = (receive_id or "").strip()
        rtype = (receive_id_type or "").strip().lower()
        if not rid or rtype not in ("open_id", "chat_id"):
            return False
        try:
            req_body = (
                lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(rid)
                .msg_type("interactive")
                .content(json.dumps(card, ensure_ascii=False))
                .build()
            )
            req = (
                lark.im.v1.CreateMessageRequest.builder()
                .receive_id_type(rtype)
                .request_body(req_body)
                .build()
            )
            resp = self._im_client.im.v1.message.create(req)
            if not resp.success():
                raw = getattr(resp, "raw", None)
                self.logger.warning(
                    "审批卡片发送失败: code=%s msg=%s raw=%s（检查机器人 IM 权限、receive_id_type=%s、是否可发 interactive）",
                    resp.code,
                    resp.msg,
                    raw,
                    rtype,
                )
                return False
            return True
        except Exception as exc:
            self.logger.warning("审批卡片 IM 请求异常（不中断主流程）: %s", exc)
            return False

    def _send_im_text(self, *, receive_id: str, receive_id_type: str, text: str) -> bool:
        rid = (receive_id or "").strip()
        rtype = (receive_id_type or "").strip().lower()
        if not rid or rtype not in ("open_id", "chat_id"):
            return False
        try:
            req_body = (
                lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(rid)
                .msg_type("text")
                .content(json.dumps({"text": text[:4000]}, ensure_ascii=False))
                .build()
            )
            req = (
                lark.im.v1.CreateMessageRequest.builder()
                .receive_id_type(rtype)
                .request_body(req_body)
                .build()
            )
            resp = self._im_client.im.v1.message.create(req)
            if not resp.success():
                self.logger.warning(
                    "审批通知文本 IM 失败: code=%s msg=%s raw=%s",
                    resp.code,
                    resp.msg,
                    getattr(resp, "raw", None),
                )
                return False
            return True
        except Exception as exc:
            self.logger.warning("审批通知文本 IM 异常: %s", exc)
            return False

    def _push_approval_card(
        self,
        open_id: str,
        demand_record: Dict[str, Any],
        debate_decision: Dict[str, Any],
        *,
        phase: str = "legacy",
        receive_id: Optional[str] = None,
        receive_id_type: Optional[str] = None,
    ) -> Tuple[bool, bool]:
        """
        推送审批 interactive 卡片；失败则短暂重试，仍失败则发纯文本兜底。
        receive_id / receive_id_type：显式指定则优先（通常为 chat_id 群/单聊会话）；否则使用 open_id（Personnel）。
        返回: (卡片是否成功, 是否至少发出了文本兜底)
        """
        oid = (open_id or "").strip()
        explicit_r = (receive_id or "").strip()
        explicit_t = (receive_id_type or "").strip().lower()
        if explicit_r and explicit_t in ("chat_id", "open_id"):
            target_id, target_type = explicit_r, explicit_t
        elif oid:
            target_id, target_type = oid, "open_id"
        else:
            self.logger.warning("_push_approval_card: 无有效接收方（open_id / receive_id）")
            return False, False

        demand_record_id = str(demand_record.get("record_id") or "")
        supplier_name = str(debate_decision.get("supplier_name", "") or "")
        reason = str(debate_decision.get("final_reason", "") or "").strip()
        chosen_supplier_id = str(debate_decision.get("record_id", "") or "")

        liaison_md = ""
        if (phase or "").strip() == "purchaser":
            df = demand_record.get("fields") if isinstance(demand_record.get("fields"), dict) else {}
            liaison_md = self._liaison_markdown_for_purchaser(df, chosen_supplier_id)

        try:
            card = self._build_interactive_approval_card(
                demand_record=demand_record,
                debate_decision=debate_decision,
                phase=phase,
                liaison_markdown=liaison_md,
            )
        except Exception as exc:
            self.logger.warning("构造审批卡片失败: %s", exc)
            card = None

        if card is not None:
            for attempt in range(3):
                if self._send_interactive_card(
                    receive_id=target_id,
                    receive_id_type=target_type,
                    card=card,
                ):
                    return True, False
                if attempt < 2:
                    time.sleep(1.2)

        fallback = (
            "【采购待审批】交互卡片发送失败（已重试），本条为文本通知。\n"
            "卡片带「同意/驳回」按钮；文本无法在消息内操作，请到多维表格改状态，或修好权限后重发卡片。\n"
            f"需求 record_id：{demand_record_id}\n"
            f"推荐供应商：{supplier_name}（supplier_id={chosen_supplier_id}）\n"
            f"摘要：{reason[:400]}\n"
            "——\n"
            "排查：群/会话是否允许机器人发言；私聊场景审批人是否已与机器人单聊；开放平台 IM 与 interactive 权限。"
        )
        text_ok = self._send_im_text(receive_id=target_id, receive_id_type=target_type, text=fallback)
        if text_ok:
            self.logger.warning(
                "审批卡片未送达会话 %s（%s），已发送文本兜底（demand=%s）",
                target_id[:24],
                target_type,
                demand_record_id,
            )
        return False, text_ok

    def _search_suppliers_by_category(self, category_from_demand: str) -> List[str]:
        """
        按 Suppliers.main_business（多选字段）做包含匹配，返回候选供应商 record_id。
        """
        if not category_from_demand:
            return []

        # 多选字段过滤：contains 逻辑
        filter_query = f'CurrentValue.[main_business].contains("{category_from_demand}")'
        candidate_ids: List[str] = []

        # 先尝试服务端过滤
        for rec in self.bitable.iter_records(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["suppliers"],
            filter_formula=filter_query,
            fields=["main_business", "credit_score", "status"],
            max_pages=5,
        ):
            rid = rec.get("record_id")
            if isinstance(rid, str):
                candidate_ids.append(rid)

        if candidate_ids:
            return candidate_ids

        # 部分租户/版本对 contains 支持不稳定时，降级为本地包含匹配
        for rec in self.bitable.iter_records(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["suppliers"],
            fields=["main_business", "credit_score", "status"],
            max_pages=10,
        ):
            fields = rec.get("fields") or {}
            if not isinstance(fields, dict):
                continue
            mb = fields.get("main_business")
            hit = False
            if isinstance(mb, list):
                for item in mb:
                    if isinstance(item, str) and item == category_from_demand:
                        hit = True
                        break
                    if isinstance(item, dict) and str(item.get("text", "")) == category_from_demand:
                        hit = True
                        break
            elif isinstance(mb, str) and mb == category_from_demand:
                hit = True
            if hit and isinstance(rec.get("record_id"), str):
                candidate_ids.append(rec["record_id"])
        return candidate_ids

    @staticmethod
    def _float_metric(val: Any, default: float = 0.0) -> float:
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def _composite_shortlist_score(self, row: Dict[str, Any]) -> float:
        """
        辩论前预筛选：综合 Q/C/D/S/R（与 credit 轻微 tie-break），不调用 LLM。
        S_composite ≈ w1*Q + w2*C + w3*D + w4*S + w5*R；异常时仍可回退纯信用分（_pick_supplier）。
        """
        q = self._float_metric(row.get("quality_pass_rate"))
        if q > 1.5:
            q = min(max(q / 100.0, 0.0), 1.0)
        else:
            q = min(max(q, 0.0), 1.0)
        c = self._float_metric(row.get("price_index"))
        if c > 10:
            c = min(max(c / 100.0, 0.0), 1.0)
        else:
            c = min(max(c, 0.0), 1.0)
        lt = self._float_metric(row.get("lead_time_days"), default=30.0)
        d = 1.0 / (1.0 + max(lt, 0.0) / 30.0)
        ur = self._float_metric(row.get("user_rating"), default=3.0)
        s = min(max(ur / 5.0, 0.0), 1.0)
        risk = str(row.get("risk_level") or row.get("status") or "").strip().lower()
        if any(x in risk for x in ("低", "优", "合格", "good", "a级")):
            r = 1.0
        elif any(x in risk for x in ("高", "差", "不良", "bad", "d级")):
            r = 0.15
        else:
            r = 0.55
        wq, wc, wd, ws, wr = 0.28, 0.28, 0.14, 0.18, 0.12
        inner = wq * q + wc * c + wd * d + ws * s + wr * r
        credit = self._float_metric(row.get("credit_score"), 0.0)
        return inner + 0.002 * min(max(credit, 0.0), 100.0)

    def _shortlist_supplier_rows(self, rows: List[Dict[str, Any]], top_n: int = 3) -> List[Dict[str, Any]]:
        if len(rows) <= top_n:
            return list(rows)
        scored = [(self._composite_shortlist_score(r), r) for r in rows]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_n]]

    @staticmethod
    def _slim_rows_for_debate_llm(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """只给模型 Q/C/D/S/R + 标识，剔除地址、开户行等（本表未拉取的字段自然不会进入）。"""
        slim: List[Dict[str, Any]] = []
        for r in rows:
            slim.append(
                {
                    "record_id": r.get("record_id"),
                    "supplier_name": str(r.get("supplier_name") or "")[:120],
                    "Q_quality": r.get("quality_pass_rate"),
                    "C_price_index": r.get("price_index"),
                    "D_lead_time_days": r.get("lead_time_days"),
                    "S_user_rating": r.get("user_rating"),
                    "R_risk_or_status": r.get("risk_level", r.get("status")),
                }
            )
        return slim

    @staticmethod
    def _balanced_json_substrings(raw: str) -> List[str]:
        """从左到右扫描每个 '{'，取与之平衡的最短闭区间，供 JSON 提取。"""
        chunks: List[str] = []
        n = len(raw)
        i = 0
        while i < n:
            if raw[i] != "{":
                i += 1
                continue
            depth = 0
            for j in range(i, n):
                if raw[j] == "{":
                    depth += 1
                elif raw[j] == "}":
                    depth -= 1
                    if depth == 0:
                        chunks.append(raw[i : j + 1])
                        i = j + 1
                        break
            else:
                i += 1
        return chunks

    def _pick_supplier(self, supplier_record_ids: List[str]) -> Optional[str]:
        # 简化：按 credit_score 最高选（读取供应商上下文）
        best_id: Optional[str] = None
        best_score: float = float("-inf")
        for sid in supplier_record_ids:
            ctx = self.get_supplier_context(sid)
            score = ctx.get("credit_score")
            try:
                score_f = float(score)
            except Exception:
                score_f = 0.0
            if score_f > best_score:
                best_score = score_f
                best_id = sid
        return best_id

    @staticmethod
    def _parse_debate_llm_json(llm_raw: str) -> Optional[Dict[str, Any]]:
        """从模型原文中提取辩论 JSON（整段 / 围栏 / 贪婪大括号 / 平衡括号扫描）。"""
        raw = (llm_raw or "").strip()
        if not raw:
            return None
        candidates: List[str] = [raw]
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
        if m:
            inner = (m.group(1) or "").strip()
            if inner:
                candidates.append(inner)
        brace = re.search(r"\{[\s\S]*\}", raw)
        if brace:
            candidates.append(brace.group(0).strip())
        for chunk in SourcingAuditorAgent._balanced_json_substrings(raw):
            if chunk not in candidates:
                candidates.append(chunk)

        def _looks_like_debate(obj: Dict[str, Any]) -> bool:
            return "decision" in obj or "debate_logs" in obj

        for c in candidates:
            try:
                obj = json.loads(c)
                if isinstance(obj, dict) and _looks_like_debate(obj):
                    return obj
            except Exception:
                continue
        for c in candidates:
            try:
                obj = json.loads(c)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
        return None

    def _build_fallback_debate(
        self,
        candidate_ids: List[str],
        supplier_rows: List[Dict[str, Any]],
        log_detail: str,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        二级降级：按信用分 _pick_supplier（全量 candidate_ids，不限于 Top3）。
        notes 面向业务使用固定话术；log_detail 写入辩论日志 argument 便于排障。
        """
        chosen_id = self._pick_supplier(candidate_ids) if candidate_ids else None
        if not chosen_id and candidate_ids:
            chosen_id = candidate_ids[0]
        name = ""
        for r in supplier_rows:
            if str(r.get("record_id", "")) == str(chosen_id or ""):
                name = str(r.get("supplier_name", "") or "")
                break
        if not chosen_id:
            return [], {}
        note = self.DEBATE_FALLBACK_AUDIT_NOTE
        arg = (log_detail or note)[:1000]
        debate_logs: List[Dict[str, Any]] = [
            {"agent_name": "系统降级", "stance": "基础选型（信用分）", "argument": arg},
        ]
        decision: Dict[str, Any] = {
            "supplier_name": name,
            "record_id": chosen_id,
            "final_reason": note,
        }
        return debate_logs, decision

    def run(self, demand_record: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        demand_record_id = str(demand_record.get("record_id", ""))
        demand_fields = demand_record.get("fields") or {}
        if not isinstance(demand_fields, dict):
            demand_fields = {}

        # 优先走显式推荐供应商 link（兼容读接口 cell 包装格式）
        candidates_raw = demand_fields.get(self.settings.demand_field_recommended_suppliers)
        candidate_ids = self._link_field_record_ids(candidates_raw)

        # 如果无推荐供应商，则按需求分类去 Suppliers.main_business 做包含匹配
        if not candidate_ids:
            category_from_demand = str(demand_fields.get(self.settings.demand_field_category, "") or "")
            candidate_ids = self._search_suppliers_by_category(category_from_demand)

        chosen_supplier = self._pick_supplier(candidate_ids) if candidate_ids else None
        if not chosen_supplier:
            self.log_to_audit_table(
                action="recommend",
                target_table="Demands",
                target_record_id=demand_record_id,
                result="fail",
                message="No candidate suppliers to audit",
                detail={
                    "candidate_count": len(candidate_ids),
                    "category_from_demand": str(demand_fields.get(self.settings.demand_field_category, "") or ""),
                },
                demand_record_id=demand_record_id,
            )
            return {}, BusinessStatus.SUPPLIER_SELECTED

        # 创建订单（Orders.demand 一对一；Orders.supplier 多对一）
        order_fields: Dict[str, Any] = {
            "order_code": f"PO-{int(time.time())}",
            self.settings.order_field_demand: demand_record_id,
            self.settings.order_field_supplier: chosen_supplier,
            self.settings.order_field_logistics_status: "待发货",
        }
        order_record_id = self.bitable.add_record(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["orders"],
            fields=order_fields,
            link_fields=[self.settings.order_field_demand, self.settings.order_field_supplier],
        )

        self.log_to_audit_table(
            action="order",
            target_table="Orders",
            target_record_id=order_record_id,
            result="success",
            message="Sourcing auditor selected supplier and placed order",
            detail={"chosen_supplier": chosen_supplier, "candidate_ids": candidate_ids},
            demand_record_id=demand_record_id,
            supplier_record_id=chosen_supplier,
            order_record_id=order_record_id,
        )

        # 推进需求状态
        update_fields = {self.settings.demand_field_status: BusinessStatus.ORDER_PLACED}
        return update_fields, BusinessStatus.ORDER_PLACED

    def _demand_debate_snapshot_for_card(
        self, demand_record_id: str
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], str]]:
        """读取需求与推荐供应商，构造卡片用 demand_record + debate_decision；失败返回 None。"""
        demand = self.bitable.get_record(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["demands"],
            record_id=demand_record_id,
        )
        demand_fields = demand.get("fields") if isinstance(demand, dict) else {}
        if not isinstance(demand_fields, dict):
            demand_fields = {}
        candidates_raw = demand_fields.get(self.settings.demand_field_recommended_suppliers)
        chosen_id = self._first_linked_record_id(candidates_raw)
        if not chosen_id:
            return None
        chosen_name = ""
        try:
            sup = self.bitable.get_record(
                app_token=self.settings.bitable_app_token,
                table_id=TABLE_IDS["suppliers"],
                record_id=chosen_id,
            )
            sf = sup.get("fields") if isinstance(sup, dict) else {}
            if isinstance(sf, dict):
                chosen_name = str(sf.get("supplier_name", "") or "").strip()
        except Exception as exc:
            self.logger.warning("读取供应商失败: %s", exc)
        if not chosen_name:
            chosen_name = chosen_id[:16]
        category = str(demand_fields.get(self.settings.demand_field_category, "") or "")
        debate_summary = str(demand_fields.get("notes", "") or "").strip()
        demand_record_for_card: Dict[str, Any] = {"record_id": demand_record_id, "fields": demand_fields}
        debate_decision: Dict[str, Any] = {
            "supplier_name": chosen_name,
            "record_id": chosen_id,
            "final_reason": debate_summary,
        }
        return demand_record_for_card, debate_decision, category

    def push_next_approval_card(self, demand_record_id: str) -> Tuple[bool, bool]:
        """按需求当前 status 向本环节负责人推送卡片（私聊 open_id；上一环节通过后由 WS 调用）。"""
        demand = self.bitable.get_record(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["demands"],
            record_id=demand_record_id,
        )
        demand_fields = demand.get("fields") if isinstance(demand, dict) else {}
        if not isinstance(demand_fields, dict):
            demand_fields = {}
        st = str(demand_fields.get(self.settings.demand_field_status, "") or "").strip()
        snap = self._demand_debate_snapshot_for_card(demand_record_id)
        if snap is None:
            self.logger.warning("push_next_approval_card: 无推荐供应商 demand=%s", demand_record_id)
            return False, False
        demand_record_for_card, debate_decision, category = snap
        mem_chat = self.get_im_chat_id_for_demand(demand_record_id)

        def _push(oid: str, phase: str) -> Tuple[bool, bool]:
            recv_id, recv_type = self._resolve_approval_card_delivery_target(oid, mem_chat)
            if not recv_id:
                return False, False
            return self._push_approval_card(
                oid,
                demand_record_for_card,
                debate_decision,
                phase=phase,
                receive_id=recv_id,
                receive_id_type=recv_type,
            )

        if not self.settings.multi_stage_approval:
            oid = self._get_approver_open_id(category)
            return _push(oid, "legacy")

        if st == BusinessStatus.DEMAND_PENDING_APPROVAL_SUPERVISOR:
            oid = self._get_personnel_open_id_by_phase(category, "supervisor")
            return _push(oid, "supervisor")
        if st in (BusinessStatus.DEMAND_PENDING_PURCHASE_CONFIRM, "待下单确认"):
            oid = self._get_personnel_open_id_by_phase(category, "purchaser")
            return _push(oid, "purchaser")
        if st == BusinessStatus.DEMAND_PENDING_APPROVAL_LOGISTICS:
            oid = self._get_personnel_open_id_by_phase(category, "logistics")
            return _push(oid, "logistics")
        if st == BusinessStatus.DEMAND_PENDING_APPROVAL:
            oid = self._get_approver_open_id(category)
            return _push(oid, "legacy")

        self.logger.info("push_next_approval_card: 状态 %s 不需要发卡片", st)
        return False, False

    def resend_approval_card(self, demand_record_id: str) -> Tuple[bool, str]:
        """在审批链各等待节点重发当前环节卡片（私聊审批人），不重新跑辩论。"""
        demand = self.bitable.get_record(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["demands"],
            record_id=demand_record_id,
        )
        demand_fields = demand.get("fields") if isinstance(demand, dict) else {}
        if not isinstance(demand_fields, dict):
            demand_fields = {}

        current_status = str(demand_fields.get(self.settings.demand_field_status, "") or "").strip()
        allowed = {
            BusinessStatus.DEMAND_PENDING_APPROVAL,
            BusinessStatus.DEMAND_PENDING_APPROVAL_SUPERVISOR,
            BusinessStatus.DEMAND_PENDING_PURCHASE_CONFIRM,
            BusinessStatus.DEMAND_PENDING_APPROVAL_LOGISTICS,
            "待下单确认",
        }
        if current_status not in allowed:
            return False, (
                f"当前状态为「{current_status or '(空)'}」，不在可重发审批卡片的状态。"
                f"若需重新辩论，请先将需求改回「{BusinessStatus.DEMAND_PENDING_DEBATE}」后再发送「触发审批」。"
            )

        snap = self._demand_debate_snapshot_for_card(demand_record_id)
        if snap is None:
            return False, (
                "未关联推荐供应商，无法生成审批卡片。"
                "请在多维表格 Demands 中检查推荐供应商字段后重试。"
            )
        demand_record_for_card, debate_decision, category = snap
        mem_chat = self.get_im_chat_id_for_demand(demand_record_id)

        if self.settings.multi_stage_approval:
            if current_status == BusinessStatus.DEMAND_PENDING_APPROVAL_SUPERVISOR:
                oid, phase = self._get_personnel_open_id_by_phase(category, "supervisor"), "supervisor"
            elif current_status in (BusinessStatus.DEMAND_PENDING_PURCHASE_CONFIRM, "待下单确认"):
                oid, phase = self._get_personnel_open_id_by_phase(category, "purchaser"), "purchaser"
            elif current_status == BusinessStatus.DEMAND_PENDING_APPROVAL_LOGISTICS:
                oid, phase = self._get_personnel_open_id_by_phase(category, "logistics"), "logistics"
            else:
                oid, phase = self._get_approver_open_id(category), "legacy"
        else:
            oid, phase = self._get_approver_open_id(category), "legacy"

        recv_id, recv_type = self._resolve_approval_card_delivery_target(oid, mem_chat)
        if not recv_id:
            return False, (
                "未配置该环节联系人飞书 open_id（Personnel 无匹配且 MOCK_PERSONNEL_FEISHU_OPEN_ID 为空），"
                "且无会话 chat_id 可用于兜底。请配置审批人后再试。"
            )

        card_ok, text_ok = self._push_approval_card(
            oid,
            demand_record_for_card,
            debate_decision,
            phase=phase,
            receive_id=recv_id,
            receive_id_type=recv_type,
        )
        if card_ok:
            return True, "已重发当前环节审批卡片。"
        if text_ok:
            return True, (
                "交互卡片仍失败，已向联系人发送文本提醒（无按钮，需在表格处理或修好权限后再重发卡片）。"
                "请查看日志中的 Feishu code/msg。"
            )
        return False, (
            "重发卡片与文本兜底均失败，请查看日志「审批卡片发送失败 / 审批通知文本 IM 失败」中的 code/msg/raw；"
            "常见原因：机器人缺 IM 权限、审批人需先与机器人单聊、或 interactive 被租户策略拦截。"
        )

    def run_audit_debate(
        self,
        demand_record_id: str,
        *,
        im_receive_id: Optional[str] = None,
        im_receive_id_type: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], str, Optional[str]]:
        """
        驱动 LLM 模拟「成本官 vs 质量官」辩论并落库；不自动下单。
        - Debate_History（优先）/ Audit_Logs（回退）
        - Demands：状态=待审批，写推荐供应商与辩论摘要；向会话 chat_id（若可得）或 Personnel open_id 推送审批卡片。
        返回第三项 skip_reason：无候选供应商等阻塞时为 \"no_candidate_suppliers\" / \"debate_aborted_no_supplier\"，成功为 None。
        """
        self.logger.info("开始辩论审计: demand_record_id=%s", demand_record_id)

        demand = self.bitable.get_record(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["demands"],
            record_id=demand_record_id,
        )
        demand_fields = demand.get("fields") if isinstance(demand, dict) else {}
        if not isinstance(demand_fields, dict):
            demand_fields = {}

        current_status = str(demand_fields.get(self.settings.demand_field_status, "") or "")
        if current_status != BusinessStatus.DEMAND_PENDING_DEBATE:
            hint = (
                f"需求状态须为「{BusinessStatus.DEMAND_PENDING_DEBATE}」才能启动辩论与审批，"
                f"当前为「{current_status or '(空)'}」。请等待 Planner 将「待规划」推进为「待辩论」，或先在表中修正状态。"
            )
            self.logger.warning("run_audit_debate 拒绝: demand_record_id=%s %s", demand_record_id, hint)
            self.log_to_audit_table(
                action="error",
                target_table="Demands",
                target_record_id=demand_record_id,
                result="fail",
                message="run_audit_debate rejected: wrong demand status",
                detail={"expected": BusinessStatus.DEMAND_PENDING_DEBATE, "actual": current_status},
                demand_record_id=demand_record_id,
            )
            raise ValueError(hint)

        # 1) 候选供应商（兼容读接口 cell 包装格式）
        candidates_raw = demand_fields.get(self.settings.demand_field_recommended_suppliers)
        candidate_ids = self._link_field_record_ids(candidates_raw)

        if not candidate_ids:
            category_from_demand = str(demand_fields.get(self.settings.demand_field_category, "") or "")
            candidate_ids = self._search_suppliers_by_category(category_from_demand)

        if not candidate_ids:
            self.logger.info("无候选供应商，辩论审计跳过: demand_record_id=%s", demand_record_id)
            self.log_to_audit_table(
                action="recommend",
                target_table="Demands",
                target_record_id=demand_record_id,
                result="skipped",
                message="run_audit_debate skipped: no candidate suppliers",
                detail={"demand_record_id": demand_record_id},
                demand_record_id=demand_record_id,
            )
            dcode = str(demand_fields.get(self.settings.demand_field_demand_code, "") or "").strip()
            cat_hint = str(demand_fields.get(self.settings.demand_field_category, "") or "").strip()
            try:
                dem = self.bitable.get_record(
                    app_token=self.settings.bitable_app_token,
                    table_id=TABLE_IDS["demands"],
                    record_id=demand_record_id,
                )
                prev_notes = str((dem.get("fields") or {}).get("notes") or "") if isinstance(dem.get("fields"), dict) else ""
            except Exception:
                prev_notes = ""
            if self.NO_CANDIDATE_SUPPLIER_MARKER not in prev_notes:
                now_s = time.strftime("%Y-%m-%d %H:%M", time.localtime())
                cat_part = f"当前品类为「{cat_hint}」。" if cat_hint else "当前未填写有效品类或品类与供应商「主营业务」不一致。"
                note_line = (
                    f"{self.NO_CANDIDATE_SUPPLIER_MARKER} [{now_s}] "
                    "AI 审计官无法启动 QCDSR 比价：供应商库中无匹配候选。"
                    f"{cat_part}"
                    "请在需求中关联「推荐供应商」，或调整供应商档案中的主营业务标签后重试。"
                )
                self._append_demand_note_line(demand_record_id, note_line)
                im_body = (
                    f"单号 **{dcode or '（待查表）'}**：未在供应商库中匹配到候选，**无法启动 AI 审计官比价**。\n"
                    f"{cat_part}\n"
                    "请在多维表格为该需求**关联推荐供应商**，或调整**品类**与 **Suppliers 主营业务** 一致后，再发「触发审批」。"
                )
                self._notify_im_debate_hint(
                    demand_record_id,
                    im_body,
                    im_receive_id=im_receive_id,
                    im_receive_id_type=im_receive_id_type,
                )
            return {}, BusinessStatus.DEMAND_PENDING_DEBATE, "no_candidate_suppliers"

        supplier_rows: List[Dict[str, Any]] = []
        for sid in candidate_ids:
            rec = self.bitable.get_record(
                app_token=self.settings.bitable_app_token,
                table_id=TABLE_IDS["suppliers"],
                record_id=sid,
            )
            fields = rec.get("fields") if isinstance(rec, dict) else {}
            if not isinstance(fields, dict):
                fields = {}
            supplier_rows.append(
                {
                    "record_id": sid,
                    "supplier_name": str(fields.get("supplier_name", "") or ""),
                    # 兼容你现有字段命名：quality_pass_rate/price_index -> quality_score/cost_score
                    "quality_pass_rate": fields.get("quality_pass_rate", fields.get("quality_score")),
                    "price_index": fields.get("price_index", fields.get("cost_score")),
                    "lead_time_days": fields.get("lead_time_days"),
                    "user_rating": fields.get("user_rating"),
                    "risk_level": fields.get("risk_level", fields.get("status")),
                    "credit_score": fields.get("credit_score"),
                }
            )

        # 2) 数据层：综合分预筛 Top3，仅 Q/C/D/S/R 进 prompt；物理层：读超时与 HTTP 重试见 BaseAgent
        shortlist_rows = self._shortlist_supplier_rows(supplier_rows, top_n=3)
        slim_for_llm = self._slim_rows_for_debate_llm(shortlist_rows)
        self.logger.info(
            "辩论候选: 全量=%s，送入模型 Top%s=%s",
            len(supplier_rows),
            len(slim_for_llm),
            [str(r.get("record_id")) for r in slim_for_llm],
        )

        system_prompt = (
            "你是采购审计辩论系统。两个角色对立：成本官重视 C（C_price_index，越高越省），"
            "质量官重视 Q、交期 D、用户评分 S、风险 R。\n"
            "decision.record_id 必须从下方候选 JSON 的 record_id 中原样复制，禁止编造 ID。\n"
            "English: Skip preamble, output JSON only, no markdown code fences. "
            "Keep each debate_logs[].argument brief (under ~80 Chinese characters). "
            "Arguments in total should stay under ~100 English words.\n"
            'Schema: {"debate_logs":[{"agent_name":"","stance":"","argument":""}],'
            '"decision":{"supplier_name":"","record_id":"","final_reason":""}}\n'
        )
        demand_brief = {
            "category": demand_fields.get(self.settings.demand_field_category),
            "budget_amount": demand_fields.get(self.settings.demand_field_budget_amount),
            "source_instruction": demand_fields.get(self.settings.demand_field_source_instruction),
        }
        prompt = (
            "采购需求摘要：\n"
            f"{json.dumps(demand_brief, ensure_ascii=False)}\n\n"
            "下列为预筛选后的候选（仅 Q/C/D/S/R 与 record_id），请仅基于这些记录输出上述 JSON：\n"
            f"{json.dumps(slim_for_llm, ensure_ascii=False)}\n"
        )

        self.logger.info(
            "辩论 LLM: 阻塞直至返回；超时/连接类错误由 HTTP 层指数退避重试（最多 3 次请求）后仍失败则降级"
        )

        llm_raw = ""
        used_fallback = False
        debate_logs: List[Dict[str, Any]] = []
        decision: Dict[str, Any] = {}

        try:
            llm_raw = self._call_llm(
                prompt,
                system_prompt,
                http_fail_use_mock=False,
                max_tokens=900,
                temperature=0.35,
                response_format_json_object=True,
            )
        except Exception as exc:
            used_fallback = True
            self.logger.warning("辩论 LLM 调用失败（含重试），降级基础选型: %s", exc)
            self.log_to_audit_table(
                action="error",
                target_table="Demands",
                target_record_id=demand_record_id,
                result="fail",
                message="run_audit_debate: LLM HTTP failed, degraded to credit pick",
                detail={"error": str(exc), "degraded": True},
                demand_record_id=demand_record_id,
            )
            debate_logs, decision = self._build_fallback_debate(
                candidate_ids,
                supplier_rows,
                f"一级重试耗尽后仍失败: {exc!s}"[:900],
            )
        else:
            parsed = self._parse_debate_llm_json(llm_raw)
            if parsed is None:
                used_fallback = True
                self.logger.warning("辩论输出无法解析为 JSON，降级基础选型")
                self.log_to_audit_table(
                    action="error",
                    target_table="Demands",
                    target_record_id=demand_record_id,
                    result="fail",
                    message="run_audit_debate: invalid JSON, degraded to credit pick",
                    detail={"llm_raw": llm_raw[:4000], "degraded": True},
                    demand_record_id=demand_record_id,
                )
                debate_logs, decision = self._build_fallback_debate(
                    candidate_ids,
                    supplier_rows,
                    f"二级降级(JSON): 原文前 500 字 {llm_raw[:500]!r}",
                )
            else:
                debate_logs = parsed.get("debate_logs") or []
                decision = parsed.get("decision") or {}
                if not isinstance(debate_logs, list):
                    debate_logs = []
                if not isinstance(decision, dict):
                    used_fallback = True
                    debate_logs, decision = self._build_fallback_debate(
                        candidate_ids,
                        supplier_rows,
                        "二级降级: decision 字段类型无效",
                    )

        if not isinstance(debate_logs, list):
            debate_logs = []

        chosen_id = str(decision.get("record_id", "") or "").strip()
        chosen_name = str(decision.get("supplier_name", "") or "").strip()
        final_reason = str(decision.get("final_reason", "") or "").strip()
        if not chosen_id:
            name_to_id = {str(r.get("supplier_name", "") or ""): str(r.get("record_id", "") or "") for r in supplier_rows}
            chosen_id = name_to_id.get(chosen_name, "")

        cand_set = set(candidate_ids)
        if chosen_id and chosen_id not in cand_set:
            self.logger.warning("模型返回的 record_id 不在全量候选集中，降级信用分选型")
            used_fallback = True
            debate_logs, decision = self._build_fallback_debate(
                candidate_ids,
                supplier_rows,
                f"二级降级: 非法 record_id={chosen_id}",
            )
            chosen_id = str(decision.get("record_id", "") or "").strip()
            chosen_name = str(decision.get("supplier_name", "") or "").strip()
            final_reason = str(decision.get("final_reason", "") or "").strip()

        if not chosen_id:
            self.logger.warning("辩论决策无有效供应商 record_id，执行基础选型降级")
            debate_logs, decision = self._build_fallback_debate(
                candidate_ids,
                supplier_rows,
                "二级降级: 无法从模型输出解析出有效 record_id",
            )
            chosen_id = str(decision.get("record_id", "") or "").strip()
            chosen_name = str(decision.get("supplier_name", "") or "").strip()
            final_reason = str(decision.get("final_reason", "") or "").strip()
            used_fallback = True

        if not chosen_id:
            self.logger.error("降级后仍无法确定供应商，终止 run_audit_debate")
            self.log_to_audit_table(
                action="error",
                target_table="Demands",
                target_record_id=demand_record_id,
                result="fail",
                message="run_audit_debate aborted after fallback: no supplier",
                detail={"candidate_count": len(candidate_ids)},
                demand_record_id=demand_record_id,
            )
            dcode = str(demand_fields.get(self.settings.demand_field_demand_code, "") or "").strip()
            try:
                dem = self.bitable.get_record(
                    app_token=self.settings.bitable_app_token,
                    table_id=TABLE_IDS["demands"],
                    record_id=demand_record_id,
                )
                prev_notes = str((dem.get("fields") or {}).get("notes") or "") if isinstance(dem.get("fields"), dict) else ""
            except Exception:
                prev_notes = ""
            if self.DEBATE_ABORT_NO_SUPPLIER_MARKER not in prev_notes:
                now_s = time.strftime("%Y-%m-%d %H:%M", time.localtime())
                note_line = (
                    f"{self.DEBATE_ABORT_NO_SUPPLIER_MARKER} [{now_s}] "
                    "辩论与降级选型后仍无法确定供应商，请检查候选数据或人工指定推荐供应商。"
                )
                self._append_demand_note_line(demand_record_id, note_line)
                im_body = (
                    f"单号 **{dcode or '（待查表）'}**：AI 审计官比价后**仍无法确定供应商**，流程已暂停在「待辩论」。\n"
                    "请检查供应商档案与推荐关联，或联系管理员处理。"
                )
                self._notify_im_debate_hint(
                    demand_record_id,
                    im_body,
                    im_receive_id=im_receive_id,
                    im_receive_id_type=im_receive_id_type,
                )
            return {}, BusinessStatus.DEMAND_PENDING_DEBATE, "debate_aborted_no_supplier"

        if not debate_logs:
            debate_logs = [
                {
                    "agent_name": "模型摘要",
                    "stance": "决策",
                    "argument": (final_reason or chosen_name or "（无辩论条目）")[:500],
                }
            ]

        if used_fallback:
            self.log_to_audit_table(
                action="recommend",
                target_table="Demands",
                target_record_id=demand_record_id,
                result="success",
                message="run_audit_debate used fallback supplier pick",
                detail={"chosen_supplier_id": chosen_id, "degraded": True},
                demand_record_id=demand_record_id,
                supplier_record_id=chosen_id,
            )

        # 3) 多表落库：辩论记录
        debate_table_id = str(TABLE_IDS.get("debate_history") or "").strip()
        fallback_log_table_id = str(TABLE_IDS.get("logs") or "").strip()
        write_table_id = debate_table_id or fallback_log_table_id

        now_ms = int(time.time() * 1000)
        wrote = 0
        for i, item in enumerate(debate_logs):
            if not isinstance(item, dict):
                continue
            agent_name = str(item.get("agent_name", "") or "")
            stance = str(item.get("stance", "") or "")
            argument = str(item.get("argument", "") or "")

            if debate_table_id:
                fields = {
                    "debate_id": f"DEB-{demand_record_id}-{now_ms}-{i}",
                    "demand_id": demand_record_id,
                    "agent_identity": agent_name,
                    "stance": stance,
                    "argument_content": argument,
                    "score_impact": 0,
                    "timestamp": now_ms,
                }
                self.bitable.add_record(
                    app_token=self.settings.bitable_app_token,
                    table_id=write_table_id,
                    fields=fields,
                    link_fields=["demand_id"],
                )
                wrote += 1
            else:
                # 回退到 Audit_Logs：尽量复用已有字段
                self.log_to_audit_table(
                    action="recommend",
                    target_table="Debate_History",
                    target_record_id=f"{demand_record_id}-{i}",
                    result="success",
                    message=stance,
                    detail={"agent_name": agent_name, "argument": argument},
                    demand_record_id=demand_record_id,
                )
                wrote += 1

        self.logger.info("辩论记录写入成功: count=%s table=%s", wrote, "Debate_History" if debate_table_id else "Audit_Logs")

        # 4) 状态挂起：单阶段「待审批」或多阶段首环节「待主管审批」（不创建订单）
        category = str(demand_fields.get(self.settings.demand_field_category, "") or "")
        pending_status = (
            BusinessStatus.DEMAND_PENDING_APPROVAL_SUPERVISOR
            if self.settings.multi_stage_approval
            else BusinessStatus.DEMAND_PENDING_APPROVAL
        )
        card_phase = "supervisor" if self.settings.multi_stage_approval else "legacy"
        update_fields: Dict[str, Any] = {
            self.settings.demand_field_status: pending_status,
        }
        if chosen_id:
            update_fields[self.settings.demand_field_recommended_suppliers] = [chosen_id]
        debate_summary = final_reason or ""
        if debate_summary:
            update_fields["notes"] = debate_summary[:1000]

        self.bitable.update_record(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["demands"],
            record_id=demand_record_id,
            fields=update_fields,
            link_fields=[self.settings.demand_field_recommended_suppliers] if chosen_id else None,
        )
        self.logger.info(
            "需求更新为 %s（未下单）: demand_record_id=%s chosen_supplier=%s(%s)",
            pending_status,
            demand_record_id,
            chosen_name,
            chosen_id,
        )

        # 5) 匹配审批人并推送飞书审批卡片（首环节）——发往审批人私聊；未配置时才用会话 chat_id 兜底
        if self.settings.multi_stage_approval:
            approver_open_id = self._get_personnel_open_id_by_phase(category, "supervisor")
        else:
            approver_open_id = self._get_approver_open_id(category)
        mem_chat = self.get_im_chat_id_for_demand(demand_record_id)
        recv_id, recv_type = self._resolve_approval_card_delivery_target(approver_open_id, mem_chat)
        demand_record_for_card: Dict[str, Any] = {"record_id": demand_record_id, "fields": demand_fields}
        debate_decision: Dict[str, Any] = {
            "supplier_name": chosen_name,
            "record_id": chosen_id,
            "final_reason": debate_summary,
        }
        card_sent = False
        text_fallback_sent = False
        if recv_id:
            self.logger.info(
                "待审批推送: receive_id_type=%s target=%s… personnel_open_id=%s",
                recv_type,
                recv_id[:20],
                (approver_open_id or "")[:16],
            )
            card_sent, text_fallback_sent = self._push_approval_card(
                approver_open_id,
                demand_record_for_card,
                debate_decision,
                phase=card_phase,
                receive_id=recv_id,
                receive_id_type=recv_type,
            )
            if card_sent:
                self.logger.info(
                    "✅ 已将需求 %s 挂起，并已推送审批卡片（%s）",
                    demand_record_id,
                    recv_type,
                )
                self.log_to_audit_table(
                    action="recommend",
                    target_table="Demands",
                    target_record_id=demand_record_id,
                    result="success",
                    message=f"Sent approval card via {recv_type}",
                    detail={
                        "approver_open_id": approver_open_id,
                        "delivery_receive_id_prefix": recv_id[:24],
                        "delivery_receive_id_type": recv_type,
                        "category": category,
                    },
                    demand_record_id=demand_record_id,
                    supplier_record_id=chosen_id or None,
                )
            elif text_fallback_sent:
                self.logger.warning(
                    "需求 %s 已挂起待审批：卡片未送达，已发文本兜底（%s）",
                    demand_record_id,
                    recv_type,
                )
            else:
                self.logger.warning(
                    "需求 %s 已挂起为待审批，但卡片与文本通知均发送失败（请查日志 code/msg 与机器人权限）",
                    demand_record_id,
                )
        else:
            self.logger.warning(
                "需求 %s 已挂起为待审批，但无可用投递目标（Personnel/MOCK 为空且无 Interaction_Memory.chat_id），未推送卡片",
                demand_record_id,
            )

        self.log_to_audit_table(
            action="update",
            target_table="Demands",
            target_record_id=demand_record_id,
            result="success",
            message=f"run_audit_debate updated demand to {pending_status}",
            detail={
                "chosen_supplier_id": chosen_id,
                "chosen_supplier_name": chosen_name,
                "final_reason": final_reason[:2000],
                "approver_open_id": approver_open_id,
                "approval_card_sent": card_sent,
                "approval_text_fallback_sent": text_fallback_sent,
                "multi_stage_approval": self.settings.multi_stage_approval,
            },
            demand_record_id=demand_record_id,
            supplier_record_id=chosen_id or None,
        )

        return update_fields, pending_status, None

