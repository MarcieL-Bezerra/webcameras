import os
import shutil
import threading
import time
import cv2
from dotenv import load_dotenv
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QWidget, QGridLayout,
    QPushButton, QDialog, QFormLayout, QLineEdit, QVBoxLayout, QMessageBox
)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap


def ensure_env():
    # If .env missing but .env.example exists, rename (or copy) it to .env
    if not os.path.exists('.env'):
        if os.path.exists('.env.example'):
            try:
                os.rename('.env.example', '.env')
            except OSError:
                shutil.copyfile('.env.example', '.env')
        else:
            # create an empty .env so the app follows exactly what's in the file
            open('.env', 'a').close()
    # load (or reload) environment variables from .env
    load_dotenv(override=True)


def load_config():
    # Collect CAM1..CAMn from env in order. If none found, return empty list.
    cams = []
    i = 1
    while True:
        key = f"CAM{i}"
        val = os.getenv(key)
        if val is None:
            break
        v = val.strip()
        if v:
            cams.append(v)
        i += 1
    return cams


class CameraThread(threading.Thread):
    def __init__(self, url, target_fps=5, max_width=640):
        super().__init__(daemon=True)
        self.url = url
        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        self._cap = None
        self.last_success = time.monotonic()
        self.failed = False
        self.target_fps = target_fps
        self.max_width = max_width

    def run(self):
        while self.running:
            try:
                if self._cap is None or not self._cap.isOpened():
                    if self._cap:
                        try:
                            self._cap.release()
                        except Exception:
                            pass
                    self._cap = cv2.VideoCapture(self.url)
                    if self._cap:
                        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        self._cap.set(cv2.CAP_PROP_FPS, self.target_fps)
                    time.sleep(0.6)
                    continue

                ret, frame = self._cap.read()
                if ret and frame is not None:
                    # keep frames smaller to reduce CPU pressure on low-power hardware
                    h, w = frame.shape[:2]
                    if w > self.max_width:
                        scale = self.max_width / float(w)
                        new_h = max(1, int(h * scale))
                        frame = cv2.resize(frame, (self.max_width, new_h), interpolation=cv2.INTER_AREA)
                    with self.lock:
                        self.frame = frame
                    self.last_success = time.monotonic()
                    self.failed = False
                    time.sleep(1.0 / max(1, self.target_fps))
                else:
                    self.failed = True
                    time.sleep(0.5)

            except Exception as e:
                print(f"Erro na captura da câmera {self.url}: {e}")
                self.failed = True
                time.sleep(1.0)

        if self._cap:
            self._cap.release()

    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def needs_reconnect(self, timeout_seconds=30):
        if not self.running:
            return False
        return (time.monotonic() - self.last_success) > timeout_seconds or self.failed

    def reconnect(self):
        try:
            if self._cap:
                self._cap.release()
        except Exception:
            pass
        self._cap = None
        self.frame = None
        self.last_success = time.monotonic()
        self.failed = True

    def stop(self):
        self.running = False
        try:
            if self._cap:
                self._cap.release()
        except Exception:
            pass


