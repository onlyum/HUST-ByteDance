"""
飞书 WebSocket 长连接下，lark-oapi 原生 Client 对 MessageType.CARD 直接 return，
不写回包 → 卡片按钮一直转圈。

使用 FeishuLarkWsClient 替代 lark.ws.Client，保证 CARD 与 EVENT 一样回传 base64 业务体。
"""

from __future__ import annotations

import base64
import http
import json
import logging
import time
from typing import Any

from lark_oapi.core.const import UTF_8
from lark_oapi.core.json import JSON
from lark_oapi.ws.client import Client as LarkWsClient
from lark_oapi.ws.client import _get_by_key, logger as ws_logger
from lark_oapi.ws.const import HEADER_BIZ_RT, HEADER_MESSAGE_ID, HEADER_SEQ, HEADER_SUM, HEADER_TRACE_ID, HEADER_TYPE
from lark_oapi.ws.enum import MessageType
from lark_oapi.ws.model import Response
from lark_oapi.ws.pb.pbbp2_pb2 import Frame

logger = logging.getLogger(__name__)


class FeishuLarkWsClient(LarkWsClient):
    """
    与 lark.ws.Client 一致，仅修正 _handle_data_frame 对 CARD 帧的回包逻辑。
    """

    async def _handle_data_frame(self, frame: Frame) -> None:  # type: ignore[override]
        hs = frame.headers
        msg_id = _get_by_key(hs, HEADER_MESSAGE_ID)
        trace_id = _get_by_key(hs, HEADER_TRACE_ID)
        sum_ = _get_by_key(hs, HEADER_SUM)
        seq = _get_by_key(hs, HEADER_SEQ)
        raw_type = (_get_by_key(hs, HEADER_TYPE) or "").strip().lower()

        pl = frame.payload
        if int(sum_) > 1:
            pl = self._combine(msg_id, int(sum_), int(seq), pl)
            if pl is None:
                return

        payload_obj: Any = None
        event_type_hint = ""
        try:
            payload_obj = json.loads(pl.decode(UTF_8))
            if isinstance(payload_obj, dict):
                hdr = payload_obj.get("header")
                if isinstance(hdr, dict):
                    event_type_hint = str(hdr.get("event_type") or "")
        except Exception:
            payload_obj = None

        logger.info(
            "WS DATA 帧: header.type=%r message_id=%s trace_id=%s bytes=%s event_type=%r",
            raw_type,
            msg_id,
            trace_id,
            len(pl),
            event_type_hint or "",
        )

        try:
            message_type = MessageType(raw_type)
        except ValueError:
            looks_like_event = isinstance(payload_obj, dict) and (
                "header" in payload_obj
                or str(payload_obj.get("schema") or "") == "2.0"
                or event_type_hint.startswith("card.")
            )
            if looks_like_event:
                logger.warning(
                    "WS 帧 header.type=%r 非 event/card，但 body 像事件 JSON，按 EVENT 回包（常见于卡片回调）",
                    raw_type,
                )
                message_type = MessageType.EVENT
            else:
                ws_logger.error(
                    self._fmt_log(
                        "unknown WS data frame type: {}, message_id: {}（未回包，客户端可能一直转圈）",
                        raw_type,
                        msg_id,
                    )
                )
                return

        try:
            pl_text = pl.decode(UTF_8)
        except Exception:
            pl_text = "(decode error)"

        ws_logger.debug(
            self._fmt_log(
                "receive message, message_type: {}, message_id: {}, trace_id: {}, payload: {}",
                message_type.value,
                msg_id,
                trace_id,
                pl_text,
            )
        )

        resp = Response(code=http.HTTPStatus.OK)
        try:
            start = int(round(time.time() * 1000))
            result = None
            if message_type == MessageType.EVENT:
                result = self._event_handler.do_without_validation(pl)
            elif message_type == MessageType.CARD:
                result = self._event_handler.do_without_validation(pl)
            else:
                return

            end = int(round(time.time() * 1000))
            header = hs.add()
            header.key = HEADER_BIZ_RT
            header.value = str(end - start)

            marshaled = JSON.marshal(result) if result is not None else None
            if marshaled:
                resp.data = base64.b64encode(marshaled.encode(UTF_8))
            else:
                # 飞书侧可能要求 data 非空；给空 toast 避免一直转圈
                resp.data = base64.b64encode(
                    '{"toast":{"type":"info","content":"ok"}}'.encode(UTF_8)
                )
                ws_logger.warning(
                    self._fmt_log(
                        "card/event handler returned None, message_id: {}, trace_id: {}",
                        msg_id,
                        trace_id,
                    )
                )
        except Exception as e:
            ws_logger.error(
                self._fmt_log(
                    "handle message failed, message_type: {}, message_id: {}, trace_id: {}, err: {}",
                    message_type.value,
                    msg_id,
                    trace_id,
                    e,
                )
            )
            resp = Response(code=http.HTTPStatus.INTERNAL_SERVER_ERROR)

        frame.payload = JSON.marshal(resp).encode(UTF_8)
        await self._write_message(frame.SerializeToString())


def apply_lark_ws_card_response_patch() -> None:
    """兼容旧代码：子类方案下可为空。"""
    logger.debug("apply_lark_ws_card_response_patch: 已改用 FeishuLarkWsClient，跳过 monkey-patch")
