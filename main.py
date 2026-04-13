import sys
import requests
import ctypes
import time
import json
import os
import shutil
import logging
from datetime import datetime
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, QTextEdit, 
                             QLabel, QTabWidget, QListWidget, QListWidgetItem,
                             QScrollArea, QFrame, QGraphicsBlurEffect, QSplitter,
                             QDialog, QCheckBox, QFileDialog, QComboBox, QDateEdit, 
                             QTimeEdit, QSpinBox, QFormLayout, QGroupBox, QAbstractSpinBox,
                             QGridLayout, QStackedWidget)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import Qt, QSize, QTimer, QThread, Signal, QUrl, QObject, Slot, QSettings, QPropertyAnimation, QEasingCurve, QPoint, QRect
from PySide6.QtGui import QPixmap, QIcon, QFont, QPalette, QColor, QBrush, QImage, QPainter, QPainterPath, QPen
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWebChannel import QWebChannel

# 导入 X-Plane TCP 客户端模块
try:
    from xplane_tcp_client import (
        XPlaneTCPClient, get_xplane_tcp_client
    )
    XPLANE_TCP_AVAILABLE = True
except ImportError as e:
    XPLANE_TCP_AVAILABLE = False
    print(f"X-Plane TCP 客户端模块未加载: {e}")

# 导入 X-Plane 插件管理器
try:
    from xplane_plugin_manager import (
        XPlanePluginManager, get_plugin_manager
    )
    XPLANE_PLUGIN_MANAGER_AVAILABLE = True
except ImportError as e:
    XPLANE_PLUGIN_MANAGER_AVAILABLE = False
    print(f"X-Plane 插件管理器模块未加载: {e}")

# 导入 FSD 客户端模块
try:
    from fsd_client import (
        FSDClient, get_fsd_client,
        FSDPilotPosition, FSDFlightPlan, PilotRating,
        SimType, TransponderMode, ProtocolRevision
    )
    FSD_AVAILABLE = True
except ImportError as e:
    FSD_AVAILABLE = False
    print(f"FSD 模块未加载: {e}")

# 导入灵动岛模块
try:
    from dynamic_island import (
        get_dynamic_island, show_dynamic_island_message,
        update_flight_on_island
    )
    DYNAMIC_ISLAND_AVAILABLE = True
except ImportError as e:
    DYNAMIC_ISLAND_AVAILABLE = False
    print(f"灵动岛模块未加载: {e}")

# ================= 日志配置 =================
def setup_logging():
    """配置日志记录"""
    # 确保 logs 文件夹存在
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    log_file = os.path.join(logs_dir, 'main.log')
    xz_log_file = os.path.join(logs_dir, 'xzphotos_get.log')
    
    # 创建格式化器
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 主日志文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='w')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    
    # XZPhotos 专用日志处理器
    xz_file_handler = logging.FileHandler(xz_log_file, encoding='utf-8', mode='w')
    xz_file_handler.setFormatter(formatter)
    xz_file_handler.setLevel(logging.DEBUG)
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    
    # 根日志配置
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # XZPhotos 专用日志配置
    xz_logger = logging.getLogger('ISFP-Connect.XZPhotos')
    xz_logger.addHandler(xz_file_handler)
    xz_logger.propagate = False  # 不向父日志传播
    
    return logging.getLogger('ISFP-Connect')

# 初始化日志
logger = setup_logging()
logger.info("=" * 60)
logger.info("ISFP-Connect 应用程序启动")
logger.info("=" * 60)