class EditDialog(QDialog):
    def __init__(self, urls, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar links das câmeras")
        self.edits = []
        form = QFormLayout()

        # Show at least 4 rows to allow adding cameras
        rows = max(len(urls), 4)
        for i in range(rows):
            text = urls[i] if i < len(urls) else ""
            le = QLineEdit(text)
            self.edits.append(le)
            form.addRow(f"Câmera {i+1}", le)

        btn_save = QPushButton("Salvar")
        btn_save.clicked.connect(self.accept)
        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(btn_save)
        self.setLayout(layout)

    def values(self):
        # return non-empty values, preserving order
        return [e.text().strip() for e in self.edits]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Monitor de Câmeras de Segurança")
        self.cameras = []
        self.labels = []
        self.economy_mode = False

        ensure_env()
        urls = load_config()

        central = QWidget()
        central.setStyleSheet("background-color: #121212; color: white;")
        grid = QGridLayout()
        central.setLayout(grid)
        self.grid = grid

        if not urls:
            lbl = QLabel("Nenhuma câmera configurada. Clique em 'Editar links'.")
            lbl.setAlignment(Qt.AlignCenter)
            grid.addWidget(lbl, 0, 0)
            self.labels.append(lbl)
        else:
            for i in range(len(urls)):
                lbl = QLabel()
                lbl.setAlignment(Qt.AlignCenter)
                lbl.setStyleSheet("background: black;")
                lbl.setScaledContents(False)
                self.labels.append(lbl)
                grid.addWidget(lbl, i // 2, i % 2)

        btn_edit = QPushButton("Editar links")
        btn_edit.clicked.connect(self.edit_links)
        btn_stop = QPushButton("Parar")
        btn_stop.clicked.connect(self.stop_and_exit_fullscreen)
        self.btn_mode = QPushButton("Ativar economia")
        self.btn_mode.clicked.connect(self.toggle_economy_mode)
        self.refresh_mode_button_label()
        button_row = (max(1, len(urls)) + 1) // 2
        grid.addWidget(btn_edit, button_row, 0)
        grid.addWidget(btn_stop, button_row, 1)
        grid.addWidget(self.btn_mode, button_row + 1, 0, 1, 2)

        self.setCentralWidget(central)

        # start cameras
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frames)
        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self.check_camera_health)
        self.health_timer.start(30000)
        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.timeout.connect(self.reconnect_cameras)
        self.reconnect_timer.start(5 * 60 * 1000)
        if urls:
            self.start_cameras(urls)
        else:
            # still start timer but with low rate so UI remains responsive
            self.timer.start(250)

    def start_cameras(self, urls):
        self.stop_cameras()
        self.cameras = []
        fps = 3 if self.economy_mode else 5
        max_width = 480 if self.economy_mode else 640
        for u in urls:
            t = CameraThread(u, target_fps=fps, max_width=max_width)
            t.start()
            self.cameras.append(t)
        # adjust update rate depending on number of cameras to avoid UI freeze
        n = len(self.cameras)
        if n <= 2:
            interval = 350 if self.economy_mode else 250
        elif n == 3:
            interval = 500 if self.economy_mode else 350
        else:
            interval = 700 if self.economy_mode else 500
        # restart timer with chosen interval
        if not self.timer.isActive():
            self.timer.start(interval)
        else:
            self.timer.setInterval(interval)

    def stop_cameras(self):
        for t in getattr(self, 'cameras', []):
            try:
                t.stop()
            except Exception:
                pass
        # clear list to release references
        self.cameras = []
        # stop UI updates to keep UI responsive
        try:
            if self.timer.isActive():
                self.timer.stop()
        except Exception:
            pass

    def reconnect_cameras(self):
        ensure_env()
        urls = load_config()
        if not urls:
            return
        # 5-minute fallback: refresh env and reconnect each stale camera
        for idx, url in enumerate(urls):
            if idx < len(self.cameras):
                if self.cameras[idx].needs_reconnect(25):
                    self.cameras[idx].reconnect()
            else:
                self.start_cameras(urls)
                break

    def check_camera_health(self):
        for idx, camera in enumerate(self.cameras):
            if camera.needs_reconnect(30):
                url = camera.url
                camera.stop()
                new_camera = CameraThread(url)
                new_camera.start()
                self.cameras[idx] = new_camera

    def update_frames(self):
        for i, t in enumerate(self.cameras):
            frame = t.get_frame() if t else None
            if i >= len(self.labels):
                continue
            label = self.labels[i]
            if frame is None:
                label.setText("Offline")
                label.setStyleSheet("background: black; color: red; font-size: 18px; font-weight: bold;")
                continue
            # convert BGR -> RGB
            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = img.shape
            bytes_per_line = ch * w
            qimg = QImage(img.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pix = QPixmap.fromImage(qimg)
            # scale to label size while keeping aspect ratio
            lbl_size = label.size()
            if not lbl_size.isEmpty():
                pix = pix.scaled(lbl_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setStyleSheet("background: black; color: white;")
            label.setText("")
            label.setPixmap(pix)

    def edit_links(self):
        urls = load_config()
        dlg = EditDialog(urls, self)
        if dlg.exec():
            vals = dlg.values()
            # write to .env only non-empty values in order
            try:
                with open('.env', 'w', encoding='utf-8') as f:
                    idx = 1
                    for v in vals:
                        v = v.strip()
                        if v:
                            f.write(f"CAM{idx}={v}\n")
                            idx += 1
            except Exception as e:
                QMessageBox.warning(self, "Erro", f"Não foi possível salvar .env: {e}")
                return

            # reload env and rebuild/start cameras
            load_dotenv(override=True)
            new_urls = load_config()
            # remove empty labels and rebuild if count changed
            if len(new_urls) != len([l for l in self.labels if isinstance(l, QLabel)]):
                self.rebuild_ui(new_urls)
            else:
                self.start_cameras(new_urls)

    def rebuild_ui(self, urls):
        self.stop_cameras()
        # clear layout widgets
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        self.labels = []
        if not urls:
            lbl = QLabel("Nenhuma câmera configurada. Clique em 'Editar links'.")
            lbl.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(lbl, 0, 0)
            self.labels.append(lbl)
            button_row = 1
        else:
            for i in range(len(urls)):
                lbl = QLabel()
                lbl.setAlignment(Qt.AlignCenter)
                lbl.setStyleSheet("background: black;")
                lbl.setScaledContents(False)
                self.labels.append(lbl)
                self.grid.addWidget(lbl, i // 2, i % 2)
            button_row = (len(urls) + 1) // 2

        btn_edit = QPushButton("Editar links")
        btn_edit.clicked.connect(self.edit_links)
        btn_stop = QPushButton("Parar")
        btn_stop.clicked.connect(self.stop_and_exit_fullscreen)
        self.btn_mode = QPushButton("Ativar economia")
        self.btn_mode.clicked.connect(self.toggle_economy_mode)
        self.refresh_mode_button_label()
        self.grid.addWidget(btn_edit, button_row, 0)
        self.grid.addWidget(btn_stop, button_row, 1)
        self.grid.addWidget(self.btn_mode, button_row + 1, 0, 1, 2)

        if urls:
            self.start_cameras(urls)

    def refresh_mode_button_label(self):
        if hasattr(self, 'btn_mode'):
            self.btn_mode.setText("Desativar economia" if self.economy_mode else "Ativar economia") 

    def toggle_economy_mode(self):
        self.economy_mode = not self.economy_mode
        self.refresh_mode_button_label()
        urls = load_config()
        if urls:
            self.start_cameras(urls)

    def stop_and_exit_fullscreen(self):
        self.stop_cameras()
        if self.isFullScreen():
            self.showNormal()

    def keyPressEvent(self, event):
        try:
            if event.key() == Qt.Key_Escape and self.isFullScreen():
                self.showNormal()
                return
        except Exception:
            pass
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.stop_cameras()
        super().closeEvent(event)


def main():
    app = QApplication([])
    w = MainWindow()
    # Use maximized so window fills one monitor
    w.showMaximized()
    app.exec()


if __name__ == '__main__':
    main()
