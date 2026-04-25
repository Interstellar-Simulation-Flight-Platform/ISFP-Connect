"""
FSD (Flight Simulator Data) 协议客户端模块
支持 9号协议连接到 FSD 服务器 (如 fsd.flyisfp.com)
基于 pilotclient 项目中的 FSD 协议实现
"""

import re
import time
import socket
import struct
import logging
import hashlib
from enum import Enum, IntEnum, IntFlag
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Callable, Any, Tuple, Union
from datetime import datetime
from PySide6.QtCore import QObject, QThread, Signal, QTimer, Qt
from PySide6.QtNetwork import QTcpSocket, QAbstractSocket, QHostAddress

# 导入连线日志模块
try:
    from connection_logger import (
        log_fsd_message, log_connection_event, log_connection_error,
        setup_connection_logging, is_logging_enabled
    )
    CONNECTION_LOGGING_AVAILABLE = True
except ImportError:
    CONNECTION_LOGGING_AVAILABLE = False

logger = logging.getLogger('ISFP-Connect.FSD')


class FSDError(Exception):
    """FSD 异常基类"""
    pass


class FSDConnectionError(FSDError):
    """FSD 连接异常"""
    pass


class FSDProtocolError(FSDError):
    """FSD 协议异常"""
    pass


class FSDAuthError(FSDError):
    """FSD 认证异常"""
    pass


# ==================== 协议常量 ====================

class ProtocolRevision(IntEnum):
    """协议版本"""
    CLASSIC = 9                    # 经典 FSD 协议 v9
    VATSIM_ATC = 10                # VATSIM ATC 协议 v10
    VATSIM_AUTH = 100              # VATSIM 认证协议 v100
    VATSIM_VELOCITY = 101          # VATSIM 速度协议 v101


class MessageType(Enum):
    """FSD 消息类型"""
    UNKNOWN = "UNKNOWN"
    ADD_ATC = "ADDATC"
    ADD_PILOT = "ADDPILOT"
    ATC_DATA_UPDATE = "ATCDATAUPDATE"
    AUTH_CHALLENGE = "AUTHCHALLENGE"
    AUTH_RESPONSE = "AUTHRESPONSE"
    CLIENT_IDENTIFICATION = "CLIENTIDENTIFICATION"
    CLIENT_QUERY = "CLIENTQUERY"
    CLIENT_RESPONSE = "CLIENTRESPONSE"
    DELETE_ATC = "DELETEATC"
    DELETE_PILOT = "DELETEPILOT"
    EUROSCOPE_SIM_DATA = "EUROSCOPESIMDATA"
    FLIGHT_PLAN = "FLIGHTPLAN"
    PRO_CONTROLLER = "PROCONTROLLER"
    FSD_IDENTIFICATION = "FSDIDENTIFICATION"
    KILL_REQUEST = "KILLREQUEST"
    PILOT_DATA_UPDATE = "PILOTDATAUPDATE"
    VISUAL_PILOT_DATA_UPDATE = "VISUALPILOTDATAUPDATE"
    VISUAL_PILOT_DATA_PERIODIC = "VISUALPILOTDATAPERIODIC"
    VISUAL_PILOT_DATA_STOPPED = "VISUALPILOTDATASTOPPED"
    VISUAL_PILOT_DATA_TOGGLE = "VISUALPILOTDATATOGGLE"
    PING = "PING"
    PONG = "PONG"
    SERVER_ERROR = "SERVERERROR"
    SERVER_HEARTBEAT = "SERVERHEARTBEAT"
    TEXT_MESSAGE = "TEXTMESSAGE"
    PILOT_CLIENT_COM = "PILOTCLIENTCOM"
    REHOST = "REHOST"
    MUTE = "MUTE"


class PilotRating(IntEnum):
    """飞行员等级"""
    OBS = 0
    S1 = 1
    S2 = 2
    S3 = 3
    C1 = 4
    C2 = 5
    C3 = 6
    I1 = 7
    I2 = 8
    I3 = 9
    SUP = 10
    ADM = 11


class AtcRating(IntEnum):
    """管制员等级"""
    OBS = 0
    S1 = 1
    S2 = 2
    S3 = 3
    C1 = 4
    C2 = 5
    C3 = 6
    I1 = 7
    I2 = 8
    I3 = 9
    SUP = 10
    ADM = 11


class SimType(IntEnum):
    """模拟器类型"""
    UNKNOWN = 0
    MSFS2020 = 1
    XPLANE = 2
    MSFS2004 = 3
    FSX = 4
    P3D = 5
    FLIGHTGEAR = 6


class TransponderMode(IntEnum):
    """应答机模式"""
    OFF = 0
    STANDBY = 1
    ON = 2
    TEST = 3


