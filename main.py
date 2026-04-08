import sys
import requests
import ctypes
import time
import json
import os
import shutil
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

# ================= API 配置 =================
ISFP_API_BASE = "https://isfpapi.flyisfp.com/api"
TAF_API_URL = "https://aviationweather.gov/api/data/taf"
# XZPhotos API 配置
XZPHOTOS_API_BASE = "https://api.xzphotos.cn/api/v1"
XZPHOTOS_API_KEY = os.environ.get('XZPHOTOS_API_KEY', '')
XZPHOTOS_API_SECRET = os.environ.get('XZPHOTOS_API_SECRET', '')

# 应用版本信息
APP_VERSION = os.environ.get('APP_VERSION', '1.0.0')
APP_VERSION_CODE = int(os.environ.get('APP_VERSION_CODE', '1'))
CHANGELOG = os.environ.get('CHANGELOG', '')

import hashlib
import hmac
import uuid
import time as time_module

def generate_xzphotos_signature(params, secret_key):
    """生成 XZPhotos API 签名"""
    # 生成时间戳和 nonce
    timestamp = str(int(time_module.time()))
    nonce = str(uuid.uuid4())
    
    # 合并参数
    all_params = {**params, 'timestamp': timestamp, 'nonce': nonce}
    
    # 按 key 排序
    sorted_keys = sorted(all_params.keys())
    param_string = '&'.join([f'{k}={all_params[k]}' for k in sorted_keys])
    
    # 追加 SecretKey
    to_sign = param_string + secret_key
    
    # 生成签名
    signature = hmac.new(
        secret_key.encode(),
        to_sign.encode(),
        hashlib.sha256
    ).hexdigest()
    
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
                # 检测JWT过期
                if result.get("code") == "MISSING_OR_MALFORMED_JWT":
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
        try:
            # 准备参数
            params = {
                'registration': self.registration,
                'limit': '1',
                'page': '1'
            }
            
            # 生成签名
            sig_data = generate_xzphotos_signature(params, self.api_secret)
            
            # 构建 URL
            url = f"{XZPHOTOS_API_BASE}/aircraft-images/{self.registration}?{sig_data['param_string']}"
            
            # 设置请求头
            headers = {
                'X-SECRET-ID': self.api_key,
                'X-SIGNATURE': sig_data['signature'],
                'X-TIMESTAMP': sig_data['timestamp'],
                'X-NONCE': sig_data['nonce']
            }
            
            # 发送请求
            response = requests.get(url, headers=headers, timeout=10)
            result = response.json()
            
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
                else:
                    compatible_result = {
                        'success': True,
                        'data': {'photo_found': False}
                    }
            else:
                compatible_result = {
                    'success': False,
                    'data': {'photo_found': False}
                }
            
            self.finished.emit(compatible_result)
        except Exception as e:
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
        self.history.insert(0, flight) # 最新航班排前面
        self.save_json(self.history_file, self.history)

    def delete_flight(self, flight):
        if flight in self.history:
            self.history.remove(flight)
            self.save_json(self.history_file, self.history)

    def clear_history(self):
        self.history = []
        self.save_json(self.history_file, self.history)

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
        self.setFixedSize(400, 300)
        self.parent_app = parent
        self.image_path = None
        self.aircraft_data = aircraft_data
        
        layout = QFormLayout(self)
        
        self.type_input = QLineEdit()
        layout.addRow("机型 (Type):", self.type_input)
        
        self.reg_input = QLineEdit()
        layout.addRow("注册号 (Reg):", self.reg_input)
        
        self.airline_input = QLineEdit()
        layout.addRow("航司 (ICAO):", self.airline_input)
        
        # 图片选择
        img_layout = QHBoxLayout()
        self.img_label = QLabel("未选择图片")
        self.img_label.setStyleSheet("color: #aaa;")
        btn_select = QPushButton("选择图片")
        btn_select.clicked.connect(self.select_image)
        img_layout.addWidget(self.img_label)
        img_layout.addWidget(btn_select)
        layout.addRow("飞机图片:", img_layout)
        
        self.status_label = QLabel("若不上传图片，将自动从网络获取")
        self.status_label.setStyleSheet("color: #f39c12; font-size: 12px;")
        layout.addRow(self.status_label)
        
        # 填充数据
        if aircraft_data:
            self.type_input.setText(aircraft_data.get('type', ''))
            self.reg_input.setText(aircraft_data.get('reg', ''))
            self.airline_input.setText(aircraft_data.get('airline', ''))
            if aircraft_data.get('image'):
                self.image_path = aircraft_data['image']
                self.img_label.setText(os.path.basename(self.image_path))
        
        # 按钮
        btn_box = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(save_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)
        
        # 样式
        self.setStyleSheet("""
            QDialog { background: #2c3e50; color: white; }
            QLineEdit { padding: 5px; border-radius: 4px; border: 1px solid #555; background: #34495e; color: white; }
            QPushButton { padding: 5px 15px; background: #3498db; color: white; border: none; border-radius: 4px; }
            QPushButton:hover { background: #2980b9; }
            QLabel { color: white; }
        """)

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
        self.resize(500, 600)
        self.hangar = hangar
        
        layout = QFormLayout(self)
        
        self.callsign_input = QLineEdit()
        layout.addRow("航班号:", self.callsign_input)
        
        self.dep_input = QLineEdit()
        layout.addRow("出发机场 (ICAO):", self.dep_input)
        
        self.arr_input = QLineEdit()
        layout.addRow("到达机场 (ICAO):", self.arr_input)
        
        self.aircraft_combo = QComboBox()
        for ac in hangar:
            self.aircraft_combo.addItem(f"{ac['reg']} - {ac['type']}", ac)
        layout.addRow("选择航空器:", self.aircraft_combo)
        
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setButtonSymbols(QAbstractSpinBox.NoButtons)
        layout.addRow("计划起飞时间:", self.time_edit)
        
        self.arr_time_edit = QTimeEdit()
        self.arr_time_edit.setDisplayFormat("HH:mm")
        self.arr_time_edit.setButtonSymbols(QAbstractSpinBox.NoButtons)
        layout.addRow("计划落地时间:", self.arr_time_edit)
        
        self.alt_spin = QSpinBox()
        self.alt_spin.setRange(0, 60000)
        self.alt_spin.setValue(30000)
        self.alt_spin.setSingleStep(1000)
        self.alt_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        layout.addRow("巡航高度 (ft):", self.alt_spin)
        
        self.ci_spin = QSpinBox()
        self.ci_spin.setRange(0, 999)
        self.ci_spin.setValue(30)
        self.ci_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        layout.addRow("成本指数 (CI):", self.ci_spin)
        
        self.pax_spin = QSpinBox()
        self.pax_spin.setRange(0, 800)
        self.pax_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        layout.addRow("乘客数:", self.pax_spin)
        
        hbox_taxi = QHBoxLayout()
        self.taxi_out = QSpinBox()
        self.taxi_out.setSuffix(" min")
        self.taxi_out.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.taxi_in = QSpinBox()
        self.taxi_in.setSuffix(" min")
        self.taxi_in.setButtonSymbols(QAbstractSpinBox.NoButtons)
        hbox_taxi.addWidget(QLabel("起飞滑行时间:"))
        hbox_taxi.addWidget(self.taxi_out)
        hbox_taxi.addWidget(QLabel("落地滑行时间:"))
        hbox_taxi.addWidget(self.taxi_in)
        layout.addRow("滑行时间:", hbox_taxi)
        
        self.payload_spin = QSpinBox()
        self.payload_spin.setRange(0, 500000)
        self.payload_spin.setSuffix(" kg")
        self.payload_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        layout.addRow("载荷:", self.payload_spin)
        
        self.extra_fuel = QSpinBox()
        self.extra_fuel.setSuffix(" min")
        self.extra_fuel.setButtonSymbols(QAbstractSpinBox.NoButtons)
        layout.addRow("备用燃油:", self.extra_fuel)
        
        self.route_input = QTextEdit()
        self.route_input.setMaximumHeight(80)
        layout.addRow("飞行航路:", self.route_input)
        
        # 按钮
        btn_box = QHBoxLayout()
        save_btn = QPushButton("创建新航班")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(save_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)
        
        self.setStyleSheet("""
            QDialog { background: #2c3e50; color: white; }
            QLineEdit, QComboBox, QTimeEdit, QSpinBox, QTextEdit { 
                padding: 5px; border-radius: 4px; border: 1px solid #555; background: #34495e; color: white; 
            }
            QPushButton { padding: 8px 20px; background: #27ae60; color: white; border: none; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background: #2ecc71; }
            QLabel { color: white; }
        """)

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
    def __init__(self, flight, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"航班详情 - {flight.get('callsign')}")
        self.resize(400, 500)
        
        layout = QVBoxLayout(self)
        
        # 标题
        title = QLabel(f"{flight.get('dep')} ✈ {flight.get('arr')}")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #3498db; margin: 10px;")
        layout.addWidget(title)
        
        # 详细信息
        form = QFormLayout()
        form.setSpacing(15)
        
        def add_row(label, value):
            lbl = QLabel(label)
            val = QLabel(str(value))
            lbl.setStyleSheet("color: #bdc3c7; font-weight: bold;")
            val.setStyleSheet("color: white;")
            form.addRow(lbl, val)
            
        add_row("航班号:", flight.get('callsign'))
        add_row("日期:", flight.get('date'))
        add_row("机型:", flight.get('aircraft', {}).get('type', 'Unknown'))
        add_row("注册号:", flight.get('aircraft', {}).get('reg', 'Unknown'))
        add_row("计划起飞:", flight.get('etd'))
        add_row("计划落地:", flight.get('eta', '--:--'))
        add_row("巡航高度:", f"{flight.get('altitude')} ft")
        add_row("乘客:", flight.get('pax'))
        add_row("载荷:", f"{flight.get('payload')} kg")
        add_row("航路:", flight.get('route'))
        
        layout.addLayout(form)
        
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("margin-top: 20px; padding: 8px; background: #34495e; color: white; border-radius: 4px;")
        layout.addWidget(close_btn)
        
        self.setStyleSheet("QDialog { background: #2c3e50; }")

class ISFPApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ISFP 云际模拟飞行连飞平台")
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
        # 将配置保存在应用同级目录下的 config.ini 中
        import os
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
        self.settings = QSettings(config_path, QSettings.IniFormat)
        
        # 签派数据管理器
        self.dispatch_manager = DispatchManager(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
        
        # 线程管理器，防止 QThread 被 GC 回收
        self._active_threads = set()
        
        self.setup_ui()
        
        # 启动时检查登录状态
        if not self.auth_token:
            # 默认显示账户页面（登录页面）
            self.switch_page(8)

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
            self.switch_page(8)
        
        thread.finished.connect(cleanup)
        if hasattr(thread, 'jwt_expired'):
            thread.jwt_expired.connect(handle_jwt_expired)
        thread.start()

    def setup_ui(self):
        # 主窗口背景
        self.bg_label = QLabel(self)
        self.bg_label.setGeometry(0, 0, self.win_width, self.win_height)
        
        # 保存原始 Pixmap 以便后续缩放
        self.bg_pixmap = QPixmap("assets/background.png")
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
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(self.create_home_tab())      # 0
        self.stacked_widget.addWidget(self.create_weather_tab())   # 1
        self.stacked_widget.addWidget(self.create_map_tab())       # 2
        self.stacked_widget.addWidget(self.create_rating_tab())    # 3
        self.stacked_widget.addWidget(self.create_dispatch_tab())  # 4
        self.stacked_widget.addWidget(self.create_flight_plan_tab()) # 5
        self.stacked_widget.addWidget(self.create_activities_tab())  # 6
        self.stacked_widget.addWidget(self.create_ticket_tab())      # 7
        self.stacked_widget.addWidget(self.create_account_tab())     # 8
        
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
        
        # 导航按钮
        nav_items = [
            ("🏠", "首页", 0),
            ("🌤", "气象", 1),
            ("🗺", "地图", 2),
            ("🏆", "排行", 3),
            ("✈", "签派", 4),
            ("📋", "计划", 5),
            ("📅", "活动", 6),
            ("🎫", "工单", 7),
            ("👤", "账户", 8),
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
        self.top_user_btn.clicked.connect(lambda: self.switch_page(8))
        top_layout.addWidget(self.top_user_btn)
        
        self.content_layout.addWidget(top_bar)

    def switch_page(self, index):
        """切换页面"""
        # 更新按钮状态
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        
        # 切换页面
        self.stacked_widget.setCurrentIndex(index)
        
        # 更新标题
        titles = ["首页", "气象", "地图", "排行", "签派", "计划", "活动", "工单", "账户"]
        self.page_title.setText(titles[index])
        
        # 自动刷新数据
        if index == 2:  # 地图
            self.load_map_data()
        elif index == 3:  # 排行
            self.load_ratings()
        elif index == 4:  # 签派
            self.load_dispatch_data()
        elif index == 5:  # 计划
            self.load_server_flight_plan()
        elif index == 6:  # 活动
            self.load_activities()
        elif index == 7:  # 工单
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
        
        # 隐藏文本
        self.title_label.hide()
        self.version_label.hide()
        self.status_label.hide()
        
        # 调整占位宽度使 Logo 居中
        self.right_spacer.setFixedWidth(0)
        
        # 按钮只显示图标
        nav_items = ["🏠", "🌤", "🗺", "🏆", "✈", "📋", "📅", "🎫", "👤"]
        for i, btn in enumerate(self.nav_buttons):
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
        
        # 恢复按钮文本
        nav_items = [
            ("🏠", "首页"),
            ("🌤", "气象"),
            ("🗺", "地图"),
            ("🏆", "排行"),
            ("✈", "签派"),
            ("📋", "计划"),
            ("📅", "活动"),
            ("🎫", "工单"),
            ("👤", "账户"),
        ]
        for i, btn in enumerate(self.nav_buttons):
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
        clear_hist_btn.setFixedSize(50, 24)
        clear_hist_btn.setToolTip("清空所有历史记录")
        clear_hist_btn.setStyleSheet("""
            QPushButton { background: rgba(192, 57, 43, 0.8); color: white; border-radius: 4px; font-size: 12px; border: none; }
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
            # 优先使用图片，如果没有则显示默认图标
            if ac.get('image') and os.path.exists(ac['image']):
                icon = QIcon(ac['image'])
            else:
                # 动态生成占位图
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
            
        # 加载历史
        self.flight_history_list.clear()
        history = self.dispatch_manager.history
        for f in history:
            # 格式化显示：日期 | 航班号 | 起降 | 机型
            text = f"📅 {f['date']}   ✈ {f['callsign']}\n" \
                   f"🛫 {f['dep']} ➔ 🛬 {f['arr']}   🛩️ {f['aircraft']['type']}"
            item = QListWidgetItem(text)
            item.setForeground(Qt.white)
            item.setFont(QFont("Consolas", 10))
            item.setData(Qt.UserRole, f) # 存储完整数据以便点击查看
            self.flight_history_list.addItem(item)

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
                    if isinstance(res, dict) and res.get('success') and res['data'].get('photo_found'):
                        img_url = res['data'].get('photo_image_url')
                        if img_url:
                            try:
                                headers = {
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                                }
                                import requests
                                r = requests.get(img_url, headers=headers, timeout=15)
                                if r.status_code == 200:
                                    img_dir = os.path.join(self.dispatch_manager.data_dir, "images")
                                    if not os.path.exists(img_dir):
                                        os.makedirs(img_dir)
                                    img_path = os.path.join(img_dir, f"{reg}.jpg")
                                    with open(img_path, 'wb') as f:
                                        f.write(r.content)
                                    
                                    # 更新数据 (这里稍微复杂，因为我们要更新的是已经修改后的数据)
                                    # 重新从 hangar 中找
                                    for ac in self.dispatch_manager.hangar:
                                        if ac['reg'] == reg: # 假设注册号没改，或者改了之后
                                            ac['image'] = img_path
                                            break
                                    self.dispatch_manager.save_json(self.dispatch_manager.hangar_file, self.dispatch_manager.hangar)
                                    self.load_dispatch_data()
                            except Exception as e:
                                print(f"下载图片失败: {e}")

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
                    if isinstance(res, dict) and res.get('success') and res['data'].get('photo_found'):
                        img_url = res['data'].get('photo_image_url')
                        if img_url:
                            # 下载图片并保存到本地
                            try:
                                headers = {
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                                }
                                import requests
                                r = requests.get(img_url, headers=headers, timeout=15)
                                if r.status_code == 200:
                                    img_dir = os.path.join(self.dispatch_manager.data_dir, "images")
                                    if not os.path.exists(img_dir):
                                        os.makedirs(img_dir)
                                    img_path = os.path.join(img_dir, f"{reg}.jpg")
                                    with open(img_path, 'wb') as f:
                                        f.write(r.content)
                                    
                                    # 更新数据
                                    for ac in self.dispatch_manager.hangar:
                                        if ac['reg'] == reg:
                                            ac['image'] = img_path
                                            break
                                    self.dispatch_manager.save_json(self.dispatch_manager.hangar_file, self.dispatch_manager.hangar)
                                    self.load_dispatch_data() # 刷新显示
                            except Exception as e:
                                print(f"下载图片失败: {e}")

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

    def show_flight_details(self, item):
        flight_data = item.data(Qt.UserRole)
        dialog = FlightDetailsDialog(flight_data, self)
        dialog.exec()

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
        online_title.setStyleSheet("color: #3498db; font-size: 16px; font-weight: bold; margin-bottom: 10px;")
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
        """切换在线机组列表的显示/隐藏"""
        self.online_panel_visible = not self.online_panel_visible
        self.online_panel.setVisible(self.online_panel_visible)

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
        # 移除旧的线程加载器逻辑
        while self.activities_layout.count() > 1:
            item = self.activities_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
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
            if reply.error() == QNetworkReply.NoError:
                img_data = reply.readAll()
                image = QImage()
                if image.loadFromData(img_data):
                    # 判断是头像(方形)还是活动封面(矩形)
                    is_avatar = label.width() == label.height()
                    
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
        dialog.setWindowTitle("连线历史")
        dialog.setFixedSize(600, 600)
        dialog.setStyleSheet("background: #2c3e50; color: white;")
        
        layout = QVBoxLayout(dialog)
        
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 0; }
            QTabBar::tab { background: #34495e; color: white; padding: 10px 20px; }
            QTabBar::tab:selected { background: #3498db; }
        """)
        
        pilot_list = QListWidget()
        atc_list = QListWidget()
        
        # 统一样式
        list_style = """
            QListWidget { background: transparent; border: none; }
            QListWidget::item { 
                background: rgba(255,255,255,0.05); 
                padding: 10px; 
                margin-bottom: 5px; 
                border-radius: 5px;
            }
        """
        pilot_list.setStyleSheet(list_style)
        atc_list.setStyleSheet(list_style)
        
        tabs.addTab(pilot_list, "飞行记录 (Pilot)")
        tabs.addTab(atc_list, "管制记录 (ATC)")
        layout.addWidget(tabs)
        
        # 加载数据
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
            
            # 更新 Tab 标题包含总时长
            pilot_hours = round(d.get("total_pilot_time", 0) / 3600, 1)
            atc_hours = round(d.get("total_atc_time", 0) / 3600, 1)
            tabs.setTabText(0, f"飞行记录 ({pilot_hours}h)")
            tabs.setTabText(1, f"管制记录 ({atc_hours}h)")
            
            def add_items(items, list_widget, icon):
                if not items:
                    list_widget.addItem("暂无记录")
                    return
                    
                for item in items:
                    start = item.get("start_time", "").replace("T", " ").split(".")[0]
                    duration = round(item.get("online_time", 0) / 60, 1)
                    callsign = item.get("callsign", "Unknown")
                    
                    text = f"{icon} {callsign}\n   开始: {start} | 时长: {duration}分钟"
                    lw_item = QListWidgetItem(text)
                    list_widget.addItem(lw_item)
            
            add_items(pilots, pilot_list, "✈")
            add_items(controllers, atc_list, "📡")
            
        self.history_thread.finished.connect(on_history_loaded)
        self.manage_thread(self.history_thread)
        
        dialog.exec()

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
        # 运行时间
        self.uptime_stat_card = self.create_stat_panel("系统状态", "正常", "#3498db")

        stats_layout.addWidget(self.pilot_stat_card)
        stats_layout.addWidget(self.atc_stat_card)
        stats_layout.addWidget(self.uptime_stat_card)

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
        
        # 更新首页卡片中的数值
        p_val = self.pilot_stat_card.findChild(QLabel, "ValueLabel")
        if p_val:
            p_val.setText(str(len(pilots)))
            
        a_val = self.atc_stat_card.findChild(QLabel, "ValueLabel")
        if a_val:
            a_val.setText(str(len(controllers)))

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
        
        self.plan_fields['transponder'] = QLineEdit()
        self.plan_fields['transponder'].setPlaceholderText("1000")
        self.plan_fields['transponder'].setMaxLength(4)
        
        # Row 1
        form_layout.addWidget(QLabel("机载设备:"), 1, 0)
        form_layout.addWidget(self.plan_fields['equipment'], 1, 1, 1, 3) # 跨3列
        form_layout.addWidget(QLabel("应答机:"), 1, 4)
        form_layout.addWidget(self.plan_fields['transponder'], 1, 5)
        
        # 3. 巡航信息
        
        self.plan_fields['dep'] = QLineEdit()
        self.plan_fields['dep'].setPlaceholderText("ZBAA")
        self.plan_fields['dep'].setMaxLength(4)
        
        self.plan_fields['dep_time'] = QTimeEdit()
        self.plan_fields['dep_time'].setDisplayFormat("HHmm")
        self.plan_fields['dep_time'].setButtonSymbols(QAbstractSpinBox.NoButtons)
        
        self.plan_fields['altitude'] = QLineEdit()
        self.plan_fields['altitude'].setPlaceholderText("FL321")

        self.plan_fields['cruise_tas'] = QSpinBox()
        self.plan_fields['cruise_tas'].setRange(0, 9999)
        self.plan_fields['cruise_tas'].setValue(450)
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
        self.plan_fields['eet_h'].setSuffix(" h")
        self.plan_fields['eet_h'].setButtonSymbols(QAbstractSpinBox.NoButtons)
        
        self.plan_fields['eet_m'] = QSpinBox()
        self.plan_fields['eet_m'].setRange(0, 59)
        self.plan_fields['eet_m'].setSuffix(" m")
        self.plan_fields['eet_m'].setButtonSymbols(QAbstractSpinBox.NoButtons)
        
        # Row 3
        form_layout.addWidget(QLabel("落地机场:"), 3, 0)
        form_layout.addWidget(self.plan_fields['arr'], 3, 1)
        form_layout.addWidget(QLabel("备降机场:"), 3, 2)
        form_layout.addWidget(self.plan_fields['alt'], 3, 3)
        form_layout.addWidget(QLabel("预计飞行时间:"), 3, 4)
        
        hbox_eet = QHBoxLayout()
        hbox_eet.addWidget(self.plan_fields['eet_h'])
        hbox_eet.addWidget(self.plan_fields['eet_m'])
        form_layout.addLayout(hbox_eet, 3, 5)
        
        # 5. 燃油与其他
        
        self.plan_fields['fuel_h'] = QSpinBox()
        self.plan_fields['fuel_h'].setRange(0, 99)
        self.plan_fields['fuel_h'].setSuffix(" h")
        self.plan_fields['fuel_h'].setButtonSymbols(QAbstractSpinBox.NoButtons)
        
        self.plan_fields['fuel_m'] = QSpinBox()
        self.plan_fields['fuel_m'].setRange(0, 59)
        self.plan_fields['fuel_m'].setSuffix(" m")
        self.plan_fields['fuel_m'].setButtonSymbols(QAbstractSpinBox.NoButtons)
        
        # Row 3 continued (Sharing row or new row? Let's use new row for fuel)
        # Row 4
        form_layout.addWidget(QLabel("续航时间:"), 3, 6)
        hbox_fuel = QHBoxLayout()
        hbox_fuel.addWidget(self.plan_fields['fuel_h'])
        hbox_fuel.addWidget(self.plan_fields['fuel_m'])
        form_layout.addLayout(hbox_fuel, 3, 7)

        # 6. 航路
        self.plan_fields['route'] = QTextEdit()
        self.plan_fields['route'].setPlaceholderText("DCT")
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
                
            # 解析 XPDR
            xpdr_match = re.search(r'/XPDR/(\d{4})', raw_remarks)
            if xpdr_match:
                self.plan_fields['transponder'].setText(xpdr_match.group(1))
                raw_remarks = raw_remarks.replace(xpdr_match.group(0), "").strip()
            else:
                self.plan_fields['transponder'].clear()
            
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
            
            # 显示删除按钮，并将提交按钮改为“更新”
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
            xpdr = self.plan_fields['transponder'].text().strip()
            
            # 将这些额外字段追加到 remarks 中以便持久化
            final_remarks = f"{remarks_base} /WAKE/{wake}"
            if eqpt:
                final_remarks += f" /EQPT/{eqpt}"
            if xpdr:
                final_remarks += f" /XPDR/{xpdr}"
            
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
            
            # 简单校验
            if not payload['callsign'] or not payload['departure'] or not payload['arrival']:
                self.show_notification("请填写完整的呼号、起降机场")
                return

            self.submit_plan_thread = APIThread(
                f"{ISFP_API_BASE}/plans",
                method="POST",
                json_data=payload,
                headers={"Authorization": f"Bearer {self.auth_token}"}
            )
            self.submit_plan_thread.finished.connect(lambda d: [
                self.show_notification(d.get('message', '操作完成')),
                self.load_server_flight_plan() if d.get('code') == 'SUBMIT_FLIGHT_PLAN' else None
            ])
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
        self.del_plan_thread.finished.connect(lambda d: [
            self.show_notification(d.get('message', '操作完成')),
            # 清空表单或重置状态
            self.load_server_flight_plan() if d.get('code') == 'DELETE_SELF_FLIGHT_PLAN' else None
        ])
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
        if data.get("success") and data["data"].get("photo_found"):
            img_url = data["data"]["photo_image_url"]
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            try:
                img_data = requests.get(img_url, headers=headers, timeout=15).content
                image = QImage()
                image.loadFromData(img_data)
                
                # 原始 Pixmap
                pixmap = QPixmap.fromImage(image).scaled(
                    self.plane_img_label.size(), 
                    Qt.KeepAspectRatio, # 改为 KeepAspectRatio 保证图片展示全
                    Qt.SmoothTransformation
                )

                # 创建圆角裁剪后的 Pixmap
                rounded_pixmap = QPixmap(pixmap.size())
                rounded_pixmap.fill(Qt.transparent)
                
                painter = QPainter(rounded_pixmap)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                
                path = QPainterPath()
                path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), 20, 20)
                painter.setClipPath(path)
                painter.drawPixmap(0, 0, pixmap)
                painter.end()

                self.plane_img_label.setPixmap(rounded_pixmap)
                self.plane_img_label.setStyleSheet("border: none;") # 移除边框，使用圆角图
                
                if not self.fields["ac"].text():
                    self.fields["ac"].setText(data["data"].get("aircraft_type", ""))
            except Exception as e:
                print(f"图片下载失败: {e}")

if __name__ == "__main__":
    # 修复 Windows 任务栏图标不显示的问题
    try:
        myappid = 'isfp.connect.app.v1'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("assets/logo.png"))
    window = ISFPApp()
    window.show()
    sys.exit(app.exec())
