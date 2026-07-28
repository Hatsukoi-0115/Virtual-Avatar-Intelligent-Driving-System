"""B站直播评论接入源。

职责：
- 根据直播间号解析真实房间号和弹幕服务器地址
- 在独立线程中连接 B站直播弹幕 WebSocket
- 将观众评论通过回调交给 UI 或业务层处理
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import threading
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Callable

import websockets

try:
    import brotli
except ImportError:  # pragma: no cover - 依赖缺失时只跳过 Brotli 包解析
    brotli = None

LOGGER = logging.getLogger(__name__)

_ROOM_INIT_URL = "https://api.live.bilibili.com/room/v1/Room/room_init?id={room_id}"
_DANMU_INFO_URL = "https://api.live.bilibili.com/room/v1/Danmu/getConf?room_id={room_id}&platform=pc&player=web"
_DANMU_HISTORY_URL = "https://api.live.bilibili.com/xlive/web-room/v1/dM/gethistory?roomid={room_id}&room_type=0"
_DEFAULT_WS_HOST = "broadcastlv.chat.bilibili.com"
_PACKET_HEADER_LENGTH = 16
_OP_HEARTBEAT = 2
_OP_MESSAGE = 5
_OP_AUTH = 7
_OP_AUTH_REPLY = 8


@dataclass(slots=True)
class BilibiliComment:
    """一条 B站直播评论。"""

    user_name: str
    text: str
    source_id: str = ""


@dataclass(slots=True)
class _BilibiliConnectionInfo:
    """B站弹幕连接信息。"""

    room_id: int
    token: str
    host: str
    port: int


class BilibiliCommentSource:
    """B站直播弹幕后台连接器。"""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._on_comment: Callable[[BilibiliComment], None] | None = None
        self._on_status: Callable[[str], None] | None = None
        self._on_debug: Callable[[str], None] | None = None
        self._on_running_changed: Callable[[bool], None] | None = None
        self._message_count = 0
        self._debug_packet_count = 0
        self._debug_command_count = 0
        self._seen_comment_keys: set[str] = set()

    @property
    def is_running(self) -> bool:
        """当前是否正在运行连接线程。"""
        return self._thread is not None and self._thread.is_alive()

    def on_comment(self, callback: Callable[[BilibiliComment], None]) -> None:
        """注册评论回调。"""
        self._on_comment = callback

    def on_status(self, callback: Callable[[str], None]) -> None:
        """注册状态回调。"""
        self._on_status = callback

    def on_debug(self, callback: Callable[[str], None]) -> None:
        """注册调试信息回调。"""
        self._on_debug = callback

    def on_running_changed(self, callback: Callable[[bool], None]) -> None:
        """注册运行状态变化回调。"""
        self._on_running_changed = callback

    def start(self, room_id: int) -> None:
        """启动后台线程连接 B站直播间。"""
        if self.is_running:
            self._emit_status("B站评论已在连接中")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_thread,
            args=(room_id,),
            name="BilibiliCommentSource",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """请求停止后台连接线程。"""
        if not self.is_running:
            return
        self._stop_event.set()
        self._emit_status("正在断开 B站评论")

    def _run_thread(self, room_id: int) -> None:
        """在线程中运行 asyncio 事件循环。"""
        self._emit_running_changed(True)
        try:
            asyncio.run(self._run(room_id))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("B站评论接入失败：%s", exc)
            self._emit_status(f"连接失败：{exc}")
        finally:
            self._emit_running_changed(False)
            if self._stop_event.is_set():
                self._emit_status("已断开 B站评论")

    async def _run(self, room_id: int) -> None:
        """连接弹幕服务器并持续读取评论。"""
        self._emit_status("正在解析直播间")
        info = await asyncio.to_thread(_resolve_connection_info, room_id)
        if self._stop_event.is_set():
            return
        self._emit_status(f"正在连接房间 {info.room_id}")

        uri = f"wss://{info.host}:{info.port}/sub"
        async with websockets.connect(uri, ping_interval=None, close_timeout=2) as websocket:
            await websocket.send(_pack_packet(_build_auth_body(info), _OP_AUTH))
            if self._stop_event.is_set():
                return
            self._emit_status(f"已连接 B站房间 {info.room_id}")

            heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket))
            history_task = asyncio.create_task(self._poll_history_loop(info.room_id))
            try:
                while not self._stop_event.is_set():
                    try:
                        raw_packet = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    self._emit_packet_debug(raw_packet)
                    for payload in _extract_message_payloads(raw_packet):
                        self._handle_message_payload(payload)
            finally:
                heartbeat_task.cancel()
                history_task.cancel()
                await asyncio.gather(heartbeat_task, history_task, return_exceptions=True)

    async def _heartbeat_loop(self, websocket) -> None:
        """定时发送心跳，保持弹幕连接。"""
        while not self._stop_event.is_set():
            await websocket.send(_pack_packet(b"[object Object]", _OP_HEARTBEAT))
            await asyncio.sleep(30)

    async def _poll_history_loop(self, room_id: int) -> None:
        """轮询最近评论，兜底获取直播姬面板可见但 WebSocket 未推送的评论。"""
        while not self._stop_event.is_set():
            try:
                comments = await asyncio.to_thread(_request_history_comments, room_id)
                for comment in comments:
                    self._emit_comment_if_new(comment)
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("B站历史评论轮询失败：%s", exc)
            await asyncio.sleep(2.0)

    def _handle_message_payload(self, payload: bytes) -> None:
        """解析单条弹幕消息并筛选评论。"""
        try:
            message = json.loads(payload.decode("utf-8", errors="ignore"))
        except json.JSONDecodeError:
            return

        command = str(message.get("cmd", ""))
        self._emit_command_debug(command)
        if command.split(":")[0] != "DANMU_MSG":
            return

        info = message.get("info", [])
        if not isinstance(info, list) or len(info) < 3:
            return
        text = str(info[1]).strip()
        user_info = info[2] if isinstance(info[2], list) else []
        user_name = str(user_info[1]).strip() if len(user_info) > 1 else "观众"
        if text:
            self._emit_comment_if_new(BilibiliComment(user_name=user_name or "观众", text=text))

    def _emit_comment(self, comment: BilibiliComment) -> None:
        """触发评论回调。"""
        if self._on_comment is not None:
            self._on_comment(comment)

    def _emit_comment_if_new(self, comment: BilibiliComment) -> None:
        """去重后触发评论回调。"""
        key = comment.source_id or f"{comment.user_name}|{comment.text}"
        if key in self._seen_comment_keys:
            return
        self._seen_comment_keys.add(key)
        if len(self._seen_comment_keys) > 200:
            # 控制去重集合大小，避免长时间直播时内存持续增长。
            self._seen_comment_keys = set(list(self._seen_comment_keys)[-100:])
        self._message_count += 1
        if self._message_count <= 3:
            self._emit_status(f"已收到 B站评论：{comment.text[:16]}")
        self._emit_comment(comment)

    def _emit_status(self, text: str) -> None:
        """触发状态回调。"""
        if self._on_status is not None:
            self._on_status(text)

    def _emit_debug(self, text: str) -> None:
        """触发调试信息回调。"""
        if self._on_debug is not None:
            self._on_debug(text)

    def _emit_packet_debug(self, packet: bytes | str) -> None:
        """输出少量原始包头信息，便于定位弹幕解析问题。"""
        if self._debug_packet_count >= 12:
            return
        for version, operation, body_length in _read_packet_headers(packet):
            if self._debug_packet_count >= 12:
                break
            self._debug_packet_count += 1
            self._emit_debug(
                f"[BilibiliDebug] packet op={operation} ver={version} body={body_length}"
            )

    def _emit_command_debug(self, command: str) -> None:
        """输出少量 B站消息命令，便于确认评论是否进入解析层。"""
        if self._debug_command_count >= 12:
            return
        self._debug_command_count += 1
        self._emit_debug(f"[BilibiliDebug] cmd={command or '<empty>'}")

    def _emit_running_changed(self, running: bool) -> None:
        """触发运行状态变化回调。"""
        if self._on_running_changed is not None:
            self._on_running_changed(running)


def _resolve_connection_info(room_id: int) -> _BilibiliConnectionInfo:
    """解析真实房间号、弹幕 token 和 WebSocket 主机。"""
    room_data = _request_json(_ROOM_INIT_URL.format(room_id=room_id))
    real_room_id = int(room_data.get("data", {}).get("room_id") or room_id)

    danmu_data = _request_json(_DANMU_INFO_URL.format(room_id=real_room_id))
    data = danmu_data.get("data", {})
    token = str(data.get("token", ""))
    host_list = data.get("host_server_list", [])
    host_item = host_list[0] if host_list else {}
    host = str(host_item.get("host") or _DEFAULT_WS_HOST)
    port = int(host_item.get("wss_port") or 443)
    return _BilibiliConnectionInfo(room_id=real_room_id, token=token, host=host, port=port)


def _request_json(url: str) -> dict:
    """请求 B站接口并解析 JSON。"""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            ),
            "Referer": "https://live.bilibili.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=8) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _request_history_comments(room_id: int) -> list[BilibiliComment]:
    """请求 B站最近评论列表。"""
    data = _request_json(_DANMU_HISTORY_URL.format(room_id=room_id)).get("data", {})
    room_comments = data.get("room", [])
    result: list[BilibiliComment] = []
    for item in room_comments:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        user_name = str(item.get("nickname", "")).strip() or "观众"
        source_id = str(item.get("id_str") or f"{item.get('timeline', '')}|{item.get('uid', '')}|{text}")
        if text:
            result.append(BilibiliComment(user_name=user_name, text=text, source_id=source_id))
    return result


def _build_auth_body(info: _BilibiliConnectionInfo) -> bytes:
    """构建 B站弹幕认证包体。"""
    payload = {
        "uid": 0,
        "roomid": info.room_id,
        # 使用 protover=2 请求 zlib 压缩弹幕包，兼容当前 B站 Web 弹幕服务器。
        "protover": 2,
        "platform": "web",
        "type": 2,
        "key": info.token,
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _pack_packet(body: bytes, operation: int, version: int = 1, sequence: int = 1) -> bytes:
    """按 B站弹幕协议封装数据包。"""
    packet_length = _PACKET_HEADER_LENGTH + len(body)
    header = struct.pack(">IHHII", packet_length, _PACKET_HEADER_LENGTH, version, operation, sequence)
    return header + body


def _extract_message_payloads(packet: bytes | str) -> list[bytes]:
    """从 WebSocket 数据包中解析出弹幕消息体。"""
    if isinstance(packet, str):
        packet = packet.encode("utf-8")

    payloads: list[bytes] = []
    offset = 0
    packet_size = len(packet)
    while offset + _PACKET_HEADER_LENGTH <= packet_size:
        packet_length, header_length, version, operation, _sequence = struct.unpack(
            ">IHHII",
            packet[offset:offset + _PACKET_HEADER_LENGTH],
        )
        if packet_length <= 0 or offset + packet_length > packet_size:
            break
        body = packet[offset + header_length:offset + packet_length]
        offset += packet_length

        if operation == _OP_AUTH_REPLY:
            continue
        if operation != _OP_MESSAGE:
            continue
        if version in (0, 1):
            payloads.append(body)
        elif version == 2:
            payloads.extend(_extract_message_payloads(zlib.decompress(body)))
        elif version == 3 and brotli is not None:
            payloads.extend(_extract_message_payloads(brotli.decompress(body)))
    return payloads


def _read_packet_headers(packet: bytes | str) -> list[tuple[int, int, int]]:
    """读取包头中的版本、操作码和包体长度，仅用于诊断。"""
    if isinstance(packet, str):
        packet = packet.encode("utf-8")

    headers: list[tuple[int, int, int]] = []
    offset = 0
    packet_size = len(packet)
    while offset + _PACKET_HEADER_LENGTH <= packet_size:
        packet_length, header_length, version, operation, _sequence = struct.unpack(
            ">IHHII",
            packet[offset:offset + _PACKET_HEADER_LENGTH],
        )
        if packet_length <= 0 or offset + packet_length > packet_size:
            break
        headers.append((version, operation, max(0, packet_length - header_length)))
        offset += packet_length
    return headers