class Capabilities(IntFlag):
    """客户端能力标志"""
    NONE = 0
    ATC_INFO = 1 << 0              # 支持 ATIS 响应
    SECONDARY_POS = 1 << 1         # 支持次要位置中心点
    AIRCRAFT_INFO = 1 << 2         # 支持现代模型包
    ONGOING_COORD = 1 << 3         # 支持设施间协调
    INTERMIN_POS = 1 << 4          # 支持临时位置更新 (已弃用)
    FAST_POS = 1 << 5              # 支持快速位置更新
    VIS_POS = 1 << 6               # 支持可视位置更新
    STEALTH = 1 << 7               # 隐身模式
    AIRCRAFT_CONFIG = 1 << 8       # 飞机配置
    ICAO_EQUIPMENT = 1 << 9        # ICAO 设备代码


# ==================== 数据结构 ====================

@dataclass
class FSDClientIdentification:
    """客户端识别信息"""
    client_name: str = "ISFP-Connect"
    client_version_major: int = 1
    client_version_minor: int = 0
    cid: str = ""
    sys_uid: str = ""
    initial_challenge: str = ""


@dataclass
class FSDFlightPlan:
    """飞行计划"""
    flight_type: str = "I"         # I=仪表, V=目视
    aircraft_type: str = ""        # ICAO 机型代码
    true_cruise_speed: str = ""    # 巡航速度
    departure_airport: str = ""
    estimated_departure_time: str = ""
    actual_departure_time: str = ""
    cruise_altitude: str = ""
    destination_airport: str = ""
    estimated_enroute_time: str = ""
    fuel_on_board: str = ""
    alternate_airport: str = ""
    remarks: str = ""
    route: str = ""


@dataclass
class FSDPilotPosition:
    """飞行员位置数据"""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_true: int = 0         # 真实高度 (英尺)
    altitude_pressure: int = 0     # 气压高度 (英尺)
    groundspeed: int = 0           # 地速 (节)
    pitch: float = 0.0             # 俯仰角 (度)
    bank: float = 0.0              # 倾斜角 (度)
    heading: float = 0.0           # 航向 (度)
    on_ground: bool = False


@dataclass
class FSDAircraftConfig:
    """飞机配置"""
    icao_code: str = ""
    airline: str = ""
    livery: str = ""
    equipment: str = ""
    transponder: str = ""
    capabilities: str = ""


# ==================== FSD 消息基类 ====================

class FSDMessage:
    """FSD 消息基类"""
    
    # PDU 标识符映射 (根据 FSD9-Protocol.md)
    PDU_IDENTIFIERS = {
        MessageType.ADD_ATC: "#AA",           # 管制员上线
        MessageType.ADD_PILOT: "#AP",         # 飞行员上线 (修复: 使用 #AP 而不是 $AP)
        MessageType.ATC_DATA_UPDATE: "%",      # 管制员主视程点更新
        MessageType.AUTH_CHALLENGE: "$ZC",
        MessageType.AUTH_RESPONSE: "$ZR",
        MessageType.CLIENT_IDENTIFICATION: "$ID",
        MessageType.CLIENT_QUERY: "$CQ",      # 客户端查询
        MessageType.CLIENT_RESPONSE: "$CR",   # 客户端查询回报
        MessageType.DELETE_ATC: "#DA",        # 管制员下线
        MessageType.DELETE_PILOT: "#DP",      # 飞行员下线 (修复: 使用 #DP 而不是 $DP)
        MessageType.FLIGHT_PLAN: "$FP",       # 飞行计划
        MessageType.FSD_IDENTIFICATION: "$DI", # 服务器识别
        MessageType.KILL_REQUEST: "$!!",      # 踢出请求
        MessageType.PILOT_DATA_UPDATE: "@",    # 飞行员数据更新
        MessageType.PING: "$PI",              # Ping
        MessageType.PONG: "$PO",              # Pong
        MessageType.SERVER_ERROR: "$ER",      # 服务器错误
        MessageType.SERVER_HEARTBEAT: "#DL",  # 服务器心跳包 (修复: 使用 #DL)
        MessageType.TEXT_MESSAGE: "#TM",      # 文本消息
        MessageType.REHOST: "$XX",            # 重新托管
        MessageType.MUTE: "#MU",              # 静音
    }
    
    def __init__(self, msg_type: MessageType, sender: str = "", receiver: str = ""):
        self.msg_type = msg_type
        self.sender = sender
        self.receiver = receiver
    
    def serialize(self) -> str:
        """序列化为 FSD 协议格式"""
        raise NotImplementedError
    
    @classmethod
    def parse(cls, data: str) -> 'FSDMessage':
        """从 FSD 协议格式解析"""
        raise NotImplementedError
    
    def _get_pdu_id(self) -> str:
        """获取 PDU 标识符"""
        return self.PDU_IDENTIFIERS.get(self.msg_type, "")


