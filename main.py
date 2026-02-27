import sys
import requests
import ctypes
import time
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, QTextEdit, 
                             QLabel, QTabWidget, QListWidget, QListWidgetItem,
                             QScrollArea, QFrame, QGraphicsBlurEffect, QSplitter,
                             QDialog)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import Qt, QSize, QTimer, QThread, Signal, QUrl
from PySide6.QtGui import QPixmap, QIcon, QFont, QPalette, QColor, QBrush, QImage, QPainter, QPainterPath, QPen
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

# ================= API 配置 =================
ISFP_API_BASE = "https://isfpapi.flyisfp.com/api"
TAF_API_URL = "https://aviationweather.gov/api/data/taf"
PLANE_INFO_URL = "https://airplane.yhphotos.top/api/get-registration-info.php"

class APIThread(QThread):
    finished = Signal(dict)
    error = Signal(str)

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
            else:
                result = {"raw_text": response.text}
            
            # 注入延迟数据
            result["_latency"] = latency
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

class ISFPApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ISFP 云际模拟飞行连飞平台")
        # 设置窗口图标
        self.setWindowIcon(QIcon("assets/logo.png"))
        # 设置 16:9 比例 (例如 1280x720)
        self.win_width = 1280
        self.win_height = 720
        self.setFixedSize(self.win_width, self.win_height)
        
        # 用户认证数据
        self.auth_token = None
        self.user_data = None
        
        self.setup_ui()

    def setup_ui(self):
        # 主窗口背景
        self.bg_label = QLabel(self)
        self.bg_label.setGeometry(0, 0, self.win_width, self.win_height)
        pixmap = QPixmap("assets/background.png")
        if not pixmap.isNull():
            self.bg_label.setPixmap(pixmap.scaled(self.win_width, self.win_height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        else:
            self.bg_label.setStyleSheet("background-color: #1a1a1a;")

        # 【核心优化】添加黑色半透明遮罩层，确保背景不会干扰文字阅读
        self.bg_overlay = QFrame(self)
        self.bg_overlay.setGeometry(0, 0, self.win_width, self.win_height)
        # 透明度设置为 0.65 (165/255)，背景会变暗但依然可见
        self.bg_overlay.setStyleSheet("background-color: rgba(0, 0, 0, 165); border: none;")
        self.bg_overlay.lower() # 确保在所有交互控件下方
        self.bg_label.lower()   # 确保背景图在最底层

        # 核心容器
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(15, 20, 15, 15)

        # 顶部 Logo 栏
        header_layout = QHBoxLayout()
        self.logo_label = QLabel()
        logo_pix = QPixmap("assets/logo.png")
        if not logo_pix.isNull():
            self.logo_label.setPixmap(logo_pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        header_layout.addWidget(self.logo_label)
        
        title_label = QLabel("ISFP CONNECT")
        title_label.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        title_label.setStyleSheet("color: white;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()

        # 新增：顶部右侧用户信息/状态区域
        self.top_auth_layout = QHBoxLayout()
        self.top_auth_layout.setSpacing(15)
        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #3498db; font-weight: bold; font-size: 13px;")
        self.top_auth_layout.addWidget(self.status_label)

        self.top_user_btn = QPushButton("未登录")
        self.top_user_btn.setCursor(Qt.PointingHandCursor)
        self.top_user_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 10);
                color: #ccc;
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 15px;
                padding: 5px 15px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: rgba(52, 152, 219, 30);
                color: white;
                border: 1px solid #3498db;
            }
        """)
        self.top_user_btn.clicked.connect(lambda: self.tabs.setCurrentIndex(self.tabs.count()-1))
        self.top_auth_layout.addWidget(self.top_user_btn)
        
        header_layout.addLayout(self.top_auth_layout)
        self.main_layout.addLayout(header_layout)

        # 选项卡
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 0; background: transparent; }
            QTabBar::tab { 
                background: rgba(0, 0, 0, 100); 
                color: #888; 
                padding: 10px 20px; 
                border-top-left-radius: 10px; 
                border-top-right-radius: 10px;
                margin-right: 2px;
            }
            QTabBar::tab:selected { 
                background: rgba(255, 255, 255, 30); 
                color: white; 
                border-bottom: 2px solid #3498db;
            }
        """)
        
        # 初始化网络管理器用于图片加载 (替代 requests 线程)
        self.nam = QNetworkAccessManager(self)

        self.tabs.addTab(self.create_home_tab(), "首页")
        self.tabs.addTab(self.create_weather_tab(), "气象")
        self.tabs.addTab(self.create_online_tab(), "在线")
        self.tabs.addTab(self.create_flight_plan_tab(), "计划")
        self.tabs.addTab(self.create_activities_tab(), "活动")
        self.tabs.addTab(self.create_ticket_tab(), "工单")
        self.tabs.addTab(self.create_account_tab(), "账户")
        
        self.main_layout.addWidget(self.tabs)
        
        # 监听 Tab 切换，自动刷新工单
        self.tabs.currentChanged.connect(self.on_tab_changed)

    def on_tab_changed(self, index):
        tab_name = self.tabs.tabText(index)
        if tab_name == "工单":
            self.load_tickets()
        elif tab_name == "活动":
            self.load_activities()

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
        self.activities_thread.start()

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
                self.sign_thread.start()
                
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
                self.unsign_thread.start()
            
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
            self.top_user_btn.setText(f"已登录: {user.get('username')}")
            self.top_user_btn.setStyleSheet(self.top_user_btn.styleSheet().replace("#ccc", "#2ecc71").replace("rgba(255, 255, 255, 20)", "#2ecc71"))
        else:
            self.top_user_btn.setText("未登录")
            self.top_user_btn.setStyleSheet(self.top_user_btn.styleSheet().replace("#2ecc71", "#ccc"))

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
        avatar_layout = QVBoxLayout(avatar_container)
        avatar = QLabel()
        avatar.setFixedSize(120, 120)
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

        logout_btn = QPushButton("退出登录")
        logout_btn.setFixedHeight(45)
        logout_btn.setCursor(Qt.PointingHandCursor)
        logout_btn.setStyleSheet("""
            QPushButton {
                background: rgba(231, 76, 60, 0.15);
                color: #e74c3c;
                border: 1px solid #e74c3c;
                border-radius: 10px;
                font-weight: bold;
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

    def handle_login(self):
        user = self.login_user.text().strip()
        pwd = self.login_pass.text().strip()
        if not user or not pwd: return

        self.login_thread = APIThread(f"{ISFP_API_BASE}/users/sessions", method="POST", json_data={
            "username": user,
            "password": pwd
        })
        self.login_thread.finished.connect(self.on_login_finished)
        self.login_thread.start()

    def on_login_finished(self, data):
        if data.get("code") == "LOGIN_SUCCESS":
            self.auth_token = data["data"].get("token")
            self.user_data = data["data"]
            self.update_account_ui()
            self.show_notification("登录成功！")
            # 登录后刷新活动和工单
            self.load_activities()
            self.load_tickets()
        else:
            self.show_notification(f"登录失败: {data.get('message')}")

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
        self.code_thread.start()

    def on_code_sent(self, data):
        # 根据 emailapi.md 更新状态码判断
        if data.get("code") == "SEND_EMAIL_SUCCESS":
            self.show_notification("验证码已发送，请查收邮件")
        elif data.get("code") == "EMAIL_SEND_INTERVAL":
            self.show_notification("发送频繁，请 60 秒后重试")
        else:
            msg = data.get("message", "发送失败")
            self.show_notification(f"发送失败: {msg}")

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
        self.reg_thread.start()

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
        self.history_thread.start()
        
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
        self.stats_thread.start()

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

    def create_flight_plan_tab(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # 使用分割器，方便用户调节左右比例
        splitter = QSplitter(Qt.Horizontal)

        # ================= 左半部分：表单制作区 =================
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(15)

        # 飞机预览（放在表单顶部）
        self.plane_img_label = QLabel()
        self.plane_img_label.setFixedSize(500, 200) 
        self.plane_img_label.setAlignment(Qt.AlignCenter)
        self.plane_img_label.setText("等待输入注册号预览照片...")
        self.plane_img_label.setStyleSheet("""
            QLabel {
                background: rgba(0,0,0,150); 
                border-radius: 15px;
                border: 1px solid rgba(255,255,255,0.1);
                color: #555;
            }
        """)
        left_layout.addWidget(self.plane_img_label, alignment=Qt.AlignCenter)

        # 表单卡片
        form_card = QFrame()
        form_card.setStyleSheet("background: rgba(0,0,0,120); border-radius: 15px; padding: 10px;")
        form_layout = QVBoxLayout(form_card)
        
        self.fields = {}
        field_configs = [
            ("航班号 (CALLSIGN)", "例如: CCA1234", "callsign"),
            ("注册号 (REGISTRATION)", "例如: B-32DN", "reg"),
            ("机型 (AIRCRAFT)", "自动识别或手动输入", "ac"),
            ("起飞机场 (DEPARTURE)", "ICAO (如 ZBAA)", "dep"),
            ("落地机场 (ARRIVAL)", "ICAO (如 ZSSS)", "arr"),
            ("航路 (ROUTE)", "输入 DCT 代表直飞", "route")
        ]

        for label, placeholder, key in field_configs:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(150)
            lbl.setStyleSheet("color: #3498db; font-weight: bold; font-size: 11px;")
            
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            if key == "route": edit.setText("DCT")
            edit.setStyleSheet("padding: 8px; background: rgba(255,255,255,10); border-radius: 5px; color: white;")
            
            if key == "reg":
                edit.editingFinished.connect(self.fetch_plane_photo)
            if key in ["dep", "arr"]:
                edit.editingFinished.connect(self.update_map)
            
            self.fields[key] = edit
            row.addWidget(lbl)
            row.addWidget(edit)
            form_layout.addLayout(row)

        left_layout.addWidget(form_card)

        # 制作按钮
        self.save_btn = QPushButton("本地制作飞行计划 (CREATE LOCAL PLAN)")
        self.save_btn.setFixedHeight(50)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background: #27ae60;
                color: white;
                border-radius: 10px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover { background: #2ecc71; }
        """)
        self.save_btn.clicked.connect(lambda: self.show_notification("飞行计划已本地生成！"))
        left_layout.addWidget(self.save_btn)
        
        splitter.addWidget(left_container)

        # ================= 右半部分：航迹地图区 =================
        self.map_view = QWebEngineView()
        self.map_view.setStyleSheet("border-radius: 15px; background: #1a1a1a; border: 1px solid rgba(255,255,255,0.1);")
        # 初始加载一个带深色主题的空地图
        self.load_empty_map()
        
        splitter.addWidget(self.map_view)
        
        # 设置左右比例
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)
        return widget

    def load_empty_map(self):
        # 使用 Leaflet.js 构建一个简单的深色主题地图
        html = """
        <html>
        <head>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                body { margin: 0; background: #1a1a1a; }
                #map { height: 100vh; width: 100vw; }
            </style>
        </head>
        <body>
            <div id="map"></div>
            <script>
                var map = L.map('map', {zoomControl: false}).setView([35, 110], 4);
                L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                    attribution: '&copy; OpenStreetMap'
                }).addTo(map);
            </script>
        </body>
        </html>
        """
        self.map_view.setHtml(html)

    def update_map(self):
        dep = self.fields["dep"].text().strip().upper()
        arr = self.fields["arr"].text().strip().upper()
        if not dep and not arr: return
        
        # 构建 SkyVector 的航图链接作为快速预览（更专业且符合连飞需求）
        # 或者继续使用 Leaflet 展示坐标（需要坐标 API，这里为了演示直接使用 SkyVector 嵌入）
        url = f"https://skyvector.com/?ll=35,110&chart=301&zoom=3"
        if dep and arr:
            url = f"https://skyvector.com/?fpl={dep}%20DCT%20{arr}"
        elif dep:
            url = f"https://skyvector.com/?fpl={dep}"
            
        self.map_view.setUrl(QUrl(url))

    def create_styled_input(self, label, placeholder, key, default="", blur_event=None):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        lbl = QLabel(label)
        lbl.setStyleSheet("color: #3498db; font-weight: bold; font-size: 12px; margin-left: 5px;")
        layout.addWidget(lbl)

        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setText(default)
        edit.setStyleSheet("""
            QLineEdit {
                padding: 12px;
                background: rgba(255,255,255,10);
                border: 1px solid rgba(255,255,255,10);
                border-radius: 10px;
                color: white;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #3498db;
                background: rgba(255,255,255,15);
            }
        """)
        if blur_event:
            edit.editingFinished.connect(blur_event)
        
        layout.addWidget(edit)
        self.fields[key] = edit
        return container

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
        # 调用 /tickets/self 接口
        self.ticket_thread = APIThread(
            f"{ISFP_API_BASE}/tickets/self",
            params={"page_number": 1, "page_size": 50},
            headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        self.ticket_thread.finished.connect(self.display_tickets)
        self.ticket_thread.start()

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
            status = "✅ 已结单" if t.get("closer") else "⏳ 处理中"
            
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
            
            status_lbl = QLabel(status)
            status_lbl.setStyleSheet(f"color: {'#2ecc71' if t.get('closer') else '#f39c12'}; font-weight: bold;")
            
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
            self.create_ticket_thread.start()
            
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
        self.metar_thread.start()

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
        self.taf_thread.start()

    def update_weather_ui(self, metar, taf, icao):
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
                    {taf.replace("\n", "<br>")}
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
        self.online_thread.start()

    def display_pilots(self, data):
        pilots = data.get("pilots", [])
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
        self.photo_thread = APIThread(PLANE_INFO_URL, {"registration": reg})
        self.photo_thread.finished.connect(self.display_plane_photo)
        self.photo_thread.start()

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
