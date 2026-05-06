"""
测试「审批人收不到卡片」时的飞书 IM 链路（与业务代码同凭证、同 API）。

用法（在 feishu_agent_demo 目录下）:
  python script/test_approval_im_chain.py
  python script/test_approval_im_chain.py --open-id ou_xxxxxxxx
  python script/test_approval_im_chain.py --category 原材料
  python script/test_approval_im_chain.py --resend-demand recvxxxxxxxx
  python script/test_approval_im_chain.py --resend-demand DEM-20260426-01

说明:
  - 文本消息失败：多为缺少「以应用身份发消息」、用户未与机器人发起私聊、open_id 错误。
  - 文本成功但卡片失败：检查卡片 JSON、interactive 能力、租户策略。
  - open_id 来源：日志里「私信发送者 open_id」、或 Personnel.feishu_open_id、或 MOCK_PERSONNEL_FEISHU_OPEN_ID。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lark_oapi as lark

from agents.sourcing_auditor import SourcingAuditorAgent
from config import load_settings
from feishu_bitable_toolbox import FeishuBitableToolbox
from handler.bot_handler import BotHandler


def _print_resp(tag: str, resp: Any) -> None:
    ok = resp.success()
    raw = getattr(resp, "raw", None)
    print(f"[{tag}] success={ok} code={getattr(resp, 'code', '')} msg={getattr(resp, 'msg', '')}")
    if raw is not None:
        print(f"[{tag}] raw={raw}")
    if not ok:
        print(
            f"[{tag}] 排查: 开放平台应用是否开通「机器人」能力并申请 im:message / im:message.group_at_msg；"
            "接收人是否已与该机器人发起过单聊；open_id 是否为用户 open_id（非 union_id）。"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="测试审批 IM 文本 + 卡片链路")
    parser.add_argument(
        "--open-id",
        default="",
        help="接收人 user open_id；不填则按 --category 从 Personnel / MOCK 解析审批人",
    )
    parser.add_argument(
        "--category",
        default="备品备件",
        help="解析审批人时的 Demands 品类（与 Personnel.managed_categories 匹配）",
    )
    parser.add_argument("--skip-text", action="store_true", help="跳过文本探测")
    parser.add_argument("--skip-card", action="store_true", help="跳过 interactive 卡片探测")
    parser.add_argument(
        "--resend-demand",
        default="",
        metavar="REF",
        help="对已是「待审批」的需求重发审批卡片：可填 record_id（recv…）或 demand_code（如 DEM-20260426-01）",
    )
    args = parser.parse_args()

    settings = load_settings()
    bitable = FeishuBitableToolbox(app_id=settings.feishu_app_id, app_secret=settings.feishu_app_secret)
    auditor = SourcingAuditorAgent("audit-chain-test", settings, bitable)

    resend = (args.resend_demand or "").strip()
    if resend:
        try:
            record_id = BotHandler(bitable)._resolve_demand_ref_to_record_id(resend)
        except ValueError as exc:
            print(f"[resend] 解析需求标识失败: {exc}")
            return 1
        print(f"[resend] 标识「{resend}」→ record_id={record_id}")
        ok, msg = auditor.resend_approval_card(record_id)
        print(f"[resend_approval_card] ok={ok} {msg}")
        return 0 if ok else 1

    open_id = (args.open_id or "").strip()
    if not open_id:
        open_id = auditor._get_approver_open_id((args.category or "").strip())
    print(f"使用接收人 open_id: {open_id or '(空)'}")
    if not open_id:
        print("失败: 无法得到审批人 open_id。请配置 Personnel（Approver + feishu_open_id）或 MOCK_PERSONNEL_FEISHU_OPEN_ID，或用 --open-id 指定。")
        return 2

    client = auditor._im_client

    if not args.skip_text:
        body = (
            lark.im.v1.CreateMessageRequestBody.builder()
            .receive_id(open_id)
            .msg_type("text")
            .content(
                json.dumps(
                    {"text": "【审批链路自检】若收到本条，说明机器人已具备向该用户发送 IM 文本消息的能力。"},
                    ensure_ascii=False,
                )
            )
            .build()
        )
        req = lark.im.v1.CreateMessageRequest.builder().receive_id_type("open_id").request_body(body).build()
        resp = client.im.v1.message.create(req)
        _print_resp("TEXT", resp)

    if not args.skip_card:
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": "审批链路自检（卡片）"},
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "若能看到此消息，说明 **interactive** 类型消息可用。正式审批卡片结构与此类似。",
                    },
                }
            ],
        }
        ok = auditor._send_interactive_card(open_id=open_id, card=card)
        print(f"[CARD] _send_interactive_card ok={ok}（失败时见上方 sourcing_auditor 的 warning 日志）")

    print("完成。请让接收人在飞书「消息」中查看是否与机器人会话里出现上述内容。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
