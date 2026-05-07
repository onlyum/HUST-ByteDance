from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import lark_oapi as lark
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    CallBackToast,
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

from config import ProcurementSettings
from handler.bot_handler import BotHandler
from agents.sourcing_auditor import SourcingAuditorAgent
from config import BusinessStatus, TABLE_IDS
from feishu_bitable_toolbox import FeishuBitableToolbox
from feishu_ws_card_patch import FeishuLarkWsClient


logger = logging.getLogger(__name__)


def _card_toast(content: str, *, toast_type: str = "info") -> P2CardActionTriggerResponse:
    r = P2CardActionTriggerResponse()
    t = CallBackToast()
    t.type = toast_type
    t.content = content
    r.toast = t
    return r


class FeishuWebSocketClient:
    """基于 lark-oapi 的长连接消息监听客户端。"""

    def __init__(self, settings: ProcurementSettings, bot_handler: BotHandler) -> None:
        self.settings = settings
        self.bot_handler = bot_handler
        self._api_client = (
            lark.Client.builder()
            .app_id(settings.feishu_app_id)
            .app_secret(settings.feishu_app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )
        # 事件可能重复投递，按 message_id 做短期去重。
        self._seen_message_ids: dict[str, float] = {}
        self._seen_ttl_seconds = 300.0
        self._recent_fingerprints: dict[str, float] = {}
        self._fingerprint_ttl_seconds = 8.0
        self._processed_approvals: dict[str, float] = {}
        self._processed_ttl_seconds = 3600.0
        self._bitable = FeishuBitableToolbox(app_id=settings.feishu_app_id, app_secret=settings.feishu_app_secret)
        self._auditor = SourcingAuditorAgent("auditor-ws-1", settings, self._bitable)
        # IM 内可能跑 LLM（分钟级），若在 WS 回调线程同步执行会阻塞心跳 → ping_timeout(3003)。单线程串行处理即可。
        self._im_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="feishu-im")
        # 卡片按钮回调须尽快回包（否则飞书端一直 loading）；落库放后台线程，与 IM 队列分离以免被 LLM 阻塞。
        self._card_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="feishu-card")

    def _cleanup_seen_cache(self) -> None:
        now = time.time()
        expired = [k for k, ts in self._seen_message_ids.items() if now - ts > self._seen_ttl_seconds]
        for k in expired:
            self._seen_message_ids.pop(k, None)
        expired_fp = [k for k, ts in self._recent_fingerprints.items() if now - ts > self._fingerprint_ttl_seconds]
        for k in expired_fp:
            self._recent_fingerprints.pop(k, None)
        expired_approval = [k for k, ts in self._processed_approvals.items() if now - ts > self._processed_ttl_seconds]
        for k in expired_approval:
            self._processed_approvals.pop(k, None)

    def _extract_message_id(self, data: Any) -> str:
        try:
            return str(data.event.message.message_id or "")
        except Exception:
            return ""

    def _is_from_bot_self(self, data: Any) -> bool:
        """
        过滤机器人自身消息，避免自回复触发循环。
        """
        try:
            sender_type = str(data.event.sender.sender_type or "").lower()
            if sender_type in {"app", "bot"}:
                return True
        except Exception:
            pass
        return False

    def _extract_event_text(self, data: Any) -> str:
        try:
            return str(data.event.message.content or "")
        except Exception:
            return ""

    def _extract_sender_open_id(self, data: Any) -> str:
        try:
            return str(data.event.sender.sender_id.open_id or "")
        except Exception:
            return ""

    def _extract_sender_display_name(self, data: Any) -> str:
        """飞书事件里发送者展示名（不同租户/SDK 字段可能略有差异）。"""
        try:
            s = data.event.sender
            for attr in ("name", "nickname", "sender_name"):
                v = getattr(s, attr, None)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        except Exception:
            pass
        try:
            sid = data.event.sender.sender_id
            for attr in ("name", "nickname"):
                v = getattr(sid, attr, None)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        except Exception:
            pass
        return ""

    def _extract_chat_id(self, data: Any) -> str:
        try:
            return str(data.event.message.chat_id or "")
        except Exception:
            return ""

    def _resolve_im_receive_target(self, data: Any) -> tuple[str, str]:
        """
        解析发消息 API 的 receive_id / receive_id_type。
        优先使用会话 chat_id：群聊为群 ID，单聊为与该用户的会话 ID，机器人回复会回到原会话（群内 @ 不会误发到私聊）。
        仅当 chat_id 缺失时回退为发送者 open_id。
        """
        chat_id = ""
        open_id = ""
        try:
            chat_id = str(data.event.message.chat_id or "").strip()
        except Exception:
            chat_id = ""
        try:
            open_id = str(data.event.sender.sender_id.open_id or "").strip()
        except Exception:
            open_id = ""
        if chat_id:
            return "chat_id", chat_id
        if open_id:
            return "open_id", open_id
        return "", ""

    def _send_message(self, *, receive_id_type: str, receive_id: str, msg_type: str, content_obj: dict[str, Any]) -> None:
        req_body = (
            lark.im.v1.CreateMessageRequestBody.builder()
            .receive_id(receive_id)
            .msg_type(msg_type)
            .content(json.dumps(content_obj, ensure_ascii=False))
            .build()
        )
        req = (
            lark.im.v1.CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(req_body)
            .build()
        )
        resp = self._api_client.im.v1.message.create(req)
        if not resp.success():
            raw = getattr(resp, "raw", None)
            logger.warning("发送IM消息失败: code=%s msg=%s raw=%s", resp.code, resp.msg, raw)

    def _process_im_message(
        self,
        content: str,
        receive_id_type: str,
        receive_id: str,
        im_context: Optional[dict[str, Any]] = None,
    ) -> None:
        """在独立线程执行，避免阻塞飞书 WS 心跳。"""
        try:
            result = self.bot_handler.handle_message(content, im_context=im_context)
            reply_text = str(result.get("reply", "") or "")
            if reply_text:
                logger.info(
                    "准备回复 text: receive_id_type=%s receive_id=%s text=%s",
                    receive_id_type,
                    receive_id,
                    reply_text[:200],
                )
                self._send_message(
                    receive_id_type=receive_id_type,
                    receive_id=receive_id,
                    msg_type="text",
                    content_obj={"text": reply_text},
                )
            if str(result.get("msg_type", "")) == "interactive" and isinstance(result.get("content"), dict):
                logger.info("准备回复 card: receive_id_type=%s receive_id=%s", receive_id_type, receive_id)
                self._send_message(
                    receive_id_type=receive_id_type,
                    receive_id=receive_id,
                    msg_type="interactive",
                    content_obj=result["content"],
                )
        except Exception as exc:
            logger.exception("IM 后台处理失败: %s", exc)

    def _on_p2p_message(self, data: Any) -> None:
        if self._is_from_bot_self(data):
            logger.info("忽略机器人自身消息事件")
            return

        self._cleanup_seen_cache()
        message_id = self._extract_message_id(data)
        if message_id:
            if message_id in self._seen_message_ids:
                logger.info("忽略重复消息事件: message_id=%s", message_id)
                return
            self._seen_message_ids[message_id] = time.time()

        print("🔥 捕获到原始事件！")
        content = self._extract_event_text(data)
        print(content)

        sender_open_id = self._extract_sender_open_id(data)
        logger.info(
            "私信发送者 open_id（可复制填入 Personnel.feishu_open_id）: %s",
            sender_open_id or "(空)",
        )
        fingerprint = f"{sender_open_id}|{content}"
        if fingerprint in self._recent_fingerprints:
            logger.info("忽略短时重复内容事件")
            return
        self._recent_fingerprints[fingerprint] = time.time()

        receive_id_type, receive_id = self._resolve_im_receive_target(data)
        if not receive_id_type or not receive_id:
            logger.warning("IM 事件无可用 receive_id（chat_id/open_id），跳过回复")
            return

        im_ctx: dict[str, Any] = {
            "message_id": message_id,
            "chat_id": self._extract_chat_id(data),
            "open_id": str(sender_open_id or ""),
            "sender_name": self._extract_sender_display_name(data),
        }

        logger.info("IM 已入队后台处理（不阻塞 WS），receive_id_type=%s", receive_id_type)
        self._im_executor.submit(self._process_im_message, content, receive_id_type, receive_id, im_ctx)

    def _append_demand_note(self, demand_id: str, line: str) -> None:
        try:
            dem = self._bitable.get_record(
                app_token=self.settings.bitable_app_token,
                table_id=TABLE_IDS["demands"],
                record_id=demand_id,
            )
            fld = dem.get("fields") if isinstance(dem, dict) else {}
            if not isinstance(fld, dict):
                fld = {}
            prev = str(fld.get("notes", "") or "").strip()
            merged = (prev + ("\n" if prev else "") + line)[:1000]
            self._bitable.update_record(
                app_token=self.settings.bitable_app_token,
                table_id=TABLE_IDS["demands"],
                record_id=demand_id,
                fields={"notes": merged},
            )
        except Exception as exc:
            logger.warning("追加需求备注失败 demand=%s: %s", demand_id, exc)

    def _place_order_for_demand(self, demand_id: str, supplier_id: str, approver_name: str, now_text: str) -> str:
        """创建订单并将需求置为已下单；返回通知文案。"""
        self._bitable.update_record(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["demands"],
            record_id=demand_id,
            fields={self.settings.demand_field_status: BusinessStatus.SUPPLIER_SELECTED},
        )
        order_fields = {
            "order_code": f"PO-{int(time.time())}",
            self.settings.order_field_demand: demand_id,
            self.settings.order_field_supplier: supplier_id,
            self.settings.order_field_logistics_status: "待发货",
        }
        order_record_id = self._bitable.add_record(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["orders"],
            fields=order_fields,
            link_fields=[self.settings.order_field_demand, self.settings.order_field_supplier],
        )
        self._bitable.update_record(
            app_token=self.settings.bitable_app_token,
            table_id=TABLE_IDS["demands"],
            record_id=demand_id,
            fields={
                self.settings.demand_field_status: BusinessStatus.ORDER_PLACED,
            },
        )
        self._append_demand_note(
            demand_id,
            f"已于 {now_text} 由 {approver_name or '确认人'} 确认下单 ✅",
        )
        logger.info("下单成功: demand_id=%s order_id=%s", demand_id, order_record_id)
        return f"已生成订单 {order_record_id[:18]}…，需求已「已下单」。"

    def _run_card_approval_job(
        self,
        *,
        action: str,
        demand_id: str,
        supplier_id: str,
        approver_name: str,
        dedupe_key: str,
        operator_open_id: str,
        phase: str,
    ) -> None:
        """卡片回调回包后再执行；多阶段时按 phase 推进并下发下一环节卡片。"""
        now_text = time.strftime("%Y-%m-%d %H:%M", time.localtime())
        notify = ""
        eff_phase = (phase or "legacy").strip()
        if not self.settings.multi_stage_approval:
            eff_phase = "legacy"
        try:
            if action == "reject":
                self._bitable.update_record(
                    app_token=self.settings.bitable_app_token,
                    table_id=TABLE_IDS["demands"],
                    record_id=demand_id,
                    fields={
                        self.settings.demand_field_status: BusinessStatus.DEMAND_REJECTED,
                    },
                )
                self._append_demand_note(demand_id, f"于 {now_text} 在环节「{eff_phase}」被驳回 ❌")
                logger.info("审批驳回: demand_id=%s phase=%s", demand_id, eff_phase)
                notify = "已驳回该需求。"
            elif action == "approve":
                dem = self._bitable.get_record(
                    app_token=self.settings.bitable_app_token,
                    table_id=TABLE_IDS["demands"],
                    record_id=demand_id,
                )
                fld = dem.get("fields") if isinstance(dem, dict) else {}
                if not isinstance(fld, dict):
                    fld = {}
                st = str(fld.get(self.settings.demand_field_status, "") or "").strip()

                if eff_phase == "legacy":
                    if st not in (
                        BusinessStatus.DEMAND_PENDING_APPROVAL,
                        BusinessStatus.DEMAND_PENDING_APPROVAL_SUPERVISOR,
                    ):
                        self._processed_approvals.pop(dedupe_key, None)
                        notify = f"状态已变化（当前「{st}」），请刷新或重发卡片。"
                    else:
                        notify = "审批已完成：" + self._place_order_for_demand(
                            demand_id, supplier_id, approver_name, now_text
                        )
                elif eff_phase == "supervisor":
                    if st not in (
                        BusinessStatus.DEMAND_PENDING_APPROVAL_SUPERVISOR,
                        BusinessStatus.DEMAND_PENDING_APPROVAL,
                    ):
                        self._processed_approvals.pop(dedupe_key, None)
                        notify = f"状态已变化（当前「{st}」），请勿重复操作。"
                    else:
                        self._bitable.update_record(
                            app_token=self.settings.bitable_app_token,
                            table_id=TABLE_IDS["demands"],
                            record_id=demand_id,
                            fields={self.settings.demand_field_status: BusinessStatus.DEMAND_PENDING_PURCHASE_CONFIRM},
                        )
                        self._append_demand_note(
                            demand_id,
                            f"[{now_text}] 终审/主管 {approver_name or '—'} 已通过 → 待采购确认（寻源对接）",
                        )
                        c_ok, t_ok = self._auditor.push_next_approval_card(demand_id)
                        notify = (
                            "终审已通过，已进入「待采购确认」。"
                            + ("已向采购联系人发送卡片（含供方/需求方对接信息）。" if c_ok else ("已发文本兜底。" if t_ok else "下环节卡片发送失败，请用「触发审批」重发。"))
                        )
                elif eff_phase == "purchaser":
                    if st not in (
                        BusinessStatus.DEMAND_PENDING_PURCHASE_CONFIRM,
                        "待下单确认",
                    ):
                        self._processed_approvals.pop(dedupe_key, None)
                        notify = f"状态已变化（当前「{st}」），请勿重复操作。"
                    else:
                        self._bitable.update_record(
                            app_token=self.settings.bitable_app_token,
                            table_id=TABLE_IDS["demands"],
                            record_id=demand_id,
                            fields={self.settings.demand_field_status: BusinessStatus.DEMAND_PENDING_APPROVAL_LOGISTICS},
                        )
                        self._append_demand_note(
                            demand_id,
                            f"[{now_text}] 采购 {approver_name or '—'} 已确认 → 待运输审批",
                        )
                        c_ok, t_ok = self._auditor.push_next_approval_card(demand_id)
                        notify = (
                            "采购环节已通过，已进入「待运输审批」。"
                            + ("已向物流联系人发送卡片。" if c_ok else ("已发文本兜底。" if t_ok else "下环节卡片发送失败，请用「触发审批」重发。"))
                        )
                elif eff_phase == "logistics":
                    if st != BusinessStatus.DEMAND_PENDING_APPROVAL_LOGISTICS:
                        self._processed_approvals.pop(dedupe_key, None)
                        notify = f"状态已变化（当前「{st}」），请勿重复操作。"
                    else:
                        notify = "运输已通过，开始建单：" + self._place_order_for_demand(
                            demand_id, supplier_id, approver_name, now_text
                        )
                else:
                    self._processed_approvals.pop(dedupe_key, None)
                    notify = f"未知环节 phase={eff_phase}，未执行。"
            else:
                return
        except Exception as exc:
            self._processed_approvals.pop(dedupe_key, None)
            logger.warning("卡片审批后台任务失败: %s", exc)
            notify = f"审批落库失败：{exc}"
        if not (notify or "").strip():
            return
        text = notify[:3500]
        # 审批人私聊确认 + 关联群/会话进度同步（依赖 Interaction_Memory.chat_id；单聊场景可能与私聊重复一条，可忽略）
        if (operator_open_id or "").strip():
            self._send_message(
                receive_id_type="open_id",
                receive_id=operator_open_id.strip(),
                msg_type="text",
                content_obj={"text": text},
            )
        chat_for_notify = (self._auditor.get_im_chat_id_for_demand(demand_id) or "").strip()
        if chat_for_notify:
            self._send_message(
                receive_id_type="chat_id",
                receive_id=chat_for_notify,
                msg_type="text",
                content_obj={"text": text},
            )
        elif not (operator_open_id or "").strip():
            logger.info("审批结果无 IM 投递目标：操作人 open_id 与会话 chat_id 均为空")

    def _on_card_action(self, data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        """
        处理飞书交互式卡片按钮回调（approve/reject）。
        须立即返回 P2CardActionTriggerResponse；慢操作放到 _card_executor，否则飞书端按钮会一直转圈。
        """
        logger.info("卡片回调已进入 _on_card_action（将立即返回 toast，后台落库异步执行）")
        self._cleanup_seen_cache()
        logger.info("card operator open_id=%s", getattr(getattr(data.event, "operator", None), "open_id", None))
        logger.info("card operator raw=%s", getattr(data.event, "operator", None))
        try:
            value = data.event.action.value if data.event and data.event.action else None
        except Exception:
            value = None
        if isinstance(value, str) and value.strip():
            try:
                value = json.loads(value)
            except Exception:
                value = None
        if not isinstance(value, dict):
            logger.info("card action value 为空或非 dict，忽略")
            return _card_toast("卡片数据无效，请重试", toast_type="error")

        action = str(value.get("action", "") or "")
        demand_id = str(value.get("demand_id", "") or "")
        supplier_id = str(value.get("supplier_id", "") or "")
        phase = str(value.get("phase") or "").strip() or "legacy"
        if not action or not demand_id:
            logger.info("card action 缺少 action/demand_id，忽略")
            return _card_toast("缺少需求信息，无法处理", toast_type="error")

        dedupe_key = f"{action}:{demand_id}:{phase}"
        if dedupe_key in self._processed_approvals:
            logger.info("忽略重复审批回调: %s", dedupe_key)
            return _card_toast("该审批已处理或正在处理，请勿重复点击", toast_type="info")

        approver_name = ""
        try:
            approver_name = str(data.event.operator.name or "")
        except Exception:
            approver_name = ""

        operator_open_id = ""
        try:
            operator_open_id = str(data.event.operator.open_id or "")
        except Exception:
            operator_open_id = ""

        if action not in ("approve", "reject"):
            logger.info("未知 action=%s，忽略", action)
            return _card_toast("未知操作", toast_type="info")

        self._processed_approvals[dedupe_key] = time.time()
        self._card_executor.submit(
            self._run_card_approval_job,
            action=action,
            demand_id=demand_id,
            supplier_id=supplier_id,
            approver_name=approver_name,
            dedupe_key=dedupe_key,
            operator_open_id=operator_open_id,
            phase=phase,
        )
        return _card_toast("已收到，正在写入多维表格…", toast_type="success")

    def start(self) -> None:
        # 当前 lark-oapi 版本中，消息接收事件注册方法为 register_p2_im_message_receive_v1。
        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_p2p_message)
            .register_p2_card_action_trigger(self._on_card_action)
            .build()
        )
        logger.info(
            "已注册事件: p2_im_message_receive_v1, p2_card_action_trigger | app_id=%s…",
            (self.settings.feishu_app_id or "")[:14],
        )
        logger.info(
            "WS: 使用 FeishuLarkWsClient（卡片回调会正确回包）；单实例连接。"
            "若点击卡片后无任何「WS DATA 帧」日志，请检查开放平台：卡片/交互事件须走长连接，且勿让另一环境独占 HTTP 回调。"
        )
        ws_cli = FeishuLarkWsClient(
            self.settings.feishu_app_id,
            self.settings.feishu_app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )
        logger.info("飞书 WebSocket 客户端 start() 阻塞运行中…")
        ws_cli.start()