class FSDIdentificationMessage(FSDMessage):
    """FSD 服务器识别消息 ($DI)"""
    
    def __init__(self, server_version: str = "", initial_challenge: str = ""):
        super().__init__(MessageType.FSD_IDENTIFICATION)
        self.server_version = server_version
        self.initial_challenge = initial_challenge
    
    def serialize(self) -> str:
        return f"$DI::{self.server_version}:{self.initial_challenge}\r\n"
    
    @classmethod
    def parse(cls, data: str) -> 'FSDIdentificationMessage':
        # 格式: $DI:SERVER:VERSION:CHALLENGE
        parts = data.strip().split(":")
        if len(parts) >= 4:
            return cls(parts[2], parts[3])
        return cls()


class FSDAddPilotMessage(FSDMessage):
    """添加飞行员消息 (#AP) - 登录用
    
    格式: #AP发送方:接收方:CID:密码:请求权限等级:FSD协议版本:模拟器类型:RealName
    例如: #APB2352:SERVER:2352:123456:1:9:16:2352 ZGHA
    """
    
    def __init__(self, callsign: str = "", cid: str = "", password: str = "",
                 rating: PilotRating = PilotRating.OBS, 
                 protocol: int = ProtocolRevision.CLASSIC,
                 sim_type: int = 16,  # X-Plane 12 = 16
                 real_name: str = ""):
        super().__init__(MessageType.ADD_PILOT, callsign)
        self.callsign = callsign
        self.cid = cid
        self.password = password
        self.rating = rating
        self.protocol = protocol
        self.sim_type = sim_type
        self.real_name = real_name
    
    def serialize(self) -> str:
        # 格式: #AP发送方:接收方:CID:密码:请求权限等级:FSD协议版本:模拟器类型:RealName
        # 例如: #APB2352:SERVER:2352:123456:1:9:16:2352 ZGHA
        return f"#AP{self.callsign}:SERVER:{self.cid}:{self.password}:{self.rating}:{self.protocol}:{self.sim_type}:{self.real_name}\r\n"


class FSDPilotDataUpdateMessage(FSDMessage):
    """飞行员数据更新消息 (@)"""
    
    def __init__(self, callsign: str = "", transponder_code: int = 2000,
                 transponder_mode: TransponderMode = TransponderMode.ON,
                 rating: PilotRating = PilotRating.OBS,
                 position: FSDPilotPosition = None):
        super().__init__(MessageType.PILOT_DATA_UPDATE, callsign)
        self.transponder_code = transponder_code
        self.transponder_mode = transponder_mode
        self.rating = rating
        self.position = position or FSDPilotPosition()
    
    def serialize(self) -> str:
        # 格式: @N:SENDER:TRANSPONDER_CODE:RATING:LAT:LON:ALT:GS:PBH:ON_GROUND
        # 注意: 根据 FSD 协议，PDU 标识符是 "N"，PBH 需要特殊编码
        pos = self.position
        
        # PBH 编码: 将 pitch, bank, heading 打包成一个 32 位整数
        # 这是 FSD 协议的标准编码方式
        def encode_pbh(pitch, bank, heading):
            # 将角度转换为弧度，然后编码
            import math
            p = int((pitch * math.pi / 180.0) * 10430.0) & 0xFFFF
            b = int((bank * math.pi / 180.0) * 10430.0) & 0xFFFF
            h = int((heading * math.pi / 180.0) * 10430.0) & 0xFFFF
            return (p << 16) | (b << 8) | h
        
        pbh = encode_pbh(pos.pitch, pos.bank, pos.heading)
        
        # 使用 "N" 作为 PDU 标识符（标准 FSD 协议）
        return (f"@N:{self.sender}:{self.transponder_code}:{self.rating}:"
                f"{pos.latitude:.6f}:{pos.longitude:.6f}:{pos.altitude_true}:"
                f"{pos.groundspeed}:{pbh}:{1 if pos.on_ground else 0}\r\n")


class FSDTextMessage(FSDMessage):
    """文本消息 (#TM)"""
    
    def __init__(self, sender: str = "", receiver: str = "", message: str = ""):
        super().__init__(MessageType.TEXT_MESSAGE, sender, receiver)
        self.message = message
    
    def serialize(self) -> str:
        # 格式: #TM:SENDER:RECEIVER:MESSAGE
        return f"#TM:{self.sender}:{self.receiver}:{self.message}\r\n"


class FSDPingMessage(FSDMessage):
    """Ping 消息 ($PI)"""
    
    def __init__(self, sender: str = "", timestamp: str = ""):
        super().__init__(MessageType.PING, sender)
        self.timestamp = timestamp or str(int(time.time()))
    
    def serialize(self) -> str:
        return f"$PI:{self.sender}:{self.timestamp}\r\n"


