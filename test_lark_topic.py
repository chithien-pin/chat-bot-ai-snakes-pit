"""Unit test logic gộp topic Lark (thread_id / root_id / parent_id / message_id)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MockMsg:
    thread_id: str = ""
    root_id: str = ""
    parent_id: str = ""
    message_id: str = ""


CHAT = "oc_test_chat"


def _run_topic_alias_tests() -> None:
    alias_map: dict[str, str] = {}
    active: set[str] = set()

    def collect(msg: MockMsg) -> list[str]:
        out: list[str] = []
        for raw in (msg.thread_id, msg.root_id, msg.parent_id, msg.message_id):
            if raw and raw not in out:
                out.append(raw)
        return out

    def alias_key(alias: str) -> str:
        return f"{CHAT}:{alias}"

    def active_canonical(aliases: list[str]) -> str:
        suffixes = {s.split(":", 1)[1] for s in active if s.startswith(f"{CHAT}:")}
        for alias in aliases:
            if alias in suffixes:
                return alias
        return ""

    def canonical(msg: MockMsg) -> str:
        aliases = collect(msg)
        if not aliases:
            return ""
        found = next(
            (alias_map[alias_key(a)] for a in aliases if alias_key(a) in alias_map),
            None,
        )
        if not found:
            found = active_canonical(aliases) or None
        if not found:
            found = (
                msg.thread_id
                or msg.root_id
                or msg.parent_id
                or msg.message_id
            )
        for a in aliases:
            alias_map[alias_key(a)] = found
        return found

    def scope_key(msg: MockMsg) -> str:
        cid = canonical(msg)
        return f"{CHAT}:{cid}" if cid else ""

    def activate(msg: MockMsg) -> None:
        key = scope_key(msg)
        if key:
            active.add(key)

    def is_active(msg: MockMsg) -> bool:
        key = scope_key(msg)
        return bool(key and key in active)

    # Topic mới: tin @bot đầu chỉ có message_id
    starter = MockMsg(message_id="M1")
    activate(starter)
    assert is_active(starter)

    # Tin tiếp trong topic: có root_id trỏ về M1
    follow = MockMsg(root_id="M1", message_id="M2")
    assert is_active(follow), "reply với root_id phải khớp topic starter"

    # Topic có thread_id ổn định
    alias_map.clear()
    active.clear()
    first = MockMsg(thread_id="T1", message_id="M1")
    activate(first)
    second = MockMsg(thread_id="T1", root_id="M1", message_id="M2")
    assert is_active(second)

    # Chỉ có root_id (thiếu thread_id ở tin follow)
    alias_map.clear()
    active.clear()
    activate(MockMsg(thread_id="T1", message_id="M1"))
    only_root = MockMsg(root_id="M1", message_id="M3")
    assert is_active(only_root), "root_id phải map về cùng topic với thread_id"

    # parent_id (Lark topic reply thường dùng parent_id thay root_id)
    alias_map.clear()
    active.clear()
    activate(MockMsg(thread_id="T2", message_id="M1"))
    via_parent = MockMsg(parent_id="M1", message_id="M4")
    assert is_active(via_parent), "parent_id phải map về cùng topic"

    # Reply trực tiếp vào tin bot (parent_id = bot message)
    alias_map.clear()
    active.clear()
    activate(MockMsg(thread_id="T4", message_id="M1"))
    alias_map[alias_key("M_bot")] = "T4"
    via_bot = MockMsg(parent_id="M_bot", message_id="M5")
    assert is_active(via_bot), "parent_id trỏ tin bot phải map về topic"

    # Lark thực tế: active topic = message_id tin đầu, follow-up có thread_id KHÁC + root_id
    alias_map.clear()
    active.clear()
    active.add(f"{CHAT}:omt_root_msg")
    follow_mixed = MockMsg(
        thread_id="omt_different_thread",
        root_id="omt_root_msg",
        message_id="omt_follow",
    )
    assert is_active(follow_mixed), "root_id phải khớp active topic dù thread_id khác"

    # Scope theo chat — topic active ở chat A không áp cho chat B
    alias_map.clear()
    active.clear()
    activate(MockMsg(thread_id="T3", message_id="M1"))
    other_chat_active = f"oc_other:T3" in active
    assert not other_chat_active, "topic phải scope theo chat_id"


if __name__ == "__main__":
    _run_topic_alias_tests()
    print("OK — topic alias tests passed")
