"""
灵动岛组件 - 类似 iPhone Dynamic Island 的悬浮通知组件
"""

import os
import logging
from PySide6.QtCore import Qt, QTimer, Signal, QPoint, QRect, QPropertyAnimation, QEasingCurve, QSettings, QObject
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QApplication
from PySide6.QtGui import QColor, QPainter, QPainterPath, QFont, QCursor, QPixmap

logger = logging.getLogger('ISFP-Connect.DynamicIsland')

# 航班状态配置
FLIGHT_STATUS_CONFIG = {
    "准备": {"color": "#3498db", "icon": "📝"},      # 蓝色
    "推出": {"color": "#9b59b6", "icon": "🚶"},      # 紫色
    "滑行": {"color": "#f39c12", "icon": "🚕"},      # 橙色
    "起飞": {"color": "#e67e22", "icon": "🛫"},      # 深橙
    "爬升": {"color": "#1abc9c", "icon": "⬆️"},      # 青色
    "巡航": {"color": "#2ecc71", "icon": "✈️"},      # 绿色
    "下降": {"color": "#1abc9c", "icon": "⬇️"},      # 青色
    "进近": {"color": "#e74c3c", "icon": "🎯"},      # 红色
    "着陆": {"color": "#c0392b", "icon": "🛬"},      # 深红
}