class FSDPongMessage(FSDMessage):
    """Pong 消息 ($PO)"""
    
    def __init__(self, sender: str = "", timestamp: str = ""):
        super().__init__(MessageType.PONG, sender)
        self.timestamp = timestamp
    
    def serialize(self) -> str:
        return f"$PO:{self.sender}:{self.timestamp}\r\n"


class FSDClientQueryMessage(FSDMessage):
    """客户端查询消息 ($CQ)"""
    
    QUERY_TYPES = {
        "ATIS": "请求 ATIS",
        "CAPS": "请求能力",
        "C?": "查询配置",
        "H?": "查询帮助",
        "IP": "查询 IP",
        "INF": "查询信息",
        "RN": "查询真实姓名",
        "SV": "查询服务器",
        "ATC": "查询 ATC 在线",
        "FP": "查询飞行计划",
    }
    
    def __init__(self, sender: str = "", receiver: str = "", query_type: str = ""):
        super().__init__(MessageType.CLIENT_QUERY, sender, receiver)
        self.query_type = query_type
    
    def serialize(self) -> str:
        return f"$CQ:{self.sender}:{self.receiver}:{self.query_type}\r\n"


class FSDClientResponseMessage(FSDMessage):
    """客户端响应消息 ($CR)"""
    
    def __init__(self, sender: str = "", receiver: str = "", response_type: str = "", data: str = ""):
        super().__init__(MessageType.CLIENT_RESPONSE, sender, receiver)
        self.response_type = response_type
        self.data = data
    
    def serialize(self) -> str:
        return f"$CR:{self.sender}:{self.receiver}:{self.response_type}:{self.data}\r\n"


class FSDFlightPlanMessage(FSDMessage):
    """飞行计划消息 ($FP)"""
    
    def __init__(self, callsign: str = "", flight_plan: FSDFlightPlan = None):
        super().__init__(MessageType.FLIGHT_PLAN, callsign)
        self.flight_plan = flight_plan or FSDFlightPlan()
    
    def serialize(self) -> str:
        fp = self.flight_plan
        return (f"$FP:{self.sender}:{fp.flight_type}:{fp.aircraft_type}:"
                f"{fp.true_cruise_speed}:{fp.departure_airport}:"
                f"{fp.estimated_departure_time}:{fp.actual_departure_time}:"
                f"{fp.cruise_altitude}:{fp.destination_airport}:"
                f"{fp.estimated_enroute_time}:{fp.fuel_on_board}:"
                f"{fp.alternate_airport}:{fp.remarks}:{fp.route}\r\n")


class FSDDeletePilotMessage(FSDMessage):
    """删除飞行员消息 (#DP) - 断开连接用
    
    格式: #DP发送方:接收方
    例如: #DPB2352:SERVER
    """
    
    def __init__(self, callsign: str = ""):
        super().__init__(MessageType.DELETE_PILOT, callsign)
    
    def serialize(self) -> str:
        # 格式: #DP发送方:接收方
        return f"#DP{self.sender}:SERVER\r\n"


class FSDServerErrorMessage(FSDMessage):
    """服务器错误消息 ($ER)"""
    
    def __init__(self, receiver: str = "", error_type: str = "", message: str = ""):
        super().__init__(MessageType.SERVER_ERROR, "", receiver)
        self.error_type = error_type
        self.message = message
    
    @classmethod
    def parse(cls, data: str) -> 'FSDServerErrorMessage':
        # 格式: $ER:RECEIVER:ERROR_TYPE:MESSAGE
        parts = data.strip().split(":", 3)
        if len(parts) >= 4:
            return cls(parts[1], parts[2], parts[3])
        return cls()


# ==================== 消息解析器 ====================

class FSDMessageParser:
    """FSD 消息解析器"""
    
    @staticmethod
    def parse(data: str) -> Optional[FSDMessage]:
        """解析 FSD 消息"""
        data = data.strip()
        if not data:
            return None
        
        # 根据 PDU 标识符判断消息类型
        if data.startswith("$DI:"):
            return FSDIdentificationMessage.parse(data)
        elif data.startswith("$ER:"):
            return FSDServerErrorMessage.parse(data)
        elif data.startswith("#TM"):
            # 格式: #TMSENDER:RECEIVER:MESSAGE
            # 例如: #TMSERVER:1234:Welcome message
            # 使用 partition 分割前两个冒号，剩余部分作为消息内容
            # 去掉 #TM 前缀
            content = data[3:]  # 去掉 #TM
            parts = content.split(":", 2)
            if len(parts) >= 3:
                return FSDTextMessage(parts[0], parts[1], parts[2])
        elif data.startswith("$CQ"):
            # 格式: $CQSENDER:RECEIVER:QUERY_TYPE
            # 例如: $CQSERVER:1234:CAPS
            parts = data.split(":")
            if len(parts) >= 3:
                return FSDClientQueryMessage(parts[1], parts[2], parts[3] if len(parts) > 3 else "")
        elif data.startswith("$PO:"):
            parts = data.split(":")
            if len(parts) >= 3:
                return FSDPongMessage(parts[1], parts[2])
        
        # 未知消息类型
        logger.debug(f"未知消息类型: {data[:50]}...")
        return None


