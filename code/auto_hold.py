
import sys
import time
import threading
from pathlib import Path

import keyboard
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QObject, QUrl, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QGraphicsOpacityEffect
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel

def resource_path(name: str) -> Path:
    """Путь к ресурсу: работает и при запуске .py, и внутри собранного exe (PyInstaller)."""
    base = getattr(sys, "_MEIPASS", None)          # PyInstaller распаковывает файлы сюда
    if base is None:
        base = Path(__file__).resolve().parent     # обычный запуск из исходников
    return Path(base) / name

UI_FILE = resource_path("ui.html")
ICON_FILE = resource_path("icon.ico")

#  ЛОГИКА ЗАЖАТИЯ

class HoldWorker:
    def __init__(self, bridge):
        self.bridge = bridge
        self.running = False
        self.key = "e"
        self.hold_seconds = 3.0
        self.pause_seconds = 0.5

    def start(self):
        if self.running:
            return
        self.running = True
        self.bridge.stateChanged.emit(True)
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        if not self.running:
            return
        self.running = False
        try:
            keyboard.release(self.key)
        except Exception:
            pass
        self.bridge.stateChanged.emit(False)

    def _loop(self):
        while self.running:
            try:
                keyboard.press(self.key)
                t0 = time.time()
                while self.running and (time.time() - t0) < self.hold_seconds:
                    time.sleep(0.01)
                keyboard.release(self.key)
            except Exception:
                pass
            if self.running:
                self.bridge.cycleDone.emit()
                t0 = time.time()
                while self.running and (time.time() - t0) < self.pause_seconds:
                    time.sleep(0.01)

#  МОСТ PYTHON <-> JS

class Bridge(QObject):
    stateChanged = pyqtSignal(bool)
    cycleDone = pyqtSignal()
    bindCaptured = pyqtSignal(str, str)

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.worker = HoldWorker(self)
        self.notify_enabled = True          # показывать ли оверлей-уведомление
        self.start_bind = "f6"
        self.stop_bind = "f7"
        self._hotkeys = []
        self._apply_hotkeys()
        self.bindCaptured.connect(self._on_bind)

    #  слоты, вызываемые из JS
    @pyqtSlot()
    def start(self): self.worker.start()

    @pyqtSlot()
    def stop(self): self.worker.stop()

    @pyqtSlot(float)
    def setHold(self, v): self.worker.hold_seconds = float(v)

    @pyqtSlot(float)
    def setPause(self, v): self.worker.pause_seconds = float(v)

    @pyqtSlot(bool)
    def setNotify(self, v):
        self.notify_enabled = bool(v)
        # если выключили — сразу прячем уже показанное уведомление
        if not self.notify_enabled:
            self.window.overlay.hide()

    @pyqtSlot(str)
    def listenBind(self, what):
        def grab():
            ev = keyboard.read_event(suppress=False)
            while ev.event_type != "down":
                ev = keyboard.read_event(suppress=False)
            self.bindCaptured.emit(what, ev.name)
        threading.Thread(target=grab, daemon=True).start()

    @pyqtSlot()
    def startMove(self):
        self.window.windowHandle().startSystemMove()

    @pyqtSlot()
    def quitApp(self):
        self.worker.stop()
        keyboard.unhook_all()
        QApplication.quit()

    #  внутреннее
    def _on_bind(self, what, key_name):
        if what == "key":
            self.worker.key = key_name
        elif what == "start":
            self.start_bind = key_name
            self._apply_hotkeys()
        elif what == "stop":
            self.stop_bind = key_name
            self._apply_hotkeys()

    def _apply_hotkeys(self):
        for h in self._hotkeys:
            try:
                keyboard.remove_hotkey(h)
            except Exception:
                pass
        self._hotkeys = [
            keyboard.add_hotkey(self.start_bind, self.worker.start),
            keyboard.add_hotkey(self.stop_bind, self.worker.stop),
        ]

#  ОВЕРЛЕЙ ПОВЕРХ ИГРЫ

class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.label = QLabel("◆  Ресурсы собраны!", self)
        self.label.setStyleSheet("""
            QLabel {
                color:#ffe2b0; background-color:rgba(16,13,7,230);
                border:1px solid rgba(245,180,82,160); border-radius:16px;
                padding:14px 32px; font-size:17px; font-weight:600;
                font-family:'Segoe UI';
            }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.label)

        self.opacity = QGraphicsOpacityEffect(self.label)
        self.label.setGraphicsEffect(self.opacity)
        self.anim = QPropertyAnimation(self.opacity, b"opacity")
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._fade_out)

    def popup(self):
        self.adjustSize()
        g = QApplication.primaryScreen().geometry()
        self.move(g.center().x() - self.width() // 2, int(g.height() * 0.12))
        self.opacity.setOpacity(0.0)
        self.show()
        self.raise_()
        self.anim.stop()
        self.anim.setDuration(220)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.start()
        self.hide_timer.start(1800)

    def _fade_out(self):
        self.anim.stop()
        self.anim.setDuration(420)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.start()
        QTimer.singleShot(450, self.hide)

#  ГЛАВНОЕ ОКНО

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HikariCore")
        if ICON_FILE.exists():
            self.setWindowIcon(QIcon(str(ICON_FILE)))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(718, 410)

        self.view = QWebEngineView(self)
        self.view.setGeometry(0, 0, 718, 410)
        self.view.page().setBackgroundColor(QColor(0, 0, 0, 0))

        # разрешаем локальной странице грузить qwebchannel.js из ресурсов Qt
        s = self.view.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

        self.bridge = Bridge(self)
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        if not UI_FILE.exists():
            print(f"Не найден файл интерфейса: {UI_FILE}")
            sys.exit(1)
        self.view.load(QUrl.fromLocalFile(str(UI_FILE)))

        self.overlay = Overlay()
        self.bridge.cycleDone.connect(self._on_cycle_done)

    def _on_cycle_done(self):
        # оверлей всплывает, только если уведомления включены;
        # счётчик "собрано" обновляется в JS отдельно и работает
        if self.bridge.notify_enabled:
            self.overlay.popup()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    if ICON_FILE.exists():
        app.setWindowIcon(QIcon(str(ICON_FILE)))
    app.setFont(QFont("Segoe UI", 10))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())