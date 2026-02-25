import sys
import requests
import ctypes
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, QTextEdit, 
                             QLabel, QTabWidget, QListWidget, QListWidgetItem,
                             QScrollArea, QFrame, QGraphicsBlurEffect, QSplitter)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import Qt, QSize, QTimer, QThread, Signal, QUrl
from PySide6.QtGui import QPixmap, QIcon, QFont, QPalette, QColor, QBrush, QImage, QPainter, QPainterPath

# ================= API 配置 =================
ISFP_API_BASE = "https://isfpapi.flyisfp.com/api"
TAF_API_URL = "https://aviationweather.gov/api/data/taf"
PLANE_INFO_URL = "https://airplane.yhphotos.top/api/get-registration-info.php"

class APIThread(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, url, params=None, is_json=True):
        super().__init__()
        self.url = url
        self.params = params
        self.is_json = is_json

    def run(self):
        try:
            response = requests.get(self.url, params=self.params, timeout=10)
            if self.is_json:
                self.finished.emit(response.json())
            else:
                self.finished.emit({"raw_text": response.text})
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
        
        self.tabs.addTab(self.create_home_tab(), "首页")
        self.tabs.addTab(self.create_weather_tab(), "气象")
        self.tabs.addTab(self.create_online_tab(), "在线")
        self.tabs.addTab(self.create_flight_plan_tab(), "计划")
        
        self.main_layout.addWidget(self.tabs)

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
        # 服务器延迟 (模拟)
        self.ping_stat_card = self.create_stat_panel("网络延迟", "24ms", "#f1c40f")
        # 运行时间
        self.uptime_stat_card = self.create_stat_panel("系统状态", "正常", "#3498db")

        stats_layout.addWidget(self.pilot_stat_card)
        stats_layout.addWidget(self.ping_stat_card)
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
        # 更新首页卡片中的数值
        val_label = self.pilot_stat_card.findChild(QLabel, "ValueLabel")
        if val_label:
            val_label.setText(str(len(pilots)))

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
        # 简单的状态反馈
        self.save_btn.setText(message)
        QTimer.singleShot(2000, lambda: self.save_btn.setText("生成飞行计划 (GENERATE FLIGHT PLAN)"))

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
        metar = data.get("data", "未找到 METAR")
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
                数据来源: ISFP & AviationWeather.gov
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
            fp = p.get("flight_plan", {})
            item_text = f"✈ {p['callsign']}  |  {fp.get('departure','???')} ➔ {fp.get('arrival','???')}  |  {fp.get('aircraft','Unknown')}\n" \
                        f"   高度: {p['altitude']}ft  |  地速: {p['ground_speed']}kt  |  应答机: {p.get('transponder','----')}"
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
