import os
import sys

import cv2
from dotenv import load_dotenv, set_key
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from main import CameraThread, ensure_env, resource_path


def load_first_camera():
    ensure_env()
    url = os.getenv("CAM1", "").strip()
    return url


class EditCameraDialog(QDialog):
    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar link da câmera")
        self.url_edit = QLineEdit(url)

        form = QFormLayout()
        form.addRow("Câmera 1", self.url_edit)

        save_button = QPushButton("Salvar")
        save_button.clicked.connect(self.accept)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(save_button)
        self.setLayout(layout)

    def value(self):
        return self.url_edit.text().strip()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Monitor de Câmeras de Segurança Lite")
        self.setWindowIcon(QIcon(resource_path("pycamview.ico")))
        self.camera = None
        self.economy_mode = False

        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background: black; color: white;")
        self.video_label.setMinimumSize(320, 180)

        self.edit_button = QPushButton("Editar link")
        self.edit_button.clicked.connect(self.edit_link)
        self.close_button = QPushButton("Fechar")
        self.close_button.clicked.connect(self.close_application)
        self.mode_button = QPushButton()
        self.mode_button.clicked.connect(self.toggle_economy_mode)
        self.refresh_mode_button_label()

        controls = QVBoxLayout()
        controls.addWidget(self.edit_button)
        controls.addWidget(self.close_button)
        controls.addWidget(self.mode_button)

        layout = QVBoxLayout()
        layout.addWidget(self.video_label, 1)
        layout.addLayout(controls)

        central = QWidget()
        central.setStyleSheet("background-color: #121212; color: white;")
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(250)

        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self.check_camera_health)
        self.health_timer.start(30000)

        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.timeout.connect(self.reconnect_camera)
        self.reconnect_timer.start(5 * 60 * 1000)

        self.start_camera(load_first_camera())

    def start_camera(self, url):
        self.stop_camera()
        if not url:
            self.video_label.setPixmap(QPixmap())
            self.video_label.setText("Nenhuma câmera configurada. Clique em 'Editar link'.")
            return

        self.video_label.setText("Conectando...")
        fps = 3 if self.economy_mode else 5
        max_width = 480 if self.economy_mode else 640
        self.camera = CameraThread(url, target_fps=fps, max_width=max_width)
        self.camera.start()

    def stop_camera(self):
        if self.camera:
            self.camera.stop()
            self.camera = None

    def update_frame(self):
        if not self.camera:
            return

        frame = self.camera.get_frame()
        if frame is None:
            self.video_label.setText("Offline")
            return

        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = image.shape
        qimage = QImage(
            image.data,
            width,
            height,
            channels * width,
            QImage.Format_RGB888,
        )
        pixmap = QPixmap.fromImage(qimage)
        if not self.video_label.size().isEmpty():
            pixmap = pixmap.scaled(
                self.video_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        self.video_label.setText("")
        self.video_label.setPixmap(pixmap)

    def check_camera_health(self):
        if self.camera and self.camera.needs_reconnect(30):
            self.start_camera(load_first_camera())

    def reconnect_camera(self):
        url = load_first_camera()
        if not url:
            return
        if not self.camera or self.camera.url != url:
            self.start_camera(url)
        elif self.camera.needs_reconnect(25):
            self.camera.reconnect()

    def edit_link(self):
        dialog = EditCameraDialog(load_first_camera(), self)
        if not dialog.exec():
            return

        try:
            set_key(".env", "CAM1", dialog.value())
            load_dotenv(override=True)
        except Exception as error:
            QMessageBox.warning(
                self,
                "Erro",
                f"Não foi possível salvar .env: {error}",
            )
            return

        self.start_camera(load_first_camera())

    def refresh_mode_button_label(self):
        label = "Desativar economia" if self.economy_mode else "Ativar economia"
        self.mode_button.setText(label)

    def toggle_economy_mode(self):
        self.economy_mode = not self.economy_mode
        self.refresh_mode_button_label()
        self.start_camera(load_first_camera())

    def close_application(self):
        self.stop_camera()
        self.health_timer.stop()
        self.reconnect_timer.stop()
        self.close()
        QApplication.instance().quit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.stop_camera()
        super().closeEvent(event)


def main():
    app = QApplication([])
    window = MainWindow()
    window.showMaximized()
    app.exec()


if __name__ == "__main__":
    main()