# ==================== FSD 客户端 ====================

class FSDClient(QObject):
    """FSD 协议客户端
    
    支持 9号协议连接到 FSD 服务器 (如 fsd.flyisfp.com)
    """
    
    # 信号
    connected = Signal()
    disconnected = Signal()
    authentication_failed = Signal(str)  # 错误信息
    error = Signal(str)
    message_received = Signal(FSDMessage)
    text_message_received = Signal(str, str, str)  # sender, receiver, message
    position_updated = Signal(str, FSDPilotPosition)  # callsign, position
    pilot_added = Signal(str)  # callsign
    pilot_removed = Signal(str)  # callsign
    atc_added = Signal(str)  # callsign
    atc_removed = Signal(str)  # callsign
    server_error = Signal(str, str)  # error_type, message
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 网络连接
        self.socket = QTcpSocket(self)
        self.socket.connected.connect(self._on_connected)
        self.socket.disconnected.connect(self._on_disconnected)
        self.socket.errorOccurred.connect(self._on_error)
        self.socket.readyRead.connect(self._on_ready_read)
        
        # 状态
        self._is_connected = False
        self._is_authenticated = False
        self._server_version = ""
        self._initial_challenge = ""
        self._capabilities = Capabilities.FAST_POS | Capabilities.VIS_POS
        
        # 用户信息
        self._callsign = ""
        self._cid = ""
        self._password = ""
        self._real_name = ""
        self._rating = 1  # 默认 rating=1，根据 FSD9 协议文档示例
        
        # 心跳定时器
        self._ping_timer = QTimer(self)
        self._ping_timer.timeout.connect(self._send_ping)
        self._ping_interval = 15000  # 15 秒发送一次 ping
        
        # 位置更新定时器
        self._position_timer = QTimer(self)
        self._position_timer.timeout.connect(self._send_position_update)
        self._position_interval = 200  # 0.2 秒发送一次位置更新
        
        # 当前位置
        self._current_position = FSDPilotPosition()
        self._transponder_code = 2000
        self._transponder_mode = TransponderMode.ON
        
        # 接收缓冲区
        self._receive_buffer = ""
        
        # 初始化连线日志
        if CONNECTION_LOGGING_AVAILABLE:
            setup_connection_logging(is_logging_enabled())
            self._log_protocol_documentation()
        
        logger.info("FSDClient 初始化完成")
        if CONNECTION_LOGGING_AVAILABLE:
            log_connection_event('FSDClient', '初始化完成')
    
    def _log_protocol_documentation(self):
        """记录 FSD 协议版本信息到日志"""
        if not CONNECTION_LOGGING_AVAILABLE:
            return
        
        # 记录协议版本信息
        log_connection_event('FSDClient', 'PROTOCOL', 'FSD Protocol 9 (Classic)')
    
    @property
    def is_connected(self) -> bool:
        """是否已连接到服务器"""
        return self._is_connected
    
    @property
    def is_authenticated(self) -> bool:
        """是否已通过认证"""
        return self._is_authenticated
    
    def connect_to_server(self, host: str, port: int = 6809) -> bool:
        """连接到 FSD 服务器
        
        Args:
            host: 服务器地址 (如 fsd.flyisfp.com)
            port: 服务器端口 (默认 6809)
        
        Returns:
            是否成功开始连接
        """
        if self._is_connected:
            logger.warning("已经连接到 FSD 服务器")
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '连接失败', '已经连接到服务器')
            return True
        
        logger.info(f"正在连接到 FSD 服务器: {host}:{port}")
        if CONNECTION_LOGGING_AVAILABLE:
            log_connection_event('FSDClient', '开始连接', f'{host}:{port}')
            log_connection_event('FSDClient', '协议信息', 'FSD Protocol 9 (Classic)')
        
        self.socket.connectToHost(host, port)
        
        result = self.socket.waitForConnected(5000)
        if CONNECTION_LOGGING_AVAILABLE:
            if result:
                log_connection_event('FSDClient', 'TCP连接成功', f'{host}:{port}')
            else:
                log_connection_error('FSDClient', f'TCP连接失败: {self.socket.errorString()}')
        
        return result
    
    def disconnect_from_server(self):
        """断开与 FSD 服务器的连接"""
        if not self._is_connected:
            return
        
        logger.info("断开与 FSD 服务器的连接")
        if CONNECTION_LOGGING_AVAILABLE:
            log_connection_event('FSDClient', '断开连接', f'callsign={self._callsign}')
        
        # 发送断开连接消息
        if self._callsign:
            self._send_message(FSDDeletePilotMessage(self._callsign))
        
        # 停止定时器
        self._ping_timer.stop()
        self._position_timer.stop()
        
        # 断开连接
        self.socket.disconnectFromHost()
        if self.socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            self.socket.waitForDisconnected(1000)
    
    def authenticate(self, callsign: str, cid: str, password: str,
                     real_name: str = "", rating: int = 1,
                     sim_type: int = 16) -> bool:
        """发送认证信息
        
        根据 FSD9-Protocol.md，建立 TCP 连接后应立即发送 #AP 消息进行认证
        格式: #AP发送方:SERVER:CID:密码:权限等级:9:模拟器类型:RealName
        例如: #APB2352:SERVER:2352:123456:1:9:16:2352 ZGHA
        
        参数:
            callsign: 呼号
            cid: CID
            password: 密码
            real_name: 真实姓名
            rating: 权限等级 (根据文档示例使用 1)
            sim_type: 模拟器类型 (X-Plane 11=15, X-Plane 12=16)
        """
        if not self._is_connected:
            logger.error("未连接到服务器，无法认证")
            return False
        
        self._callsign = callsign.upper()
        self._cid = cid
        self._password = password
        self._real_name = real_name
        
        # 对于标准 FSD 9号协议，直接发送明文密码
        password_to_send = password
        
        # 根据 FSD9-Protocol.md 文档示例，rating 使用 1
        rating_value = 1
        
        # 构建 #AP 消息
        # 格式: #AP发送方:SERVER:CID:密码:权限等级:9:模拟器类型:RealName
        auth_msg = f"#AP{self._callsign}:SERVER:{cid}:{password_to_send}:{rating_value}:9:{sim_type}:{real_name}\r\n"
        
        logger.info(f"发送认证信息: callsign={callsign}, cid={cid}, protocol=9")
        if CONNECTION_LOGGING_AVAILABLE:
            log_connection_event('FSDClient', '发送认证', f'原始消息: {repr(auth_msg)}')
        
        # 直接发送原始消息
        encoded_data = auth_msg.encode('utf-8')
        bytes_written = self.socket.write(encoded_data)
        result = bytes_written == len(encoded_data)
        
        if result:
            self._is_authenticated = True
            logger.info("认证信息已发送，等待服务器确认")
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '认证已发送', f'已发送 {bytes_written} bytes')
            
            # 启动心跳检测（每15秒发送一次ping）
            self.start_heartbeat(15000)
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '心跳启动', '每15秒发送一次ping')
        else:
            logger.error("认证发送失败")
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_error('FSDClient', f'认证发送失败: 期望 {len(encoded_data)} bytes, 实际 {bytes_written} bytes')
        
        return result
    
    def send_text_message(self, message: str, receiver: str = ""):
        """发送文本消息
        
        Args:
            message: 消息内容
            receiver: 接收者（空字符串表示发送给所有 ATC）
        """
        if not self._is_authenticated:
            logger.error("未通过认证，无法发送消息")
            return
        
        msg = FSDTextMessage(self._callsign, receiver, message)
        self._send_message(msg)
    
    def send_private_message(self, message: str, receiver: str):
        """发送私聊消息"""
        self.send_text_message(message, receiver)
    
    def update_position(self, position: FSDPilotPosition,
                       transponder_code: int = None,
                       transponder_mode: TransponderMode = None):
        """更新位置信息
        
        位置更新会自动定期发送给服务器
        """
        self._current_position = position
        if transponder_code is not None:
            self._transponder_code = transponder_code
        if transponder_mode is not None:
            self._transponder_mode = transponder_mode
    
    def send_flight_plan(self, flight_plan: FSDFlightPlan):
        """提交飞行计划"""
        if not self._is_authenticated:
            logger.error("未通过认证，无法提交飞行计划")
            return
        
        msg = FSDFlightPlanMessage(self._callsign, flight_plan)
        self._send_message(msg)
    
    def request_atis(self, atc_callsign: str):
        """请求 ATIS 信息"""
        if not self._is_authenticated:
            return
        
        msg = FSDClientQueryMessage(self._callsign, atc_callsign, "ATIS")
        self._send_message(msg)
    
    def _on_connected(self):
        """连接成功回调
        
        根据 FSD9 协议，建立 TCP 连接后，客户端应立即发送 #AP (Add Pilot) 消息进行认证
        """
        self._is_connected = True
        logger.info("已连接到 FSD 服务器")
        if CONNECTION_LOGGING_AVAILABLE:
            log_connection_event('FSDClient', '已连接', 'TCP连接成功，准备发送#AP认证')
        
        # 根据 FSD9-Protocol.md，建立连接后应立即发送 #AP 消息
        # 如果认证信息已设置，立即发送认证
        if self._callsign and self._cid and self._password:
            logger.info(f"自动发送认证信息: callsign={self._callsign}")
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '认证信息', f'Callsign={self._callsign}, CID={self._cid}')
            # 使用设置的 sim_type，默认为 16 (X-Plane 12)
            sim_type = getattr(self, '_sim_type', 16)
            self.authenticate(self._callsign, self._cid, self._password, self._real_name, sim_type=sim_type)
        else:
            logger.warning(f"认证信息不完整: callsign={self._callsign}, cid={self._cid}, password={'已设置' if self._password else '未设置'}")
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '认证失败', f'信息不完整: callsign={self._callsign}, cid={self._cid}, has_password={bool(self._password)}')
        
        self.connected.emit()
    
    def _on_disconnected(self):
        """断开连接回调"""
        was_connected = self._is_connected
        self._is_connected = False
        self._is_authenticated = False
        self._ping_timer.stop()
        self._position_timer.stop()
        logger.info("与 FSD 服务器断开连接")
        if CONNECTION_LOGGING_AVAILABLE and was_connected:
            log_connection_event('FSDClient', '连接断开', '连接已关闭')
        self.disconnected.emit()
    
    def _on_error(self, error_code):
        """错误回调"""
        error_msg = self.socket.errorString()
        logger.error(f"FSD 连接错误: {error_msg}")
        if CONNECTION_LOGGING_AVAILABLE:
            log_connection_error('FSDClient', f'连接错误: {error_msg}')
        self.error.emit(error_msg)
    
    def _on_ready_read(self):
        """数据可读回调"""
        while self.socket.bytesAvailable() > 0:
            data = self.socket.readAll().data().decode('utf-8', errors='ignore')
            
            if CONNECTION_LOGGING_AVAILABLE and data:
                log_connection_event('FSDClient', '原始数据接收', f'字节数={len(data)}, 内容={repr(data[:200])}')
            
            self._receive_buffer += data
            
            # 处理完整的消息（以 \r\n 分隔）
            while '\r\n' in self._receive_buffer:
                line, self._receive_buffer = self._receive_buffer.split('\r\n', 1)
                if CONNECTION_LOGGING_AVAILABLE:
                    log_connection_event('FSDClient', '消息分隔', f'提取消息: {repr(line)}')
                self._process_message(line)
    
    def _process_message(self, data: str):
        """处理接收到的消息"""
        if not data:
            return
        
        logger.debug(f"收到消息: {data[:100]}...")
        if CONNECTION_LOGGING_AVAILABLE:
            log_fsd_message('RECV', data)
            log_connection_event('FSDClient', '消息处理', f'原始数据: {repr(data)}')
        
        # 解析消息
        msg = FSDMessageParser.parse(data)
        if not msg:
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '收到未知消息', f'无法解析: {repr(data[:200])}')
                # 尝试分析消息类型
                if data.startswith('$'):
                    log_connection_event('FSDClient', '消息分析', f'可能是服务器消息: {data[:50]}')
                elif data.startswith('#'):
                    log_connection_event('FSDClient', '消息分析', f'可能是ATC消息: {data[:50]}')
                elif data.startswith('@'):
                    log_connection_event('FSDClient', '消息分析', f'可能是飞行员位置: {data[:50]}')
                else:
                    log_connection_event('FSDClient', '消息分析', f'未知格式: {repr(data[:50])}')
            return
        
        # 处理特定消息类型
        if isinstance(msg, FSDIdentificationMessage):
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '收到$DI', f'version={msg.server_version}, challenge={msg.initial_challenge}')
            self._handle_identification(msg)
        elif isinstance(msg, FSDServerErrorMessage):
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '收到$ER', f'type={msg.error_type}, msg={msg.message}')
            self._handle_server_error(msg)
        elif isinstance(msg, FSDTextMessage):
            self.text_message_received.emit(msg.sender, msg.receiver, msg.message)
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '收到文本消息', f'from={msg.sender}: {msg.message[:50]}')
        elif isinstance(msg, FSDClientQueryMessage):
            # 处理客户端查询，例如 CAPS (能力查询)
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '收到$CQ', f'from={msg.sender}, type={msg.query_type}')
            self._handle_client_query(msg)
        elif isinstance(msg, FSDPongMessage):
            logger.debug(f"收到 Pong: {msg.timestamp}")
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '收到$PO', f'timestamp={msg.timestamp}')
        
        self.message_received.emit(msg)
    
    def _handle_client_query(self, msg: FSDClientQueryMessage):
        """处理客户端查询"""
        if msg.query_type == "CAPS":
            # 服务器查询客户端能力，回复支持的能力
            # 格式: $CR:RECEIVER:SENDER:CAPS:CAPABILITY1:CAPABILITY2:...
            caps_response = f"$CR:{msg.sender}:{self._callsign}:CAPS:ATCINFO:SECPOS:MODELDESC:INTERIMPOS\r\n"
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '发送$CR', f'回复CAPS查询: {caps_response.strip()}')
            encoded_data = caps_response.encode('utf-8')
            self.socket.write(encoded_data)
    
    def _handle_identification(self, msg: FSDIdentificationMessage):
        """处理服务器识别消息"""
        self._server_version = msg.server_version
        self._initial_challenge = msg.initial_challenge
        logger.info(f"服务器版本: {self._server_version}, 挑战: {self._initial_challenge}")
        
        if CONNECTION_LOGGING_AVAILABLE:
            log_connection_event('FSDClient', '协议流程', 'Step 1: 收到 $DI (Server Identification)')
            log_connection_event('FSDClient', '服务器信息', f'Version={self._server_version}, Challenge={self._initial_challenge}')
            log_connection_event('FSDClient', '协议流程', 'Step 2: 准备发送 $AP (Add Pilot) 进行认证')
        
        # 自动发送认证信息（如果已设置）
        if self._callsign and self._cid and self._password:
            logger.info(f"自动发送认证信息: callsign={self._callsign}")
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '认证信息', f'Callsign={self._callsign}, CID={self._cid}, Rating={self._rating}')
            self.authenticate(self._callsign, self._cid, self._password, self._real_name, self._rating)
        else:
            logger.warning(f"认证信息不完整: callsign={self._callsign}, cid={self._cid}, password={'已设置' if self._password else '未设置'}")
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_event('FSDClient', '认证失败', f'信息不完整: callsign={self._callsign}, cid={self._cid}, has_password={bool(self._password)}')
    
    def _handle_server_error(self, msg: FSDServerErrorMessage):
        """处理服务器错误"""
        logger.error(f"服务器错误 [{msg.error_type}]: {msg.message}")
        self.server_error.emit(msg.error_type, msg.message)
        
        # 检查是否是认证失败
        if msg.error_type in ("AUTH", "SYNTAX", "INVALID"):
            self.authentication_failed.emit(msg.message)
            self._is_authenticated = False
    
    def _send_message(self, msg: FSDMessage) -> bool:
        """发送消息"""
        if not self._is_connected:
            logger.error("未连接到服务器，无法发送消息")
            if CONNECTION_LOGGING_AVAILABLE:
                log_connection_error('FSDClient', '发送失败: 未连接')
            return False
        
        data = msg.serialize()
        logger.debug(f"发送消息: {data.strip()}")
        if CONNECTION_LOGGING_AVAILABLE:
            log_fsd_message('SEND', data)
            log_connection_event('FSDClient', '发送数据', f'原始数据: {repr(data)}')
            log_connection_event('FSDClient', '发送数据', f'字节数: {len(data)}, 编码后: {len(data.encode("utf-8"))} bytes')
        
        encoded_data = data.encode('utf-8')
        bytes_written = self.socket.write(encoded_data)
        result = bytes_written == len(encoded_data)
        
        if CONNECTION_LOGGING_AVAILABLE:
            if result:
                log_connection_event('FSDClient', '发送成功', f'已发送 {bytes_written} bytes')
            else:
                log_connection_error('FSDClient', f'发送失败: 期望 {len(encoded_data)} bytes, 实际 {bytes_written} bytes, 错误: {self.socket.errorString()}')
        
        return result
    
    def _send_ping(self):
        """发送心跳 ping"""
        if not self._is_connected:
            return
        
        msg = FSDPingMessage(self._callsign)
        self._send_message(msg)
    
    def _send_position_update(self):
        """发送位置更新"""
        if not self._is_authenticated:
            return
        
        msg = FSDPilotDataUpdateMessage(
            callsign=self._callsign,
            transponder_code=self._transponder_code,
            transponder_mode=self._transponder_mode,
            rating=self._rating,
            position=self._current_position
        )
        self._send_message(msg)
    
    def start_position_updates(self, interval_ms: int = 200):
        """开始定期发送位置更新"""
        self._position_interval = interval_ms
        self._position_timer.start(interval_ms)
    
    def stop_position_updates(self):
        """停止定期发送位置更新"""
        self._position_timer.stop()
    
    def start_heartbeat(self, interval_ms: int = 15000):
        """开始心跳检测"""
        self._ping_interval = interval_ms
        self._ping_timer.start(interval_ms)
    
    def stop_heartbeat(self):
        """停止心跳检测"""
        self._ping_timer.stop()


# ==================== 全局客户端实例 ====================

_fsd_client: Optional[FSDClient] = None


def get_fsd_client(parent=None) -> FSDClient:
    """获取 FSDClient 单例实例"""
    global _fsd_client
    if _fsd_client is None:
        _fsd_client = FSDClient(parent)
    return _fsd_client


def reset_fsd_client():
    """重置客户端（用于测试）"""
    global _fsd_client
    if _fsd_client is not None:
        _fsd_client.disconnect_from_server()
        _fsd_client = None
