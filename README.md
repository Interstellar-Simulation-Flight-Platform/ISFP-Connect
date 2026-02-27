# ISFP-Connect (v0.1.0)

ISFP-Connect 官方桌面客户端是一款专为模拟飞行爱好者设计的综合性辅助工具。基于 **PySide6** 框架开发，提供极佳的 Windows 原生性能与现代化视觉体验。

## 🌟 核心功能

- **🚀 现代化首页**: 实时展示 ISFP 连飞服务器状态、在线机组人数及网络延迟。采用极简航空仪表风格设计。
- **🌤️ 气象报文查询**: 支持全球机场 METAR 与 TAF 报文查询。报文经过 HTML 格式化美化，清晰易读。
- **👥 在线机组监控**: 实时获取连飞服务器上的飞行员动态，包含呼号、高度、速度、航路及机型信息。
- **📝 本地飞行计划制作**:
  - **自动识别**: 输入飞机注册号（如 B-32DN）自动获取高清飞机照片及机型。
  - **航迹预览**: 内置 SkyVector 交互式地图，根据输入的起降机场自动渲染实时航线。
  - **分栏布局**: 左侧表单制作，右侧地图预览，支持自由调节比例。

## 🛠️ 安装要求

- **操作系统**: Windows 10/11 (推荐)
- **Python 版本**: 3.9+
- **核心依赖**:
  - `PySide6`: GUI 框架
  - `PySide6-WebEngine`: 地图渲染内核
  - `requests`: 网络请求

## 🚀 快速开始

1. **克隆/下载项目**
2. **安装依赖**:
   ```powershell
   pip install PySide6 PySide6-WebEngine requests
   ```
3. **准备素材**:
   确保 `assets/` 文件夹下包含：
   - `logo.png`: 应用图标
   - `background.png`: 全局背景图
4. **运行程序**:
   ```powershell
   python main.py
   ```

## 📦 打包教程

推荐使用 **Nuitka** 进行高性能打包，以确保任务栏图标正常显示：

1. **安装 Nuitka**:
   ```powershell
   pip install nuitka
   ```
2. **执行打包命令**:
   ```powershell
   nuitka --standalone --show-progress --plugin-enable=pyside6 --windows-disable-console --include-data-dir=assets=assets main.py
   ```

## 🛠️ 技术细节

- **AppUserModelID**: 解决了 Python 程序在 Windows 任务栏无法显示独立图标的顽疾。
- **异步多线程**: 所有 API 请求（气象、图片下载、在线人数）均在独立线程执行，确保 UI 界面永不卡顿。
- **圆角裁剪算法**: 动态从云端下载飞机图片并实时进行圆角裁剪处理，保持视觉风格统一。

## 📅 版本历史

- **v0.1.0 (2026-02-26)**: 初始版本发布，集成首页、气象、在线、计划四大核心模块。
- **v0.2.0 (2026-02-27)**: 大更新：增加工单、活动、登陆注册等核心模块。

---
© 2026 ISFP 云际模拟飞行连飞平台. All Rights Reserved.