class DynamicIsland(QWidget):
    """灵动岛悬浮组件"""
    
    # 信号
    position_changed = Signal(QPoint)
    clicked = Signal()
    
    def __init__(self, parent=None):
        # 忽略 parent，让灵动岛成为独立窗口
        super().__init__(None)
        
        # 设置窗口属性
        self.setWindowFlags(
            Qt.FramelessWindowHint |  # 无边框
            Qt.WindowStaysOnTopHint |  # 置顶
            Qt.Tool |  # 不在任务栏显示
            Qt.WindowDoesNotAcceptFocus |  # 不获取焦点
            Qt.WindowTransparentForInput  # 默认点击穿透
        )
        self.setAttribute(Qt.WA_TranslucentBackground)  # 透明背景
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # 默认鼠标事件穿透
        
        # 尺寸（必须先定义，后面计算默认位置要用）
        # 日常尺寸（当前编辑状态的大小）
        self.fixed_width = 180
        self.fixed_height = 40
        
        # 展开/收起尺寸（编辑模式时更大）
        self.collapsed_width = self.fixed_width
        self.collapsed_height = self.fixed_height
        self.expanded_width = 220  # 编辑模式时更大
        self.expanded_height = 50
        
        # 设置
        self.settings = QSettings('ISFP-Connect', 'DynamicIsland')
        self.is_enabled = self.settings.value('dynamic_island_enabled', True, bool)
        
        # 默认位置：屏幕中央正上方
        screen = QApplication.primaryScreen().geometry()
        default_x = (screen.width() - self.fixed_width) // 2
        default_y = 20  # 距离顶部 20 像素
        
        self.position = QPoint(
            self.settings.value('dynamic_island_x', default_x, int),
            self.settings.value('dynamic_island_y', default_y, int)
        )
        self.is_editing = False  # 是否处于编辑模式
        
        self.current_width = self.fixed_width
        self.current_height = self.fixed_height
        
        # 定时器用于自动收起（必须在init_ui之前创建）
        self.collapse_timer = QTimer(self)
        self.collapse_timer.timeout.connect(self.collapse)
        
        # 航班信息
        self.flight_number = None
        self.flight_status = None
        self.showing_flight = False
        
        # 动画相关
        self._animation_in_progress = False
        
        # 初始化UI
        self.init_ui()
        
        # 移动到保存的位置
        self.move(self.position)
        
        # 根据设置显示/隐藏
        if self.is_enabled:
            self.show()
        else:
            self.hide()
    
    def init_ui(self):
        """初始化UI"""
        self.setFixedSize(self.fixed_width, self.fixed_height)
        
        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(0)
        
        # === 默认内容区域 ===
        self.default_widget = QWidget()
        default_layout = QHBoxLayout(self.default_widget)
        default_layout.setContentsMargins(0, 0, 0, 0)
        default_layout.setSpacing(6)
        default_layout.setAlignment(Qt.AlignCenter)
        
        # Logo 图片
        self.logo_label = QLabel()
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'logo.png')
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            if not pixmap.isNull():
                scaled_logo = pixmap.scaled(22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.logo_label.setPixmap(scaled_logo)
        self.logo_label.setFixedSize(22, 22)
        default_layout.addWidget(self.logo_label)
        
        # 内容标签
        self.content_label = QLabel("ISFP Connect")
        self.content_label.setAlignment(Qt.AlignCenter)
        self.content_label.setFont(QFont("Microsoft YaHei", 11))
        self.content_label.setStyleSheet("color: white;")
        default_layout.addWidget(self.content_label)
        
        layout.addWidget(self.default_widget)
        
        # === 航班信息区域（初始隐藏）===
        self.flight_widget = QWidget()
        flight_layout = QHBoxLayout(self.flight_widget)
        flight_layout.setContentsMargins(0, 0, 0, 0)
        flight_layout.setSpacing(6)
        flight_layout.setAlignment(Qt.AlignCenter)
        
        # Logo（小尺寸）
        self.flight_logo_label = QLabel()
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'logo.png')
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            if not pixmap.isNull():
                scaled_logo = pixmap.scaled(18, 18, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.flight_logo_label.setPixmap(scaled_logo)
        self.flight_logo_label.setFixedSize(18, 18)
        flight_layout.addWidget(self.flight_logo_label)
        
        # 航班号
        self.flight_number_label = QLabel()
        self.flight_number_label.setAlignment(Qt.AlignCenter)
        self.flight_number_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        self.flight_number_label.setStyleSheet("color: white;")
        flight_layout.addWidget(self.flight_number_label)
        
        # 分隔线
        self.separator_label = QLabel("|")
        self.separator_label.setStyleSheet("color: rgba(255,255,255,0.5);")
        self.separator_label.setFont(QFont("Microsoft YaHei", 10))
        flight_layout.addWidget(self.separator_label)
        
        # 状态图标
        self.status_icon_label = QLabel()
        self.status_icon_label.setFont(QFont("Segoe UI Emoji", 14))
        flight_layout.addWidget(self.status_icon_label)
        
        # 状态文字
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(QFont("Microsoft YaHei", 10))
        flight_layout.addWidget(self.status_label)
        
        self.flight_widget.hide()
        layout.addWidget(self.flight_widget)
        
        # 编辑模式提示
        self.edit_hint = QLabel("拖动调整位置")
        self.edit_hint.setAlignment(Qt.AlignCenter)
        self.edit_hint.setFont(QFont("Microsoft YaHei", 9))
        self.edit_hint.setStyleSheet("color: rgba(255,255,255,0.7);")
        self.edit_hint.hide()
        layout.addWidget(self.edit_hint)
    
    def paintEvent(self, event):
        """绘制圆角黑色背景"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 编辑模式时显示边框
        if self.is_editing:
            border_color = QColor(52, 152, 219, 200)  # 蓝色边框
            border_width = 2
        else:
            border_color = QColor(0, 0, 0, 0)
            border_width = 0
        
        # 绘制黑色背景
        path = QPainterPath()
        path.addRoundedRect(
            QRect(border_width, border_width, 
                  self.current_width - border_width * 2, 
                  self.current_height - border_width * 2),
            self.current_height / 2,  # 圆角半径
            self.current_height / 2
        )
        
        # 填充黑色
        painter.fillPath(path, QColor(0, 0, 0, 230))
        
        # 绘制边框（编辑模式）
        if self.is_editing:
            painter.setPen(border_color)
            painter.drawPath(path)
    
    def show_message(self, message, duration=3000):
        """显示消息（带动画效果）
        
        Args:
            message: 要显示的消息
            duration: 显示持续时间（毫秒）
        """
        if not self.is_enabled:
            return
        
        # 如果正在显示航班信息，不覆盖
        if self.showing_flight:
            return
        
        # 停止之前的定时器
        self.collapse_timer.stop()
        
        # 保存当前消息以便显示
        self._current_message = message
        
        # 切换到默认显示模式
        self.flight_widget.hide()
        self.default_widget.show()
        
        # 计算需要的宽度（根据消息长度）
        # 每个字符约 8-10 像素，加上边距
        text_width = len(message) * 10 + 60  # 60 是边距和图标
        target_width = max(self.expanded_width, min(text_width, 400))  # 最小 220，最大 400
        
        # 先立即更新文字（在动画之前，这样文字不会出现在框外）
        self.content_label.setText(message)
        
        # 如果当前是收起状态，先立即扩展到最小展开大小（无动画），然后再动画到目标大小
        if self.current_width <= self.collapsed_width + 10:
            # 立即设置为最小展开大小（无动画）
            self._instant_resize(self.expanded_width, self.expanded_height)
            # 然后动画到目标大小
            self.animate_size(target_width, self.expanded_height, duration=300)
        else:
            # 已经在展开状态，直接动画到目标大小
            self.animate_size(target_width, self.expanded_height, duration=300)
        
        # 设置定时收起（collapse 方法会处理收起和重置）
        self.collapse_timer.start(duration)
    
    def _instant_resize(self, width, height):
        """立即改变大小（无动画）"""
        # 计算位置偏移以保持中心点不变
        old_center = self.geometry().center()
        
        self.current_width = width
        self.current_height = height
        self.setFixedSize(width, height)
        
        # 调整位置保持中心点
        new_x = old_center.x() - width // 2
        new_y = old_center.y() - height // 2
        self.move(new_x, new_y)
        
        self.update()
    
    def show_flight_info(self, flight_number, status):
        """显示航班信息（带动画）
        
        Args:
            flight_number: 航班号
            status: 航班状态（如"巡航"、"进近"等）
        """
        if not self.is_enabled:
            return
        
        # 如果状态是"着陆"或"落地"，不显示
        if status in ["着陆", "落地", "ARRIVED", "LANDED"]:
            self.hide_flight_info()
            return
        
        # 如果信息没有变化，不重新动画
        if self.flight_number == flight_number and self.flight_status == status and self.showing_flight:
            return
        
        self.flight_number = flight_number
        self.flight_status = status
        self.showing_flight = True
        
        # 更新航班信息
        self.flight_number_label.setText(flight_number)
        
        # 获取状态配置
        config = FLIGHT_STATUS_CONFIG.get(status, {"color": "#bdc3c7", "icon": "✈️"})
        self.status_icon_label.setText(config["icon"])
        self.status_label.setText(status)
        self.status_label.setStyleSheet(f"color: {config['color']};")
        
        # 切换到航班显示（带动画）
        self._animate_to_flight_mode()
    
    def hide_flight_info(self):
        """隐藏航班信息，恢复默认显示"""
        if not self.showing_flight:
            return
        
        self.showing_flight = False
        self.flight_number = None
        self.flight_status = None
        
        # 切换回默认显示（带动画）
        self._animate_to_default_mode()
    
    def _animate_to_flight_mode(self):
        """动画切换到航班显示模式"""
        if self._animation_in_progress:
            return
        
        self._animation_in_progress = True
        
        # 先展开一点以容纳航班信息
        target_width = 240
        self.animate_size(target_width, self.fixed_height)
        
        # 淡出默认内容，淡入航班内容
        self.default_widget.hide()
        self.flight_widget.show()
        
        self._animation_in_progress = False
    
    def _animate_to_default_mode(self):
        """动画切换到默认显示模式"""
        if self._animation_in_progress:
            return
        
        self._animation_in_progress = True
        
        # 恢复原始大小
        self.animate_size(self.fixed_width, self.fixed_height)
        
        # 切换显示
        self.flight_widget.hide()
        self.default_widget.show()
        
        self._animation_in_progress = False
    
    def expand(self):
        """展开灵动岛"""
        if self.current_width == self.expanded_width:
            return
        
        self.animate_size(self.expanded_width, self.expanded_height)
    
    def collapse(self):
        """收起灵动岛并恢复初始状态（先隐藏logo和文字，再缩小，再显示默认）"""
        if self.current_width == self.collapsed_width and self.current_height == self.collapsed_height:
            # 已经收起，只重置消息
            self._reset_to_default()
            return
        
        # 第1步：先隐藏 logo 和文字
        self.logo_label.hide()
        self.content_label.hide()
        
        # 第2步：执行收缩动画
        self.animate_size(self.collapsed_width, self.collapsed_height, duration=300)
        
        # 第3步：动画完成后显示默认 logo 和文字
        QTimer.singleShot(300, self._show_default_content)
    
    def _show_default_content(self):
        """显示默认内容（收缩完成后）"""
        # 恢复默认文字
        self.content_label.setText("ISFP Connect")
        # 显示 logo 和文字
        self.logo_label.show()
        self.content_label.show()
        # 清除当前消息
        if hasattr(self, '_current_message'):
            self._current_message = None
        # 确保显示默认内容
        self.default_widget.show()
        self.flight_widget.hide()
    
    def _reset_to_default(self):
        """重置为默认状态（立即，无动画）"""
        # 重置消息为默认文本
        self.content_label.setText("ISFP Connect")
        # 清除当前消息
        if hasattr(self, '_current_message'):
            self._current_message = None
        # 确保显示默认内容
        self.default_widget.show()
        self.flight_widget.hide()
    
    def animate_size(self, target_width, target_height, duration=300):
        """动画改变大小（带丝滑动画效果）
        
        Args:
            target_width: 目标宽度
            target_height: 目标高度
            duration: 动画持续时间（毫秒）
        """
        # 计算位置偏移以保持中心点不变
        old_center = self.geometry().center()
        start_rect = self.geometry()
        
        # 计算目标位置和大小（保持中心点）
        target_x = old_center.x() - target_width // 2
        target_y = old_center.y() - target_height // 2
        
        # 创建几何动画（同时改变位置和大小）
        self._geometry_anim = QPropertyAnimation(self, b"geometry")
        self._geometry_anim.setDuration(duration)
        self._geometry_anim.setStartValue(start_rect)
        self._geometry_anim.setEndValue(QRect(target_x, target_y, target_width, target_height))
        self._geometry_anim.setEasingCurve(QEasingCurve.OutCubic)
        
        # 动画过程中实时更新当前尺寸
        def on_value_changed(value):
            self.current_width = value.width()
            self.current_height = value.height()
            self.update()
        
        self._geometry_anim.valueChanged.connect(on_value_changed)
        
        # 动画完成后确保最终状态
        def on_finished():
            self.current_width = target_width
            self.current_height = target_height
            self.setFixedSize(target_width, target_height)
            self.update()
        
        self._geometry_anim.finished.connect(on_finished)
        
        # 启动动画
        self._geometry_anim.start()
    
    def set_enabled(self, enabled):
        """设置是否启用"""
        self.is_enabled = enabled
        self.settings.setValue('dynamic_island_enabled', enabled)
        
        if enabled:
            self.show()
        else:
            self.hide()
    
    def start_edit_mode(self):
        """开始编辑模式"""
        self.is_editing = True
        
        # 禁用点击穿透
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.WindowDoesNotAcceptFocus
        )
        self.show()
        
        # 显示编辑提示
        self.edit_hint.show()
        self.expand()
        
        self.update()
        logger.info("灵动岛进入编辑模式")
    
    def stop_edit_mode(self):
        """停止编辑模式"""
        self.is_editing = False
        
        # 重新启用点击穿透
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.WindowDoesNotAcceptFocus |
            Qt.WindowTransparentForInput
        )
        self.show()
        
        # 隐藏编辑提示
        self.edit_hint.hide()
        self.collapse()
        
        # 保存位置
        self.save_position()
        
        self.update()
        logger.info("灵动岛退出编辑模式，位置已保存")
    
    def save_position(self):
        """保存位置到设置"""
        self.position = self.pos()
        self.settings.setValue('dynamic_island_x', self.position.x())
        self.settings.setValue('dynamic_island_y', self.position.y())
    
    def mousePressEvent(self, event):
        """鼠标按下 - 编辑模式下开始拖动"""
        if self.is_editing and event.button() == Qt.LeftButton:
            self.drag_start_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """鼠标移动 - 编辑模式下拖动"""
        if self.is_editing and event.buttons() == Qt.LeftButton:
            new_pos = event.globalPos() - self.drag_start_pos
            self.move(new_pos)
            self.position_changed.emit(new_pos)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """鼠标释放"""
        if self.is_editing:
            event.accept()
    
    def enterEvent(self, event):
        """鼠标进入 - 编辑模式下改变光标"""
        if self.is_editing:
            self.setCursor(QCursor(Qt.OpenHandCursor))
    
    def leaveEvent(self, event):
        """鼠标离开"""
        self.unsetCursor()


class DynamicIslandEditor(QObject):
    """灵动岛位置编辑器 - 非全屏模式，在主应用内显示按钮"""
    
    saved = Signal()
    cancelled = Signal()
    
    def __init__(self, dynamic_island, main_window):
        super().__init__(main_window)
        
        self.dynamic_island = dynamic_island
        self.main_window = main_window
        
        # 保存原始位置用于取消
        self.original_pos = dynamic_island.pos()
    
    def start_editing(self):
        """开始编辑模式"""
        # 启动灵动岛编辑模式
        self.dynamic_island.start_edit_mode()
        
        # 在主窗口显示编辑提示和按钮
        self._create_edit_controls()
    
    def _create_edit_controls(self):
        """在主窗口创建编辑控制按钮"""
        from PySide6.QtWidgets import QPushButton, QHBoxLayout, QWidget, QLabel
        
        # 创建浮动控制栏
        self.control_bar = QWidget(self.main_window)
        self.control_bar.setStyleSheet("""
            QWidget {
                background-color: rgba(0, 0, 0, 0.8);
                border-radius: 10px;
                padding: 10px;
            }
        """)
        
        layout = QHBoxLayout(self.control_bar)
        layout.setSpacing(10)
        
        # 提示文字
        hint = QLabel("🖱 拖动灵动岛调整位置")
        hint.setStyleSheet("color: white; font-size: 13px;")
        layout.addWidget(hint)
        
        layout.addSpacing(20)
        
        # 保存按钮
        save_btn = QPushButton("💾 保存")
        save_btn.setStyleSheet("""
            QPushButton {
                background: #27ae60;
                color: white;
                padding: 8px 20px;
                border-radius: 5px;
                font-size: 12px;
                border: none;
            }
            QPushButton:hover {
                background: #2ecc71;
            }
        """)
        save_btn.clicked.connect(self.on_save)
        layout.addWidget(save_btn)
        
        # 取消按钮
        cancel_btn = QPushButton("❌ 取消")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #c0392b;
                color: white;
                padding: 8px 20px;
                border-radius: 5px;
                font-size: 12px;
                border: none;
            }
            QPushButton:hover {
                background: #e74c3c;
            }
        """)
        cancel_btn.clicked.connect(self.on_cancel)
        layout.addWidget(cancel_btn)
        
        # 设置大小和位置（主窗口底部中央）
        self.control_bar.adjustSize()
        main_geo = self.main_window.geometry()
        self.control_bar.move(
            (main_geo.width() - self.control_bar.width()) // 2,
            main_geo.height() - 80
        )
        self.control_bar.show()
        
        # 保存按钮引用
        self.save_btn = save_btn
        self.cancel_btn = cancel_btn
    
    def on_save(self):
        """保存位置"""
        self.dynamic_island.stop_edit_mode()
        self._cleanup()
        self.saved.emit()
    
    def on_cancel(self):
        """取消编辑"""
        # 先停止编辑模式（恢复大小但不保存位置）
        self.dynamic_island.stop_edit_mode()
        # 恢复原来的位置
        self.dynamic_island.move(self.original_pos)
        self._cleanup()
        self.cancelled.emit()
    
    def _cleanup(self):
        """清理控件"""
        if hasattr(self, 'control_bar'):
            self.control_bar.deleteLater()


# 全局灵动岛实例
_dynamic_island = None


def get_dynamic_island(parent=None):
    """获取灵动岛单例实例"""
    global _dynamic_island
    if _dynamic_island is None:
        _dynamic_island = DynamicIsland(None)  # 独立窗口，不依附于主窗口
    return _dynamic_island


def show_dynamic_island_message(message, duration=3000):
    """显示灵动岛消息"""
    island = get_dynamic_island()
    island.show_message(message, duration)


def update_flight_on_island(flight_number, status):
    """更新灵动岛航班信息
    
    Args:
        flight_number: 航班号
        status: 航班状态
    """
    island = get_dynamic_island()
    if status in ["着陆", "落地", "ARRIVED", "LANDED", None, ""]:
        island.hide_flight_info()
    else:
        island.show_flight_info(flight_number, status)