# 加载 .env 文件
def load_env_file():
    """从 .env 文件加载环境变量"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

load_env_file()
logger.info("已加载 .env 文件")

# ================= API 配置 =================
ISFP_API_BASE = "https://isfpapi.flyisfp.com/api"
TAF_API_URL = "https://aviationweather.gov/api/data/taf"
# XZPhotos API 配置
XZPHOTOS_API_BASE = "https://api.xzphotos.cn/api/v1"
XZPHOTOS_API_KEY = os.environ.get('XZPHOTOS_API_KEY', '')
XZPHOTOS_API_SECRET = os.environ.get('XZPHOTOS_API_SECRET', '')

logger.info(f"XZPhotos API 配置: 已配置")

# 应用版本信息
APP_VERSION = os.environ.get('APP_VERSION', '1.0.0')
APP_VERSION_CODE = int(os.environ.get('APP_VERSION_CODE', '1'))
CHANGELOG = os.environ.get('CHANGELOG', '')

logger.info(f"应用版本: {APP_VERSION} (build {APP_VERSION_CODE})")

import hashlib
import hmac
import uuid
import time as time_module

def generate_xzphotos_signature(params, secret_key):
    """生成 XZPhotos API 签名
    
    签名算法:
    1. 生成 timestamp 和 nonce
    2. 将所有参数（包括 timestamp 和 nonce）按 key 字母顺序排序
    3. 用 & 连接成 key=value 格式的字符串
    4. 使用 secret_key 作为 HMAC-SHA256 的 key，对参数字符串进行签名
    """
    sig_logger = logging.getLogger('ISFP-Connect.XZPhotos.Signature')
    sig_logger.debug(f"签名生成 - 输入参数: {params}")
    
    # 生成时间戳和 nonce
    timestamp = str(int(time_module.time()))
    nonce = str(uuid.uuid4())
    sig_logger.debug(f"生成时间戳: {timestamp}, Nonce: {nonce}")
    
    # 合并参数
    all_params = {**params, 'timestamp': timestamp, 'nonce': nonce}
    sig_logger.debug(f"合并后参数: {all_params}")
    
    # 按 key 排序
    sorted_keys = sorted(all_params.keys())
    sig_logger.debug(f"排序后的 keys: {sorted_keys}")
    
    param_string = '&'.join([f'{k}={all_params[k]}' for k in sorted_keys])
    sig_logger.debug(f"参数字符串: {param_string}")
    
    # 使用 HMAC-SHA256 签名，secret_key 作为 key
    signature = hmac.new(
        secret_key.encode('utf-8'),
        param_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    sig_logger.debug(f"生成的签名: {signature}")
    
    return {
        'timestamp': timestamp,
        'nonce': nonce,
        'signature': signature,
        'param_string': param_string
    }

class APIThread(QThread):
    finished = Signal(dict)
    error = Signal(str)
    jwt_expired = Signal()

    def __init__(self, url, params=None, is_json=True, headers=None, method="GET", json_data=None):
        super().__init__()
        self.url = url
        self.params = params
        self.is_json = is_json
        self.headers = headers or {}
        self.method = method
        self.json_data = json_data

    def run(self):
        try:
            start_time = time.time()
            if self.method == "POST":
                response = requests.post(self.url, params=self.params, json=self.json_data, headers=self.headers, timeout=10)
            elif self.method == "DELETE":
                response = requests.delete(self.url, params=self.params, json=self.json_data, headers=self.headers, timeout=10)
            else:
                response = requests.get(self.url, params=self.params, headers=self.headers, timeout=10)
            
            end_time = time.time()
            latency = int((end_time - start_time) * 1000)
            
            result = {}
            if self.is_json:
                result = response.json()
                # 检测JWT过期或认证错误
                error_code = result.get("code", "")
                if error_code in ["MISSING_OR_MALFORMED_JWT", "UNAUTHORIZED", "TOKEN_EXPIRED", "JWT_EXPIRED", "401", 401]:
                    self.jwt_expired.emit()
                    return
                # 也检查 message 中是否包含过期关键词
                message = result.get("message", "").lower()
                if any(keyword in message for keyword in ["token", "jwt", "expired", "过期", "未授权", "unauthorized"]):
                    self.jwt_expired.emit()
                    return
            else:
                result = {"raw_text": response.text}
            
            # 注入延迟数据
            result["_latency"] = latency
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

class XZPhotosAPIThread(QThread):
    """专门用于 XZPhotos API 的线程，自动处理签名"""
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, registration, api_key=None, api_secret=None):
        super().__init__()
        self.registration = registration
        self.api_key = api_key or XZPHOTOS_API_KEY
        self.api_secret = api_secret or XZPHOTOS_API_SECRET
    
    def run(self):
        xz_logger = logging.getLogger('ISFP-Connect.XZPhotos')
        try:
            xz_logger.info(f"=" * 60)
            xz_logger.info(f"XZPhotos API 请求开始 - 注册号: {self.registration}")
            xz_logger.info(f"=" * 60)
            
            # 准备参数（不包含 registration，因为它在路径中）
            params = {
                'limit': '1',
                'page': '1'
            }
            xz_logger.debug(f"请求参数: {params}")
            
            # 生成签名
            sig_data = generate_xzphotos_signature(params, self.api_secret)
            xz_logger.debug(f"生成的时间戳: {sig_data['timestamp']}")
            xz_logger.debug(f"生成的 Nonce: {sig_data['nonce']}")
            
            # 构建 URL（参数需要编码）
            from urllib.parse import urlencode
            encoded_params = urlencode({
                'limit': '1',
                'page': '1',
                'timestamp': sig_data['timestamp'],
                'nonce': sig_data['nonce']
            })
            url = f"{XZPHOTOS_API_BASE}/aircraft-images/{self.registration}?{encoded_params}"
            xz_logger.info(f"请求 URL: {url}")
            
            # 设置请求头
            headers = {
                'X-SECRET-ID': self.api_key,
                'X-SIGNATURE': sig_data['signature'],
                'X-TIMESTAMP': sig_data['timestamp'],
                'X-NONCE': sig_data['nonce']
            }
            xz_logger.info(f"请求头已设置")
            
            # 发送请求
            xz_logger.info(f"发送 GET 请求...")
            response = requests.get(url, headers=headers, timeout=10)
            xz_logger.info(f"响应状态码: {response.status_code}")
            xz_logger.debug(f"响应内容: {response.text[:500]}")
            
            result = response.json()
            xz_logger.info(f"解析后的响应: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")
            
            # 转换为与旧 API 兼容的格式
            if result.get('success') and result.get('data', {}).get('images'):
                images = result['data']['images']
                if images:
                    # 获取第一张图片
                    img = images[0]
                    compatible_result = {
                        'success': True,
                        'data': {
                            'photo_found': True,
                            'photo_image_url': img.get('watermark_url') or img.get('original_url'),
                            'aircraft_type': img.get('aircraft_info', {}).get('aircraft_model', ''),
                            'airline': img.get('aircraft_info', {}).get('airline', ''),
                            'registration': self.registration
                        }
                    }
                    xz_logger.info(f"找到图片: {compatible_result['data']['photo_image_url'][:60]}...")
                else:
                    compatible_result = {
                        'success': True,
                        'data': {'photo_found': False}
                    }
                    xz_logger.info(f"未找到图片 (images 为空)")
            else:
                compatible_result = {
                    'success': False,
                    'data': {'photo_found': False}
                }
                xz_logger.warning(f"API 返回失败: success={result.get('success')}, message={result.get('message', 'N/A')}")
            
            xz_logger.info(f"转换后的结果: {json.dumps(compatible_result, ensure_ascii=False)}")
            xz_logger.info(f"XZPhotos API 请求完成")
            self.finished.emit(compatible_result)
        except Exception as e:
            xz_logger.error(f"XZPhotos API 请求异常: {str(e)}")
            xz_logger.exception("详细异常信息:")
            self.error.emit(str(e))

# ================= 工具类：防抖装饰器 =================
def debounce(wait_ms=500):
    """ 装饰器：防止按钮被快速重复点击 """
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            current_time = time.time() * 1000
            if not hasattr(self, '_last_click_time'):
                self._last_click_time = {}
            
            # 使用函数名作为 key，区分不同按钮
            key = func.__name__
            last_time = self._last_click_time.get(key, 0)
            
            if current_time - last_time < wait_ms:
                # print(f"DEBUG: Click ignored for {key}")
                return
            
            self._last_click_time[key] = current_time
            return func(self, *args, **kwargs)
        return wrapper
    return decorator

class DispatchManager:
    """ 签派数据管理器：处理机库和航班历史 """
    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        self.hangar_file = os.path.join(data_dir, "hangar.json")
        self.history_file = os.path.join(data_dir, "flight_history.json")
        self.hangar = self.load_json(self.hangar_file)
        self.history = self.load_json(self.history_file)

    def load_json(self, path):
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []

    def save_json(self, path, data):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def add_aircraft(self, aircraft):
        self.hangar.append(aircraft)
        self.save_json(self.hangar_file, self.hangar)

    def add_flight(self, flight):
        flight['status'] = '计划'  # 默认状态
        self.history.insert(0, flight) # 最新航班排前面
        self.save_json(self.history_file, self.history)

    def delete_flight(self, flight):
        if flight in self.history:
            self.history.remove(flight)
            self.save_json(self.history_file, self.history)

    def clear_history(self):
        self.history = []
        self.save_json(self.history_file, self.history)

    def update_flight_status(self, flight, new_status):
        """更新航班状态 - 使用航班号和日期作为唯一标识"""
        callsign = flight.get('callsign')
        date = flight.get('date')
        
        for index, f in enumerate(self.history):
            if f.get('callsign') == callsign and f.get('date') == date:
                self.history[index]['status'] = new_status
                self.save_json(self.history_file, self.history)
                # 同时更新传入的flight对象的状态
                flight['status'] = new_status
                return True
        return False

    def delete_aircraft(self, aircraft):
        # 使用注册号作为唯一标识尝试删除，或者直接比较字典
        #由于字典比较是完全匹配，可以直接用 remove
        if aircraft in self.hangar:
            self.hangar.remove(aircraft)
            self.save_json(self.hangar_file, self.hangar)

    def update_aircraft(self, old_data, new_data):
        if old_data in self.hangar:
            index = self.hangar.index(old_data)
            self.hangar[index] = new_data
            self.save_json(self.hangar_file, self.hangar)

class MapBridge(QObject):
    """ 连飞地图 JS 交互桥接 """
    # 定义信号，用于从 Python 向 JS 推送数据
    updatePilotsSignal = Signal(str)
    drawPathSignal = Signal(str)

    def __init__(self, app):
        super().__init__()
        self.app = app

    @Slot(str)
    def get_flight_path(self, callsign):
        self.app.fetch_flight_path(callsign)

    @Slot()
    def map_ready(self):
        """ JS 通知地图已加载完毕 """
        self.app._map_js_ready = True
        # 立即触发一次数据加载
        QTimer.singleShot(100, self.app.load_map_data)

class AddAircraftDialog(QDialog):
    def __init__(self, parent=None, aircraft_data=None):
        super().__init__(parent)
        self.setWindowTitle("修改航空器" if aircraft_data else "添加航空器")
        self.setFixedSize(420, 380)
        self.parent_app = parent
        self.image_path = None
        self.aircraft_data = aircraft_data
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # 标题
        title = QLabel("✈️ 修改航空器" if aircraft_data else "✈️ 添加航空器")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title.setStyleSheet("color: white; margin-bottom: 5px;")
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: rgba(255,255,255,0.2);")
        line.setFixedHeight(1)
        main_layout.addWidget(line)
        
        # 表单区域
        form_layout = QFormLayout()
        form_layout.setContentsMargins(0, 10, 0, 0)
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        
        # 设置表单标签样式
        form_layout.setHorizontalSpacing(15)
        form_layout.setVerticalSpacing(12)
        
        # 输入框样式
        input_style = """
            QLineEdit { 
                padding: 6px 10px; 
                border-radius: 5px; 
                border: 1px solid rgba(255,255,255,0.2); 
                background: rgba(255,255,255,0.1); 
                color: white;
                font-size: 13px;
            }
            QLineEdit:focus { border: 1px solid #3498db; }
        """
        
        # 机型输入
        self.type_input = QLineEdit()
        self.type_input.setPlaceholderText("如: A320, B737")
        self.type_input.setStyleSheet(input_style)
        form_layout.addRow("机型 (Type):", self.type_input)
        
        # 注册号输入
        self.reg_input = QLineEdit()
        self.reg_input.setPlaceholderText("如: B-1234")
        self.reg_input.setStyleSheet(input_style)
        form_layout.addRow("注册号 (Reg):", self.reg_input)
        
        # 航司输入
        self.airline_input = QLineEdit()
        self.airline_input.setPlaceholderText("如: CCA, CES")
        self.airline_input.setStyleSheet(input_style)
        form_layout.addRow("航司 (ICAO):", self.airline_input)
        
        # 图片选择区域
        img_widget = QWidget()
        img_layout = QHBoxLayout(img_widget)
        img_layout.setContentsMargins(0, 0, 0, 0)
        img_layout.setSpacing(8)
        
        self.img_label = QLabel("未选择图片")
        self.img_label.setStyleSheet("""
            color: #aaa; 
            padding: 6px 10px;
            background: rgba(255,255,255,0.05);
            border-radius: 5px;
            border: 1px dashed rgba(255,255,255,0.2);
            font-size: 12px;
        """)
        
        btn_select = QPushButton("选择图片")
        btn_select.setCursor(Qt.PointingHandCursor)
        btn_select.setStyleSheet("""
            QPushButton { 
                padding: 6px 12px; 
                background: rgba(52, 152, 219, 0.8); 
                color: white; 
                border: none; 
                border-radius: 5px;
                font-size: 12px;
            }
            QPushButton:hover { background: #3498db; }
        """)
        btn_select.clicked.connect(self.select_image)
        
        img_layout.addWidget(self.img_label, 1)
        img_layout.addWidget(btn_select)
        form_layout.addRow("飞机图片:", img_widget)
        
        # 提示信息
        hint_label = QLabel("若不上传图片，将自动从网络获取")
        hint_label.setStyleSheet("color: #f39c12; font-size: 11px;")
        form_layout.addRow("", hint_label)
        
        main_layout.addLayout(form_layout)
        main_layout.addStretch()
        
        # 填充数据
        if aircraft_data:
            self.type_input.setText(aircraft_data.get('type', ''))
            self.reg_input.setText(aircraft_data.get('reg', ''))
            self.airline_input.setText(aircraft_data.get('airline', ''))
            if aircraft_data.get('image'):
                self.image_path = aircraft_data['image']
                self.img_label.setText(os.path.basename(self.image_path))
                self.img_label.setStyleSheet("""
                    color: #2ecc71; 
                    padding: 8px 12px;
                    background: rgba(46, 204, 113, 0.1);
                    border-radius: 6px;
                    border: 1px solid rgba(46, 204, 113, 0.3);
                """)
        
        # 按钮区域
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(15)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton { 
                padding: 10px 30px; 
                background: rgba(127, 140, 141, 0.5); 
                color: white; 
                border: none; 
                border-radius: 8px;
                font-size: 14px;
            }
            QPushButton:hover { background: rgba(127, 140, 141, 0.8); }
        """)
        cancel_btn.clicked.connect(self.reject)
        
        save_btn = QPushButton("💾 保存")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet("""
            QPushButton { 
                padding: 10px 30px; 
                background: rgba(46, 204, 113, 0.8); 
                color: white; 
                border: none; 
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background: #2ecc71; }
        """)
        save_btn.clicked.connect(self.accept)
        
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        
        main_layout.addWidget(btn_container)
        
        # 对话框样式
        self.setStyleSheet("""
            QDialog { 
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #1a1a2e, stop:1 #16213e); 
            }
            QLabel { color: white; }
        """)
    
    def create_label(self, text):
        """创建表单标签"""
        label = QLabel(text)
        label.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 14px;")
        return label

    def select_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择飞机图片", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            self.image_path = path
            self.img_label.setText(os.path.basename(path))

    def get_data(self):
        return {
            "type": self.type_input.text().strip().upper(),
            "reg": self.reg_input.text().strip().upper(),
            "airline": self.airline_input.text().strip().upper(),
            "image": self.image_path
        }

class NewFlightDialog(QDialog):
    def __init__(self, hangar, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建航班")
        self.setFixedSize(550, 700)
        self.hangar = hangar
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(25, 25, 25, 25)
        main_layout.setSpacing(15)
        
        # 标题
        title = QLabel("🛫 新建航班计划")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        title.setStyleSheet("color: white; padding-bottom: 10px;")
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: rgba(255,255,255,0.2);")
        line.setFixedHeight(1)
        main_layout.addWidget(line)
        
        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                background: rgba(0, 0, 0, 0.3);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.3);
            }
        """)
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        form_layout = QFormLayout(scroll_content)
        form_layout.setContentsMargins(0, 15, 0, 15)
        form_layout.setSpacing(18)
        form_layout.setLabelAlignment(Qt.AlignRight)
        
        # 基础信息分组
        basic_group = self.create_group_box("📋 基础信息")
        basic_layout = QFormLayout(basic_group)
        basic_layout.setSpacing(12)
        
        self.callsign_input = QLineEdit()
        self.callsign_input.setPlaceholderText("如: CCA1234")
        self.callsign_input.setStyleSheet(self.get_input_style())
        basic_layout.addRow(self.create_label("航班号:"), self.callsign_input)
        
        # 机场选择行
        airport_widget = QWidget()
        airport_layout = QHBoxLayout(airport_widget)
        airport_layout.setContentsMargins(0, 0, 0, 0)
        airport_layout.setSpacing(10)
        
        self.dep_input = QLineEdit()
        self.dep_input.setPlaceholderText("出发 ICAO")
        self.dep_input.setStyleSheet(self.get_input_style())
        self.dep_input.setMaximumWidth(100)
        
        arrow_label = QLabel("→")
        arrow_label.setStyleSheet("color: #3498db; font-size: 20px; font-weight: bold;")
        arrow_label.setAlignment(Qt.AlignCenter)
        
        self.arr_input = QLineEdit()
        self.arr_input.setPlaceholderText("到达 ICAO")
        self.arr_input.setStyleSheet(self.get_input_style())
        self.arr_input.setMaximumWidth(100)
        
        airport_layout.addWidget(self.dep_input)
        airport_layout.addWidget(arrow_label)
        airport_layout.addWidget(self.arr_input)
        airport_layout.addStretch()
        
        basic_layout.addRow(self.create_label("航段:"), airport_widget)
        
        self.aircraft_combo = QComboBox()
        self.aircraft_combo.setStyleSheet(self.get_combo_style())
        for ac in hangar:
            self.aircraft_combo.addItem(f"{ac['reg']} - {ac['type']}", ac)
        basic_layout.addRow(self.create_label("航空器:"), self.aircraft_combo)
        
        form_layout.addRow(basic_group)
        
        # 时间分组
        time_group = self.create_group_box("⏰ 时间设置")
        time_layout = QFormLayout(time_group)
        time_layout.setSpacing(12)
        
        # 起飞时间
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.time_edit.setStyleSheet(self.get_time_style())
        time_layout.addRow(self.create_label("计划起飞 (ETD):"), self.time_edit)
        
        # 落地时间
        self.arr_time_edit = QTimeEdit()
        self.arr_time_edit.setDisplayFormat("HH:mm")
        self.arr_time_edit.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.arr_time_edit.setStyleSheet(self.get_time_style())
        time_layout.addRow(self.create_label("计划落地 (ETA):"), self.arr_time_edit)
        
        # 滑行时间行
        taxi_widget = QWidget()
        taxi_layout = QHBoxLayout(taxi_widget)
        taxi_layout.setContentsMargins(0, 0, 0, 0)
        taxi_layout.setSpacing(15)
        
        self.taxi_out = QSpinBox()
        self.taxi_out.setRange(0, 60)
        self.taxi_out.setValue(10)
        self.taxi_out.setSuffix(" min")
        self.taxi_out.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.taxi_out.setStyleSheet(self.get_spin_style())
        
        self.taxi_in = QSpinBox()
        self.taxi_in.setRange(0, 60)
        self.taxi_in.setValue(5)
        self.taxi_in.setSuffix(" min")
        self.taxi_in.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.taxi_in.setStyleSheet(self.get_spin_style())
        
        takeoff_label = QLabel("起飞:")
        takeoff_label.setStyleSheet("color: white;")
        landing_label = QLabel("落地:")
        landing_label.setStyleSheet("color: white;")
        taxi_layout.addWidget(takeoff_label)
        taxi_layout.addWidget(self.taxi_out)
        taxi_layout.addWidget(landing_label)
        taxi_layout.addWidget(self.taxi_in)
        taxi_layout.addStretch()
        
        time_layout.addRow(self.create_label("滑行时间:"), taxi_widget)
        
        form_layout.addRow(time_group)
        
        # 飞行参数分组
        param_group = self.create_group_box("✈️ 飞行参数")
        param_layout = QFormLayout(param_group)
        param_layout.setSpacing(12)
        
        self.alt_spin = QSpinBox()
        self.alt_spin.setRange(0, 60000)
        self.alt_spin.setValue(30000)
        self.alt_spin.setSingleStep(1000)
        self.alt_spin.setSuffix(" ft")
        self.alt_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.alt_spin.setStyleSheet(self.get_spin_style())
        param_layout.addRow(self.create_label("巡航高度:"), self.alt_spin)
        
        self.ci_spin = QSpinBox()
        self.ci_spin.setRange(0, 999)
        self.ci_spin.setValue(30)
        self.ci_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.ci_spin.setStyleSheet(self.get_spin_style())
        param_layout.addRow(self.create_label("成本指数 (CI):"), self.ci_spin)
        
        self.pax_spin = QSpinBox()
        self.pax_spin.setRange(0, 800)
        self.pax_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.pax_spin.setStyleSheet(self.get_spin_style())
        param_layout.addRow(self.create_label("乘客数:"), self.pax_spin)
        
        self.payload_spin = QSpinBox()
        self.payload_spin.setRange(0, 500000)
        self.payload_spin.setSuffix(" kg")
        self.payload_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.payload_spin.setStyleSheet(self.get_spin_style())
        param_layout.addRow(self.create_label("载荷:"), self.payload_spin)
        
        self.extra_fuel = QSpinBox()
        self.extra_fuel.setSuffix(" min")
        self.extra_fuel.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.extra_fuel.setStyleSheet(self.get_spin_style())
        param_layout.addRow(self.create_label("备用燃油:"), self.extra_fuel)
        
        form_layout.addRow(param_group)
        
        # 航路分组
        route_group = self.create_group_box("🗺️ 航路信息")
        route_layout = QVBoxLayout(route_group)
        
        self.route_input = QTextEdit()
        self.route_input.setPlaceholderText("输入飞行航路，如: DOTRA W56 SJG...")
        self.route_input.setMaximumHeight(100)
        self.route_input.setStyleSheet("""
            QTextEdit { 
                padding: 10px; 
                border-radius: 8px; 
                border: 1px solid rgba(255,255,255,0.2); 
                background: rgba(255,255,255,0.1); 
                color: white;
                font-size: 13px;
            }
            QTextEdit:focus { border: 1px solid #3498db; }
        """)
        route_layout.addWidget(self.route_input)
        
        form_layout.addRow(route_group)
        
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)
        
        # 按钮区域
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 10, 0, 0)
        btn_layout.setSpacing(15)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton { 
                padding: 12px 35px; 
                background: rgba(127, 140, 141, 0.5); 
                color: white; 
                border: none; 
                border-radius: 8px;
                font-size: 14px;
            }
            QPushButton:hover { background: rgba(127, 140, 141, 0.8); }
        """)
        cancel_btn.clicked.connect(self.reject)
        
        save_btn = QPushButton("🚀 创建航班")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet("""
            QPushButton { 
                padding: 12px 35px; 
                background: rgba(46, 204, 113, 0.8); 
                color: white; 
                border: none; 
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background: #2ecc71; }
        """)
        save_btn.clicked.connect(self.accept)
        
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        
        main_layout.addWidget(btn_container)
        
        # 对话框样式
        self.setStyleSheet("""
            QDialog { 
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #1a1a2e, stop:1 #16213e); 
            }
        """)
    
    def create_group_box(self, title):
        """创建分组框"""
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox {
                color: white;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 10px;
                margin-top: 15px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px;
            }
        """)
        return group
    
    def create_label(self, text):
        """创建表单标签"""
        label = QLabel(text)
        label.setStyleSheet("color: rgba(255,255,255,0.85); font-size: 13px;")
        return label
    
    def get_input_style(self):
        """获取输入框样式"""
        return """
            QLineEdit { 
                padding: 10px; 
                border-radius: 8px; 
                border: 1px solid rgba(255,255,255,0.2); 
                background: rgba(255,255,255,0.1); 
                color: white;
                font-size: 13px;
            }
            QLineEdit:focus { border: 1px solid #3498db; }
        """
    
    def get_combo_style(self):
        """获取下拉框样式"""
        return """
            QComboBox { 
                padding: 10px; 
                border-radius: 8px; 
                border: 1px solid rgba(255,255,255,0.2); 
                background: rgba(255,255,255,0.1); 
                color: white;
                font-size: 13px;
            }
            QComboBox:focus { border: 1px solid #3498db; }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox QAbstractItemView {
                background: #2c3e50;
                color: white;
                selection-background-color: #3498db;
            }
        """
    
    def get_time_style(self):
        """获取时间选择器样式"""
        return """
            QTimeEdit { 
                padding: 10px; 
                border-radius: 8px; 
                border: 1px solid rgba(255,255,255,0.2); 
                background: rgba(255,255,255,0.1); 
                color: white;
                font-size: 13px;
            }
            QTimeEdit:focus { border: 1px solid #3498db; }
        """
    
    def get_spin_style(self):
        """获取数字输入框样式"""
        return """
            QSpinBox { 
                padding: 10px; 
                border-radius: 8px; 
                border: 1px solid rgba(255,255,255,0.2); 
                background: rgba(255,255,255,0.1); 
                color: white;
                font-size: 13px;
            }
            QSpinBox:focus { border: 1px solid #3498db; }
        """

    def get_data(self):
        ac_data = self.aircraft_combo.currentData()
        return {
            "callsign": self.callsign_input.text().upper(),
            "dep": self.dep_input.text().upper(),
            "arr": self.arr_input.text().upper(),
            "aircraft": ac_data,
            "etd": self.time_edit.text(),
            "eta": self.arr_time_edit.text(),
            "altitude": self.alt_spin.value(),
            "ci": self.ci_spin.value(),
            "pax": self.pax_spin.value(),
            "taxi_out": self.taxi_out.value(),
            "taxi_in": self.taxi_in.value(),
            "payload": self.payload_spin.value(),
            "extra_fuel": self.extra_fuel.value(),
            "route": self.route_input.toPlainText(),
            "date": time.strftime("%Y-%m-%d")
        }

class FlightDetailsDialog(QDialog):
    # 定义状态变更信号
    status_changed = Signal(str)
    
    def __init__(self, flight, parent=None, editable=False):
        super().__init__(parent)
        self.flight = flight
        self.editable = editable
        self.setWindowTitle(f"航班详情 - {flight.get('callsign')}")
        self.setFixedSize(420, 600)
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # 标题
        title = QLabel("🛫 航班详情")
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        title.setStyleSheet("color: white; margin-bottom: 5px;")
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        
        # 航段信息
        route_title = QLabel(f"{flight.get('dep')} ✈ {flight.get('arr')}")
        route_title.setAlignment(Qt.AlignCenter)
        route_title.setStyleSheet("font-size: 22px; font-weight: bold; color: #3498db; margin-bottom: 10px;")
        main_layout.addWidget(route_title)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: rgba(255,255,255,0.2);")
        line.setFixedHeight(1)
        main_layout.addWidget(line)
        
        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                background: rgba(0, 0, 0, 0.3);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.3);
            }
        """)
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(0, 10, 0, 10)
        content_layout.setSpacing(15)
        
        # 状态管理分组（仅在可编辑模式下显示）
        if editable:
            status_group = self.create_group_box("📍 航班状态")
            status_layout = QVBoxLayout(status_group)
            
            # 当前状态显示
            current_status = flight.get('status', '计划')
            self.status_label = QLabel(f"当前状态: {current_status}")
            self.status_label.setStyleSheet("""
                color: #2ecc71; 
                font-size: 14px; 
                font-weight: bold;
                padding: 8px;
                background: rgba(46, 204, 113, 0.1);
                border-radius: 6px;
            """)
            status_layout.addWidget(self.status_label)
            
            # 状态按钮组
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(0, 10, 0, 0)
            btn_layout.setSpacing(8)
            
            statuses = [
                ("推出", "#e67e22"),
                ("起飞", "#f39c12"),
                ("巡航", "#3498db"),
                ("下降", "#9b59b6"),
                ("落地", "#2ecc71")
            ]
            
            for status, color in statuses:
                btn = QPushButton(status)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet(f"""
                    QPushButton {{
                        padding: 8px 12px;
                        background: {color};
                        color: white;
                        border: none;
                        border-radius: 5px;
                        font-size: 12px;
                        font-weight: bold;
                    }}
                    QPushButton:hover {{
                        background: {color}dd;
                    }}
                """)
                btn.clicked.connect(lambda checked, s=status: self.on_status_change(s))
                btn_layout.addWidget(btn)
            
            status_layout.addWidget(btn_widget)
            content_layout.addWidget(status_group)
        
        # 基础信息分组
        basic_group = self.create_group_box("📋 基础信息")
        basic_form = QFormLayout(basic_group)
        basic_form.setSpacing(10)
        
        self.add_detail_row(basic_form, "航班号:", flight.get('callsign'))
        self.add_detail_row(basic_form, "日期:", flight.get('date'))
        self.add_detail_row(basic_form, "机型:", flight.get('aircraft', {}).get('type', 'Unknown'))
        self.add_detail_row(basic_form, "注册号:", flight.get('aircraft', {}).get('reg', 'Unknown'))
        if not editable:
            self.add_detail_row(basic_form, "状态:", flight.get('status', '计划'))
        
        content_layout.addWidget(basic_group)
        
        # 时间信息分组
        time_group = self.create_group_box("⏰ 时间信息")
        time_form = QFormLayout(time_group)
        time_form.setSpacing(10)
        
        self.add_detail_row(time_form, "计划起飞 (ETD):", flight.get('etd'))
        self.add_detail_row(time_form, "计划落地 (ETA):", flight.get('eta', '--:--'))
        
        content_layout.addWidget(time_group)
        
        # 飞行参数分组
        param_group = self.create_group_box("✈️ 飞行参数")
        param_form = QFormLayout(param_group)
        param_form.setSpacing(10)
        
        self.add_detail_row(param_form, "巡航高度:", f"{flight.get('altitude')} ft")
        self.add_detail_row(param_form, "成本指数 (CI):", flight.get('ci', 'N/A'))
        self.add_detail_row(param_form, "乘客数:", flight.get('pax'))
        self.add_detail_row(param_form, "载荷:", f"{flight.get('payload')} kg")
        self.add_detail_row(param_form, "备用燃油:", f"{flight.get('extra_fuel', 0)} min")
        
        content_layout.addWidget(param_group)
        
        # 航路信息分组
        route_group = self.create_group_box("🗺️ 航路信息")
        route_layout = QVBoxLayout(route_group)
        
        route_text = QTextEdit()
        route_text.setPlainText(flight.get('route', 'N/A'))
        route_text.setReadOnly(True)
        route_text.setMaximumHeight(80)
        route_text.setStyleSheet("""
            QTextEdit { 
                padding: 10px; 
                border-radius: 6px; 
                border: 1px solid rgba(255,255,255,0.2); 
                background: rgba(255,255,255,0.05); 
                color: white;
                font-size: 12px;
            }
        """)
        route_layout.addWidget(route_text)
        
        content_layout.addWidget(route_group)
        content_layout.addStretch()
        
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)
        
        # 关闭按钮
        close_btn = QPushButton("✓ 关闭")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("""
            QPushButton {
                margin-top: 10px; 
                padding: 10px 30px; 
                background: rgba(52, 152, 219, 0.8); 
                color: white; 
                border: none; 
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background: #3498db; }
        """)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)
        
        # 对话框样式
        self.setStyleSheet("""
            QDialog { 
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #1a1a2e, stop:1 #16213e); 
            }
            QLabel { color: white; }
        """)
    
    def on_status_change(self, new_status):
        """处理状态变更"""
        self.status_label.setText(f"当前状态: {new_status}")
        self.status_changed.emit(new_status)
    
    def create_group_box(self, title):
        """创建分组框"""
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox {
                color: white;
                font-size: 13px;
                font-weight: bold;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px;
            }
        """)
        return group
    
    def add_detail_row(self, form_layout, label, value):
        """添加详情行"""
        lbl = QLabel(label)
        lbl.setStyleSheet("color: rgba(255,255,255,0.7); font-size: 12px;")
        val = QLabel(str(value))
        val.setStyleSheet("color: white; font-size: 13px; font-weight: 500;")
        form_layout.addRow(lbl, val)

class ISFPApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ISFP Connect")
        # 设置窗口图标
        self.setWindowIcon(QIcon("assets/logo.png"))
        # 设置 16:9 比例 (例如 1280x720)
        self.win_width = 1280
        self.win_height = 720
        self.resize(self.win_width, self.win_height) # 移除固定大小限制，允许调整
        
        # 用户认证数据
        self.auth_token = None
        self.user_data = None
        
        # 初始化设置 - 使用本地 ini 文件存储，不使用注册表
        # 将配置保存在 data 文件夹下的 config.ini 中
        import os
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        config_path = os.path.join(data_dir, "config.ini")
        self.settings = QSettings(config_path, QSettings.IniFormat)
        
        # 签派数据管理器
        self.dispatch_manager = DispatchManager(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
        
        # 线程管理器，防止 QThread 被 GC 回收
        self._active_threads = set()
        
        # 初始化 X-Plane 插件管理器
        self._init_plugin_manager()
        
        self.setup_ui()
        
        # 加载保存的 X-Plane 路径
        self._load_xplane_path()
        
        # 启动时检查插件状态
        self._check_plugin_status_on_startup()
        
        # 初始化灵动岛
        self._init_dynamic_island()
        
        # 启动时检查登录状态
        if not self.auth_token:
            # 默认显示账户页面（登录页面）
            self.switch_page(9)  # 账户页面现在是第9个
    
    def _init_plugin_manager(self):
        """初始化 X-Plane 插件管理器"""
        if XPLANE_PLUGIN_MANAGER_AVAILABLE:
            try:
                self.plugin_manager = get_plugin_manager(self.settings, self)
                # 连接信号
                self.plugin_manager.path_changed.connect(self._on_xplane_path_changed)
                self.plugin_manager.version_detected.connect(self._on_xplane_version_detected)
                self.plugin_manager.plugin_installed.connect(self._on_plugin_installed)
                self.plugin_manager.plugin_uninstalled.connect(self._on_plugin_uninstalled)
                logger.info("X-Plane 插件管理器初始化成功")
            except Exception as e:
                logger.error(f"初始化插件管理器失败: {e}")
                self.plugin_manager = None
        else:
            self.plugin_manager = None
    
    def _check_plugin_status_on_startup(self):
        """启动时检查插件状态"""
        if self.plugin_manager:
            try:
                status = self.plugin_manager.check_and_update_status()
                logger.info(f"启动时插件状态检查: {status}")
            except Exception as e:
                logger.error(f"启动时检查插件状态失败: {e}")
    
    def _on_xplane_path_changed(self, path: str):
        """X-Plane 路径改变回调"""
        logger.info(f"X-Plane 路径已更改: {path}")
        # 更新设置页面的显示
        if hasattr(self, 'xplane_path_label'):
            self.xplane_path_label.setText(f"当前路径: {path}")
    
    def _on_xplane_version_detected(self, version: int):
        """检测到 X-Plane 版本回调"""
        logger.info(f"检测到 X-Plane 版本: {version}")
        # 更新设置页面的显示
        if hasattr(self, 'xplane_version_label'):
            self.xplane_version_label.setText(f"检测版本: X-Plane {version}")
    
    def _on_plugin_installed(self, success: bool, message: str):
        """插件安装完成回调"""
        if success:
            self.show_notification(f"✅ {message}")
            logger.info(message)
        else:
            self.show_notification(f"❌ {message}")
            logger.error(message)
        # 更新设置页面的按钮状态
        self._update_plugin_ui_status()
    
    def _on_plugin_uninstalled(self, success: bool, message: str):
        """插件卸载完成回调"""
        if success:
            self.show_notification(f"✅ {message}")
            logger.info(message)
        else:
            self.show_notification(f"❌ {message}")
            logger.error(message)
        # 更新设置页面的按钮状态
        self._update_plugin_ui_status()
    
    def _load_xplane_path(self):
        """加载保存的 X-Plane 路径（由插件管理器处理）"""
        # 插件管理器会自动加载保存的路径
        pass
    
    def _init_dynamic_island(self):
        """初始化灵动岛"""
        try:
            from dynamic_island import get_dynamic_island
            # 获取灵动岛实例（如果启用了会自动显示）
            self.dynamic_island = get_dynamic_island(self)
            logger.info("灵动岛已初始化")
        except ImportError:
            logger.warning("灵动岛模块未找到")
            self.dynamic_island = None

    def resizeEvent(self, event):
        """ 处理窗口大小调整事件 """
        new_size = event.size()
        
        # 调整背景和遮罩层
        if hasattr(self, 'bg_label'):
            self.bg_label.setGeometry(0, 0, new_size.width(), new_size.height())
            if hasattr(self, 'bg_pixmap') and not self.bg_pixmap.isNull():
                self.bg_label.setPixmap(self.bg_pixmap.scaled(
                    new_size.width(), 
                    new_size.height(), 
                    Qt.KeepAspectRatioByExpanding, 
                    Qt.SmoothTransformation
                ))
                
        if hasattr(self, 'bg_overlay'):
            self.bg_overlay.setGeometry(0, 0, new_size.width(), new_size.height())
            
        super().resizeEvent(event)

    def manage_thread(self, thread):
        """ 托管线程生命周期，防止被 GC 回收导致崩溃 """
        self._active_threads.add(thread)
        
        def cleanup():
            if thread in self._active_threads:
                self._active_threads.remove(thread)
                
        def handle_jwt_expired():
            """ 处理JWT过期 """
            self.auth_token = None
            self.user_data = None
            self.update_account_ui()
            self.show_notification("登录已过期，请重新登录")
            # 显示登录页面
            self.switch_page(9)  # 账户页面现在是第9个
        
        thread.finished.connect(cleanup)
        if hasattr(thread, 'jwt_expired'):
            thread.jwt_expired.connect(handle_jwt_expired)
        thread.start()

    def setup_ui(self):
        # 主窗口背景
        self.bg_label = QLabel(self)
        self.bg_label.setGeometry(0, 0, self.win_width, self.win_height)
        
        # 检查是否有自定义背景
        custom_bg = self.settings.value("custom_bg_path", "")
        if custom_bg and os.path.exists(custom_bg):
            # 使用自定义背景
            self.bg_pixmap = QPixmap(custom_bg)
            if not self.bg_pixmap.isNull():
                self.bg_label.setPixmap(self.bg_pixmap.scaled(self.win_width, self.win_height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        else:
            # 使用默认背景
            default_bg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "background.png")
            self.bg_pixmap = QPixmap(default_bg)
            if not self.bg_pixmap.isNull():
                self.bg_label.setPixmap(self.bg_pixmap.scaled(self.win_width, self.win_height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            else:
                self.bg_label.setStyleSheet("background-color: #1a1a1a;")

        # 【核心优化】添加黑色半透明遮罩层，确保背景不会干扰文字阅读
        self.bg_overlay = QFrame(self)
        self.bg_overlay.setGeometry(0, 0, self.win_width, self.win_height)
        # 透明度设置为 0.78 (200/255)，背景会变暗但依然可见
        self.bg_overlay.setStyleSheet("background-color: rgba(0, 0, 0, 200); border: none;")
        self.bg_overlay.lower() # 确保在所有交互控件下方
        self.bg_label.lower()   # 确保背景图在最底层

        # 核心容器 - 使用水平布局，左侧导航，右侧内容
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 全局样式 - 添加动画效果
        self.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 8px;
                padding: 10px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(52, 152, 219, 0.8);
            }
            QPushButton:pressed {
                background-color: rgba(41, 128, 185, 1.0);
            }
            QListWidget::item:hover {
                background: rgba(52, 152, 219, 0.3);
            }
            QLineEdit {
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 8px;
                padding: 10px;
                background: rgba(255, 255, 255, 0.05);
                color: white;
            }
            QLineEdit:focus {
                border: 2px solid #3498db;
                background: rgba(255, 255, 255, 0.1);
            }
            QTextEdit {
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 8px;
                padding: 10px;
                background: rgba(255, 255, 255, 0.05);
                color: white;
            }
            QTextEdit:focus {
                border: 2px solid #3498db;
            }
            QComboBox {
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 8px;
                padding: 8px;
                background: rgba(255, 255, 255, 0.05);
                color: white;
            }
            QComboBox:hover {
                border: 1px solid #3498db;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QSpinBox, QDateEdit, QTimeEdit {
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 8px;
                padding: 8px;
                background: rgba(255, 255, 255, 0.05);
                color: white;
            }
            QSpinBox:focus, QDateEdit:focus, QTimeEdit:focus {
                border: 2px solid #3498db;
            }
            QGroupBox {
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                color: #3498db;
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QCheckBox {
                color: #ccc;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #555;
                background: rgba(255, 255, 255, 0.1);
            }
            QCheckBox::indicator:checked {
                background: #3498db;
                border-color: #3498db;
            }
            QScrollBar:vertical {
                background: rgba(255, 255, 255, 0.05);
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(52, 152, 219, 0.5);
            }
        """)
        
        # 左侧导航栏
        self.create_sidebar()
        
        # 右侧内容区域
        self.content_area = QWidget()
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(15, 15, 15, 15)
        self.content_layout.setSpacing(10)
        
        # 顶部状态栏
        self.create_top_bar()
        
        # 初始化网络管理器用于图片加载
        self.nam = QNetworkAccessManager(self)
        
        # 创建堆叠窗口用于切换页面
        # 注意：页面顺序必须与导航按钮顺序一致
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(self.create_home_tab())        # 0 - 首页
        self.stacked_widget.addWidget(self.create_connection_tab())  # 1 - 连线（正数第二个）
        self.stacked_widget.addWidget(self.create_weather_tab())     # 2 - 气象
        self.stacked_widget.addWidget(self.create_map_tab())         # 3 - 地图
        self.stacked_widget.addWidget(self.create_rating_tab())      # 4 - 排行
        self.stacked_widget.addWidget(self.create_dispatch_tab())    # 5 - 签派
        self.stacked_widget.addWidget(self.create_flight_plan_tab()) # 6 - 计划
        self.stacked_widget.addWidget(self.create_activities_tab())  # 7 - 活动
        self.stacked_widget.addWidget(self.create_ticket_tab())      # 8 - 工单
        self.stacked_widget.addWidget(self.create_account_tab())     # 9 - 账户
        self.stacked_widget.addWidget(self.create_settings_tab())    # 10 - 设置
        
        self.content_layout.addWidget(self.stacked_widget, stretch=1)
        
        self.main_layout.addWidget(self.sidebar, stretch=0)
        self.main_layout.addWidget(self.content_area, stretch=1)
        
        # 默认显示首页
        self.switch_page(0)

    def create_sidebar(self):
        """创建左侧导航栏"""
        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(200)
        self.sidebar.setStyleSheet("""
            QWidget {
                background: rgba(0, 0, 0, 0.4);
                border-right: 1px solid rgba(255, 255, 255, 0.1);
            }
        """)
        
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 25, 10, 15)
        sidebar_layout.setSpacing(5)
        
        # Logo
        self.logo_container = QWidget()
        self.logo_container.setAttribute(Qt.WA_TranslucentBackground)
        self.logo_container.setFixedHeight(45)
        self.logo_layout = QHBoxLayout(self.logo_container)
        self.logo_layout.setContentsMargins(0, 0, 0, 0)
        self.logo_layout.setSpacing(0)
        
        # 左侧占位
        left_spacer = QWidget()
        left_spacer.setFixedWidth(0)
        self.logo_layout.addWidget(left_spacer)
        self.logo_layout.addStretch()
        
        self.logo_label = QLabel()
        self.logo_label.setAttribute(Qt.WA_TranslucentBackground)
        self.logo_label.setFixedSize(35, 35)
        logo_pix = QPixmap("assets/logo.png")
        if not logo_pix.isNull():
            self.logo_label.setPixmap(logo_pix.scaled(35, 35, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.logo_layout.addWidget(self.logo_label)
        
        self.title_label = QLabel("ISFP")
        self.title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        self.title_label.setAttribute(Qt.WA_TranslucentBackground)
        self.title_label.setStyleSheet("color: #3498db; background: transparent;")
        self.logo_layout.addWidget(self.title_label)
        
        self.logo_layout.addStretch()
        
        # 右侧占位（比左侧小一点，使整体靠左）
        self.right_spacer = QWidget()
        self.right_spacer.setFixedWidth(10)
        self.right_spacer.setAttribute(Qt.WA_TranslucentBackground)
        self.right_spacer.setStyleSheet("background: transparent;")
        self.logo_layout.addWidget(self.right_spacer)
        
        sidebar_layout.addWidget(self.logo_container)
        sidebar_layout.addSpacing(30)
        
        # 导航按钮（连线固定在正数第二个，索引为1）
        nav_items = [
            ("🏠", "首页", 0),
            ("🎮", "连线", 1),
            ("🌤", "气象", 2),
            ("🗺", "地图", 3),
            ("🏆", "排行", 4),
            ("✈️", "签派", 5),
            ("📋", "计划", 6),
            ("📅", "活动", 7),
            ("🎫", "工单", 8),
            ("👤", "账户", 9),
            ("⚙", "设置", 10),
        ]
        
        self.nav_buttons = []
        self.nav_texts = []  # 保存按钮文本
        for icon, text, index in nav_items:
            btn = QPushButton(f"{icon}  {text}")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(45)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #bdc3c7;
                    text-align: left;
                    padding-left: 15px;
                    font-size: 13px;
                    border-radius: 8px;
                    border: none;
                }
                QPushButton:hover {
                    background: rgba(52, 152, 219, 0.2);
                    color: white;
                }
                QPushButton:checked {
                    background: rgba(52, 152, 219, 0.4);
                    color: white;
                    border-left: 3px solid #3498db;
                }
            """)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, idx=index: self.switch_page(idx))
            btn.pressed.connect(lambda b=btn: self.animate_button_click(b))
            self.nav_buttons.append(btn)
            self.nav_texts.append(text)
            sidebar_layout.addWidget(btn)
        
        sidebar_layout.addStretch()
        
        # 版本号显示（可点击查看更新日志）
        self.version_container = QWidget()
        self.version_container.setAttribute(Qt.WA_TranslucentBackground)
        self.version_layout = QHBoxLayout(self.version_container)
        self.version_layout.setContentsMargins(0, 5, 0, 5)
        self.version_layout.setAlignment(Qt.AlignCenter)
        
        self.version_label = QLabel(f"v{APP_VERSION}")
        self.version_label.setFont(QFont("Microsoft YaHei", 10))
        self.version_label.setStyleSheet("color: #7f8c8d; background: transparent;")
        self.version_label.setAlignment(Qt.AlignCenter)
        self.version_label.setCursor(Qt.PointingHandCursor)
        self.version_label.mousePressEvent = lambda e: self.show_changelog_dialog()
        self.version_label.setToolTip("点击查看更新日志")
        
        self.version_layout.addWidget(self.version_label)
        sidebar_layout.addWidget(self.version_container)
        
        # 底部状态
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #3498db; font-size: 11px; background: transparent;")
        self.status_label.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(self.status_label)
        
        sidebar_layout.addSpacing(10)
        
        # 收缩/展开按钮（放在底部）
        self.toggle_sidebar_btn = QPushButton("◀")
        self.toggle_sidebar_btn.setFixedSize(32, 32)
        self.toggle_sidebar_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_sidebar_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #7f8c8d;
                border: 2px solid #7f8c8d;
                border-radius: 16px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #3498db;
                border: 2px solid #3498db;
                background: rgba(52, 152, 219, 0.1);
            }
        """)
        self.toggle_sidebar_btn.clicked.connect(self.toggle_sidebar)
        
        toggle_container = QWidget()
        toggle_container.setAttribute(Qt.WA_TranslucentBackground)
        toggle_layout = QHBoxLayout(toggle_container)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setAlignment(Qt.AlignCenter)
        toggle_layout.addWidget(self.toggle_sidebar_btn)
        sidebar_layout.addWidget(toggle_container)
        
        # 初始化侧边栏状态
        self.sidebar_expanded = True
        self.sidebar_normal_width = 200
        self.sidebar_compact_width = 70

    def create_top_bar(self):
        """创建顶部状态栏"""
        top_bar = QWidget()
        top_bar.setFixedHeight(50)
        top_bar.setStyleSheet("background: transparent;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        # 页面标题
        self.page_title = QLabel("首页")
        self.page_title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        self.page_title.setStyleSheet("color: white;")
        top_layout.addWidget(self.page_title)
        
        top_layout.addStretch()
        
        # 用户信息按钮
        self.top_user_btn = QPushButton("未登录")
        self.top_user_btn.setCursor(Qt.PointingHandCursor)
        self.top_user_btn.setFixedSize(120, 35)
        self.top_user_btn.setStyleSheet("""
            QPushButton {
                background: rgba(52, 152, 219, 0.3);
                color: white;
                border-radius: 17px;
                font-size: 12px;
                border: none;
            }
            QPushButton:hover {
                background: rgba(52, 152, 219, 0.5);
            }
        """)
        self.top_user_btn.clicked.connect(lambda: self.switch_page(9))  # 账户页面现在是第9个
        top_layout.addWidget(self.top_user_btn)
        
        self.content_layout.addWidget(top_bar)

    def switch_page(self, index):
        """切换页面"""
        # 检查是否需要登录（所有页面都需要登录，除了登录页本身）
        # 页面索引: 0=首页, 1=连线, 2=气象, 3=地图, 4=排行, 5=签派, 6=计划, 7=活动, 8=工单, 9=账户, 10=设置
        protected_pages = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10]  # 首页、连线、气象、地图、排行、签派、计划、活动、工单、设置
        if index in protected_pages and not self.auth_token:
            self.show_notification("请先登录")
            index = 9  # 跳转到账户/登录页面
        
        # 更新按钮状态
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        
        # 切换页面
        self.stacked_widget.setCurrentIndex(index)
        
        # 更新标题（顺序必须与页面堆栈一致）
        titles = ["首页", "连线", "气象", "地图", "排行", "签派", "计划", "活动", "工单", "账户", "设置"]
        self.page_title.setText(titles[index])
        
        # 自动刷新数据
        if index == 3:  # 地图
            self.load_map_data()
        elif index == 4:  # 排行
            self.load_ratings()
        elif index == 5:  # 签派
            self.load_dispatch_data()
        elif index == 6:  # 计划
            self.load_server_flight_plan()
        elif index == 7:  # 活动
            self.load_activities()
        elif index == 8:  # 工单
            self.load_tickets()
        
        # 添加切换动画效果
        self.animate_page_switch()

    def animate_page_switch(self):
        """页面切换动画 - 淡入+滑动效果"""
        current_widget = self.stacked_widget.currentWidget()
        if current_widget:
            # 淡入动画
            opacity_anim = QPropertyAnimation(current_widget, b"windowOpacity")
            opacity_anim.setDuration(250)
            opacity_anim.setStartValue(0.0)
            opacity_anim.setEndValue(1.0)
            opacity_anim.setEasingCurve(QEasingCurve.InOutQuad)
            
            # 滑动动画
            pos_anim = QPropertyAnimation(current_widget, b"pos")
            pos_anim.setDuration(250)
            pos_anim.setStartValue(QPoint(20, 0))
            pos_anim.setEndValue(QPoint(0, 0))
            pos_anim.setEasingCurve(QEasingCurve.OutCubic)
            
            opacity_anim.start()
            pos_anim.start()
            
            # 保存动画引用防止被垃圾回收
            self._current_animation = (opacity_anim, pos_anim)
    
    def animate_button_click(self, button):
        """按钮点击动画 - 缩放效果"""
        anim = QPropertyAnimation(button, b"geometry")
        anim.setDuration(100)
        original_geo = button.geometry()
        
        # 缩小
        shrink_geo = QRect(
            original_geo.x() + 2,
            original_geo.y() + 2,
            original_geo.width() - 4,
            original_geo.height() - 4
        )
        
        anim.setStartValue(shrink_geo)
        anim.setEndValue(original_geo)
        anim.setEasingCurve(QEasingCurve.OutBounce)
        anim.start()
        
        # 保存引用
        self._button_animation = anim
    
    def animate_widget_show(self, widget, duration=300):
        """控件显示动画"""
        widget.setWindowOpacity(0.0)
        anim = QPropertyAnimation(widget, b"windowOpacity")
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.start()
        self._show_animation = anim
    
    def animate_list_item_enter(self, item_widget):
        """列表项进入动画"""
        anim = QPropertyAnimation(item_widget, b"pos")
        anim.setDuration(200)
        anim.setStartValue(QPoint(-20, item_widget.y()))
        anim.setEndValue(QPoint(0, item_widget.y()))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._list_animation = anim

    def toggle_sidebar(self):
        """切换侧边栏收缩/展开状态"""
        if self.sidebar_expanded:
            self.collapse_sidebar()
        else:
            self.expand_sidebar()

    def collapse_sidebar(self):
        """收缩侧边栏"""
        self.sidebar_expanded = False
        self.toggle_sidebar_btn.setText("▶")
        
        # 动画改变侧边栏宽度
        self._sidebar_anim = QPropertyAnimation(self.sidebar, b"minimumWidth")
        self._sidebar_anim.setDuration(250)
        self._sidebar_anim.setStartValue(self.sidebar_normal_width)
        self._sidebar_anim.setEndValue(self.sidebar_compact_width)
        self._sidebar_anim.setEasingCurve(QEasingCurve.InOutCubic)
        
        # 同时动画最大宽度
        self._sidebar_max_anim = QPropertyAnimation(self.sidebar, b"maximumWidth")
        self._sidebar_max_anim.setDuration(250)
        self._sidebar_max_anim.setStartValue(self.sidebar_normal_width)
        self._sidebar_max_anim.setEndValue(self.sidebar_compact_width)
        self._sidebar_max_anim.setEasingCurve(QEasingCurve.InOutCubic)
        
        # 动画完成后才改变按钮文本
        def on_collapse_finished():
            # 隐藏文本
            self.title_label.hide()
            self.version_label.hide()
            self.status_label.hide()
            
            # 调整占位宽度使 Logo 居中
            self.right_spacer.setFixedWidth(0)
            
            # 按钮只显示图标（连线固定在正数第二个）
            nav_items = ["🏠", "🎮", "🌤", "🗺", "🏆", "✈️", "📋", "📅", "🎫", "👤", "⚙"]
            for i, btn in enumerate(self.nav_buttons):
                if i < len(nav_items):
                    btn.setText(nav_items[i])
                btn.setStyleSheet("""
                    QPushButton {
                        background: transparent;
                        color: #bdc3c7;
                        text-align: center;
                        font-size: 18px;
                        border-radius: 8px;
                        border: none;
                    }
                    QPushButton:hover {
                        background: rgba(52, 152, 219, 0.2);
                        color: white;
                    }
                    QPushButton:checked {
                        background: rgba(52, 152, 219, 0.4);
                        color: white;
                        border-left: 3px solid #3498db;
                    }
                """)
        
        self._sidebar_anim.finished.connect(on_collapse_finished)
        self._sidebar_anim.start()
        self._sidebar_max_anim.start()

    def expand_sidebar(self):
        """展开侧边栏"""
        self.sidebar_expanded = True
        self.toggle_sidebar_btn.setText("◀")
        
        # 动画改变侧边栏宽度
        self._sidebar_anim = QPropertyAnimation(self.sidebar, b"minimumWidth")
        self._sidebar_anim.setDuration(250)
        self._sidebar_anim.setStartValue(self.sidebar_compact_width)
        self._sidebar_anim.setEndValue(self.sidebar_normal_width)
        self._sidebar_anim.setEasingCurve(QEasingCurve.InOutCubic)
        
        # 同时动画最大宽度
        self._sidebar_max_anim = QPropertyAnimation(self.sidebar, b"maximumWidth")
        self._sidebar_max_anim.setDuration(250)
        self._sidebar_max_anim.setStartValue(self.sidebar_compact_width)
        self._sidebar_max_anim.setEndValue(self.sidebar_normal_width)
        self._sidebar_max_anim.setEasingCurve(QEasingCurve.InOutCubic)
        
        # 显示文本
        self.title_label.show()
        self.version_label.show()
        self.status_label.show()
        
        # 调整占位宽度使 Logo 和标题居中偏左
        self.right_spacer.setFixedWidth(10)
        
        # 恢复按钮文本（连线固定在正数第二个）
        nav_items = [
            ("🏠", "首页"),
            ("🎮", "连线"),
            ("🌤", "气象"),
            ("🗺", "地图"),
            ("🏆", "排行"),
            ("✈️", "签派"),
            ("📋", "计划"),
            ("📅", "活动"),
            ("🎫", "工单"),
            ("👤", "账户"),
            ("⚙", "设置"),
        ]
        for i, btn in enumerate(self.nav_buttons):
            if i < len(nav_items):
                btn.setText(f"{nav_items[i][0]}  {nav_items[i][1]}")
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #bdc3c7;
                    text-align: left;
                    padding-left: 15px;
                    font-size: 13px;
                    border-radius: 8px;
                    border: none;
                }
                QPushButton:hover {
                    background: rgba(52, 152, 219, 0.2);
                    color: white;
                }
                QPushButton:checked {
                    background: rgba(52, 152, 219, 0.4);
                    color: white;
                    border-left: 3px solid #3498db;
                }
            """)
        
        self._sidebar_anim.start()
        self._sidebar_max_anim.start()

    def show_changelog_dialog(self):
        """显示更新日志弹窗"""
        dialog = QDialog(self)
        dialog.setWindowTitle("更新日志")
        dialog.setFixedSize(520, 450)
        dialog.setStyleSheet("""
            QDialog {
                background: #1a1a2e;
                border: 2px solid #3498db;
                border-radius: 12px;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)
        
        # 标题区域
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(5)
        
        title = QLabel("🚀 更新日志")
        title.setFont(QFont("Microsoft YaHei", 22, QFont.Bold))
        title.setStyleSheet("color: #3498db;")
        title.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(title)
        
        version = QLabel(f"当前版本: v{APP_VERSION}")
        version.setFont(QFont("Microsoft YaHei", 12))
        version.setStyleSheet("color: #7f8c8d;")
        version.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(version)
        
        layout.addWidget(header)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 transparent, stop:0.5 #3498db, stop:1 transparent);")
        line.setFixedHeight(2)
        layout.addWidget(line)
        
        # 更新日志内容 - 使用 QTextEdit 显示富文本
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet("""
            QTextEdit {
                background: transparent;
                border: none;
                padding: 10px;
                color: white;
            }
            QScrollBar:vertical {
                background: rgba(255, 255, 255, 0.05);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(52, 152, 219, 0.5);
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(52, 152, 219, 0.8);
            }
        """)
        
        # 构建 HTML 内容
        html_content = self.build_changelog_html()
        text_edit.setHtml(html_content)
        layout.addWidget(text_edit)
        
        # 关闭按钮
        close_btn = QPushButton("✓ 知道了")
        close_btn.setFixedSize(120, 40)
        close_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3498db, stop:1 #2980b9);
                color: white;
                border: none;
                border-radius: 20px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4aa3df, stop:1 #3498db);
            }
        """)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)
        
        # 显示弹窗
        dialog.exec()

    def build_changelog_html(self):
        """构建更新日志 HTML 内容"""
        html = """
        <style>
            body {
                font-family: 'Microsoft YaHei', sans-serif;
                color: #ecf0f1;
                line-height: 1.6;
                background: transparent;
            }
            .version-block {
                margin-bottom: 15px;
                padding: 10px 0;
                background: transparent;
                border-left: 3px solid #3498db;
                padding-left: 15px;
            }
            .version-title {
                color: #3498db;
                font-size: 15px;
                font-weight: bold;
                margin-bottom: 8px;
                background: transparent;
            }
            .change-item {
                color: #bdc3c7;
                font-size: 13px;
                margin: 3px 0;
                padding-left: 5px;
                background: transparent;
            }
            .change-item::before {
                content: "• ";
                color: #2ecc71;
            }
            .no-data {
                color: #7f8c8d;
                text-align: center;
                padding: 30px;
                font-size: 14px;
                background: transparent;
            }
        </style>
        <body>
        """
        
        if CHANGELOG and CHANGELOG.strip():
            # 解析 CHANGELOG 格式: 版本|内容1;内容2|版本2|内容1;内容2
            parts = CHANGELOG.split('|')
            i = 0
            while i < len(parts):
                if i + 1 < len(parts):
                    version = parts[i].strip()
                    changes_text = parts[i + 1].strip()
                    
                    if version and changes_text:
                        html += f'<div class="version-block">\n'
                        html += f'<div class="version-title">📌 {version}</div>\n'
                        
                        # 解析更新内容
                        changes = changes_text.split(';')
                        for change in changes:
                            change = change.strip()
                            if change:
                                html += f'<div class="change-item">{change}</div>\n'
                        
                        html += '</div>\n'
                i += 2
        else:
            html += '<div class="no-data">暂无更新日志</div>'
        
        html += "</body>"
        return html

    def create_dispatch_tab(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # 左侧：我的机库
        hangar_group = QGroupBox("我的机库 (My Hangar)")
        hangar_group.setStyleSheet("""
            QGroupBox { 
                color: #f39c12; 
                font-weight: bold; 
                font-size: 16px;
                border: 2px solid #f39c12; 
                border-radius: 8px; 
                margin-top: 15px; 
                background: rgba(0, 0, 0, 0.3);
            } 
            QGroupBox::title { 
                subcontrol-origin: margin; 
                left: 15px; 
                padding: 0 5px; 
            }
        """)
        hangar_layout = QVBoxLayout(hangar_group)
        hangar_layout.setContentsMargins(15, 25, 15, 15)
        
        # 使用 IconMode 展示机库
        self.hangar_list = QListWidget()
        self.hangar_list.setViewMode(QListWidget.IconMode)
        self.hangar_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.hangar_list.customContextMenuRequested.connect(self.show_hangar_menu)
        self.hangar_list.setIconSize(QSize(220, 150))
        self.hangar_list.setSpacing(10)
        self.hangar_list.setResizeMode(QListWidget.Adjust)
        self.hangar_list.setStyleSheet("""
            QListWidget {
                background: transparent; 
                border: none;
            }
            QListWidget::item {
                background: rgba(255, 255, 255, 0.05);
                border-radius: 8px;
                padding: 5px;
                color: white;
                margin: 5px;
            }
            QListWidget::item:hover {
                background: rgba(255, 255, 255, 0.1);
                border: 1px solid #f39c12;
            }
            QListWidget::item:selected {
                background: rgba(243, 156, 18, 0.2);
                border: 1px solid #f39c12;
            }
        """)
        hangar_layout.addWidget(self.hangar_list)
        
        add_ac_btn = QPushButton("➕ 添加航空器")
        add_ac_btn.setStyleSheet("""
            QPushButton {
                background: #2980b9; 
                color: white; 
                padding: 12px; 
                border-radius: 6px; 
                font-size: 14px; 
                font-weight: bold;
            }
            QPushButton:hover {
                background: #3498db;
            }
        """)
        add_ac_btn.clicked.connect(self.show_add_aircraft_dialog)
        hangar_layout.addWidget(add_ac_btn)
        
        layout.addWidget(hangar_group, 6) # 占比 60%
        
        # 右侧：航班签派
        flight_group = QGroupBox("航班签派 (Dispatch)")
        flight_group.setStyleSheet("""
            QGroupBox { 
                color: #2ecc71; 
                font-weight: bold; 
                font-size: 16px;
                border: 2px solid #2ecc71; 
                border-radius: 8px; 
                margin-top: 15px; 
                background: rgba(0, 0, 0, 0.3);
            } 
            QGroupBox::title { 
                subcontrol-origin: margin; 
                left: 15px; 
                padding: 0 5px; 
            }
        """)
        flight_layout = QVBoxLayout(flight_group)
        flight_layout.setContentsMargins(15, 25, 15, 15)
        
        new_flight_btn = QPushButton("🛫 新建航班")
        new_flight_btn.setStyleSheet("""
            QPushButton {
                background: #27ae60; 
                color: white; 
                padding: 12px; 
                border-radius: 6px; 
                font-size: 14px; 
                font-weight: bold;
            }
            QPushButton:hover {
                background: #2ecc71;
            }
        """)
        new_flight_btn.clicked.connect(self.show_new_flight_dialog)
        flight_layout.addWidget(new_flight_btn)
        
        # 历史记录头部工具栏
        hist_header = QHBoxLayout()
        history_label = QLabel("📋 历史航班记录")
        history_label.setStyleSheet("color: #bdc3c7; font-size: 13px;")
        hist_header.addWidget(history_label)
        hist_header.addStretch()
        
        clear_hist_btn = QPushButton("清空")
        clear_hist_btn.setCursor(Qt.PointingHandCursor)
        clear_hist_btn.setFixedSize(50, 26)
        clear_hist_btn.setToolTip("清空所有历史记录")
        clear_hist_btn.setStyleSheet("""
            QPushButton { 
                background: rgba(192, 57, 43, 0.8); 
                color: white; 
                border-radius: 4px; 
                font-size: 12px; 
                border: none;
                padding: 0;
            }
            QPushButton:hover { background: #e74c3c; }
        """)
        clear_hist_btn.clicked.connect(self.confirm_clear_history)
        hist_header.addWidget(clear_hist_btn)
        
        flight_layout.addLayout(hist_header)
        
        self.flight_history_list = QListWidget()
        self.flight_history_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.flight_history_list.customContextMenuRequested.connect(self.show_history_menu)
        self.flight_history_list.setStyleSheet("""
            QListWidget {
                background: rgba(0,0,0,0.2); 
                border: 1px solid rgba(255,255,255,0.1); 
                border-radius: 6px;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid rgba(255,255,255,0.05);
            }
            QListWidget::item:hover {
                background: rgba(255, 255, 255, 0.05);
            }
            QListWidget::item:selected {
                background: rgba(46, 204, 113, 0.2);
                border-left: 3px solid #2ecc71;
            }
        """)
        self.flight_history_list.itemClicked.connect(self.show_flight_details)
        flight_layout.addWidget(self.flight_history_list)
        
        layout.addWidget(flight_group, 4) # 占比 40%
        
        return widget

    def confirm_clear_history(self):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(self, "确认清空", "确定要删除所有航班历史记录吗？此操作不可恢复。",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.dispatch_manager.clear_history()
            self.load_dispatch_data()
            self.show_notification("历史记录已清空")

    def load_dispatch_data(self):
        # 加载机库
        self.hangar_list.clear()
        hangar = self.dispatch_manager.hangar
        for ac in hangar:
            # 动态生成占位图作为默认图标
            pix = QPixmap(220, 150)
            pix.fill(QColor(44, 62, 80))
            painter = QPainter(pix)
            painter.setPen(QPen(Qt.white))
            painter.setFont(QFont("Arial", 14, QFont.Bold))
            painter.drawText(pix.rect(), Qt.AlignCenter, "NO IMAGE")
            painter.end()
            icon = QIcon(pix)
            
            text = f"{ac['airline']} {ac['reg']}\n{ac['type']}"
            item = QListWidgetItem(icon, text)
            item.setForeground(Qt.white)
            item.setFont(QFont("Consolas", 10, QFont.Bold))
            item.setTextAlignment(Qt.AlignCenter)
            item.setData(Qt.UserRole, ac)
            self.hangar_list.addItem(item)
            
            # 如果有图片URL，异步加载图片
            if ac.get('image'):
                img_path_or_url = ac['image']
                if img_path_or_url.startswith('http'):
                    # 是URL，异步加载
                    self.async_load_hangar_image(img_path_or_url, item)
                elif os.path.exists(img_path_or_url):
                    # 是本地路径且存在
                    icon = QIcon(img_path_or_url)
                    item.setIcon(icon)
            
        # 加载历史
        self.flight_history_list.clear()
        history = self.dispatch_manager.history
        
        # 状态颜色映射
        status_colors = {
            '计划': '#95a5a6',
            '推出': '#e67e22',
            '起飞': '#f39c12',
            '巡航': '#3498db',
            '下降': '#9b59b6',
            '落地': '#2ecc71'
        }
        
        for f in history:
            status = f.get('status', '计划')
            status_color = status_colors.get(status, '#95a5a6')
            
            # 格式化显示：日期 | 航班号 | 起降 | 机型 | 状态
            text = f"📅 {f['date']}   ✈ {f['callsign']}\n🛫 {f['dep']} ➔ 🛬 {f['arr']}   🛩️ {f['aircraft']['type']}   [{status}]"
            item = QListWidgetItem(text)
            item.setForeground(QColor(status_color))
            item.setFont(QFont("Consolas", 10))
            item.setData(Qt.UserRole, f) # 存储完整数据以便点击查看
            self.flight_history_list.addItem(item)

    def async_load_hangar_image(self, url, list_item):
        """异步加载机库图片并设置到列表项"""
        xz_logger = logging.getLogger('ISFP-Connect.XZPhotos')
        
        # 获取航空器注册号作为唯一标识
        aircraft_data = list_item.data(Qt.UserRole)
        reg = aircraft_data.get('reg', 'unknown') if aircraft_data else 'unknown'
        
        # URL 解析
        from urllib.parse import urljoin, quote, urlparse, urlunparse
        base_api_url = "https://xzphotos.cn"
        
        if url.startswith("http"):
            full_url = url
        else:
            full_url = urljoin(base_api_url, url)
            
        try:
            parsed = urlparse(full_url)
            new_path = quote(parsed.path, safe='/')
            full_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                new_path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))
        except:
            pass
        
        req = QNetworkRequest(QUrl(full_url))
        req.setRawHeader(b"User-Agent", b"Mozilla/5.0 ISFP-Connect/1.0")
        
        reply = self.nam.get(req)
        
        def on_finished():
            # 检查列表项是否仍然有效（通过注册号查找）
            found_item = None
            for i in range(self.hangar_list.count()):
                item = self.hangar_list.item(i)
                if item:
                    item_data = item.data(Qt.UserRole)
                    if item_data and item_data.get('reg') == reg:
                        found_item = item
                        break
            
            if not found_item:
                xz_logger.debug(f"[机库图片] 列表项已不存在，跳过 - 注册号: {reg}")
                reply.deleteLater()
                return
            
            if reply.error() == QNetworkReply.NoError:
                img_data = reply.readAll()
                image = QImage()
                if image.loadFromData(img_data):
                    # 缩放到合适大小
                    pixmap = QPixmap.fromImage(image).scaled(
                        220, 150,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    icon = QIcon(pixmap)
                    found_item.setIcon(icon)
                    xz_logger.info(f"[机库图片] 加载成功 - 注册号: {reg}")
                else:
                    xz_logger.warning(f"[机库图片] 图片格式错误 - 注册号: {reg}")
            else:
                xz_logger.warning(f"[机库图片] 加载失败 - 注册号: {reg}, 错误: {reply.errorString()}")
            
            reply.deleteLater()
        
        reply.finished.connect(on_finished)

    def show_history_menu(self, pos):
        item = self.flight_history_list.itemAt(pos)
        if not item: return
        
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu { background: #2c3e50; color: white; border: 1px solid #555; }
            QMenu::item { padding: 5px 20px; }
            QMenu::item:selected { background: #e74c3c; }
        """)
        
        del_action = menu.addAction("🗑️ 删除此记录")
        action = menu.exec(self.flight_history_list.mapToGlobal(pos))
        
        if action == del_action:
            flight_data = item.data(Qt.UserRole)
            self.dispatch_manager.delete_flight(flight_data)
            self.load_dispatch_data()
            self.show_notification("航班记录已删除")

    def show_hangar_menu(self, pos):
        item = self.hangar_list.itemAt(pos)
        if not item: return
        
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu { background: #2c3e50; color: white; border: 1px solid #555; }
            QMenu::item { padding: 5px 20px; }
            QMenu::item:selected { background: #3498db; }
        """)
        
        edit_action = menu.addAction("✏️ 修改信息")
        del_action = menu.addAction("🗑️ 删除航空器")
        
        action = menu.exec(self.hangar_list.mapToGlobal(pos))
        
        if action == edit_action:
            self.show_edit_aircraft_dialog(item)
        elif action == del_action:
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(self, "确认删除", "确定要删除该航空器吗？",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                aircraft_data = item.data(Qt.UserRole)
                self.dispatch_manager.delete_aircraft(aircraft_data)
                self.load_dispatch_data()
                self.show_notification("航空器已删除")

    def show_edit_aircraft_dialog(self, item):
        original_data = item.data(Qt.UserRole)
        dialog = AddAircraftDialog(self, aircraft_data=original_data)
        if dialog.exec():
            new_data = dialog.get_data()
            # 如果没有上传新图片且原图片存在，保持原图片
            if not new_data['image'] and original_data.get('image'):
                 new_data['image'] = original_data['image']
            
            # 同样处理自动获取图片逻辑
            if not new_data['image']:
                 # 如果是修改，且原本也没图，或者虽然是修改但没图且想重新获取...
                 # 简单起见，如果没有图，就尝试获取
                 reg = new_data['reg']
                 def on_photo_ready(res):
                    xz_logger = logging.getLogger('ISFP-Connect.XZPhotos')
                    if isinstance(res, dict) and res.get('success') and res['data'].get('photo_found'):
                        img_url = res['data'].get('photo_image_url')
                        if img_url:
                            try:
                                xz_logger.info(f"[图片URL] 获取成功 - 注册号: {reg}, URL: {img_url}")
                                
                                # 直接保存URL，不下载图片到本地
                                for ac in self.dispatch_manager.hangar:
                                    if ac['reg'] == reg:
                                        ac['image'] = img_url  # 保存URL而不是本地路径
                                        break
                                self.dispatch_manager.save_json(self.dispatch_manager.hangar_file, self.dispatch_manager.hangar)
                                self.load_dispatch_data()
                                xz_logger.info(f"[图片URL] 航空器数据已更新 - 注册号: {reg}")
                            except Exception as e:
                                xz_logger.error(f"[图片URL] 异常 - 注册号: {reg}, 错误: {str(e)}")
                    else:
                        xz_logger.info(f"[图片URL] 未找到图片 - 注册号: {reg}")

                 self.auto_photo_thread = XZPhotosAPIThread(reg)
                 self.auto_photo_thread.finished.connect(on_photo_ready)
                 self.manage_thread(self.auto_photo_thread)
            
            self.dispatch_manager.update_aircraft(original_data, new_data)
            self.load_dispatch_data()
            self.show_notification("航空器信息已更新")

    def show_add_aircraft_dialog(self):
        dialog = AddAircraftDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            
            # 如果没有图片，尝试从 API 获取
            if not data['image']:
                # 启动线程获取图片 URL
                # 这里为了简化，我们先保存数据，然后用 APIThread 去更新
                # 但 DispatchManager 是同步的。
                # 我们可以先存一个标记，或者在这里阻塞一下（不推荐），或者用 APIThread 回调来更新
                
                # 方案：先添加，然后启动线程获取图片，获取成功后更新 JSON
                self.dispatch_manager.add_aircraft(data)
                self.load_dispatch_data()
                
                # 自动获取图片
                reg = data['reg']
                def on_photo_ready(res):
                    xz_logger = logging.getLogger('ISFP-Connect.XZPhotos')
                    if isinstance(res, dict) and res.get('success') and res['data'].get('photo_found'):
                        img_url = res['data'].get('photo_image_url')
                        if img_url:
                            try:
                                xz_logger.info(f"[图片URL] 获取成功 - 注册号: {reg}, URL: {img_url}")
                                
                                # 直接保存URL，不下载图片到本地
                                for ac in self.dispatch_manager.hangar:
                                    if ac['reg'] == reg:
                                        ac['image'] = img_url  # 保存URL而不是本地路径
                                        break
                                self.dispatch_manager.save_json(self.dispatch_manager.hangar_file, self.dispatch_manager.hangar)
                                self.load_dispatch_data() # 刷新显示
                                xz_logger.info(f"[图片URL] 航空器数据已更新 - 注册号: {reg}")
                            except Exception as e:
                                xz_logger.error(f"[图片URL] 异常 - 注册号: {reg}, 错误: {str(e)}")
                        else:
                            xz_logger.info(f"[图片URL] 未找到图片 - 注册号: {reg}")
                    else:
                        xz_logger.info(f"[图片URL] API未返回图片 - 注册号: {reg}")

                self.auto_photo_thread = XZPhotosAPIThread(reg)
                self.auto_photo_thread.finished.connect(on_photo_ready)
                self.manage_thread(self.auto_photo_thread)
            else:
                self.dispatch_manager.add_aircraft(data)
                self.load_dispatch_data()

    def show_new_flight_dialog(self):
        if not self.dispatch_manager.hangar:
            self.show_notification("机库为空，请先添加航空器")
            return
            
        dialog = NewFlightDialog(self.dispatch_manager.hangar, self)
        if dialog.exec():
            data = dialog.get_data()
            self.dispatch_manager.add_flight(data)
            self.load_dispatch_data()
            self.show_notification("航班签派成功，已添加至历史记录")
            
            # 在灵动岛显示新航班信息
            if DYNAMIC_ISLAND_AVAILABLE:
                callsign = data.get('callsign', '')
                update_flight_on_island(callsign, '准备')

    def show_flight_details(self, item):
        flight_data = item.data(Qt.UserRole)
        dialog = FlightDetailsDialog(flight_data, self, editable=True)
        dialog.status_changed.connect(lambda status: self.on_flight_status_changed(flight_data, status))
        dialog.exec()

    def on_flight_status_changed(self, flight_data, new_status):
        """处理航班状态变更"""
        if self.dispatch_manager.update_flight_status(flight_data, new_status):
            self.load_dispatch_data()
            logger.info(f"航班 {flight_data.get('callsign')} 状态更新为: {new_status}")
            
            # 更新灵动岛航班信息
            if DYNAMIC_ISLAND_AVAILABLE:
                callsign = flight_data.get('callsign', '')
                update_flight_on_island(callsign, new_status)
                
                # 显示状态变更通知
                if new_status not in ['着陆', '落地']:
                    self.show_notification(f"航班 {callsign} 状态: {new_status}")

    def create_map_tab(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 左侧：在线机组列表
        self.online_panel = QWidget()
        self.online_panel.setFixedWidth(300)
        self.online_panel.setStyleSheet("background: rgba(0, 0, 0, 0.3); border-right: 1px solid rgba(255, 255, 255, 0.1);")
        online_layout = QVBoxLayout(self.online_panel)
        online_layout.setContentsMargins(10, 10, 10, 10)
        
        # 在线机组标题
        online_title = QLabel("在线机组")
        online_title.setStyleSheet("color: #3498db; font-size: 16px; font-weight: bold; background: transparent;")
        online_layout.addWidget(online_title)
        
        # 刷新按钮
        refresh_btn = QPushButton("刷新机组动态")
        refresh_btn.setStyleSheet("padding: 8px; background: #27ae60; color: white; border-radius: 6px; font-size: 12px;")
        refresh_btn.clicked.connect(self.load_map_data)
        online_layout.addWidget(refresh_btn)
        
        # 在线机组列表
        self.online_list = QListWidget()
        self.online_list.setStyleSheet("""
            QListWidget {
                background: rgba(0,0,0,0.5); 
                border-radius: 8px; 
                color: white; 
                padding: 5px;
                border: 1px solid rgba(255,255,255,0.1);
                outline: none;
            }
            QListWidget::item {
                background: rgba(255,255,255,0.08);
                margin-bottom: 4px;
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 12px;
                border: 1px solid transparent;
                min-height: 60px;
            }
            QListWidget::item:hover {
                background: rgba(52, 152, 219, 0.2);
                border: 1px solid rgba(52, 152, 219, 0.5);
            }
            QListWidget::item:selected {
                background: rgba(52, 152, 219, 0.4);
                border: 1px solid #3498db;
            }
        """)
        online_layout.addWidget(self.online_list)
        
        # 右侧：地图容器（包含地图和切换按钮）
        map_container = QWidget()
        map_layout = QVBoxLayout(map_container)
        map_layout.setContentsMargins(0, 0, 0, 0)
        
        self.map_view = QWebEngineView()
        self.map_view.setStyleSheet("background: #1a1a1a;")
        
        # 配置 WebChannel
        self.map_channel = QWebChannel()
        self.map_bridge = MapBridge(self)
        self.map_channel.registerObject("bridge", self.map_bridge)
        self.map_view.page().setWebChannel(self.map_channel)
        
        # 标记 JS 是否已就绪
        self._map_js_ready = False
        
        # 移除不可靠的 loadFinished 监听，改用 JS 主动通知
        # self.map_view.loadFinished.connect(lambda: setattr(self, '_map_js_ready', True))
        
        # 加载地图 HTML
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body, html, #map { height: 100%; margin: 0; padding: 0; background: #1a1a1a; }
                .leaflet-popup-content-wrapper { background: rgba(0,0,0,0.8); color: white; border-radius: 8px; }
                .leaflet-popup-tip { background: rgba(0,0,0,0.8); }
                .map-controls {
                    position: absolute;
                    top: 10px;
                    right: 10px;
                    z-index: 1000;
                    background: rgba(0,0,0,0.7);
                    border-radius: 8px;
                    padding: 5px;
                }
                .map-controls button {
                    background: #3498db;
                    color: white;
                    border: none;
                    padding: 8px 12px;
                    border-radius: 5px;
                    cursor: pointer;
                    font-size: 12px;
                    margin: 2px;
                }
                .map-controls button:hover {
                    background: #2980b9;
                }
                .map-controls button.active {
                    background: #2ecc71;
                }
            </style>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
        </head>
        <body>
            <div id="map"></div>
            <div class="map-controls">
                <button id="btn-light" onclick="switchLayer('light')" class="active">浅色</button>
                <button id="btn-dark" onclick="switchLayer('dark')">暗色</button>
                <button id="btn-satellite" onclick="switchLayer('satellite')">卫星</button>
            </div>
            <script>
                var map = L.map('map').setView([35.0, 105.0], 4);
                
                // 定义不同图源
                var layers = {
                    dark: L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                        attribution: '&copy; OpenStreetMap &copy; CARTO',
                        subdomains: 'abcd',
                        maxZoom: 19
                    }),
                    satellite: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                        attribution: '&copy; Esri',
                        maxZoom: 19
                    }),
                    light: L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
                        attribution: '&copy; OpenStreetMap &copy; CARTO',
                        subdomains: 'abcd',
                        maxZoom: 19
                    })
                };
                
                // 默认添加浅色图层
                layers.light.addTo(map);
                var currentLayer = 'light';
                
                // 切换图层函数
                switchLayer = function(type) {
                    if (type === currentLayer) return;
                    
                    // 移除当前图层
                    map.removeLayer(layers[currentLayer]);
                    
                    // 添加新图层
                    layers[type].addTo(map);
                    currentLayer = type;
                    
                    // 更新按钮状态
                    document.getElementById('btn-dark').classList.remove('active');
                    document.getElementById('btn-satellite').classList.remove('active');
                    document.getElementById('btn-light').classList.remove('active');
                    document.getElementById('btn-' + type).classList.add('active');
                };

                // 将变量挂载到 window 对象，确保全局可访问
                window.markers = {};
                window.flightPaths = {}; // 改为存储多个航迹: {callsign: polyline}
                window.bridge = null;

                // 核心修复：直接定义在 window 上，不要用 var/let
                updatePilots = function(pilots) {
                    var currentIds = [];
                    pilots.forEach(function(p) {
                        var id = p.cid; 
                        currentIds.push(id);
                        
                        var lat = p.latitude;
                        var lng = p.longitude;
                        
                        // 动态按钮文本
                        var hasPath = window.flightPaths[p.callsign] ? "隐藏航迹" : "显示航迹";
                        var btnColor = window.flightPaths[p.callsign] ? "#c0392b" : "#34495e";
                        
                        var info = `
                            <div style='font-family: Consolas, sans-serif; font-size: 13px;'>
                                <b style='color: #3498db; font-size: 15px;'>${p.callsign}</b><br>
                                <hr style='border: 0; border-top: 1px solid #555; margin: 5px 0;'>
                                👤 CID: <span style='color: #9b59b6;'>${p.cid || 'N/A'}</span><br>
                                ✈ 机型: <span style='color: #2ecc71;'>${p.aircraft || 'Unknown'}</span><br>
                                📏 高度: <span style='color: #f1c40f;'>${p.altitude} ft</span><br>
                                🚀 速度: ${p.ground_speed} kts<br>
                                📡 应答机: ${p.transponder}<br>
                                <button id="btn-${p.callsign}" onclick="window.togglePath('${p.callsign}')" style="margin-top:8px; width: 100%; padding: 5px; background: ${btnColor}; color: white; border: none; border-radius: 4px; cursor: pointer;">${hasPath}</button>
                            </div>
                        `;

                        if (window.markers[id]) {
                            window.markers[id].setLatLng([lat, lng]);
                            if (window.markers[id].getPopup().isOpen()) {
                                // 保持 popup 内容最新
                            } else {
                                window.markers[id].setPopupContent(info);
                            }
                        } else {
                            // 自定义飞机图标
                            var icon = L.divIcon({
                                className: 'plane-icon',
                                html: `<div style='transform: rotate(${p.heading}deg); color: #3498db; font-size: 20px;'>✈</div>`,
                                iconSize: [24, 24],
                                iconAnchor: [12, 12]
                            });
                            
                            var marker = L.marker([lat, lng], {icon: icon}).addTo(map);
                            marker.bindPopup(info);
                            window.markers[id] = marker;
                        }
                        
                        // 更新图标旋转
                        var iconDiv = window.markers[id].getElement().querySelector('div');
                        if(iconDiv) iconDiv.style.transform = `rotate(${p.heading - 45}deg)`;
                    });

                    // 移除下线机组
                    for (var id in window.markers) {
                        if (!currentIds.includes(parseInt(id)) && !currentIds.includes(id)) {
                            map.removeLayer(window.markers[id]);
                            delete window.markers[id];
                        }
                    }
                };
                
                // 切换航迹显示/隐藏
                togglePath = function(callsign) {
                    if (window.flightPaths[callsign]) {
                        // 如果已存在，则移除（隐藏）
                        map.removeLayer(window.flightPaths[callsign]);
                        delete window.flightPaths[callsign];
                        // 更新按钮状态
                        var btn = document.getElementById('btn-' + callsign);
                        if(btn) {
                            btn.innerText = "显示航迹";
                            btn.style.background = "#34495e";
                        }
                    } else {
                        // 如果不存在，则请求获取（显示）
                        // 互斥逻辑：先清除其他所有航迹
                        for (var key in window.flightPaths) {
                            map.removeLayer(window.flightPaths[key]);
                            delete window.flightPaths[key];
                            // 重置对应按钮状态
                            var otherBtn = document.getElementById('btn-' + key);
                            if(otherBtn) {
                                otherBtn.innerText = "显示航迹";
                                otherBtn.style.background = "#34495e";
                            }
                        }
                        
                        if (window.bridge) window.bridge.get_flight_path(callsign);
                        // 不再显示"加载中..."，保持原样直到数据返回
                    }
                };

                // 生成随机颜色 (H:0-360, S:70-100%, L:50-60%)
                function getRandomColor() {
                    var h = Math.floor(Math.random() * 360);
                    return 'hsl(' + h + ', 100%, 50%)';
                }

                drawPath = function(data) {
                    var callsign = data.callsign;
                    var pathData = data.path;
                    
                    // 再次确保互斥：清除所有现有航迹
                    for (var key in window.flightPaths) {
                        map.removeLayer(window.flightPaths[key]);
                        delete window.flightPaths[key];
                        var otherBtn = document.getElementById('btn-' + key);
                        if(otherBtn) {
                            otherBtn.innerText = "显示航迹";
                            otherBtn.style.background = "#34495e";
                        }
                    }
                    
                    var latlngs = pathData.map(p => [p.latitude, p.longitude]);
                    // 生成一个均匀的随机颜色
                    var color = getRandomColor();
                    
                    // 绘制整条均匀颜色的航迹
                    var polyline = L.polyline(latlngs, {color: color, weight: 4, opacity: 0.8}).addTo(map);
                    window.flightPaths[callsign] = polyline;
                    map.fitBounds(polyline.getBounds());
                    
                    // 更新按钮状态
                    var btn = document.getElementById('btn-' + callsign);
                    if(btn) {
                        btn.innerText = "隐藏航迹";
                        btn.style.background = "#c0392b";
                    }
                };

                // 最后再初始化通信
                new QWebChannel(qt.webChannelTransport, function(channel) {
                    window.bridge = channel.objects.bridge;
                    
                    // 监听 Python 信号
                    window.bridge.updatePilotsSignal.connect(function(jsonData) {
                        var pilots = JSON.parse(jsonData);
                        updatePilots(pilots);
                    });
                    
                    window.bridge.drawPathSignal.connect(function(jsonData) {
                        var pathData = JSON.parse(jsonData);
                        drawPath(pathData);
                    });

                    // 通知 Python 端 JS 已就绪
                    if (window.bridge) window.bridge.map_ready();
                });
            </script>
        </body>
        </html>
        """
        self.map_view.setHtml(html_content)
        map_layout.addWidget(self.map_view)
        
        # 创建浮动按钮容器（使用绝对定位）- 放在右上角，但在地图控制按钮下方
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        
        toggle_container = QWidget(map_container)
        toggle_container.setGeometry(10, map_container.height() - 50, 110, 40)
        toggle_container.setStyleSheet("background: transparent;")
        toggle_layout = QHBoxLayout(toggle_container)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        
        # 添加在线机组列表开关按钮
        self.toggle_btn = QPushButton("☰ 在线机组")
        self.toggle_btn.setFixedSize(100, 35)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background: rgba(52, 152, 219, 0.95);
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(52, 152, 219, 1.0);
            }
            QPushButton:pressed {
                background: rgba(41, 128, 185, 1.0);
            }
        """)
        
        # 添加阴影效果
        shadow = QGraphicsDropShadowEffect(self.toggle_btn)
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(2, 2)
        self.toggle_btn.setGraphicsEffect(shadow)
        
        self.toggle_btn.clicked.connect(self.toggle_online_panel)
        toggle_layout.addWidget(self.toggle_btn)
        
        # 确保按钮始终显示在左下角
        def update_toggle_position():
            toggle_container.setGeometry(10, map_container.height() - 50, 110, 40)
        
        map_container.resizeEvent = lambda event: update_toggle_position()
        
        # 添加到主布局
        layout.addWidget(self.online_panel)
        layout.addWidget(map_container, stretch=1)
        
        # 定时刷新地图
        self.map_timer = QTimer(self)
        self.map_timer.setInterval(15000) # 15秒刷新一次
        self.map_timer.timeout.connect(self.load_map_data)
        self.map_timer.start()
        
        # 初始化在线面板可见性
        self.online_panel_visible = True
        
        return widget
    
    def toggle_online_panel(self):
        """切换在线机组列表的显示/隐藏（带动画）"""
        self.online_panel_visible = not self.online_panel_visible
        
        # 获取当前宽度和目标宽度
        start_width = self.online_panel.width()
        end_width = 300 if self.online_panel_visible else 0
        
        # 创建动画
        self._online_panel_anim = QPropertyAnimation(self.online_panel, b"minimumWidth")
        self._online_panel_anim.setDuration(250)
        self._online_panel_anim.setStartValue(start_width)
        self._online_panel_anim.setEndValue(end_width)
        self._online_panel_anim.setEasingCurve(QEasingCurve.InOutCubic)
        
        # 同时动画最大宽度
        self._online_panel_max_anim = QPropertyAnimation(self.online_panel, b"maximumWidth")
        self._online_panel_max_anim.setDuration(250)
        self._online_panel_max_anim.setStartValue(start_width)
        self._online_panel_max_anim.setEndValue(end_width)
        self._online_panel_max_anim.setEasingCurve(QEasingCurve.InOutCubic)
        
        # 更新按钮文字
        if self.online_panel_visible:
            self.toggle_btn.setText("☰ 隐藏")
        else:
            self.toggle_btn.setText("☰ 在线机组")
        
        self._online_panel_anim.start()
        self._online_panel_max_anim.start()

    def on_pilot_item_clicked(self, item):
        """点击在线机组列表项时在地图上定位"""
        data = item.data(Qt.UserRole)
        if data:
            callsign = data.get('callsign')
            lat = data.get('latitude')
            lng = data.get('longitude')
            
            # 在地图上定位并显示 popup
            js_code = f"""
                if (window.markers) {{
                    for (var id in window.markers) {{
                        var marker = window.markers[id];
                        var popup = marker.getPopup();
                        if (popup && popup.getContent().includes('{callsign}')) {{
                            map.setView(marker.getLatLng(), 10);
                            marker.openPopup();
                            break;
                        }}
                    }}
                }}
            """
            self.map_view.page().runJavaScript(js_code)

    def load_map_data(self):
        # 使用 /clients 接口获取所有在线客户端
        self.map_data_thread = APIThread(f"{ISFP_API_BASE}/clients")
        # 使用 QueuedConnection 确保槽函数在主线程中执行
        self.map_data_thread.finished.connect(self.on_map_data_ready, Qt.QueuedConnection)
        self.manage_thread(self.map_data_thread)

    def on_map_data_ready(self, data):
        # 获取 pilots 数据
        pilots = data.get("pilots", [])
        
        # 兼容处理：如果数据在 data.data.pilots
        if not pilots and "data" in data and isinstance(data["data"], dict):
            pilots = data["data"].get("pilots", [])
        
        # 检查 online_list 是否存在
        if not hasattr(self, 'online_list') or self.online_list is None:
            return
        
        # 检查 online_list 是否已经被销毁
        try:
            # 更新左侧在线机组列表
            self.online_list.clear()
            if not pilots:
                item = QListWidgetItem("✈️ 暂无机组在线")
                item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(QColor("#bdc3c7"))
                item.setSizeHint(QSize(0, 40))
                self.online_list.addItem(item)
            else:
                for p in pilots:
                    fp = p.get("flight_plan") or {}
                    callsign = p.get("callsign", "Unknown")
                    aircraft = fp.get("aircraft", "Unknown")
                    altitude = p.get("altitude", 0)
                    ground_speed = p.get("ground_speed", 0)
                    latitude = p.get("latitude", 0)
                    longitude = p.get("longitude", 0)
                    
                    # 格式化显示文本 - 显示更多信息
                    dep = fp.get('departure', '???')
                    arr = fp.get('arrival', '???')
                    item_text = f"✈ {callsign}\n   {dep} → {arr}\n   📏 {altitude} ft | 🚀 {ground_speed} kts"
                    item = QListWidgetItem(item_text)
                    item.setData(Qt.UserRole, {
                        'callsign': callsign,
                        'latitude': latitude,
                        'longitude': longitude,
                        'departure': dep,
                        'arrival': arr,
                        'altitude': altitude,
                        'ground_speed': ground_speed,
                        'aircraft': aircraft
                    })
                    item.setSizeHint(QSize(0, 75))
                    item.setToolTip(f"机型: {aircraft}\n起飞机场: {dep}\n降落机场: {arr}\n高度: {altitude} ft\n速度: {ground_speed} kts")
                    self.online_list.addItem(item)
                
                # 连接点击事件
                self.online_list.itemClicked.connect(self.on_pilot_item_clicked)
        except RuntimeError:
            # 忽略 GUI 对象已销毁的错误
            pass
        
        # 如果 JS 还没加载完，直接跳过
        if not getattr(self, '_map_js_ready', False):
            return

        # 转换数据为 JS 友好的格式
        js_data = []
        for p in pilots:
            fp = p.get("flight_plan") or {}
            js_data.append({
                "cid": p.get("cid"),
                "callsign": p.get("callsign"),
                "latitude": p.get("latitude"),
                "longitude": p.get("longitude"),
                "heading": p.get("heading", 0),
                "altitude": p.get("altitude", 0),
                "ground_speed": p.get("ground_speed", 0),
                "transponder": p.get("transponder", "----"),
                "aircraft": fp.get("aircraft", "Unknown")
            })
        
        # 改用信号机制推送数据，不再直接调用 runJavaScript
        import json
        json_str = json.dumps(js_data)
        self.map_bridge.updatePilotsSignal.emit(json_str)

    def fetch_flight_path(self, callsign):
        self.path_thread = APIThread(
            f"{ISFP_API_BASE}/clients/paths/{callsign}",
            headers={"Authorization": f"Bearer {self.auth_token}"} if self.auth_token else {}
        )
        self.path_thread.finished.connect(self.on_path_ready)
        self.manage_thread(self.path_thread)

    def on_path_ready(self, data):
        if data.get("code") == "200" or isinstance(data.get("data"), list):
            path_data = data.get("data", [])
            import json
            # 改用信号推送航迹数据，同时带上呼号以便 JS 区分
            # 这里我们需要从请求参数中找回 callsign，或者让 APIThread 返回它
            # 由于 APIThread 不返回原始参数，我们从 url 中解析 callsign
            # URL 格式: .../clients/paths/{callsign}
            callsign = self.sender().url.split('/')[-1]
            
            payload = {
                "callsign": callsign,
                "path": path_data
            }
            self.map_bridge.drawPathSignal.emit(json.dumps(payload))
        else:
            self.show_notification("获取航迹失败或未登录")

    def create_activities_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 顶部工具栏
        tool_layout = QHBoxLayout()
        refresh_btn = QPushButton("刷新近期活动")
        refresh_btn.setFixedWidth(150)
        refresh_btn.setStyleSheet("""
            QPushButton {
                padding: 10px; 
                background: #8e44ad; 
                color: white; 
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover { background: #9b59b6; }
        """)
        refresh_btn.clicked.connect(self.load_activities)
        tool_layout.addWidget(refresh_btn)
        tool_layout.addStretch()
        layout.addLayout(tool_layout)

        # 滚动区域
        self.activities_scroll = QScrollArea()
        self.activities_scroll.setWidgetResizable(True)
        self.activities_scroll.setStyleSheet("background: transparent; border: none;")
        
        self.activities_container = QWidget()
        self.activities_container.setStyleSheet("background: transparent;")
        self.activities_layout = QVBoxLayout(self.activities_container)
        self.activities_layout.setSpacing(15)
        self.activities_layout.addStretch()
        
        self.activities_scroll.setWidget(self.activities_container)
        layout.addWidget(self.activities_scroll)
        
        # 初始加载
        QTimer.singleShot(1000, self.load_activities)
        
        return widget

    def load_activities(self):
        # 如果有正在进行的请求，先终止它
        if hasattr(self, 'activities_thread') and self.activities_thread and self.activities_thread.isRunning():
            self.activities_thread.terminate()
            self.activities_thread.wait(1000)
        
        # 清理旧的活动卡片和错误信息
        # 保留最后的 stretch 项，移除其他所有 widget
        while self.activities_layout.count() > 1:
            item = self.activities_layout.takeAt(0)
            if item and item.widget():
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()
        
        # 强制处理事件，确保删除操作立即生效
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        # 修复：根据 hdapi.md 发送当前月份参数，避免 TIME_FORMAT_ERROR
        current_month = time.strftime("%Y-%m")
        params = {"time": current_month}

        self.activities_thread = APIThread(f"{ISFP_API_BASE}/activities", params=params, headers=headers)
        self.activities_thread.finished.connect(self.display_activities)
        self.activities_thread.error.connect(self.on_activities_error)
        self.manage_thread(self.activities_thread)

    def on_activities_error(self, error_msg):
        error_lbl = QLabel(f"❌ 网络请求异常:\n{error_msg}")
        error_lbl.setStyleSheet("color: #e74c3c; font-size: 15px; font-weight: bold; margin-top: 20px;")
        error_lbl.setAlignment(Qt.AlignCenter)
        self.activities_layout.insertWidget(0, error_lbl)

    def display_activities(self, data):
        activities = data.get("data")
        code = data.get("code")
        message = data.get("message", "未知错误")
        
        # 如果后端直接报错 TIME_FORMAT_ERROR，说明后端数据结构有问题，但我们尝试兼容
        if code == "TIME_FORMAT_ERROR" and not activities:
            error_lbl = QLabel(f"⚠️ 数据格式错误: {message}")
            error_lbl.setStyleSheet("color: #f39c12; font-size: 15px; font-weight: bold; margin-top: 20px;")
            error_lbl.setAlignment(Qt.AlignCenter)
            self.activities_layout.insertWidget(0, error_lbl)
            return

        if isinstance(activities, list):
            # 过滤：仅显示状态为 0 (报名中/未开始) 的活动
            filtered_activities = [act for act in activities if act.get("status") == 0]
            
            if not filtered_activities:
                no_data = QLabel("📅 暂无正在报名中的活动")
                no_data.setStyleSheet("color: #888; font-size: 18px;")
                no_data.setAlignment(Qt.AlignCenter)
                self.activities_layout.insertWidget(0, no_data)
                return

            for act in filtered_activities:
                card = self.create_activity_card(act)
                self.activities_layout.insertWidget(self.activities_layout.count() - 1, card)
            return

        # 错误处理
        if code == "MISSING_OR_MALFORMED_JWT":
            error_lbl = QLabel("🔒 请先在“账户”板块登录后查看活动")
            error_lbl.setStyleSheet("color: #f1c40f; font-size: 16px; font-weight: bold; margin-top: 20px;")
        else:
            error_lbl = QLabel(f"❌ 获取失败: {message}\n(错误码: {code})")
            error_lbl.setStyleSheet("color: #e74c3c; font-size: 16px; font-weight: bold; margin-top: 20px;")
        
        error_lbl.setAlignment(Qt.AlignCenter)
        self.activities_layout.insertWidget(0, error_lbl)

    def create_activity_card(self, act):
        card = QFrame()
        card.setFixedHeight(120)
        card.setCursor(Qt.PointingHandCursor)
        card.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.05);
                border-radius: 15px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            QFrame:hover {
                background: rgba(255, 255, 255, 0.1);
                border: 1px solid #3498db;
            }
        """)
        
        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(20)

        # 活动图片
        img_label = QLabel()
        img_label.setFixedSize(160, 100)
        img_label.setStyleSheet("background: #000; border-radius: 10px;")
        img_label.setAlignment(Qt.AlignCenter)
        img_label.setText("加载中...")
        layout.addWidget(img_label)

        # 异步加载活动图片
        self.async_load_activity_img(act.get("image_url"), img_label)

        # 文字信息
        info_layout = QVBoxLayout()
        title = QLabel(act.get("title", "未知活动"))
        title.setStyleSheet("color: white; font-size: 18px; font-weight: bold; border: none; background: transparent;")
        
        # 彻底修复：不再对 active_time 进行复杂的字符串处理，直接显示
        time_val = act.get("active_time", "未知时间")
        display_time = str(time_val).replace("T", " ").replace("Z", "")[:16]
        time_lbl = QLabel(f"📅 活动时间: {display_time}")
        time_lbl.setStyleSheet("color: #aaa; font-size: 14px; border: none; background: transparent;")
        
        info_layout.addWidget(title)
        info_layout.addWidget(time_lbl)
        info_layout.addStretch()
        layout.addLayout(info_layout)
        
        layout.addStretch()
        
        # 详情按钮
        detail_btn = QPushButton("查看详情")
        detail_btn.setFixedWidth(100)
        detail_btn.setStyleSheet("""
            QPushButton {
                background: rgba(52, 152, 219, 0.15);
                color: #3498db;
                border: 1px solid #3498db;
                border-radius: 5px;
                padding: 5px;
            }
            QPushButton:hover { background: #3498db; color: white; }
        """)
        detail_btn.clicked.connect(lambda: self.show_activity_detail(act))
        layout.addWidget(detail_btn)

        card.mousePressEvent = lambda e: self.show_activity_detail(act)
        return card

    def async_load_activity_img(self, url, label):
        if not url or url == "null":
            label.setText("无图片")
            return
            
        # 终极 URL 解析方案
        from urllib.parse import urljoin, quote, urlparse, urlunparse
        base_api_url = "https://isfpapi.flyisfp.com"
        
        if url.startswith("http"):
            full_url = url
        else:
            full_url = urljoin(base_api_url, url)
            
        try:
            # 修复：使用 urlparse 正确处理 query 参数，防止 ? 和 = 被编码
            parsed = urlparse(full_url)
            # 仅对 path 部分进行编码，保留 /
            new_path = quote(parsed.path, safe='/')
            
            full_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                new_path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))
        except: pass
        
        req = QNetworkRequest(QUrl(full_url))
        req.setRawHeader(b"User-Agent", b"Mozilla/5.0 ISFP-Connect/1.0")
        
        # 使用闭包保持对 reply 的引用
        reply = self.nam.get(req)
        
        def on_finished():
            # 检查 label 是否仍然有效（可能已被删除）
            try:
                label_width = label.width()
                label_height = label.height()
            except RuntimeError:
                # QLabel 已被删除，忽略此次回调
                reply.deleteLater()
                return
            
            if reply.error() == QNetworkReply.NoError:
                img_data = reply.readAll()
                image = QImage()
                if image.loadFromData(img_data):
                    # 判断是头像(方形)还是活动封面(矩形)
                    is_avatar = label_width == label_height
                    
                    if is_avatar:
                        # 头像：先裁剪为正方形，然后按 Expanding 模式缩放填满 label
                        from PySide6.QtCore import QRect
                        size = min(image.width(), image.height())
                        rect = QRect((image.width() - size) // 2, (image.height() - size) // 2, size, size)
                        image = image.copy(rect)
                        
                        # 关键修改：使用 KeepAspectRatioByExpanding 确保填满容器
                        pixmap = QPixmap.fromImage(image).scaled(
                            label.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                        )
                        radius = label.width() / 2
                    else:
                        # 封面：修复溢出问题，改用 KeepAspectRatio 保证图片完整显示在框内
                        pixmap = QPixmap.fromImage(image).scaled(
                            label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )
                        radius = 15.0

                    rounded_pixmap = QPixmap(label.size())
                    rounded_pixmap.fill(Qt.transparent)
                    
                    painter = QPainter(rounded_pixmap)
                    painter.setRenderHint(QPainter.Antialiasing)
                    
                    path = QPainterPath()
                    # 确保圆形路径不留缝隙
                    # 如果是海报，这里可能因为 KeepAspectRatio 导致 label 有空白，所以只给 pixmap 区域加圆角，或者干脆对整个 label 加
                    # 为了简单且不出错，这里对整个 label 区域做圆角裁剪
                    path.addRoundedRect(0, 0, label.width(), label.height(), radius, radius)
                    painter.setClipPath(path)
                    
                    # 居中绘制
                    x = int((label.width() - pixmap.width()) / 2)
                    y = int((label.height() - pixmap.height()) / 2)
                    painter.drawPixmap(x, y, pixmap)
                    
                    # 如果是头像，再画一个极细的白色边框提升质感，但不占用空间
                    if is_avatar:
                         pen = QPen(QColor(255, 255, 255, 100))
                         pen.setWidth(2)
                         painter.setPen(pen)
                         painter.drawRoundedRect(1, 1, label.width()-2, label.height()-2, radius-1, radius-1)
                    
                    painter.end()
                    
                    label.setPixmap(rounded_pixmap)
                    label.setText("")
                else:
                    label.setText("解码失败")
            else:
                # 自动尝试 /storage/ 路径重试
                if reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) == 404 and "storage" not in full_url:
                     alt_url = urljoin("https://isfpapi.flyisfp.com/storage/", url.split("/")[-1])
                     self.async_load_activity_img(alt_url, label) # 递归重试
                else:
                    label.setText("加载失败")
            reply.deleteLater()
            
        reply.finished.connect(on_finished)

    def show_activity_detail(self, act):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"活动详情: {act.get('title')}")
        dialog.setFixedSize(600, 800)  # 增加高度以适应 16:9 海报
        dialog.setStyleSheet("background-color: #1a1a1a; color: white;")
        
        layout = QVBoxLayout(dialog)
        
        # 大图容器：固定高度，确保不溢出
        # 16:9 比例：宽度 580 -> 高度 326
        banner_height = 326
        
        banner_container = QWidget()
        banner_container.setFixedHeight(banner_height)
        banner_layout = QVBoxLayout(banner_container)
        banner_layout.setContentsMargins(0, 0, 0, 0)
        
        banner = QLabel()
        banner.setFixedHeight(banner_height)
        # 宽度设为 dialog 宽度减去边距 (约 580)，或者直接跟随 layout
        banner.setFixedWidth(580)
        banner.setStyleSheet("background: #000; border-radius: 10px;")
        banner.setAlignment(Qt.AlignCenter)
        
        banner_layout.addWidget(banner)
        layout.addWidget(banner_container)
        
        self.async_load_activity_img(act.get("image_url"), banner)
        
        # 详情信息
        info_box = QTextEdit()
        info_box.setReadOnly(True)
        info_box.setStyleSheet("background: transparent; border: none; font-size: 14px; line-height: 1.6;")
        
        # 时间显示
        time_val = act.get("active_time", "")
        time_str = str(time_val).replace("T", " ").replace("Z", "")[:16]
        
        html = f"""
        <h2 style='color: #3498db;'>{act.get('title')}</h2>
        <p><b>📅 活动时间:</b> {time_str}</p>
        <hr style='border-top: 1px solid rgba(255,255,255,0.1);'>
        <div style='background: rgba(255,255,255,0.05); padding: 15px; border-radius: 10px;'>
            <p><b>🛫 起飞机场:</b> <span style='color: #3498db; font-family: Consolas;'>{act.get('departure_airport', '---')}</span></p>
            <p><b>🛬 落地机场:</b> <span style='color: #3498db; font-family: Consolas;'>{act.get('arrival_airport', '---')}</span></p>
            <p><b>📏 飞行距离:</b> {act.get('distance', 0)} nm</p>
            <p><b>🛣️ 推荐航路:</b></p>
            <div style='background: rgba(0,0,0,0.3); padding: 10px; border-radius: 5px; font-family: Consolas; color: #2ecc71;'>
                {act.get('route', 'DIRECT')}
            </div>
            
            <p style='margin-top: 15px;'><b>📝 NOTAM (航行通告):</b></p>
            <div style='background: rgba(231, 76, 60, 0.1); padding: 10px; border-radius: 5px; color: #e74c3c; border: 1px solid rgba(231, 76, 60, 0.3);'>
                {act.get('NOTAMS') or "暂无通告"}
            </div>
        </div>
        """
        info_box.setHtml(html)
        layout.addWidget(info_box)

        # 报名区域 (仅登录后显示)
        if self.auth_token:
            sign_frame = QFrame()
            sign_frame.setStyleSheet("background: rgba(255,255,255,0.05); border-radius: 10px; padding: 10px;")
            sign_layout = QHBoxLayout(sign_frame)
            
            callsign_input = QLineEdit()
            callsign_input.setPlaceholderText("呼号 (如 CCA123)")
            callsign_input.setStyleSheet("padding: 8px; background: #222; border-radius: 5px; color: white;")
            
            ac_type_input = QLineEdit()
            ac_type_input.setPlaceholderText("机型 (如 B738)")
            ac_type_input.setStyleSheet("padding: 8px; background: #222; border-radius: 5px; color: white;")
            
            # 按钮容器
            btn_layout = QHBoxLayout()
            
            sign_btn = QPushButton("立即报名")
            sign_btn.setCursor(Qt.PointingHandCursor)
            sign_btn.setStyleSheet("padding: 8px 15px; background: #2ecc71; color: white; border-radius: 5px; font-weight: bold;")
            
            unsign_btn = QPushButton("取消报名")
            unsign_btn.setCursor(Qt.PointingHandCursor)
            unsign_btn.setStyleSheet("padding: 8px 15px; background: #e74c3c; color: white; border-radius: 5px; font-weight: bold;")
            
            def handle_sign():
                cs = callsign_input.text().strip().upper()
                ac = ac_type_input.text().strip().upper()
                if not cs or not ac:
                    self.show_notification("请填写呼号和机型")
                    return
                
                self.sign_thread = APIThread(
                    f"{ISFP_API_BASE}/activities/{act.get('id')}/pilots",
                    method="POST",
                    json_data={"callsign": cs, "aircraft_type": ac},
                    headers={"Authorization": f"Bearer {self.auth_token}"}
                )
                self.sign_thread.finished.connect(lambda d: self.show_notification(d.get("message", "报名成功")))
                self.manage_thread(self.sign_thread)
                
            def handle_unsign():
                # 二次确认
                from PySide6.QtWidgets import QMessageBox
                msg_box = QMessageBox(dialog)
                msg_box.setWindowTitle("取消报名")
                msg_box.setText("确定要取消该活动的报名吗？")
                msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                msg_box.setStyleSheet("background-color: #2c3e50; color: white;")
                if msg_box.exec() != QMessageBox.Yes:
                    return

                self.unsign_thread = APIThread(
                    f"{ISFP_API_BASE}/activities/{act.get('id')}/pilots",
                    method="DELETE",
                    headers={"Authorization": f"Bearer {self.auth_token}"}
                )
                self.unsign_thread.finished.connect(lambda d: self.show_notification(d.get("message", "取消报名成功")))
                self.manage_thread(self.unsign_thread)
            
            sign_btn.clicked.connect(handle_sign)
            unsign_btn.clicked.connect(handle_unsign)
            
            sign_layout.addWidget(callsign_input)
            sign_layout.addWidget(ac_type_input)
            sign_layout.addWidget(sign_btn)
            sign_layout.addWidget(unsign_btn)
            layout.addWidget(sign_frame)
        else:
            tip = QLabel("🔒 登录后即可参与活动报名")
            tip.setStyleSheet("color: #f1c40f; font-size: 13px;")
            tip.setAlignment(Qt.AlignCenter)
            layout.addWidget(tip)

        close_btn = QPushButton("返回列表")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet("padding: 10px; background: #34495e; border-radius: 5px; margin-top: 10px;")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.exec()

    def create_connection_tab(self):
        """创建连线页面（X-Plane Native Plugin 连接）"""
        # 使用滚动区域作为主容器
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
            QScrollBar:vertical {
                background: rgba(0, 0, 0, 0.3);
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.3);
                border-radius: 5px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.5);
            }
        """)
        
        # 创建内容容器
        content_widget = QWidget()
        content_widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        
        # 标题
        title = QLabel("🎮 模拟器连线")
        title.setFont(QFont("Microsoft YaHei", 24, QFont.Bold))
        title.setStyleSheet("color: white;")
        layout.addWidget(title)
        
        # 副标题说明
        subtitle = QLabel("通过 ISFP Connect 原生插件连接 X-Plane 模拟器")
        subtitle.setStyleSheet("color: #7f8c8d; font-size: 13px;")
        layout.addWidget(subtitle)
        
        # 检查 X-Plane TCP 客户端是否可用
        if not XPLANE_TCP_AVAILABLE:
            error_label = QLabel("⚠️ X-Plane TCP 客户端模块未加载，请检查 xplane_tcp_client.py 文件是否存在")
            error_label.setStyleSheet("color: #e74c3c; font-size: 14px; padding: 20px;")
            layout.addWidget(error_label)
            layout.addStretch()
            scroll_area.setWidget(content_widget)
            return scroll_area
        
        # 连接状态卡片
        status_card = QFrame()
        status_card.setStyleSheet("""
            QFrame {
                background: rgba(0, 0, 0, 0.3);
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                padding: 20px;
            }
        """)
        status_layout = QVBoxLayout(status_card)
        
        # 状态标题
        status_title = QLabel("连接状态")
        status_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        status_title.setStyleSheet("color: white;")
        status_layout.addWidget(status_title)
        
        # 状态指示器
        self.connection_status_label = QLabel("🔴 未连接")
        self.connection_status_label.setFont(QFont("Microsoft YaHei", 16))
        self.connection_status_label.setStyleSheet("color: #e74c3c; padding: 10px 0;")
        status_layout.addWidget(self.connection_status_label)
        
        # 连接信息
        self.connection_info_label = QLabel('点击"连接"按钮连接到 X-Plane')
        self.connection_info_label.setStyleSheet("color: #bdc3c7; font-size: 12px;")
        status_layout.addWidget(self.connection_info_label)
        
        # 按钮区域
        btn_layout = QHBoxLayout()
        
        self.connect_btn = QPushButton("🔗 连接")
        self.connect_btn.setCursor(Qt.PointingHandCursor)
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background: #27ae60;
                color: white;
                padding: 12px 30px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background: #2ecc71;
            }
            QPushButton:disabled {
                background: #7f8c8d;
            }
        """)
        self.connect_btn.clicked.connect(self.on_connect_xplane)
        btn_layout.addWidget(self.connect_btn)
        
        self.disconnect_btn = QPushButton("❌ 断开")
        self.disconnect_btn.setCursor(Qt.PointingHandCursor)
        self.disconnect_btn.setStyleSheet("""
            QPushButton {
                background: #c0392b;
                color: white;
                padding: 12px 30px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background: #e74c3c;
            }
            QPushButton:disabled {
                background: #7f8c8d;
            }
        """)
        self.disconnect_btn.clicked.connect(self.on_disconnect_xplane)
        self.disconnect_btn.setEnabled(False)
        btn_layout.addWidget(self.disconnect_btn)
        
        btn_layout.addStretch()
        status_layout.addLayout(btn_layout)
        
        layout.addWidget(status_card)
        
        # 飞机数据卡片
        data_card = QFrame()
        data_card.setStyleSheet("""
            QFrame {
                background: rgba(0, 0, 0, 0.3);
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                padding: 20px;
            }
        """)
        data_layout = QVBoxLayout(data_card)
        
        data_title = QLabel("✈️ 本机数据")
        data_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        data_title.setStyleSheet("color: white;")
        data_layout.addWidget(data_title)
        
        # 数据标签
        self.own_data_label = QLabel("未连接模拟器")
        self.own_data_label.setStyleSheet("color: #bdc3c7; font-size: 12px; font-family: Consolas, monospace;")
        self.own_data_label.setWordWrap(True)
        data_layout.addWidget(self.own_data_label)
        
        layout.addWidget(data_card)
        
        # ==================== FSD 服务器连接卡片 ====================
        fsd_card = QFrame()
        fsd_card.setStyleSheet("""
            QFrame {
                background: rgba(0, 0, 0, 0.3);
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                padding: 20px;
            }
        """)
        fsd_layout = QVBoxLayout(fsd_card)
        
        fsd_title = QLabel("🌐 FSD 服务器连接")
        fsd_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        fsd_title.setStyleSheet("color: white;")
        fsd_layout.addWidget(fsd_title)
        
        # 检查 FSD 模块是否可用
        if not FSD_AVAILABLE:
            fsd_error_label = QLabel("⚠️ FSD 模块未加载")
            fsd_error_label.setStyleSheet("color: #e74c3c; font-size: 12px; padding: 10px;")
            fsd_layout.addWidget(fsd_error_label)
        else:
            # FSD 连接状态
            self.fsd_status_label = QLabel("🔴 未连接")
            self.fsd_status_label.setFont(QFont("Microsoft YaHei", 14))
            self.fsd_status_label.setStyleSheet("color: #e74c3c; padding: 10px 0;")
            fsd_layout.addWidget(self.fsd_status_label)
            
            # FSD 连接信息
            self.fsd_info_label = QLabel('点击按钮连接到服务器')
            self.fsd_info_label.setStyleSheet("color: #bdc3c7; font-size: 12px;")
            fsd_layout.addWidget(self.fsd_info_label)
            
            # 服务器配置（使用垂直布局，去掉表单的外框）
            fsd_config_layout = QVBoxLayout()
            fsd_config_layout.setSpacing(10)
            fsd_config_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            
            # 服务器和端口固定，不需要用户输入
            self.fsd_server = "fsd.flyisfp.com"
            self.fsd_port = 6809
            
            # 显示固定的服务器信息（只读）
            server_info = QLabel("🌐 fsd.flyisfp.com:6809")
            server_info.setStyleSheet("color: #7f8c8d; font-size: 12px;")
            fsd_config_layout.addWidget(server_info)
            
            # 呼号输入
            self.fsd_callsign_input = QLineEdit()
            self.fsd_callsign_input.setMaximumWidth(300)
            self.fsd_callsign_input.setFixedHeight(28)
            self.fsd_callsign_input.setStyleSheet("""
                QLineEdit {
                    background: transparent;
                    border: none;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.3);
                    padding: 2px 4px;
                    color: white;
                }
                QLineEdit:focus {
                    border-bottom: 1px solid #3498db;
                }
            """)
            self.fsd_callsign_input.setPlaceholderText("呼号 (如 CCA1234)")
            fsd_config_layout.addWidget(self.fsd_callsign_input)
            
            # 真实姓名输入
            self.fsd_realname_input = QLineEdit()
            self.fsd_realname_input.setMaximumWidth(300)
            self.fsd_realname_input.setFixedHeight(28)
            self.fsd_realname_input.setStyleSheet("""
                QLineEdit {
                    background: transparent;
                    border: none;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.3);
                    padding: 2px 4px;
                    color: white;
                }
                QLineEdit:focus {
                    border-bottom: 1px solid #3498db;
                }
            """)
            self.fsd_realname_input.setPlaceholderText("昵称或CID (如 quanquan)")
            fsd_config_layout.addWidget(self.fsd_realname_input)
            
            fsd_layout.addLayout(fsd_config_layout)
            
            # FSD 按钮区域
            fsd_btn_layout = QHBoxLayout()
            
            self.fsd_connect_btn = QPushButton("🔗 连接服务器")
            self.fsd_connect_btn.setCursor(Qt.PointingHandCursor)
            self.fsd_connect_btn.setStyleSheet("""
                QPushButton {
                    background: #2980b9;
                    color: white;
                    padding: 10px 25px;
                    border-radius: 6px;
                    font-size: 13px;
                    font-weight: bold;
                    border: none;
                }
                QPushButton:hover {
                    background: #3498db;
                }
                QPushButton:disabled {
                    background: #7f8c8d;
                }
            """)
            self.fsd_connect_btn.clicked.connect(self.on_connect_fsd)
            fsd_btn_layout.addWidget(self.fsd_connect_btn)
            
            self.fsd_disconnect_btn = QPushButton("❌ 断开")
            self.fsd_disconnect_btn.setCursor(Qt.PointingHandCursor)
            self.fsd_disconnect_btn.setStyleSheet("""
                QPushButton {
                    background: #c0392b;
                    color: white;
                    padding: 10px 25px;
                    border-radius: 6px;
                    font-size: 13px;
                    font-weight: bold;
                    border: none;
                }
                QPushButton:hover {
                    background: #e74c3c;
                }
                QPushButton:disabled {
                    background: #7f8c8d;
                }
            """)
            self.fsd_disconnect_btn.clicked.connect(self.on_disconnect_fsd)
            self.fsd_disconnect_btn.setEnabled(False)
            fsd_btn_layout.addWidget(self.fsd_disconnect_btn)
            
            fsd_btn_layout.addStretch()
            fsd_layout.addLayout(fsd_btn_layout)
            
            # 日志显示区域（只显示连接日志）
            fsd_log_label = QLabel("📋 连接日志")
            fsd_log_label.setStyleSheet("color: #bdc3c7; font-size: 12px; margin-top: 10px;")
            fsd_layout.addWidget(fsd_log_label)
            
            self.fsd_messages = QTextEdit()
            self.fsd_messages.setReadOnly(True)
            self.fsd_messages.setMaximumHeight(80)
            self.fsd_messages.setStyleSheet("""
                QTextEdit {
                    background: rgba(0, 0, 0, 0.5);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 5px;
                    color: #7f8c8d;
                    font-family: Consolas, monospace;
                    font-size: 10px;
                }
            """)
            fsd_layout.addWidget(self.fsd_messages)
            
            # 信息栏目（显示文本消息）
            fsd_info_label = QLabel("💬 信息")
            fsd_info_label.setStyleSheet("color: #bdc3c7; font-size: 12px; margin-top: 10px;")
            fsd_layout.addWidget(fsd_info_label)
            
            self.fsd_info_messages = QTextEdit()
            self.fsd_info_messages.setReadOnly(True)
            self.fsd_info_messages.setMinimumHeight(150)
            self.fsd_info_messages.setStyleSheet("""
                QTextEdit {
                    background: rgba(0, 0, 0, 0.5);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 5px;
                    color: #2ecc71;
                    font-family: Consolas, monospace;
                    font-size: 11px;
                }
            """)
            fsd_layout.addWidget(self.fsd_info_messages)
        
        layout.addWidget(fsd_card)
        
        layout.addStretch()
        
        # 设置内容容器到滚动区域
        scroll_area.setWidget(content_widget)
        
        # 初始化 X-Plane TCP Client
        self.xplane_connector = None
        self._connection_update_timer = QTimer(self)
        self._connection_update_timer.timeout.connect(self.update_connection_ui)
        self._connection_update_timer.start(1000)  # 每秒更新一次 UI
        
        # 初始化 FSD Client
        self.fsd_client = None
        
        return scroll_area
    

    
    def on_connect_xplane(self):
        """连接到 X-Plane"""
        if not XPLANE_TCP_AVAILABLE:
            self.show_notification("X-Plane TCP 客户端模块不可用")
            return
        
        # 获取或创建连接器
        if self.xplane_connector is None:
            self.xplane_connector = get_xplane_tcp_client()
            # 连接信号
            self.xplane_connector.connected.connect(self.on_xplane_connected)
            self.xplane_connector.disconnected.connect(self.on_xplane_disconnected)
            self.xplane_connector.flight_data_received.connect(self.on_xplane_data_received)
            self.xplane_connector.error_occurred.connect(self.on_xplane_connection_error)
        
        # 尝试连接
        self.connect_btn.setEnabled(False)
        self.connection_status_label.setText("🟡 连接中...")
        self.connection_status_label.setStyleSheet("color: #f39c12; padding: 10px 0;")
        self.connection_info_label.setText("正在连接到 X-Plane 插件...")
        
        # 在后台线程中连接
        import threading
        thread = threading.Thread(target=self._do_connect_xplane, daemon=True)
        thread.start()
    
    def _do_connect_xplane(self):
        """执行连接（在后台线程中）"""
        try:
            success = self.xplane_connector.connect_to_xplane()
            if not success:
                # 连接失败，在主线程中更新 UI
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self._on_xplane_connect_failed)
        except Exception as e:
            logger.error(f"连接 X-Plane 异常: {e}")
            from PySide6.QtCore import QTimer
            self._connect_error_msg = str(e)
            QTimer.singleShot(0, self._on_xplane_connect_error)
    
    def _on_xplane_connect_failed(self):
        """连接失败回调（在主线程中）"""
        self.connect_btn.setEnabled(True)
        self.connection_status_label.setText("🔴 连接失败")
        self.connection_status_label.setStyleSheet("color: #e74c3c; padding: 10px 0;")
        self.connection_info_label.setText("连接失败，请检查 X-Plane 是否运行并加载了 ISFP Connect 插件")
    
    def _on_xplane_connect_error(self):
        """连接错误回调（在主线程中）"""
        error_msg = getattr(self, '_connect_error_msg', 'Unknown error')
        self.connect_btn.setEnabled(True)
        self.connection_status_label.setText("🔴 连接异常")
        self.connection_status_label.setStyleSheet("color: #e74c3c; padding: 10px 0;")
        self.connection_info_label.setText(f"连接异常: {error_msg}")
    
    def on_xplane_connected(self):
        """X-Plane 已连接回调"""
        self.connection_status_label.setText("🟢 已连接")
        self.connection_status_label.setStyleSheet("color: #2ecc71; padding: 10px 0;")
        self.connection_info_label.setText("已成功连接到 X-Plane")
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        self.show_notification("已成功连接到 X-Plane")
    
    def on_xplane_disconnected(self):
        """X-Plane 断开连接回调"""
        self.connection_status_label.setText("🔴 未连接")
        self.connection_status_label.setStyleSheet("color: #e74c3c; padding: 10px 0;")
        self.connection_info_label.setText('点击"连接"按钮连接到 X-Plane')
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
    
    def on_xplane_data_received(self, data):
        """接收到 X-Plane 飞行数据"""
        # 更新本机数据显示
        data_text = f"""
<b>位置:</b> {data.get('latitude', 0):.4f}°, {data.get('longitude', 0):.4f}°<br>
<b>高度:</b> {data.get('altitude_msl', 0):.0f}ft / {data.get('altitude_agl', 0):.0f}ft AGL<br>
<b>姿态:</b> P:{data.get('pitch', 0):.1f}° R:{data.get('roll', 0):.1f}° H:{data.get('heading', 0):.1f}°<br>
<b>速度:</b> IAS:{data.get('indicated_airspeed', 0):.0f}kt GS:{data.get('groundspeed', 0):.0f}kt<br>
<b>应答机:</b> {data.get('transponder', 0):04d}
        """.strip()
        self.own_data_label.setText(data_text)
        
        # 保存最新数据用于 FSD 位置更新
        self._latest_xplane_data = data
        
        # 如果 FSD 已连接，更新位置数据
        if FSD_AVAILABLE and self.fsd_client and hasattr(self.fsd_client, '_is_authenticated') and self.fsd_client._is_authenticated:
            self._update_fsd_position(data)
    
    def on_disconnect_xplane(self):
        """断开与 X-Plane 的连接"""
        if self.xplane_connector:
            self.xplane_connector.disconnect()
            self.show_notification("已断开与 X-Plane 的连接")
    
    def _update_fsd_position(self, data):
        """更新 FSD 位置数据"""
        try:
            from fsd_client import FSDPilotPosition, TransponderMode
            
            # 从 X-Plane 数据创建 FSD 位置对象
            # 注意：FSDPilotPosition 使用 bank 而不是 roll
            altitude_msl = data.get('altitude_msl', 0)
            position = FSDPilotPosition(
                latitude=data.get('latitude', 0),
                longitude=data.get('longitude', 0),
                altitude_true=int(altitude_msl),
                altitude_pressure=int(altitude_msl),  # 使用 MSL 高度作为气压高度
                groundspeed=int(data.get('groundspeed', 0)),
                pitch=data.get('pitch', 0),
                bank=data.get('roll', 0),  # roll 对应 bank
                heading=data.get('heading', 0),
                on_ground=data.get('on_ground', False)
            )
            
            # 获取应答机代码和模式
            transponder = data.get('transponder', 1200)
            transponder_mode = TransponderMode.ON  # 默认 Mode C (ON)
            
            # 更新 FSD 客户端位置
            self.fsd_client.update_position(
                position=position,
                transponder_code=transponder,
                transponder_mode=transponder_mode
            )
            
            logger.debug(f"FSD 位置已更新: lat={position.latitude:.4f}, lon={position.longitude:.4f}, alt={position.altitude_true}")
        except Exception as e:
            logger.debug(f"更新 FSD 位置失败: {e}")
    
    def on_xplane_connection_error(self, error_msg):
        """X-Plane 连接错误回调"""
        self.show_notification(f"X-Plane 连接错误: {error_msg}")
        self.connection_info_label.setText(f"错误: {error_msg}")
    
    def update_connection_ui(self):
        """更新连接页面 UI"""
        if not XPLANE_TCP_AVAILABLE or not self.xplane_connector:
            return
        
        # 更新连接状态
        if self.xplane_connector.is_connected():
            self.connection_status_label.setText("🟢 已连接")
            self.connection_status_label.setStyleSheet("color: #2ecc71; padding: 10px 0;")
        else:
            self.connection_status_label.setText("🔴 未连接")
            self.connection_status_label.setStyleSheet("color: #e74c3c; padding: 10px 0;")
    
    # ==================== FSD 服务器连接方法 ====================
    
    def on_connect_fsd(self):
        """连接到 FSD 服务器"""
        from PySide6.QtWidgets import QMessageBox
        
        if not FSD_AVAILABLE:
            self.show_notification("FSD 模块不可用")
            return
        
        # 检查是否已连接 X-Plane 模拟器
        if not self.xplane_connector or not self.xplane_connector.is_connected:
            QMessageBox.warning(self, "无法连接", "请先连接 X-Plane 模拟器后再连接 FSD 服务器。")
            return
        
        # 获取连接参数（服务器和端口固定）
        server = self.fsd_server
        port = self.fsd_port
        callsign = self.fsd_callsign_input.text().strip().upper()
        real_name = self.fsd_realname_input.text().strip()
        
        # 自动检测 X-Plane 版本并转换为 FSD sim_type
        # X-Plane 11 = 15, X-Plane 12 = 16
        xp_version = self.xplane_connector.get_simulator_version()
        sim_type = 15 if xp_version == 11 else 16
        
        if not callsign:
            self.show_notification("请输入呼号")
            return
        
        if not real_name:
            self.show_notification("请输入真实姓名")
            return
        
        # 获取用户凭证
        cid = ""
        password = ""
        if self.user_data:
            cid = str(self.user_data.get('user', {}).get('cid', ''))
            password = self.settings.value("password", "")
        
        if not cid or not password:
            self.show_notification("请先登录以获取 CID 和密码")
            return
        
        # 获取或创建 FSD 客户端
        if self.fsd_client is None:
            self.fsd_client = get_fsd_client(self)
            # 连接信号
            self.fsd_client.connected.connect(self.on_fsd_connected)
            self.fsd_client.disconnected.connect(self.on_fsd_disconnected)
            self.fsd_client.error.connect(self.on_fsd_error)
            self.fsd_client.text_message_received.connect(self.on_fsd_text_message)
            self.fsd_client.server_error.connect(self.on_fsd_server_error)
        
        # 设置认证信息
        self.fsd_client._callsign = callsign
        self.fsd_client._cid = cid
        self.fsd_client._password = password
        self.fsd_client._real_name = real_name
        self.fsd_client._sim_type = sim_type
        
        # 更新 UI
        self.fsd_status_label.setText("🟡 连接中...")
        self.fsd_status_label.setStyleSheet("color: #f39c12; padding: 10px 0;")
        self.fsd_info_label.setText(f"正在连接到 {server}:{port}...")
        self.fsd_connect_btn.setEnabled(False)
        
        # 尝试连接
        try:
            success = self.fsd_client.connect_to_server(server, port)
            if success:
                self._append_fsd_message(f"已连接到服务器 {server}:{port}")
                self._append_fsd_message("等待服务器识别...")
            else:
                self.fsd_status_label.setText("🔴 连接失败")
                self.fsd_status_label.setStyleSheet("color: #e74c3c; padding: 10px 0;")
                self.fsd_info_label.setText("连接失败，请检查服务器地址和端口")
                self.fsd_connect_btn.setEnabled(True)
        except Exception as e:
            logger.error(f"连接 FSD 服务器异常: {e}")
            self.fsd_status_label.setText("🔴 连接异常")
            self.fsd_status_label.setStyleSheet("color: #e74c3c; padding: 10px 0;")
            self.fsd_info_label.setText(f"连接异常: {str(e)}")
            self.fsd_connect_btn.setEnabled(True)
    
    def on_disconnect_fsd(self):
        """断开 FSD 服务器连接"""
        if self.fsd_client:
            self.fsd_client.disconnect_from_server()
            self._append_fsd_message("已断开与 FSD 服务器的连接")
    
    def on_fsd_connected(self):
        """FSD 连接成功"""
        self.fsd_status_label.setText("🟢 已连接")
        self.fsd_status_label.setStyleSheet("color: #2ecc71; padding: 10px 0;")
        self.fsd_info_label.setText(f"已连接到 FSD 服务器，呼号: {self.fsd_client._callsign}")
        self.fsd_connect_btn.setEnabled(False)
        self.fsd_disconnect_btn.setEnabled(True)
        self.show_notification("已连接到 FSD 服务器")
        
        # 启动定期位置更新（每 5 秒）
        self.fsd_client.start_position_updates(5000)
        logger.info("FSD 位置更新已启动（每 5 秒）")
        
        # 立即发送一次当前位置数据（如果有）
        if hasattr(self, '_latest_xplane_data') and self._latest_xplane_data:
            self._update_fsd_position(self._latest_xplane_data)
            logger.info("FSD 连接成功，已发送初始位置数据")
    
    def on_fsd_disconnected(self):
        """FSD 断开连接"""
        self.fsd_status_label.setText("🔴 未连接")
        self.fsd_status_label.setStyleSheet("color: #e74c3c; padding: 10px 0;")
        self.fsd_info_label.setText('点击"连接服务器"按钮连接到 FSD')
        self.fsd_connect_btn.setEnabled(True)
        self.fsd_disconnect_btn.setEnabled(False)
        
        # 停止位置更新
        if self.fsd_client:
            self.fsd_client.stop_position_updates()
            logger.info("FSD 位置更新已停止")
    
    def on_fsd_error(self, error_msg):
        """FSD 错误处理"""
        self._append_fsd_message(f"[错误] {error_msg}")
        self.show_notification(f"FSD 错误: {error_msg}")
    
    def on_fsd_text_message(self, sender, receiver, message):
        """收到 FSD 文本消息 - 显示在信息栏目、播放提示音、展示在灵动岛"""
        # 显示在信息栏目
        self._append_fsd_info_message(f"[{sender}] {message}")
        
        # 播放提示音
        self._play_message_sound()
        
        # 在灵动岛展示消息（5秒）
        try:
            from dynamic_island import get_dynamic_island
            island = get_dynamic_island(self)
            if island and island.is_enabled:
                # 截断消息如果太长
                display_msg = message[:30] + "..." if len(message) > 30 else message
                island.show_message(f"📨 {sender}: {display_msg}", duration=5000)
        except Exception as e:
            logger.debug(f"灵动岛显示消息失败: {e}")
    
    def _play_message_sound(self):
        """播放消息提示音"""
        try:
            from PySide6.QtMultimedia import QSoundEffect
            from PySide6.QtCore import QUrl
            
            # 创建提示音
            sound = QSoundEffect(self)
            sound.setSource(QUrl.fromLocalFile("assets/message.wav"))
            sound.setVolume(0.5)
            sound.play()
        except Exception as e:
            # 如果播放失败（没有音频文件或不支持），使用系统提示音
            try:
                from PySide6.QtWidgets import QApplication
                QApplication.beep()
            except:
                pass
    
    def on_fsd_server_error(self, error_type, message):
        """收到 FSD 服务器错误 - 显示在信息栏目"""
        self._append_fsd_info_message(f"[服务器错误 - {error_type}] {message}")
    
    def _append_fsd_message(self, message):
        """添加日志到 FSD 日志显示区（连接日志）"""
        if hasattr(self, 'fsd_messages'):
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.fsd_messages.append(f"[{timestamp}] {message}")
            # 滚动到底部
            scrollbar = self.fsd_messages.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
    
    def _append_fsd_info_message(self, message):
        """添加消息到 FSD 信息栏目（文本消息）"""
        if hasattr(self, 'fsd_info_messages'):
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.fsd_info_messages.append(f"[{timestamp}] {message}")
            # 滚动到底部
            scrollbar = self.fsd_info_messages.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def create_account_tab(self):
        self.account_widget = QWidget()
        self.account_layout = QVBoxLayout(self.account_widget)
        self.update_account_ui()
        return self.account_widget

    def update_account_ui(self):
        # 更新顶部栏状态
        if self.auth_token and self.user_data:
            user = self.user_data.get("user", {})
            username = user.get('username', '用户')
            self.top_user_btn.setText(f"👤 {username}")
            self.top_user_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(46, 204, 113, 0.3);
                    color: white;
                    border-radius: 17px;
                    font-size: 12px;
                    border: none;
                }
                QPushButton:hover {
                    background: rgba(46, 204, 113, 0.5);
                }
            """)
        else:
            self.top_user_btn.setText("未登录")
            self.top_user_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(52, 152, 219, 0.3);
                    color: white;
                    border-radius: 17px;
                    font-size: 12px;
                    border: none;
                }
                QPushButton:hover {
                    background: rgba(52, 152, 219, 0.5);
                }
            """)

        # 清空当前布局
        while self.account_layout.count():
            item = self.account_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self.auth_token:
            self.show_profile_view()
        else:
            self.show_login_view()

    def show_login_view(self):
        container = QFrame()
        container.setFixedWidth(450)
        container.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.05);
                border-radius: 30px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
        """)
        
        # 磨砂效果
        blur = QGraphicsBlurEffect()
        blur.setBlurRadius(20)
        # container.setGraphicsEffect(blur) # 注意：对容器整体设置模糊会模糊子控件，这里用半透明背景代替

        layout = QVBoxLayout(container)
        layout.setContentsMargins(40, 50, 40, 50)
        layout.setSpacing(25)

        title = QLabel("登 录")
        title.setFont(QFont("Microsoft YaHei", 28, QFont.Bold))
        title.setStyleSheet("color: white; border: none; background: transparent;")
        layout.addWidget(title, alignment=Qt.AlignCenter)

        subtitle = QLabel("欢迎回到 ISFP CONNECT")
        subtitle.setStyleSheet("color: #888; border: none; background: transparent; font-size: 14px;")
        layout.addWidget(subtitle, alignment=Qt.AlignCenter)

        # 输入框样式
        input_style = """
            QLineEdit {
                padding: 15px;
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
                color: white;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #3498db;
                background: rgba(255, 255, 255, 0.1);
            }
        """

        self.login_user = QLineEdit()
        self.login_user.setPlaceholderText("用户名 / 邮箱 / CID")
        self.login_user.setStyleSheet(input_style)
        layout.addWidget(self.login_user)

        self.login_pass = QLineEdit()
        self.login_pass.setPlaceholderText("密码")
        self.login_pass.setEchoMode(QLineEdit.Password)
        self.login_pass.setStyleSheet(input_style)
        layout.addWidget(self.login_pass)

        login_btn = QPushButton("登 录")
        login_btn.setFixedHeight(50)
        login_btn.setCursor(Qt.PointingHandCursor)
        login_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3498db, stop:1 #2980b9);
                color: white;
                font-weight: bold;
                font-size: 16px;
                border-radius: 12px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4aa3df, stop:1 #3498db);
            }
        """)
        login_btn.clicked.connect(self.handle_login)
        
        # 记住我复选框
        self.remember_me_cb = QCheckBox("记住我")
        # 修复：显式设置勾选状态的图标，这里用文字 √ 代替图片，确保可见
        self.remember_me_cb.setStyleSheet("""
            QCheckBox { 
                color: #ccc; 
                font-size: 13px; 
                background: transparent; 
                spacing: 5px;
            }
            QCheckBox::indicator { 
                width: 18px; 
                height: 18px; 
                border-radius: 4px; 
                border: 1px solid #555; 
                background-color: rgba(255, 255, 255, 0.1);
            }
            QCheckBox::indicator:checked { 
                background-color: #3498db; 
                border-color: #3498db; 
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjMiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCI+PHBvbHlsaW5lIHBvaW50cz0iMjAgNiA5IDE3IDQgMTIiPjwvcG9seWxpbmU+PC9zdmc+);
            }
            QCheckBox::indicator:hover {
                border-color: #3498db;
            }
        """)
        self.remember_me_cb.setCursor(Qt.PointingHandCursor)
        
        # 加载保存的凭据
        if self.settings.value("remember_me", False, type=bool):
            self.remember_me_cb.setChecked(True)
            self.login_user.setText(self.settings.value("username", ""))
            self.login_pass.setText(self.settings.value("password", ""))
        
        # 按钮行布局
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addWidget(self.remember_me_cb)
        
        layout.addLayout(btn_layout)
        layout.addWidget(login_btn)

        reg_btn = QPushButton("没有账号？立即注册")
        reg_btn.setCursor(Qt.PointingHandCursor)
        reg_btn.setStyleSheet("color: #3498db; background: transparent; text-decoration: none; border: none; font-size: 13px;")
        reg_btn.clicked.connect(self.show_register_view)
        layout.addWidget(reg_btn, alignment=Qt.AlignCenter)

        self.account_layout.addStretch()
        self.account_layout.addWidget(container, alignment=Qt.AlignCenter)
        self.account_layout.addStretch()

    def show_register_view(self):
        # 清空当前布局
        while self.account_layout.count():
            item = self.account_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        container = QFrame()
        container.setFixedWidth(500)
        container.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.05);
                border-radius: 30px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
        """)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(15)

        title = QLabel("注 册")
        title.setFont(QFont("Microsoft YaHei", 28, QFont.Bold))
        title.setStyleSheet("color: white; border: none; background: transparent;")
        layout.addWidget(title, alignment=Qt.AlignCenter)

        input_style = """
            QLineEdit {
                padding: 12px;
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 10px;
                color: white;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #8e44ad;
                background: rgba(255, 255, 255, 0.1);
            }
        """

        self.reg_user = QLineEdit(); self.reg_user.setPlaceholderText("用户名")
        self.reg_email = QLineEdit(); self.reg_email.setPlaceholderText("电子邮箱")
        self.reg_pass = QLineEdit(); self.reg_pass.setPlaceholderText("设置密码"); self.reg_pass.setEchoMode(QLineEdit.Password)
        self.reg_cid = QLineEdit(); self.reg_cid.setPlaceholderText("数字呼号 (CID)")
        
        for w in [self.reg_user, self.reg_email, self.reg_pass, self.reg_cid]:
            w.setStyleSheet(input_style)
            layout.addWidget(w)
        
        # 验证码行
        code_layout = QHBoxLayout()
        code_layout.setSpacing(10)
        self.reg_code = QLineEdit(); self.reg_code.setPlaceholderText("邮箱验证码")
        self.reg_code.setStyleSheet(input_style)
        
        send_code_btn = QPushButton("获取验证码")
        send_code_btn.setFixedWidth(120)
        send_code_btn.setFixedHeight(45)
        send_code_btn.setCursor(Qt.PointingHandCursor)
        send_code_btn.setStyleSheet("""
            QPushButton {
                background: rgba(142, 68, 173, 0.2);
                color: #9b59b6;
                border: 1px solid #8e44ad;
                border-radius: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #8e44ad;
                color: white;
            }
        """)
        send_code_btn.clicked.connect(self.handle_send_code)
        code_layout.addWidget(self.reg_code)
        code_layout.addWidget(send_code_btn)
        layout.addLayout(code_layout)

        reg_btn = QPushButton("立 即 注 册")
        reg_btn.setFixedHeight(50)
        reg_btn.setCursor(Qt.PointingHandCursor)
        reg_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8e44ad, stop:1 #6c3483);
                color: white;
                font-weight: bold;
                font-size: 16px;
                border-radius: 12px;
                border: none;
                margin-top: 10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #9b59b6, stop:1 #8e44ad);
            }
        """)
        reg_btn.clicked.connect(self.handle_register)
        layout.addWidget(reg_btn)

        back_btn = QPushButton("已有账号？返回登录")
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.setStyleSheet("color: #888; background: transparent; text-decoration: none; border: none; font-size: 13px;")
        back_btn.clicked.connect(self.update_account_ui)
        layout.addWidget(back_btn, alignment=Qt.AlignCenter)

        self.account_layout.addStretch()
        self.account_layout.addWidget(container, alignment=Qt.AlignCenter)
        self.account_layout.addStretch()

    def show_profile_view(self):
        container = QFrame()
        container.setFixedWidth(500)
        container.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.05);
                border-radius: 30px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
        """)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(50, 50, 50, 50)
        layout.setSpacing(25)

        user = self.user_data.get("user", {})
        
        # 头像区
        avatar_container = QWidget()
        avatar_container.setAttribute(Qt.WA_TranslucentBackground)
        avatar_layout = QVBoxLayout(avatar_container)
        avatar_layout.setContentsMargins(0, 0, 0, 0)
        avatar = QLabel()
        avatar.setFixedSize(120, 120)
        avatar.setAttribute(Qt.WA_TranslucentBackground)
        # 移除 border，防止蓝边干扰，同时保持背景色以防图片加载失败时太突兀
        avatar.setStyleSheet("background: transparent; border-radius: 60px;")
        avatar.setAlignment(Qt.AlignCenter)
        
        # 异步加载头像
        avatar_url = user.get("avatar_url")
        if avatar_url:
            self.async_load_activity_img(avatar_url, avatar) # 复用图片加载逻辑
        
        avatar_layout.addWidget(avatar, alignment=Qt.AlignCenter)
        layout.addWidget(avatar_container)

        name = QLabel(user.get("username", "Unknown"))
        name.setFont(QFont("Microsoft YaHei", 24, QFont.Bold))
        name.setStyleSheet("color: white; border: none; background: transparent;")
        layout.addWidget(name, alignment=Qt.AlignCenter)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(10)
        
        def add_info_row(icon, label, value):
            row = QHBoxLayout()
            l_lbl = QLabel(f"{icon} {label}:")
            l_lbl.setStyleSheet("color: #888; font-size: 14px; border: none; background: transparent;")
            v_lbl = QLabel(str(value))
            v_lbl.setStyleSheet("color: white; font-weight: bold; font-size: 14px; border: none; background: transparent;")
            row.addWidget(l_lbl)
            row.addStretch()
            row.addWidget(v_lbl)
            info_layout.addLayout(row)

        add_info_row("🆔", "呼号 (CID)", user.get("cid"))
        add_info_row("📧", "电子邮箱", user.get("email"))
        add_info_row("🛡️", "FSD权限", f"Rating {user.get('rating', 0)}")
        
        layout.addLayout(info_layout)

        # 连线历史按钮
        history_btn = QPushButton("查看连线历史")
        history_btn.setCursor(Qt.PointingHandCursor)
        history_btn.setStyleSheet("""
            QPushButton {
                background: rgba(52, 152, 219, 0.15);
                color: #3498db;
                border: 1px solid #3498db;
                border-radius: 10px;
                font-weight: bold;
                padding: 10px;
                margin-top: 10px;
            }
            QPushButton:hover {
                background: #3498db;
                color: white;
            }
        """)
        history_btn.clicked.connect(self.show_history_dialog)
        layout.addWidget(history_btn)

        logout_btn = QPushButton("🚪 退出登录")
        logout_btn.setCursor(Qt.PointingHandCursor)
        logout_btn.setStyleSheet("""
            QPushButton {
                background: rgba(231, 76, 60, 0.15);
                color: #e74c3c;
                border: 1px solid #e74c3c;
                border-radius: 10px;
                font-weight: bold;
                padding: 10px;
                margin-top: 20px;
            }
            QPushButton:hover {
                background: #e74c3c;
                color: white;
            }
        """)
        logout_btn.clicked.connect(self.handle_logout)
        layout.addWidget(logout_btn)

        self.account_layout.addStretch()
        self.account_layout.addWidget(container, alignment=Qt.AlignCenter)
        self.account_layout.addStretch()

    @debounce(1000)
    def handle_login(self):
        user = self.login_user.text().strip()
        pwd = self.login_pass.text().strip()
        if not user or not pwd: return

        self.login_thread = APIThread(f"{ISFP_API_BASE}/users/sessions", method="POST", json_data={
            "username": user,
            "password": pwd
        })
        self.login_thread.finished.connect(self.on_login_finished)
        self.manage_thread(self.login_thread)

    def on_login_finished(self, data):
        if data.get("code") == "LOGIN_SUCCESS":
            self.auth_token = data.get("data", {}).get("token")
            self.user_data = data.get("data")
            
            # 处理“记住我”逻辑
            if self.remember_me_cb.isChecked():
                self.settings.setValue("remember_me", True)
                self.settings.setValue("username", self.login_user.text().strip())
                self.settings.setValue("password", self.login_pass.text().strip())
            else:
                self.settings.setValue("remember_me", False)
                self.settings.remove("username")
                self.settings.remove("password")
            
            self.update_account_ui()
            self.show_notification("登录成功！")
            # 登录后跳转到首页
            self.switch_page(0)
            # 登录后刷新活动和工单
            self.load_activities()
            self.load_tickets()
        else:
            self.show_notification(f"登录失败: {data.get('message')}")

    @debounce(1000)
    def handle_send_code(self):
        email = self.reg_email.text().strip()
        cid = self.reg_cid.text().strip()
        if not email or not cid:
            self.show_notification("请输入邮箱和CID")
            return
        
        # 根据 emailapi.md 修复接口路径为 /codes
        self.code_thread = APIThread(f"{ISFP_API_BASE}/codes", method="POST", json_data={
            "email": email,
            "cid": int(cid)
        })
        self.code_thread.finished.connect(self.on_code_sent)
        self.manage_thread(self.code_thread)

    def on_code_sent(self, data):
        # 根据 emailapi.md 更新状态码判断
        if data.get("code") == "SEND_EMAIL_SUCCESS":
            self.show_notification("验证码已发送，请查收邮件")
        elif data.get("code") == "EMAIL_SEND_INTERVAL":
            self.show_notification("发送频繁，请 60 秒后重试")
        else:
            msg = data.get("message", "发送失败")
            self.show_notification(f"发送失败: {msg}")

    @debounce(1000)
    def handle_register(self):
        payload = {
            "username": self.reg_user.text().strip(),
            "email": self.reg_email.text().strip(),
            "password": self.reg_pass.text().strip(),
            "cid": int(self.reg_cid.text().strip() or 0),
            "email_code": int(self.reg_code.text().strip() or 0)
        }
        self.reg_thread = APIThread(f"{ISFP_API_BASE}/users", method="POST", json_data=payload)
        self.reg_thread.finished.connect(self.on_register_finished)
        self.manage_thread(self.reg_thread)

    def on_register_finished(self, data):
        if data.get("code") == "REGISTER_SUCCESS":
            self.show_notification("注册成功，请登录")
            self.update_account_ui()
        else:
            self.show_notification(f"注册失败: {data.get('message')}")

    def handle_logout(self):
        self.auth_token = None
        self.user_data = None
        self.update_account_ui()
        self.load_activities() # 刷新活动列表（会显示报错）

    def show_history_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("🕐 连线历史")
        dialog.setFixedSize(700, 650)
        dialog.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a1a2e, stop:1 #16213e);
            }
            QFrame {
                border: none;
            }
        """)
        
        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # 标题
        title = QLabel("🕐 连线历史记录")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        title.setStyleSheet("color: white; margin-bottom: 10px;")
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        
        # 统计卡片区域
        stats_widget = QWidget()
        stats_layout = QHBoxLayout(stats_widget)
        stats_layout.setSpacing(15)
        
        # 飞行时长卡片
        self.pilot_stats_card = self._create_stat_card("✈️", "飞行时长", "0h", "#3498db")
        # 管制时长卡片
        self.atc_stats_card = self._create_stat_card("📡", "管制时长", "0h", "#e67e22")
        # 总连线次数卡片
        self.total_stats_card = self._create_stat_card("📊", "总连线次数", "0", "#2ecc71")
        
        stats_layout.addWidget(self.pilot_stats_card)
        stats_layout.addWidget(self.atc_stats_card)
        stats_layout.addWidget(self.total_stats_card)
        main_layout.addWidget(stats_widget)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: rgba(255,255,255,0.1);")
        line.setFixedHeight(1)
        main_layout.addWidget(line)
        
        # Tab 控件
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { 
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 10px;
                background: rgba(0,0,0,0.2);
            }
            QTabBar::tab { 
                background: rgba(255,255,255,0.05);
                color: rgba(255,255,255,0.7);
                padding: 12px 25px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-weight: bold;
            }
            QTabBar::tab:selected { 
                background: rgba(52, 152, 219, 0.3);
                color: white;
                border-bottom: 2px solid #3498db;
            }
            QTabBar::tab:hover:!selected {
                background: rgba(255,255,255,0.1);
            }
        """)
        
        # 创建飞行记录列表
        pilot_scroll = QScrollArea()
        pilot_scroll.setWidgetResizable(True)
        pilot_scroll.setStyleSheet("""
            QScrollArea { 
                border: none; 
                background: transparent; 
            }
            QScrollBar:vertical {
                background: rgba(0, 0, 0, 0.3);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.3);
            }
        """)
        self.pilot_container = QWidget()
        self.pilot_container.setStyleSheet("background: transparent;")
        self.pilot_layout = QVBoxLayout(self.pilot_container)
        self.pilot_layout.setSpacing(10)
        self.pilot_layout.setContentsMargins(15, 15, 15, 15)
        self.pilot_layout.addStretch()
        pilot_scroll.setWidget(self.pilot_container)
        
        # 创建管制记录列表
        atc_scroll = QScrollArea()
        atc_scroll.setWidgetResizable(True)
        atc_scroll.setStyleSheet("""
            QScrollArea { 
                border: none; 
                background: transparent; 
            }
            QScrollBar:vertical {
                background: rgba(0, 0, 0, 0.3);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.3);
            }
        """)
        self.atc_container = QWidget()
        self.atc_container.setStyleSheet("background: transparent;")
        self.atc_layout = QVBoxLayout(self.atc_container)
        self.atc_layout.setSpacing(10)
        self.atc_layout.setContentsMargins(15, 15, 15, 15)
        self.atc_layout.addStretch()
        atc_scroll.setWidget(self.atc_container)
        
        tabs.addTab(pilot_scroll, "✈️ 飞行记录")
        tabs.addTab(atc_scroll, "📡 管制记录")
        main_layout.addWidget(tabs)
        
        # 关闭按钮
        close_btn = QPushButton("✓ 关闭")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(52, 152, 219, 0.8);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 40px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background: #3498db; }
        """)
        close_btn.clicked.connect(dialog.accept)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)
        
        # 加载数据
        self._load_history_data()
        
        dialog.exec()
    
    def _create_stat_card(self, icon, title, value, color):
        """创建统计卡片"""
        card = QFrame()
        card.setFixedHeight(80)
        card.setStyleSheet(f"""
            QFrame {{
                background: rgba(255,255,255,0.05);
                border-radius: 12px;
                border: 1px solid {color}40;
            }}
            QFrame:hover {{
                background: rgba(255,255,255,0.08);
                border: 1px solid {color}80;
            }}
        """)
        
        layout = QHBoxLayout(card)
        layout.setContentsMargins(15, 10, 15, 10)
        
        # 图标
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"font-size: 28px; color: {color};")
        layout.addWidget(icon_lbl)
        
        # 文字信息
        info_layout = QVBoxLayout()
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 12px;")
        value_lbl = QLabel(value)
        value_lbl.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold;")
        # 使用属性来标识这个label，而不是objectName
        value_lbl.setProperty("stat_type", title)
        info_layout.addWidget(title_lbl)
        info_layout.addWidget(value_lbl)
        layout.addLayout(info_layout)
        layout.addStretch()
        
        # 保存value_lbl的引用到card上，方便后续更新
        card.value_label = value_lbl
        
        return card
    
    def _load_history_data(self):
        """加载连线历史数据"""
        self.history_thread = APIThread(
            f"{ISFP_API_BASE}/users/histories/self", 
            headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        
        def on_history_loaded(data):
            if data.get("code") != "GET_USER_HISTORY":
                self.show_notification("获取历史失败")
                return
                
            d = data.get("data", {})
            pilots = d.get("pilots", [])
            controllers = d.get("controllers", [])
            
            # 更新统计卡片
            pilot_hours = round(d.get("total_pilot_time", 0) / 3600, 1)
            atc_hours = round(d.get("total_atc_time", 0) / 3600, 1)
            total_count = len(pilots) + len(controllers)
            
            # 直接通过保存的引用更新统计值
            if hasattr(self.pilot_stats_card, 'value_label'):
                self.pilot_stats_card.value_label.setText(f"{pilot_hours}h")
            if hasattr(self.atc_stats_card, 'value_label'):
                self.atc_stats_card.value_label.setText(f"{atc_hours}h")
            if hasattr(self.total_stats_card, 'value_label'):
                self.total_stats_card.value_label.setText(str(total_count))
            
            # 添加飞行记录
            self._add_history_items(pilots, self.pilot_layout, "✈️", "#3498db")
            # 添加管制记录
            self._add_history_items(controllers, self.atc_layout, "📡", "#e67e22")
            
        self.history_thread.finished.connect(on_history_loaded)
        self.manage_thread(self.history_thread)
    
    def _add_history_items(self, items, layout, icon, color):
        """添加历史记录项"""
        # 清空现有内容（保留stretch）
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not items:
            empty_lbl = QLabel("📭 暂无记录")
            empty_lbl.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 16px; padding: 50px;")
            empty_lbl.setAlignment(Qt.AlignCenter)
            layout.insertWidget(0, empty_lbl)
            return
        
        # 按时间倒序排列
        sorted_items = sorted(items, key=lambda x: x.get("start_time", ""), reverse=True)
        
        for item_data in sorted_items:
            card = self._create_history_card(item_data, icon, color)
            layout.insertWidget(layout.count() - 1, card)
    
    def _create_history_card(self, item_data, icon, color):
        """创建单条历史记录卡片"""
        card = QFrame()
        card.setFixedHeight(90)
        card.setStyleSheet(f"""
            QFrame {{
                background: rgba(255,255,255,0.03);
                border-radius: 10px;
                border-left: 4px solid {color};
            }}
            QFrame:hover {{
                background: rgba(255,255,255,0.06);
            }}
        """)
        
        layout = QHBoxLayout(card)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)
        
        # 图标区域
        icon_widget = QWidget()
        icon_widget.setFixedSize(50, 50)
        icon_widget.setStyleSheet(f"""
            background: {color}30;
            border-radius: 25px;
        """)
        icon_layout = QHBoxLayout(icon_widget)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"font-size: 20px; color: {color};")
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_layout.addWidget(icon_lbl)
        layout.addWidget(icon_widget)
        
        # 信息区域
        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)
        
        callsign = item_data.get("callsign", "Unknown")
        callsign_lbl = QLabel(callsign)
        callsign_lbl.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        info_layout.addWidget(callsign_lbl)
        
        # 时间和时长
        start_time = item_data.get("start_time", "").replace("T", " ").split(".")[0]
        duration_sec = item_data.get("online_time", 0)
        duration_min = round(duration_sec / 60, 1)
        duration_hr = round(duration_sec / 3600, 2)
        
        if duration_hr >= 1:
            duration_text = f"{duration_hr}小时"
        else:
            duration_text = f"{duration_min}分钟"
        
        detail_lbl = QLabel(f"🕐 {start_time}  ·  ⏱️ {duration_text}")
        detail_lbl.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 12px;")
        info_layout.addWidget(detail_lbl)
        
        layout.addLayout(info_layout, stretch=1)
        
        # 右侧状态指示
        status_lbl = QLabel("✓")
        status_lbl.setStyleSheet(f"color: {color}; font-size: 18px; font-weight: bold;")
        layout.addWidget(status_lbl)
        
        return card

    def create_settings_tab(self):
        """创建设置页面"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # 标题
        title = QLabel("⚙ 设置")
        title.setFont(QFont("Microsoft YaHei", 24, QFont.Bold))
        title.setStyleSheet("color: white;")
        layout.addWidget(title)
        
        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { 
                border: none; 
                background: transparent; 
            }
            QScrollBar:vertical {
                background: rgba(0, 0, 0, 0.3);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.3);
            }
        """)
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(20)
        
        # ===== 1. 日志设置 =====
        log_group = QGroupBox("📋 日志设置")
        log_group.setStyleSheet("""
            QGroupBox {
                color: white;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 10px;
                margin-top: 15px;
                padding-top: 15px;
                background: rgba(0, 0, 0, 0.2);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px;
            }
        """)
        log_layout = QVBoxLayout(log_group)
        
        self.log_switch = QCheckBox("启用日志文件记录")
        self.log_switch.setChecked(self.settings.value("log_enabled", True, type=bool))
        self.log_switch.setStyleSheet("""
            QCheckBox {
                color: #bdc3c7;
                font-size: 13px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid rgba(255,255,255,0.3);
                background: rgba(0,0,0,0.3);
            }
            QCheckBox::indicator:checked {
                background: #3498db;
                border: 2px solid #3498db;
                image: none;
            }
        """)
        self.log_switch.stateChanged.connect(self.on_log_switch_changed)
        log_layout.addWidget(self.log_switch)
        
        log_info = QLabel("日志文件位置: logs/main.log")
        log_info.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        log_layout.addWidget(log_info)
        
        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background: rgba(255,255,255,0.1); margin: 10px 0;")
        log_layout.addWidget(separator)
        
        # 连线日志开关
        self.connection_log_switch = QCheckBox("启用连线日志记录 (connect.log)")
        self.connection_log_switch.setChecked(self.settings.value("connection_log_enabled", True, type=bool))
        self.connection_log_switch.setStyleSheet("""
            QCheckBox {
                color: #bdc3c7;
                font-size: 13px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid rgba(255,255,255,0.3);
                background: rgba(0,0,0,0.3);
            }
            QCheckBox::indicator:checked {
                background: #27ae60;
                border: 2px solid #27ae60;
                image: none;
            }
        """)
        self.connection_log_switch.stateChanged.connect(self.on_connection_log_switch_changed)
        log_layout.addWidget(self.connection_log_switch)
        
        connection_log_info = QLabel("记录 FSD 和 XSwiftBus 的详细通信日志")
        connection_log_info.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        log_layout.addWidget(connection_log_info)
        
        # 清空日志按钮
        clear_log_btn = QPushButton("🗑 清空日志")
        clear_log_btn.setStyleSheet("""
            QPushButton {
                background: rgba(192, 57, 43, 0.8);
                color: white;
                padding: 8px 16px;
                border-radius: 6px;
                font-size: 12px;
                border: none;
                margin-top: 10px;
            }
            QPushButton:hover {
                background: #e74c3c;
            }
        """)
        clear_log_btn.clicked.connect(self.on_clear_log)
        log_layout.addWidget(clear_log_btn)
        
        scroll_layout.addWidget(log_group)
        
        # ===== 2. 账号密码设置 =====
        account_group = QGroupBox("👤 账号设置")
        account_group.setStyleSheet("""
            QGroupBox {
                color: white;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 10px;
                margin-top: 15px;
                padding-top: 15px;
                background: rgba(0, 0, 0, 0.2);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px;
            }
            QLabel {
                color: #bdc3c7;
                font-size: 13px;
            }
        """)
        account_layout = QFormLayout(account_group)
        account_layout.setSpacing(15)
        account_layout.setLabelAlignment(Qt.AlignLeft)
        account_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        
        # 当前账号显示
        current_user = self.settings.value("username", "未保存")
        self.current_user_label = QLabel(f"当前保存的账号: {current_user}")
        self.current_user_label.setStyleSheet("color: #bdc3c7; font-size: 13px;")
        account_layout.addRow(self.current_user_label)
        
        # 新用户名
        self.new_username_input = QLineEdit()
        self.new_username_input.setPlaceholderText("输入新用户名")
        self.new_username_input.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 6px;
                color: white;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #3498db;
                background: rgba(255,255,255,0.1);
            }
        """)
        account_layout.addRow("新用户名:", self.new_username_input)
        
        # 新密码
        self.new_password_input = QLineEdit()
        self.new_password_input.setPlaceholderText("输入新密码")
        self.new_password_input.setEchoMode(QLineEdit.Password)
        self.new_password_input.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 6px;
                color: white;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #3498db;
                background: rgba(255,255,255,0.1);
            }
        """)
        account_layout.addRow("新密码:", self.new_password_input)
        
        # 保存按钮
        save_account_btn = QPushButton("💾 保存账号密码")
        save_account_btn.setStyleSheet("""
            QPushButton {
                background: #3498db;
                color: white;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 13px;
                border: none;
            }
            QPushButton:hover {
                background: #2980b9;
            }
        """)
        save_account_btn.clicked.connect(self.on_save_account_settings)
        account_layout.addRow(save_account_btn)
        
        # 提示文字
        account_tip = QLabel("⚠️ 修改后需要重新登录才能生效")
        account_tip.setStyleSheet("color: #e74c3c; font-size: 11px;")
        account_layout.addRow(account_tip)
        
        scroll_layout.addWidget(account_group)
        
        # ===== 3. 背景图设置 =====
        bg_group = QGroupBox("🖼 背景设置")
        bg_group.setStyleSheet("""
            QGroupBox {
                color: white;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 10px;
                margin-top: 15px;
                padding-top: 15px;
                background: rgba(0, 0, 0, 0.2);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px;
            }
        """)
        bg_layout = QVBoxLayout(bg_group)
        
        # 当前背景预览
        self.bg_preview_label = QLabel("当前背景: 默认")
        self.bg_preview_label.setStyleSheet("color: #bdc3c7; font-size: 13px;")
        bg_layout.addWidget(self.bg_preview_label)
        
        # 预览图
        self.bg_preview = QLabel()
        self.bg_preview.setFixedSize(300, 150)
        self.bg_preview.setStyleSheet("""
            QLabel {
                background: rgba(0,0,0,0.3);
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 8px;
            }
        """)
        self.bg_preview.setAlignment(Qt.AlignCenter)
        bg_layout.addWidget(self.bg_preview)
        
        # 更新预览
        self.update_bg_preview()
        
        # 按钮区域
        bg_btn_layout = QHBoxLayout()
        
        select_bg_btn = QPushButton("📁 选择图片")
        select_bg_btn.setStyleSheet("""
            QPushButton {
                background: #27ae60;
                color: white;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 13px;
                border: none;
            }
            QPushButton:hover {
                background: #2ecc71;
            }
        """)
        select_bg_btn.clicked.connect(self.on_select_background)
        bg_btn_layout.addWidget(select_bg_btn)
        
        reset_bg_btn = QPushButton("🔄 恢复默认")
        reset_bg_btn.setStyleSheet("""
            QPushButton {
                background: #7f8c8d;
                color: white;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 13px;
                border: none;
            }
            QPushButton:hover {
                background: #95a5a6;
            }
        """)
        reset_bg_btn.clicked.connect(self.on_reset_background)
        bg_btn_layout.addWidget(reset_bg_btn)
        
        bg_layout.addLayout(bg_btn_layout)
        
        # 提示
        bg_tip = QLabel("支持 JPG、PNG 格式，建议尺寸 1920x1080")
        bg_tip.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        bg_layout.addWidget(bg_tip)
        
        scroll_layout.addWidget(bg_group)
        
        # ===== 4. 灵动岛设置 =====
        island_group = QGroupBox("🏝 灵动岛设置")
        island_group.setStyleSheet("""
            QGroupBox {
                color: white;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 10px;
                margin-top: 15px;
                padding-top: 15px;
                background: rgba(0, 0, 0, 0.2);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px;
            }
        """)
        island_layout = QVBoxLayout(island_group)
        island_layout.setSpacing(10)
        
        # 灵动岛开关
        self.island_switch = QCheckBox("启用灵动岛")
        self.island_switch.setChecked(self.settings.value("dynamic_island_enabled", False, type=bool))
        self.island_switch.setStyleSheet("""
            QCheckBox {
                color: #bdc3c7;
                font-size: 13px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid rgba(255,255,255,0.3);
                background: rgba(0,0,0,0.3);
            }
            QCheckBox::indicator:checked {
                background: #27ae60;
                border: 2px solid #27ae60;
                image: none;
            }
        """)
        self.island_switch.stateChanged.connect(self.on_island_switch_changed)
        island_layout.addWidget(self.island_switch)
        
        # 灵动岛说明
        island_info = QLabel("灵动岛是个好东西~")
        island_info.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        island_layout.addWidget(island_info)
        
        # 编辑位置按钮
        self.edit_island_pos_btn = QPushButton("📍 编辑位置")
        self.edit_island_pos_btn.setStyleSheet("""
            QPushButton {
                background: #3498db;
                color: white;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 13px;
                border: none;
                margin-top: 10px;
            }
            QPushButton:hover {
                background: #2980b9;
            }
            QPushButton:disabled {
                background: #7f8c8d;
            }
        """)
        self.edit_island_pos_btn.clicked.connect(self.on_edit_island_position)
        self.edit_island_pos_btn.setEnabled(self.island_switch.isChecked())
        island_layout.addWidget(self.edit_island_pos_btn)
        
        scroll_layout.addWidget(island_group)
        
        # ===== 5. X-Plane 插件管理 =====
        xplane_group = QGroupBox("✈ X-Plane 插件管理")
        xplane_group.setStyleSheet("""
            QGroupBox {
                color: white;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 10px;
                margin-top: 15px;
                padding-top: 15px;
                background: rgba(0, 0, 0, 0.2);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px;
            }
            QLabel {
                color: #bdc3c7;
                font-size: 13px;
            }
        """)
        xplane_layout = QVBoxLayout(xplane_group)
        xplane_layout.setSpacing(15)
        
        # 当前路径显示
        self.xplane_path_label = QLabel("当前路径: 未设置")
        self.xplane_path_label.setStyleSheet("color: #bdc3c7; font-size: 13px;")
        xplane_layout.addWidget(self.xplane_path_label)
        
        # 检测版本显示
        self.xplane_version_label = QLabel("检测版本: 未知")
        self.xplane_version_label.setStyleSheet("color: #bdc3c7; font-size: 13px;")
        xplane_layout.addWidget(self.xplane_version_label)
        
        # 插件状态显示
        self.plugin_status_label = QLabel("插件状态: 未检测")
        self.plugin_status_label.setStyleSheet("color: #bdc3c7; font-size: 13px;")
        xplane_layout.addWidget(self.plugin_status_label)
        
        # 按钮区域
        xplane_btn_layout = QHBoxLayout()
        
        # 选择路径按钮
        select_path_btn = QPushButton("📁 选择 X-Plane 路径")
        select_path_btn.setStyleSheet("""
            QPushButton {
                background: #3498db;
                color: white;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 13px;
                border: none;
            }
            QPushButton:hover {
                background: #2980b9;
            }
        """)
        select_path_btn.clicked.connect(self.on_select_xplane_path)
        xplane_btn_layout.addWidget(select_path_btn)
        
        # 自动检测按钮
        auto_detect_btn = QPushButton("🔍 自动检测")
        auto_detect_btn.setStyleSheet("""
            QPushButton {
                background: #9b59b6;
                color: white;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 13px;
                border: none;
            }
            QPushButton:hover {
                background: #8e44ad;
            }
        """)
        auto_detect_btn.clicked.connect(self.on_auto_detect_xplane)
        xplane_btn_layout.addWidget(auto_detect_btn)
        
        xplane_layout.addLayout(xplane_btn_layout)
        
        # 安装/卸载按钮区域
        plugin_btn_layout = QHBoxLayout()
        
        # 安装插件按钮
        self.install_plugin_btn = QPushButton("⬇ 安装插件")
        self.install_plugin_btn.setStyleSheet("""
            QPushButton {
                background: #27ae60;
                color: white;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 13px;
                border: none;
            }
            QPushButton:hover {
                background: #2ecc71;
            }
            QPushButton:disabled {
                background: #7f8c8d;
            }
        """)
        self.install_plugin_btn.clicked.connect(self.on_install_plugin)
        plugin_btn_layout.addWidget(self.install_plugin_btn)
        
        # 卸载插件按钮
        self.uninstall_plugin_btn = QPushButton("🗑 卸载插件")
        self.uninstall_plugin_btn.setStyleSheet("""
            QPushButton {
                background: #e74c3c;
                color: white;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 13px;
                border: none;
            }
            QPushButton:hover {
                background: #c0392b;
            }
            QPushButton:disabled {
                background: #7f8c8d;
            }
        """)
        self.uninstall_plugin_btn.clicked.connect(self.on_uninstall_plugin)
        plugin_btn_layout.addWidget(self.uninstall_plugin_btn)
        
        xplane_layout.addLayout(plugin_btn_layout)
        
        # 提示信息
        plugin_tip = QLabel("提示: 选择 X-Plane 安装目录后，可以自动安装或卸载 ISFP Connect 插件")
        plugin_tip.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        plugin_tip.setWordWrap(True)
        xplane_layout.addWidget(plugin_tip)
        
        scroll_layout.addWidget(xplane_group)
        
        # 更新插件 UI 状态
        self._update_plugin_ui_status()
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        return widget

    def on_log_switch_changed(self, state):
        """日志开关状态改变"""
        enabled = bool(state)
        self.settings.setValue("log_enabled", enabled)
        
        # 更新日志级别
        root_logger = logging.getLogger()
        if enabled:
            root_logger.setLevel(logging.DEBUG)
            self.show_notification("日志记录已启用")
        else:
            root_logger.setLevel(logging.CRITICAL + 1)  # 禁用所有日志
            self.show_notification("日志记录已禁用")
    
    def on_connection_log_switch_changed(self, state):
        """连线日志开关状态改变"""
        enabled = bool(state)
        self.settings.setValue("connection_log_enabled", enabled)
        
        # 导入连线日志模块
        try:
            from connection_logger import enable_connection_logging, disable_connection_logging
            if enabled:
                enable_connection_logging()
                self.show_notification("连线日志已启用 (logs/connect.log)")
            else:
                disable_connection_logging()
                self.show_notification("连线日志已禁用")
        except ImportError:
            self.show_notification("连线日志模块未加载")

    def on_save_account_settings(self):
        """保存账号密码设置"""
        new_username = self.new_username_input.text().strip()
        new_password = self.new_password_input.text().strip()
        
        if not new_username and not new_password:
            self.show_notification("请输入新的用户名或密码")
            return
        
        # 保存新设置
        if new_username:
            self.settings.setValue("username", new_username)
        if new_password:
            self.settings.setValue("password", new_password)
        
        # 清除输入框
        self.new_username_input.clear()
        self.new_password_input.clear()
        
        # 更新显示
        current_user = self.settings.value("username", "未保存")
        self.current_user_label.setText(f"当前保存的账号: {current_user}")
    
    def _update_plugin_ui_status(self):
        """更新插件管理 UI 状态"""
        if not hasattr(self, 'plugin_manager') or self.plugin_manager is None:
            self.xplane_path_label.setText("当前路径: 插件管理器未加载")
            self.xplane_version_label.setText("检测版本: 未知")
            self.plugin_status_label.setText("插件状态: 未知")
            self.install_plugin_btn.setEnabled(False)
            self.uninstall_plugin_btn.setEnabled(False)
            return
        
        # 更新路径显示
        path = self.plugin_manager.get_xplane_path()
        if path:
            self.xplane_path_label.setText(f"当前路径: {path}")
            self.xplane_version_label.setText(f"检测版本: X-Plane {self.plugin_manager.get_version()}")
            self.install_plugin_btn.setEnabled(True)
        else:
            self.xplane_path_label.setText("当前路径: 未设置")
            self.xplane_version_label.setText("检测版本: 未知")
            self.install_plugin_btn.setEnabled(False)
        
        # 更新插件状态
        if self.plugin_manager.is_plugin_installed():
            self.plugin_status_label.setText("插件状态: ✅ 已安装")
            self.install_plugin_btn.setText("⬇ 重新安装")
            self.uninstall_plugin_btn.setEnabled(True)
        else:
            self.plugin_status_label.setText("插件状态: ❌ 未安装")
            self.install_plugin_btn.setText("⬇ 安装插件")
            self.uninstall_plugin_btn.setEnabled(False)
    
    def on_select_xplane_path(self):
        """选择 X-Plane 路径按钮点击"""
        if self.plugin_manager:
            path = self.plugin_manager.select_xplane_path(self)
            if path:
                self.show_notification(f"已选择 X-Plane 路径: {path}")
                self._update_plugin_ui_status()
        else:
            self.show_notification("插件管理器未加载")
    
    def on_auto_detect_xplane(self):
        """自动检测 X-Plane 路径按钮点击"""
        if self.plugin_manager:
            path = self.plugin_manager.auto_detect_path()
            if path:
                self.show_notification(f"自动检测到 X-Plane: {path}")
                self._update_plugin_ui_status()
            else:
                self.show_notification("未找到 X-Plane 安装目录，请手动选择")
        else:
            self.show_notification("插件管理器未加载")
    
    def on_install_plugin(self):
        """安装插件按钮点击"""
        if self.plugin_manager:
            success, message = self.plugin_manager.install_plugin(self)
            # 结果显示通过信号处理
        else:
            self.show_notification("插件管理器未加载")
    
    def on_uninstall_plugin(self):
        """卸载插件按钮点击"""
        if self.plugin_manager:
            success, message = self.plugin_manager.uninstall_plugin(self)
            # 结果显示通过信号处理
        else:
            self.show_notification("插件管理器未加载")
        
        # 如果已登录，提示需要重新登录
        if self.auth_token:
            self.show_notification("账号信息已更新，请重新登录")
            # 执行登出
            self.handle_logout()
        else:
            self.show_notification("账号信息已保存")

    def on_select_background(self):
        """选择自定义背景图"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择背景图片",
            "",
            "图片文件 (*.jpg *.jpeg *.png *.bmp)"
        )
        
        if file_path:
            # 复制到 data 文件夹
            import shutil
            data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
            target_path = os.path.join(data_dir, "custom_bg.jpg")
            try:
                shutil.copy(file_path, target_path)
                self.settings.setValue("custom_bg_path", target_path)
                self.update_bg_preview()
                self.apply_background()
                self.show_notification("背景图片已更新")
            except Exception as e:
                self.show_notification(f"设置背景失败: {str(e)}")

    def on_reset_background(self):
        """恢复默认背景"""
        # 删除自定义背景文件
        custom_bg = self.settings.value("custom_bg_path", "")
        if custom_bg and os.path.exists(custom_bg):
            try:
                os.remove(custom_bg)
            except Exception as e:
                logger.warning(f"删除自定义背景文件失败: {e}")
        
        self.settings.remove("custom_bg_path")
        self.update_bg_preview()
        self.apply_background()
        self.show_notification("已恢复默认背景")

    def on_island_switch_changed(self, state):
        """灵动岛开关状态改变"""
        enabled = bool(state)
        self.settings.setValue("dynamic_island_enabled", enabled)
        
        # 更新编辑位置按钮状态
        self.edit_island_pos_btn.setEnabled(enabled)
        
        # 获取或创建灵动岛实例
        try:
            from dynamic_island import get_dynamic_island
            island = get_dynamic_island(self)
            island.set_enabled(enabled)
            
            if enabled:
                self.show_notification("灵动岛已启用")
            else:
                self.show_notification("灵动岛已禁用")
        except ImportError:
            self.show_notification("灵动岛模块未找到")
    
    def on_edit_island_position(self):
        """编辑灵动岛位置"""
        try:
            from dynamic_island import get_dynamic_island, DynamicIslandEditor
            island = get_dynamic_island(self)
            
            # 创建编辑器并开始编辑
            self.island_editor = DynamicIslandEditor(island, self)
            self.island_editor.saved.connect(lambda: self.show_notification("灵动岛位置已保存"))
            self.island_editor.cancelled.connect(lambda: self.show_notification("已取消编辑"))
            self.island_editor.start_editing()
        except ImportError:
            self.show_notification("灵动岛模块未找到")
    
    def on_clear_log(self):
        """清空日志文件"""
        logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
        
        # 清空 main.log
        log_file = os.path.join(logs_dir, 'main.log')
        try:
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [INFO] 日志已清空\n")
            main_log_cleared = True
        except Exception as e:
            main_log_cleared = False
            main_log_error = str(e)
        
        # 清空 connect.log
        connect_log_file = os.path.join(logs_dir, 'connect.log')
        try:
            if os.path.exists(connect_log_file):
                with open(connect_log_file, 'w', encoding='utf-8') as f:
                    f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [INFO] 连线日志已清空\n")
                connect_log_cleared = True
            else:
                connect_log_cleared = True  # 文件不存在也算成功
        except Exception as e:
            connect_log_cleared = False
            connect_log_error = str(e)
        
        # 显示通知
        if main_log_cleared and connect_log_cleared:
            self.show_notification("日志已清空 (main.log 和 connect.log)")
        elif main_log_cleared:
            self.show_notification(f"main.log 已清空，connect.log 清空失败: {connect_log_error}")
        elif connect_log_cleared:
            self.show_notification(f"connect.log 已清空，main.log 清空失败: {main_log_error}")
        else:
            self.show_notification(f"清空日志失败: {main_log_error}")

    def update_bg_preview(self):
        """更新背景预览"""
        custom_bg = self.settings.value("custom_bg_path", "")
        if custom_bg and os.path.exists(custom_bg):
            self.bg_preview_label.setText("当前背景: 自定义")
            pixmap = QPixmap(custom_bg)
            if not pixmap.isNull():
                scaled = pixmap.scaled(300, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.bg_preview.setPixmap(scaled)
        else:
            self.bg_preview_label.setText("当前背景: 默认")
            self.bg_preview.setText("默认背景")

    def apply_background(self):
        """应用背景设置"""
        custom_bg = self.settings.value("custom_bg_path", "")
        if custom_bg and os.path.exists(custom_bg):
            pixmap = QPixmap(custom_bg)
            if not pixmap.isNull():
                self.bg_pixmap = pixmap
                self.bg_label.setPixmap(pixmap.scaled(
                    self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                ))
        else:
            # 恢复默认背景
            default_bg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "background.png")
            if os.path.exists(default_bg):
                pixmap = QPixmap(default_bg)
                if not pixmap.isNull():
                    self.bg_pixmap = pixmap
                    self.bg_label.setPixmap(pixmap.scaled(
                        self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                    ))

    def create_home_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部英雄区 (Hero Section)
        hero_section = QFrame()
        hero_section.setFixedHeight(400)
        hero_section.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 rgba(52, 152, 219, 0.3), 
                        stop:0.5 rgba(0, 0, 0, 0.2),
                        stop:1 transparent);
        """)
        hero_layout = QVBoxLayout(hero_section)
        hero_layout.setAlignment(Qt.AlignCenter)
        hero_layout.setSpacing(10)

        # 悬浮 Logo
        logo = QLabel()
        logo.setPixmap(QPixmap("assets/logo.png").scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setStyleSheet("background: transparent; margin-bottom: 20px;")
        hero_layout.addWidget(logo, alignment=Qt.AlignCenter)

        title = QLabel("ISFP 云际模拟飞行")
        title.setFont(QFont("Microsoft YaHei", 42, QFont.Bold))
        title.setStyleSheet("color: white; background: transparent; letter-spacing: 4px;")
        hero_layout.addWidget(title, alignment=Qt.AlignCenter)

        subtitle = QLabel("INTERSTELLAR SIMULATION FLIGHT PLATFORM")
        subtitle.setFont(QFont("Consolas", 16))
        subtitle.setStyleSheet("color: #3498db; background: transparent; letter-spacing: 2px;")
        hero_layout.addWidget(subtitle, alignment=Qt.AlignCenter)

        layout.addWidget(hero_section)

        # 底部仪表盘区
        stats_container = QWidget()
        stats_layout = QHBoxLayout(stats_container)
        stats_layout.setContentsMargins(100, 20, 100, 50)
        stats_layout.setSpacing(40)

        # 在线机组卡片
        self.pilot_stat_card = self.create_stat_panel("在线机组", "---", "#2ecc71")
        # 在线管制 (替代原网络延迟)
        self.atc_stat_card = self.create_stat_panel("在线管制", "---", "#f1c40f")
        # 在线总人数
        self.total_stat_card = self.create_stat_panel("在线总人数", "---", "#3498db")

        stats_layout.addWidget(self.pilot_stat_card)
        stats_layout.addWidget(self.atc_stat_card)
        stats_layout.addWidget(self.total_stat_card)

        layout.addWidget(stats_container)
        layout.addStretch()

        # 启动首页数据更新
        QTimer.singleShot(500, self.update_home_stats)
        return widget

    def create_stat_panel(self, title, value, color):
        card = QFrame()
        card.setFixedSize(250, 150)
        card.setStyleSheet(f"""
            QFrame {{
                background: rgba(255, 255, 255, 0.05);
                border-radius: 20px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }}
            QFrame:hover {{
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid {color};
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setAlignment(Qt.AlignCenter)
        
        t_lbl = QLabel(title)
        t_lbl.setStyleSheet("color: #888; font-size: 14px; font-weight: bold;")
        layout.addWidget(t_lbl, alignment=Qt.AlignCenter)

        v_lbl = QLabel(value)
        v_lbl.setObjectName("ValueLabel")
        v_lbl.setStyleSheet(f"color: {color}; font-size: 36px; font-weight: bold; font-family: Consolas;")
        layout.addWidget(v_lbl, alignment=Qt.AlignCenter)
        
        return card

    def update_home_stats(self):
        self.stats_thread = APIThread(f"{ISFP_API_BASE}/clients")
        self.stats_thread.finished.connect(self.on_home_stats_ready)
        self.manage_thread(self.stats_thread)

    def on_home_stats_ready(self, data):
        pilots = data.get("pilots", [])
        controllers = data.get("controllers", [])
        total = len(pilots) + len(controllers)
        
        # 更新首页卡片中的数值
        p_val = self.pilot_stat_card.findChild(QLabel, "ValueLabel")
        if p_val:
            p_val.setText(str(len(pilots)))
            
        a_val = self.atc_stat_card.findChild(QLabel, "ValueLabel")
        if a_val:
            a_val.setText(str(len(controllers)))
        
        # 更新在线总人数
        t_val = self.total_stat_card.findChild(QLabel, "ValueLabel")
        if t_val:
            t_val.setText(str(total))

    def create_weather_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        search_layout = QHBoxLayout()
        self.icao_input = QLineEdit()
        self.icao_input.setPlaceholderText("输入机场 ICAO (如: ZBAA)")
        self.icao_input.setStyleSheet("""
            QLineEdit {
                padding: 12px; 
                border-radius: 8px; 
                background: rgba(255,255,255,25); 
                color: white; 
                font-size: 16px;
                border: 1px solid rgba(255,255,255,10);
            }
        """)
        
        search_btn = QPushButton("查询气象报文")
        search_btn.setCursor(Qt.PointingHandCursor)
        search_btn.setStyleSheet("""
            QPushButton {
                padding: 12px 30px; 
                background: #3498db; 
                color: white; 
                border-radius: 8px; 
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover { background: #2980b9; }
        """)
        search_btn.clicked.connect(self.query_weather)
        
        search_layout.addWidget(self.icao_input)
        search_layout.addWidget(search_btn)
        layout.addLayout(search_layout)

        self.weather_display = QTextEdit()
        self.weather_display.setReadOnly(True)
        self.weather_display.setHtml("<div style='color: #888; text-align: center; margin-top: 50px;'>输入机场四字码并点击查询</div>")
        self.weather_display.setStyleSheet("""
            QTextEdit {
                background: rgba(0,0,0,120); 
                border-radius: 12px; 
                color: #ecf0f1; 
                padding: 20px; 
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 15px;
                line-height: 1.5;
                border: 1px solid rgba(255,255,255,10);
            }
        """)
        layout.addWidget(self.weather_display)
        
        return widget

    def create_online_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        refresh_btn = QPushButton("刷新机组动态")
        refresh_btn.setStyleSheet("padding: 10px; background: #27ae60; color: white; border-radius: 8px;")
        refresh_btn.clicked.connect(self.load_online_pilots)
        layout.addWidget(refresh_btn)

        self.online_list = QListWidget()
        self.online_list.setStyleSheet("background: rgba(0,0,0,100); border-radius: 10px; color: white; padding: 5px;")
        
        layout.addWidget(self.online_list)
        
        return widget

    def create_rating_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 顶部栏
        header = QHBoxLayout()
        title = QLabel("🏆 服务器时长排行榜 (Server Rating)")
        title.setStyleSheet("color: #f1c40f; font-size: 20px; font-weight: bold;")
        
        refresh_btn = QPushButton("刷新数据")
        refresh_btn.clicked.connect(self.load_ratings)
        refresh_btn.setStyleSheet("background: rgba(241, 196, 15, 0.2); color: #f1c40f; border: 1px solid #f1c40f; border-radius: 5px; padding: 5px 15px;")
        
        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh_btn)
        layout.addLayout(header)
        
        # 内容区 - 双列布局
        content_layout = QHBoxLayout()
        content_layout.setSpacing(20)
        
        # 飞行员排行
        pilot_group = QFrame()
        pilot_group.setStyleSheet("background: rgba(0,0,0,100); border-radius: 10px; padding: 10px;")
        pilot_layout = QVBoxLayout(pilot_group)
        
        p_title = QLabel("✈️ 飞行员时长排行 (Top Pilots)")
        p_title.setStyleSheet("color: #3498db; font-weight: bold; font-size: 16px; margin-bottom: 10px;")
        pilot_layout.addWidget(p_title)
        
        self.pilot_rating_list = QListWidget()
        self.pilot_rating_list.setStyleSheet("background: transparent; border: none;")
        pilot_layout.addWidget(self.pilot_rating_list)
        
        # 管制员排行
        atc_group = QFrame()
        atc_group.setStyleSheet("background: rgba(0,0,0,100); border-radius: 10px; padding: 10px;")
        atc_layout = QVBoxLayout(atc_group)
        
        a_title = QLabel("📡 管制员时长排行 (Top ATC)")
        a_title.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 16px; margin-bottom: 10px;")
        atc_layout.addWidget(a_title)
        
        self.atc_rating_list = QListWidget()
        self.atc_rating_list.setStyleSheet("background: transparent; border: none;")
        atc_layout.addWidget(self.atc_rating_list)
        
        content_layout.addWidget(pilot_group)
        content_layout.addWidget(atc_group)
        layout.addLayout(content_layout)
        
        return widget

    def load_ratings(self):
        if not self.auth_token:
            self.show_notification("请先登录后查看排行榜")
            return
            
        self.rating_thread = APIThread(
            f"{ISFP_API_BASE}/server/rating",
            headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        self.rating_thread.finished.connect(self.display_ratings)
        self.manage_thread(self.rating_thread)

    def display_ratings(self, data):
        if data.get("code") != "GET_TIME_RATING":
            self.show_notification(f"获取排行失败: {data.get('message')}")
            return
            
        pilots = data.get("data", {}).get("pilots", [])
        controllers = data.get("data", {}).get("controllers", [])
        
        # 辅助函数：格式化时间
        def format_time(seconds):
            h = seconds // 3600
            m = (seconds % 3600) // 60
            return f"{h}h {m}m"
            
        # 填充列表
        self.pilot_rating_list.clear()
        for i, p in enumerate(pilots):
            rank = i + 1
            color = "#f1c40f" if rank == 1 else "#bdc3c7" if rank == 2 else "#e67e22" if rank == 3 else "white"
            icon = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"{rank}."
            
            item = QListWidgetItem(f"{icon} CID: {p['cid']} - {format_time(p['time'])}")
            item.setForeground(QColor(color))
            item.setFont(QFont("Consolas", 14 if rank <= 3 else 12))
            self.pilot_rating_list.addItem(item)
            
        self.atc_rating_list.clear()
        for i, c in enumerate(controllers):
            rank = i + 1
            color = "#f1c40f" if rank == 1 else "#bdc3c7" if rank == 2 else "#e67e22" if rank == 3 else "white"
            icon = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"{rank}."
            
            item = QListWidgetItem(f"{icon} CID: {c['cid']} - {format_time(c['time'])}")
            item.setForeground(QColor(color))
            item.setFont(QFont("Consolas", 14 if rank <= 3 else 12))
            self.atc_rating_list.addItem(item)

    def create_flight_plan_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # 标题栏
        header = QHBoxLayout()
        title = QLabel("📝 提交飞行计划 (File Flight Plan)")
        title.setStyleSheet("color: white; font-size: 24px; font-weight: bold;")
        
        # 操作按钮
        btn_box = QHBoxLayout()
        self.submit_plan_btn = QPushButton("提交计划 (Submit)")
        self.submit_plan_btn.setStyleSheet("""
            QPushButton { background: #27ae60; color: white; padding: 10px 20px; border-radius: 5px; font-weight: bold; }
            QPushButton:hover { background: #2ecc71; }
        """)
        self.submit_plan_btn.clicked.connect(self.submit_server_flight_plan)
        
        self.delete_plan_btn = QPushButton("删除计划 (Delete)")
        self.delete_plan_btn.setStyleSheet("""
            QPushButton { background: #c0392b; color: white; padding: 10px 20px; border-radius: 5px; font-weight: bold; }
            QPushButton:hover { background: #e74c3c; }
        """)
        self.delete_plan_btn.clicked.connect(self.delete_server_flight_plan)
        self.delete_plan_btn.hide() # 默认隐藏，有计划时显示
        
        refresh_plan_btn = QPushButton("刷新 (Refresh)")
        refresh_plan_btn.setStyleSheet("""
            QPushButton { background: #3498db; color: white; padding: 10px 20px; border-radius: 5px; font-weight: bold; }
            QPushButton:hover { background: #2980b9; }
        """)
        refresh_plan_btn.clicked.connect(self.load_server_flight_plan)

        btn_box.addWidget(self.submit_plan_btn)
        btn_box.addWidget(self.delete_plan_btn)
        btn_box.addWidget(refresh_plan_btn)
        
        header.addWidget(title)
        header.addStretch()
        header.addLayout(btn_box)
        layout.addLayout(header)

        # 滚动区域容器
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(15)
        
        # 表单容器
        form_group = QGroupBox("飞行计划详情")
        form_group.setStyleSheet("""
            QGroupBox { 
                color: #f39c12; font-weight: bold; font-size: 16px;
                border: 2px solid #f39c12; border-radius: 8px; margin-top: 15px; 
                background: rgba(0, 0, 0, 0.3);
            }
            QGroupBox::title { subcontrol-origin: margin; left: 15px; padding: 0 5px; }
            QLineEdit, QComboBox, QTimeEdit, QSpinBox, QTextEdit {
                padding: 8px; border-radius: 5px; border: 1px solid #555; background: #2c3e50; color: white; font-size: 14px;
            }
            QLabel { color: #bdc3c7; font-weight: bold; }
        """)
        form_layout = QGridLayout(form_group)
        form_layout.setContentsMargins(20, 30, 20, 20)
        form_layout.setSpacing(15)

        self.plan_fields = {}

        # 1. 基础信息
        
        self.plan_fields['callsign'] = QLineEdit()
        self.plan_fields['callsign'].setPlaceholderText("CCA123")
        
        self.plan_fields['flight_rules'] = QComboBox()
        self.plan_fields['flight_rules'].addItems(["I - IFR", "V - VFR"])
        
        self.plan_fields['aircraft'] = QLineEdit()
        self.plan_fields['aircraft'].setPlaceholderText("B738")
        
        self.plan_fields['wake_turbulence'] = QComboBox()
        self.plan_fields['wake_turbulence'].addItems(["L - Light", "M - Medium", "H - Heavy", "J - Super"])
        self.plan_fields['wake_turbulence'].setCurrentIndex(1) # Default M
        
        # Row 0
        form_layout.addWidget(QLabel("航班号:"), 0, 0)
        form_layout.addWidget(self.plan_fields['callsign'], 0, 1)
        form_layout.addWidget(QLabel("飞行规则:"), 0, 2)
        form_layout.addWidget(self.plan_fields['flight_rules'], 0, 3)
        form_layout.addWidget(QLabel("航空器型别:"), 0, 4)
        form_layout.addWidget(self.plan_fields['aircraft'], 0, 5)
        form_layout.addWidget(QLabel("尾流等级:"), 0, 6)
        form_layout.addWidget(self.plan_fields['wake_turbulence'], 0, 7)
        
        # 2. 设备与代码
        
        self.plan_fields['equipment'] = QLineEdit()
        self.plan_fields['equipment'].setPlaceholderText("SDE1E2E3FGHIJ1RWXY/LB1")
        
        # Row 1
        form_layout.addWidget(QLabel("机载设备:"), 1, 0)
        form_layout.addWidget(self.plan_fields['equipment'], 1, 1, 1, 5) # 跨5列
        
        # 3. 巡航信息
        
        self.plan_fields['dep'] = QLineEdit()
        self.plan_fields['dep'].setPlaceholderText("ZBAA")
        self.plan_fields['dep'].setMaxLength(4)
        
        self.plan_fields['dep_time'] = QTimeEdit()
        self.plan_fields['dep_time'].setDisplayFormat("HHmm")
        self.plan_fields['dep_time'].setButtonSymbols(QAbstractSpinBox.NoButtons)
        
        self.plan_fields['altitude'] = QLineEdit()
        self.plan_fields['altitude'].setPlaceholderText("32100")

        self.plan_fields['cruise_tas'] = QSpinBox()
        self.plan_fields['cruise_tas'].setRange(0, 9999)
        self.plan_fields['cruise_tas'].setValue(0)
        self.plan_fields['cruise_tas'].setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.plan_fields['cruise_tas'].setSuffix(" kt")

        # Row 2
        form_layout.addWidget(QLabel("起飞机场:"), 2, 0)
        form_layout.addWidget(self.plan_fields['dep'], 2, 1)
        form_layout.addWidget(QLabel("预计起飞时间:"), 2, 2)
        form_layout.addWidget(self.plan_fields['dep_time'], 2, 3)
        form_layout.addWidget(QLabel("巡航高度:"), 2, 4)
        form_layout.addWidget(self.plan_fields['altitude'], 2, 5)
        form_layout.addWidget(QLabel("巡航真空速:"), 2, 6)
        form_layout.addWidget(self.plan_fields['cruise_tas'], 2, 7)
        
        # 4. 落地与备降
        
        self.plan_fields['arr'] = QLineEdit()
        self.plan_fields['arr'].setPlaceholderText("ZSSS")
        self.plan_fields['arr'].setMaxLength(4)
        
        self.plan_fields['alt'] = QLineEdit()
        self.plan_fields['alt'].setPlaceholderText("ZSPD")

        self.plan_fields['eet_h'] = QSpinBox()
        self.plan_fields['eet_h'].setRange(0, 99)
        self.plan_fields['eet_h'].setValue(0)
        self.plan_fields['eet_h'].setSuffix(" h")
        self.plan_fields['eet_h'].setButtonSymbols(QAbstractSpinBox.NoButtons)
        
        self.plan_fields['eet_m'] = QSpinBox()
        self.plan_fields['eet_m'].setRange(0, 59)
        self.plan_fields['eet_m'].setValue(0)
        self.plan_fields['eet_m'].setSuffix(" m")
        self.plan_fields['eet_m'].setButtonSymbols(QAbstractSpinBox.NoButtons)
        
        # Row 3
        form_layout.addWidget(QLabel("落地机场:"), 3, 0)
        form_layout.addWidget(self.plan_fields['arr'], 3, 1)
        form_layout.addWidget(QLabel("备降机场:"), 3, 2)
        form_layout.addWidget(self.plan_fields['alt'], 3, 3)
        form_layout.addWidget(QLabel("飞行时间:"), 3, 4)
        
        hbox_eet = QHBoxLayout()
        hbox_eet.addWidget(self.plan_fields['eet_h'])
        hbox_eet.addWidget(self.plan_fields['eet_m'])
        form_layout.addLayout(hbox_eet, 3, 5)
        
        # 5. 燃油与其他
        
        self.plan_fields['fuel_h'] = QSpinBox()
        self.plan_fields['fuel_h'].setRange(0, 99)
        self.plan_fields['fuel_h'].setValue(0)
        self.plan_fields['fuel_h'].setSuffix(" h")
        self.plan_fields['fuel_h'].setButtonSymbols(QAbstractSpinBox.NoButtons)
        
        self.plan_fields['fuel_m'] = QSpinBox()
        self.plan_fields['fuel_m'].setRange(0, 59)
        self.plan_fields['fuel_m'].setValue(0)
        self.plan_fields['fuel_m'].setSuffix(" m")
        self.plan_fields['fuel_m'].setButtonSymbols(QAbstractSpinBox.NoButtons)
        
        # Row 3 continued (Sharing row or new row? Let's use new row for fuel)
        # Row 4
        form_layout.addWidget(QLabel("滞空时间:"), 3, 6)
        hbox_fuel = QHBoxLayout()
        hbox_fuel.addWidget(self.plan_fields['fuel_h'])
        hbox_fuel.addWidget(self.plan_fields['fuel_m'])
        form_layout.addLayout(hbox_fuel, 3, 7)

        # 6. 航路
        self.plan_fields['route'] = QTextEdit()
        self.plan_fields['route'].setMaximumHeight(100)
        
        # Row 5
        form_layout.addWidget(QLabel("飞行航路:"), 4, 0)
        form_layout.addWidget(self.plan_fields['route'], 4, 1, 1, 7)

        # 7. 备注
        self.plan_fields['remarks'] = QLineEdit()
        self.plan_fields['remarks'].setPlaceholderText("PBN/A1B1C1D1L1O1S1 DOF/240101...")
        
        # Row 6
        form_layout.addWidget(QLabel("备注 (RMK):"), 5, 0)
        form_layout.addWidget(self.plan_fields['remarks'], 5, 1, 1, 7)


        content_layout.addWidget(form_group)
        content_layout.addStretch()
        
        scroll.setWidget(content_widget)
        layout.addWidget(scroll)
        
        # 初始加载
        QTimer.singleShot(1000, self.load_server_flight_plan)
        
        return widget

    def load_server_flight_plan(self):
        if not self.auth_token:
            self.show_notification("请先登录")
            return

        self.get_plan_thread = APIThread(
            f"{ISFP_API_BASE}/plans/self",
            headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        self.get_plan_thread.finished.connect(self.on_plan_loaded)
        self.manage_thread(self.get_plan_thread)

    def on_plan_loaded(self, data):
        # 成功获取：GET_FLIGHT_PLAN，无计划：可能是 404 或者 data 为 null
        # 根据 API 文档，如果没有计划，可能返回 null 或者特定的 code，这里需做兼容
        if data.get("code") == "GET_FLIGHT_PLAN" and data.get("data"):
            plan = data["data"]
            self.plan_fields['callsign'].setText(plan.get('callsign', ''))
            
            # 规则处理 (I, V)
            rules = ["I", "V"]
            rule_char = plan.get('flight_rules', 'I')
            for i, r in enumerate(rules):
                if rule_char == r:
                    self.plan_fields['flight_rules'].setCurrentIndex(i)
                    break
            
            self.plan_fields['aircraft'].setText(plan.get('aircraft', ''))
            self.plan_fields['cruise_tas'].setValue(int(plan.get('cruise_tas', 450)))
            self.plan_fields['dep'].setText(plan.get('departure', ''))
            
            # 尝试从备注或机型中解析 尾流、设备、应答机
            # 假设存储格式为 remarks: "... /WAKE/M /EQPT/SDE... /XPDR/1000"
            raw_remarks = plan.get('remarks', '')
            
            # 解析 WAKE
            wake_map = {"L": 0, "M": 1, "H": 2, "J": 3}
            import re
            wake_match = re.search(r'/WAKE/([LMHJ])', raw_remarks)
            if wake_match:
                w = wake_match.group(1)
                if w in wake_map:
                    self.plan_fields['wake_turbulence'].setCurrentIndex(wake_map[w])
                raw_remarks = raw_remarks.replace(wake_match.group(0), "").strip()
            
            # 解析 EQPT
            eqpt_match = re.search(r'/EQPT/([^ ]+)', raw_remarks)
            if eqpt_match:
                self.plan_fields['equipment'].setText(eqpt_match.group(1))
                raw_remarks = raw_remarks.replace(eqpt_match.group(0), "").strip()
            else:
                self.plan_fields['equipment'].clear()
                
            # 清理后的 remarks 回显
            self.plan_fields['remarks'].setText(raw_remarks)
            
            # 时间格式 HHMM -> QTime
            dep_time_int = plan.get('departure_time', 0)
            h = dep_time_int // 100
            m = dep_time_int % 100
            from PySide6.QtCore import QTime
            self.plan_fields['dep_time'].setTime(QTime(h, m))
            
            self.plan_fields['altitude'].setText(plan.get('altitude', ''))
            self.plan_fields['arr'].setText(plan.get('arrival', ''))
            
            self.plan_fields['eet_h'].setValue(int(plan.get('route_time_hour', 0)))
            self.plan_fields['eet_m'].setValue(int(plan.get('route_time_minute', 0)))
            
            self.plan_fields['fuel_h'].setValue(int(plan.get('fuel_time_hour', 0)))
            self.plan_fields['fuel_m'].setValue(int(plan.get('fuel_time_minute', 0)))
            
            self.plan_fields['alt'].setText(plan.get('alternate', ''))
            self.plan_fields['remarks'].setText(plan.get('remarks', ''))
            self.plan_fields['route'].setPlainText(plan.get('route', ''))
            
            # 显示删除按钮，并将提交按钮改为"更新"
            self.delete_plan_btn.show()
            self.submit_plan_btn.setText("更新计划 (Update)")
            self.show_notification("已加载现有飞行计划")
        else:
            # 没有计划或获取失败
            self.delete_plan_btn.hide()
            self.submit_plan_btn.setText("提交计划 (Submit)")
            # self.show_notification("暂无飞行计划，请填写提交")

    def submit_server_flight_plan(self):
        if not self.auth_token:
            self.show_notification("请先登录")
            return
            
        # 收集数据
        try:
            # 确保 CID 存在
            cid = self.user_data.get('user', {}).get('cid')
            if not cid:
                self.show_notification("无法获取 CID，请重新登录")
                return

            dep_time_str = self.plan_fields['dep_time'].text() # HHmm
            dep_time_int = int(dep_time_str)
            
            # 构建备注 (包含 Wake, Equipment, Transponder)
            remarks_base = self.plan_fields['remarks'].text().strip().upper()
            wake = self.plan_fields['wake_turbulence'].currentText()[0] # L, M, H, J
            eqpt = self.plan_fields['equipment'].text().strip().upper()
            
            # 将这些额外字段追加到 remarks 中以便持久化
            final_remarks = f"{remarks_base} /WAKE/{wake}"
            if eqpt:
                final_remarks += f" /EQPT/{eqpt}"
            
            payload = {
                "cid": int(cid),
                "callsign": self.plan_fields['callsign'].text().strip().upper(),
                "flight_rules": self.plan_fields['flight_rules'].currentText()[0], # 取首字母
                "aircraft": self.plan_fields['aircraft'].text().strip().upper(),
                "cruise_tas": self.plan_fields['cruise_tas'].value(),
                "departure": self.plan_fields['dep'].text().strip().upper(),
                "departure_time": dep_time_int,
                "altitude": self.plan_fields['altitude'].text().strip().upper(),
                "arrival": self.plan_fields['arr'].text().strip().upper(),
                "route_time_hour": str(self.plan_fields['eet_h'].value()),
                "route_time_minute": str(self.plan_fields['eet_m'].value()),
                "fuel_time_hour": str(self.plan_fields['fuel_h'].value()),
                "fuel_time_minute": str(self.plan_fields['fuel_m'].value()),
                "alternate": self.plan_fields['alt'].text().strip().upper(),
                "remarks": final_remarks,
                "route": self.plan_fields['route'].toPlainText().strip().upper(),
                "locked": False
            }
            
            # 完整校验 - 除备降机场外所有字段必填
            required_fields = {
                'callsign': '呼号',
                'flight_rules': '飞行规则',
                'aircraft': '机型',
                'cruise_tas': '巡航速度',
                'departure': '起飞机场',
                'departure_time': '起飞时间',
                'altitude': '巡航高度',
                'arrival': '目的地机场',
                'route_time_hour': '飞行时间(小时)',
                'route_time_minute': '飞行时间(分钟)',
                'fuel_time_hour': '滞空时间(小时)',
                'fuel_time_minute': '滞空时间(分钟)',
                'route': '航路'
            }
            
            missing_fields = []
            for field, name in required_fields.items():
                value = payload.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    missing_fields.append(name)
            
            if missing_fields:
                self.show_notification(f"请填写以下必填项: {', '.join(missing_fields)}")
                return

            self.submit_plan_thread = APIThread(
                f"{ISFP_API_BASE}/plans",
                method="POST",
                json_data=payload,
                headers={"Authorization": f"Bearer {self.auth_token}"}
            )
            def on_submit_finished(d):
                self.show_notification(d.get('message', '操作完成'))
                if d.get('code') == 'SUBMIT_FLIGHT_PLAN':
                    self.load_server_flight_plan()
            
            self.submit_plan_thread.finished.connect(on_submit_finished)
            self.manage_thread(self.submit_plan_thread)
            
        except Exception as e:
            self.show_notification(f"数据错误: {str(e)}")

    def delete_server_flight_plan(self):
        if not self.auth_token: return
        
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(self, "确认删除", "确定要删除当前的飞行计划吗？",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        self.del_plan_thread = APIThread(
            f"{ISFP_API_BASE}/plans/self",
            method="DELETE",
            headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        def on_delete_finished(d):
            self.show_notification(d.get('message', '操作完成'))
            if d.get('code') == 'DELETE_SELF_FLIGHT_PLAN':
                self.load_server_flight_plan()
        
        self.del_plan_thread.finished.connect(on_delete_finished)
        self.manage_thread(self.del_plan_thread)

    def load_empty_map(self):
        # 保留此方法防止报错，但不再使用
        pass

    def update_map(self):
        # 保留此方法防止报错，但不再使用
        pass

    def create_styled_input(self, label, placeholder, key, default="", blur_event=None):
        # 保留此方法防止报错，但不再使用
        return QWidget()

    def show_notification(self, message):
        # 全局状态反馈
        if hasattr(self, 'status_label'):
            self.status_label.setText(str(message))
            QTimer.singleShot(5000, lambda: self.status_label.setText(""))
        
        # 兼容旧的按钮反馈（如果存在）
        if hasattr(self, 'save_btn') and self.save_btn:
            try:
                self.save_btn.setText(str(message))
                QTimer.singleShot(3000, lambda: self.save_btn.setText("生成飞行计划 (GENERATE FLIGHT PLAN)"))
            except: pass

    # ================= 工单系统 =================
    def create_ticket_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 顶部栏：标题 + 创建按钮
        header_layout = QHBoxLayout()
        title = QLabel("工单系统 (Support Tickets)")
        title.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        
        create_btn = QPushButton("+ 创建工单")
        create_btn.setCursor(Qt.PointingHandCursor)
        create_btn.setStyleSheet("""
            QPushButton {
                background: #27ae60; color: white; font-weight: bold;
                border-radius: 5px; padding: 8px 15px;
            }
            QPushButton:hover { background: #2ecc71; }
        """)
        create_btn.clicked.connect(self.show_create_ticket_dialog)
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(create_btn)
        layout.addLayout(header_layout)
        
        # 工单列表
        self.ticket_list = QListWidget()
        self.ticket_list.setStyleSheet("""
            QListWidget {
                background: transparent; border: none; outline: none;
            }
            QListWidget::item {
                background: rgba(255,255,255,0.05);
                border-radius: 10px;
                margin-bottom: 10px;
                padding: 10px;
                border: 1px solid rgba(255,255,255,0.1);
            }
            QListWidget::item:hover {
                background: rgba(255,255,255,0.1);
                border: 1px solid #3498db;
            }
        """)
        layout.addWidget(self.ticket_list)
        
        # 刷新加载
        refresh_btn = QPushButton("刷新列表")
        refresh_btn.clicked.connect(self.load_tickets)
        refresh_btn.setStyleSheet("""
            QPushButton { background: rgba(52, 152, 219, 0.2); color: #3498db; border: 1px solid #3498db; border-radius: 5px; padding: 8px; }
            QPushButton:hover { background: #3498db; color: white; }
        """)
        layout.addWidget(refresh_btn, alignment=Qt.AlignCenter)
        
        # 初始加载
        QTimer.singleShot(1000, self.load_tickets)
        
        return widget

    def load_tickets(self):
        if not self.auth_token:
            self.ticket_list.clear()
            item = QListWidgetItem("🔒 请先登录后查看工单")
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#f1c40f"))
            self.ticket_list.addItem(item)
            return

        self.ticket_list.clear()
        
        # 修复：防止线程被垃圾回收导致崩溃
        if hasattr(self, 'ticket_thread') and self.ticket_thread.isRunning():
            self.ticket_thread.terminate()
            self.ticket_thread.wait()
            
        # 调用 /tickets/self 接口
        self.ticket_thread = APIThread(
            f"{ISFP_API_BASE}/tickets/self",
            params={"page_number": 1, "page_size": 50},
            headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        self.ticket_thread.finished.connect(self.display_tickets)
        self.manage_thread(self.ticket_thread)

    def display_tickets(self, data):
        items = data.get("data", {}).get("items", [])
        if not items:
            item = QListWidgetItem("暂无工单记录")
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#888"))
            self.ticket_list.addItem(item)
            return

        type_map = {0: "建议 (Feature)", 1: "Bug", 2: "投诉 (Complain)", 3: "表扬 (Recognition)", 4: "其他 (Other)"}
        type_colors = {0: "#3498db", 1: "#e74c3c", 2: "#e67e22", 3: "#2ecc71", 4: "#95a5a6"}

        for t in items:
            t_type = t.get("type", 4)
            title_text = f"[{type_map.get(t_type, '未知')}] {t.get('title', '无标题')}"
            
            # 状态逻辑修正：
            # 1. 如果有 closer (结单人ID)，则为“已关闭”
            # 2. 如果没有 closer 但有 reply (回复内容)，则为“已回复”
            # 3. 否则为“处理中”
            reply = t.get("reply")
            closer = t.get("closer")
            
            if closer:
                status_text = "🔒 已关闭"
                status_color = "#95a5a6" # 灰色
            elif reply:
                status_text = "✅ 已回复"
                status_color = "#2ecc71" # 绿色
            else:
                status_text = "⏳ 处理中"
                status_color = "#f39c12" # 黄色
            
            # 自定义 Item Widget
            item_widget = QWidget()
            v_layout = QVBoxLayout(item_widget)
            v_layout.setContentsMargins(5, 5, 5, 5)
            
            # 标题行
            top_row = QHBoxLayout()
            type_lbl = QLabel(type_map.get(t_type, "其他"))
            type_lbl.setStyleSheet(f"color: white; background: {type_colors.get(t_type, '#999')}; padding: 2px 8px; border-radius: 4px; font-size: 12px;")
            title_lbl = QLabel(t.get("title", ""))
            title_lbl.setStyleSheet("color: white; font-weight: bold; font-size: 15px; margin-left: 5px;")
            
            status_lbl = QLabel(status_text)
            status_lbl.setStyleSheet(f"color: {status_color}; font-weight: bold;")
            
            top_row.addWidget(type_lbl)
            top_row.addWidget(title_lbl)
            top_row.addStretch()
            top_row.addWidget(status_lbl)
            
            # 内容行
            content_lbl = QLabel(t.get("content", ""))
            content_lbl.setStyleSheet("color: #ccc; margin-top: 5px;")
            content_lbl.setWordWrap(True)
            
            # 回复行
            reply = t.get("reply")
            if reply:
                reply_lbl = QLabel(f"👨‍💼 管理员回复: {reply}")
                reply_lbl.setStyleSheet("color: #3498db; background: rgba(52, 152, 219, 0.1); padding: 8px; border-radius: 5px; margin-top: 8px;")
                reply_lbl.setWordWrap(True)
            else:
                reply_lbl = None

            v_layout.addLayout(top_row)
            v_layout.addWidget(content_lbl)
            if reply_lbl: v_layout.addWidget(reply_lbl)
            
            # 计算高度
            height = 80 + (40 if reply else 0) + (len(t.get("content","")) // 50 * 20)
            
            list_item = QListWidgetItem(self.ticket_list)
            list_item.setSizeHint(QSize(0, height))
            self.ticket_list.setItemWidget(list_item, item_widget)

    def show_create_ticket_dialog(self):
        if not self.auth_token:
            self.show_notification("请先登录")
            return
            
        dialog = QDialog(self)
        dialog.setWindowTitle("创建新工单")
        dialog.setFixedSize(500, 400)
        dialog.setStyleSheet("background: #2c3e50; color: white;")
        
        layout = QVBoxLayout(dialog)
        
        # 类型选择
        layout.addWidget(QLabel("工单类型:"))
        from PySide6.QtWidgets import QComboBox
        type_combo = QComboBox()
        type_combo.addItems(["建议 (Feature)", "Bug 反馈", "投诉 (Complain)", "表扬 (Recognition)", "其他 (Other)"])
        type_combo.setStyleSheet("padding: 8px; border-radius: 5px; background: #34495e; color: white;")
        layout.addWidget(type_combo)
        
        # 标题
        layout.addWidget(QLabel("标题:"))
        title_edit = QLineEdit()
        title_edit.setPlaceholderText("简短描述问题...")
        title_edit.setStyleSheet("padding: 8px; border-radius: 5px; background: #34495e; color: white;")
        layout.addWidget(title_edit)
        
        # 内容
        layout.addWidget(QLabel("详细内容:"))
        content_edit = QTextEdit()
        content_edit.setPlaceholderText("请详细描述您遇到的问题或建议...")
        content_edit.setStyleSheet("padding: 8px; border-radius: 5px; background: #34495e; color: white;")
        layout.addWidget(content_edit)
        
        # 提交按钮
        submit_btn = QPushButton("提交工单")
        submit_btn.setStyleSheet("padding: 10px; background: #27ae60; color: white; border-radius: 5px; font-weight: bold; margin-top: 10px;")
        
        def submit():
            t_type = type_combo.currentIndex()
            title = title_edit.text().strip()
            content = content_edit.toPlainText().strip()
            
            if not title or not content:
                self.show_notification("请填写完整信息")
                return
            
            self.create_ticket_thread = APIThread(
                f"{ISFP_API_BASE}/tickets",
                method="POST",
                json_data={"type": t_type, "title": title, "content": content},
                headers={"Authorization": f"Bearer {self.auth_token}"}
            )
            self.create_ticket_thread.finished.connect(lambda d: [self.show_notification("工单创建成功"), dialog.accept(), self.load_tickets()])
            self.manage_thread(self.create_ticket_thread)
            
        submit_btn.clicked.connect(submit)
        layout.addWidget(submit_btn)
        
        dialog.exec()

    # ================= 功能逻辑 =================

    def query_weather(self):
        icao = self.icao_input.text().strip().upper()
        if not icao: return
        self.weather_display.setText("正在查询...")
        
        # 嵌套调用示例（实际应使用多个线程或链式调用）
        self.metar_thread = APIThread(f"{ISFP_API_BASE}/metar", {"icao": icao})
        self.metar_thread.finished.connect(lambda data: self.handle_metar(data, icao))
        self.manage_thread(self.metar_thread)

    def handle_metar(self, data, icao):
        # 核心修复：处理 API 返回的数组或字符串，并移除多余的引号和括号
        metar_raw = data.get("data", "未找到 METAR")
        
        # 优化显示：如果是多个机场的查询结果，分行显示
        if isinstance(metar_raw, list):
            # 将列表中的每个 METAR 清理后用换行符连接，不空行
            metar = "<br>".join([m.strip('[]"\'') for m in metar_raw])
        else:
            metar = str(metar_raw).strip('[]"\'')
            
        self.taf_thread = APIThread(TAF_API_URL, {"ids": icao.lower()}, is_json=False)
        self.taf_thread.finished.connect(lambda res: self.update_weather_ui(metar, res.get('raw_text', '未找到 TAF'), icao))
        self.manage_thread(self.taf_thread)

    def update_weather_ui(self, metar, taf, icao):
        # 清理 TAF 报文末尾的换行符，防止多显示一行背景
        taf_cleaned = taf.strip().replace(chr(10), "<br>")
        html = f"""
        <div style='font-family: "Segoe UI", Tahoma, sans-serif;'>
            <h2 style='color: #3498db; margin-bottom: 5px;'>{icao} 气象信息</h2>
            <hr style='border: 0; border-top: 1px solid rgba(255,255,255,0.1);'>
            
            <div style='margin-top: 15px;'>
                <b style='color: #2ecc71; font-size: 16px;'>METAR</b>
                <div style='background: rgba(46, 204, 113, 0.1); border-left: 4px solid #2ecc71; padding: 10px; margin-top: 5px; font-family: "Consolas";'>
                    {metar}
                </div>
            </div>

            <div style='margin-top: 25px;'>
                <b style='color: #e67e22; font-size: 16px;'>TAF</b>
                <div style='background: rgba(230, 126, 34, 0.1); border-left: 4px solid #e67e22; padding: 10px; margin-top: 5px; font-family: "Consolas";'>
                    {taf_cleaned}
                </div>
            </div>
            
            <p style='color: #7f8c8d; font-size: 11px; margin-top: 30px; text-align: right;'>
                数据来源: ISFP云际模拟飞行连飞平台
            </p>
        </div>
        """
        self.weather_display.setHtml(html)

    def load_online_pilots(self):
        self.online_list.clear()
        self.online_thread = APIThread(f"{ISFP_API_BASE}/clients")
        self.online_thread.finished.connect(self.display_pilots)
        self.manage_thread(self.online_thread)

    def display_pilots(self, data):
        pilots = data.get("pilots", [])
        
        # 兼容处理：如果数据在 data.data.pilots
        if not pilots and "data" in data and isinstance(data["data"], dict):
            pilots = data["data"].get("pilots", [])
            
        self.online_list.setStyleSheet("""
            QListWidget {
                background: rgba(0,0,0,120); 
                border-radius: 12px; 
                color: white; 
                padding: 10px;
                border: 1px solid rgba(255,255,255,10);
            }
            QListWidget::item {
                background: rgba(255,255,255,10);
                margin-bottom: 8px;
                border-radius: 8px;
                padding: 10px;
            }
            QListWidget::item:selected {
                background: rgba(52, 152, 219, 50);
                border: 1px solid #3498db;
            }
        """)
        
        if not pilots:
            item = QListWidgetItem("✈️ 暂无机组在线")
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#bdc3c7"))
            item.setSizeHint(QSize(0, 50))
            self.online_list.addItem(item)
            return

        for p in pilots:
            # 修复：fp 可能为 None，需要提供默认字典
            fp = p.get("flight_plan") or {}
            
            # 安全获取字段，防止 NoneType 错误
            dep = fp.get('departure', '???') if fp else '???'
            arr = fp.get('arrival', '???') if fp else '???'
            ac = fp.get('aircraft', 'Unknown') if fp else 'Unknown'
            
            item_text = f"✈ {p.get('callsign', 'Unknown')}  |  {dep} ➔ {arr}  |  {ac}\n" \
                        f"   高度: {p.get('altitude', 0)}ft  |  地速: {p.get('ground_speed', 0)}kt  |  应答机: {p.get('transponder','----')}"
            
            item = QListWidgetItem(item_text)
            item.setSizeHint(QSize(0, 70))
            self.online_list.addItem(item)

    def fetch_plane_photo(self):
        reg = self.fields["reg"].text().strip().upper()
        if not reg: return
        self.photo_thread = XZPhotosAPIThread(reg)
        self.photo_thread.finished.connect(self.display_plane_photo)
        self.manage_thread(self.photo_thread)

    def display_plane_photo(self, data):
        xz_logger = logging.getLogger('ISFP-Connect.XZPhotos')
        reg = self.fields["reg"].text().strip().upper()
        
        if data.get("success") and data["data"].get("photo_found"):
            img_url = data["data"]["photo_image_url"]
            xz_logger.info(f"[图片URL-预览] 获取成功 - 注册号: {reg}, URL: {img_url}")
            
            # 使用异步加载方式从URL加载图片
            self.async_load_image_from_url(img_url, self.plane_img_label)
            
            # 自动填充机型
            if not self.fields["ac"].text():
                aircraft_type = data["data"].get("aircraft_type", "")
                self.fields["ac"].setText(aircraft_type)
                xz_logger.info(f"[图片URL-预览] 自动填充机型: {aircraft_type}")
        else:
            xz_logger.info(f"[图片URL-预览] API未返回图片 - 注册号: {reg}")
    
    def async_load_image_from_url(self, url, label):
        """从URL异步加载图片并显示"""
        xz_logger = logging.getLogger('ISFP-Connect.XZPhotos')
        
        # 终极 URL 解析方案
        from urllib.parse import urljoin, quote, urlparse, urlunparse
        base_api_url = "https://xzphotos.cn"
        
        if url.startswith("http"):
            full_url = url
        else:
            full_url = urljoin(base_api_url, url)
            
        try:
            # 修复：使用 urlparse 正确处理 query 参数
            parsed = urlparse(full_url)
            new_path = quote(parsed.path, safe='/')
            
            full_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                new_path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))
        except: 
            pass
        
        req = QNetworkRequest(QUrl(full_url))
        req.setRawHeader(b"User-Agent", b"Mozilla/5.0 ISFP-Connect/1.0")
        
        reply = self.nam.get(req)
        
        def on_finished():
            # 检查 label 是否仍然有效
            try:
                label_width = label.width()
                label_height = label.height()
            except RuntimeError:
                reply.deleteLater()
                return
            
            if reply.error() == QNetworkReply.NoError:
                img_data = reply.readAll()
                image = QImage()
                if image.loadFromData(img_data):
                    # 判断是头像(方形)还是封面(矩形)
                    is_avatar = label_width == label_height
                    
                    if is_avatar:
                        # 头像处理
                        from PySide6.QtCore import QRect
                        size = min(image.width(), image.height())
                        rect = QRect((image.width() - size) // 2, (image.height() - size) // 2, size, size)
                        image = image.copy(rect)
                        
                        pixmap = QPixmap.fromImage(image).scaled(
                            label.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                        )
                        radius = label_width / 2
                    else:
                        # 封面处理
                        pixmap = QPixmap.fromImage(image).scaled(
                            label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )
                        radius = 15.0

                    rounded_pixmap = QPixmap(label.size())
                    rounded_pixmap.fill(Qt.transparent)
                    
                    painter = QPainter(rounded_pixmap)
                    painter.setRenderHint(QPainter.Antialiasing)
                    
                    path = QPainterPath()
                    path.addRoundedRect(0, 0, label.width(), label.height(), radius, radius)
                    painter.setClipPath(path)
                    
                    # 居中绘制
                    x = int((label.width() - pixmap.width()) / 2)
                    y = int((label.height() - pixmap.height()) / 2)
                    painter.drawPixmap(x, y, pixmap)
                    
                    if is_avatar:
                        pen = QPen(QColor(255, 255, 255, 100))
                        pen.setWidth(1)
                        painter.setPen(pen)
                        painter.setBrush(Qt.NoBrush)
                        painter.drawEllipse(0, 0, label.width(), label.height())
                    
                    painter.end()
                    
                    label.setPixmap(rounded_pixmap)
                    label.setStyleSheet("border: none;")
                    xz_logger.info(f"[图片URL-预览] 图片已显示 - URL: {url[:60]}...")
                else:
                    label.setText("图片格式错误")
            else:
                label.setText("加载失败")
            
            reply.deleteLater()
        
        reply.finished.connect(on_finished)

if __name__ == "__main__":
    # 修复 Windows 任务栏图标不显示的问题
    try:
        myappid = 'isfp.connect.app.v1'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    # 初始化默认连线日志
    try:
        from connection_logger import setup_connection_logging
        setup_connection_logging(True)
    except ImportError:
        pass

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("assets/logo.png"))
    window = ISFPApp()
    window.show()
    sys.exit(app.exec())
