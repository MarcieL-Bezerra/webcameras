import logging
import math
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
from dotenv import dotenv_values, load_dotenv, set_key, unset_key
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from screen_recorder import ScreenRecorder, recordings_directory


APP_DIRECTORY = Path(__file__).resolve().parent
ENV_FILE = APP_DIRECTORY / ".env"
CAMERA_FPS = 5
ECONOMY_CAMERA_FPS = 3
CAMERA_WIDTH = 640
ECONOMY_CAMERA_WIDTH = 480
JPEG_QUALITY = 80
TILE_WIDTH = 640
TILE_HEIGHT = 360
logger = logging.getLogger(__name__)


def ensure_env():
    ENV_FILE.touch(exist_ok=True)
    load_dotenv(ENV_FILE, override=True)


def load_config():
    cameras = []
    index = 1
    while True:
        camera_url = os.getenv(f"CAM{index}")
        if camera_url is None:
            break
        camera_url = camera_url.strip()
        if camera_url:
            cameras.append(camera_url)
        index += 1
    return cameras


def save_config(cameras):
    existing_values = dotenv_values(ENV_FILE)
    for key in existing_values:
        if re.fullmatch(r"CAM\d+", key):
            unset_key(ENV_FILE, key)
    for index, camera_url in enumerate(cameras, start=1):
        set_key(ENV_FILE, f"CAM{index}", camera_url, quote_mode="always")

    for key in tuple(os.environ):
        if re.fullmatch(r"CAM\d+", key):
            os.environ.pop(key)
    load_dotenv(ENV_FILE, override=True)


class CameraThread:
    def __init__(self, url, target_fps=CAMERA_FPS, max_width=CAMERA_WIDTH):
        self.url = url
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._frame = None
        self._jpeg = None
        self._frame_number = 0
        self._last_success = 0.0
        self._started_at = time.monotonic()
        self.target_fps = target_fps
        self.max_width = max_width
        self._cap = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self._capture_frame()
            except cv2.error as error:
                logger.warning("Falha ao capturar uma câmera: %s", error)
                if self._cap is not None:
                    self._cap.release()
                    self._cap = None
                self._stop_event.wait(0.5)

        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _capture_frame(self):
        if self._cap is None:
            self._cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not self._cap.isOpened():
                self._cap.release()
                self._cap = None
                self._stop_event.wait(0.6)
                return
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        success, frame = self._cap.read()
        if not success or frame is None:
            self._cap.release()
            self._cap = None
            self._stop_event.wait(0.5)
            return

        with self._lock:
            max_width = self.max_width
            target_fps = self.target_fps
        height, width = frame.shape[:2]
        if width > max_width:
            scale = max_width / float(width)
            frame = cv2.resize(
                frame,
                (max_width, max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )

        encoded, jpeg = cv2.imencode(
            ".jpg",
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY],
        )
        if encoded:
            with self._lock:
                self._frame = frame
                self._jpeg = jpeg.tobytes()
                self._frame_number += 1
                self._last_success = time.monotonic()
        self._stop_event.wait(1 / max(1, target_fps))

    def get_snapshot(self):
        with self._lock:
            frame = self._frame.copy() if self._frame is not None else None
            return frame, self._last_success

    def get_jpeg(self):
        with self._lock:
            return self._frame_number, self._jpeg

    def set_performance(self, target_fps, max_width):
        with self._lock:
            self.target_fps = target_fps
            self.max_width = max_width

    def status(self):
        with self._lock:
            last_success = self._last_success
        age = time.monotonic() - last_success if last_success else None
        stale = age >= 30 if age is not None else time.monotonic() - self._started_at >= 30
        return {
            "online": not stale,
            "last_frame_seconds": round(age, 1) if age is not None else None,
        }

    def stop(self):
        self._stop_event.set()
        if self._cap is not None:
            self._cap.release()
        if self._thread.is_alive():
            self._thread.join(timeout=5)


class CameraConfiguration(BaseModel):
    cameras: list[str]


class EconomyConfiguration(BaseModel):
    enabled: bool


class CameraService:
    def __init__(self):
        self._lock = threading.Lock()
        self.cameras = []
        self.economy_mode = False
        self.recorder = None
        self.recording_error = None
        self._recording_stop = threading.Event()
        self._recording_thread = None
        self._health_stop = threading.Event()
        self._health_thread = None

    def start(self):
        ensure_env()
        self.set_cameras(load_config())
        self._health_thread = threading.Thread(
            target=self._monitor_cameras,
            daemon=True,
        )
        self._health_thread.start()
        try:
            self.recorder = ScreenRecorder(recordings_directory())
        except (OSError, RuntimeError, ValueError) as error:
            self.recording_error = str(error)
            logger.exception("Não foi possível iniciar a gravação.")
            return

        self._recording_thread = threading.Thread(
            target=self._record_dashboard,
            daemon=True,
        )
        self._recording_thread.start()

    def stop(self):
        with self._lock:
            cameras = self.cameras
            self.cameras = []
        for camera in cameras:
            camera.stop()

        self._health_stop.set()
        if self._health_thread and self._health_thread.is_alive():
            self._health_thread.join(timeout=5)
        self._recording_stop.set()
        if self._recording_thread and self._recording_thread.is_alive():
            self._recording_thread.join(timeout=5)
        if self.recorder:
            try:
                self.recorder.stop()
            except RuntimeError as error:
                self.recording_error = str(error)
                logger.exception("Não foi possível finalizar a gravação.")
            self.recorder = None

    def set_cameras(self, urls):
        with self._lock:
            old_cameras = self.cameras
            self.cameras = []
            target_fps = ECONOMY_CAMERA_FPS if self.economy_mode else CAMERA_FPS
            max_width = ECONOMY_CAMERA_WIDTH if self.economy_mode else CAMERA_WIDTH
            self.cameras = [
                CameraThread(url, target_fps, max_width)
                for url in urls
            ]
            cameras = self.cameras
        for camera in old_cameras:
            camera.stop()
        return cameras

    def set_economy_mode(self, enabled):
        with self._lock:
            self.economy_mode = enabled
            target_fps = ECONOMY_CAMERA_FPS if enabled else CAMERA_FPS
            max_width = ECONOMY_CAMERA_WIDTH if enabled else CAMERA_WIDTH
            cameras = list(self.cameras)
        for camera in cameras:
            camera.set_performance(target_fps, max_width)

    def _monitor_cameras(self):
        while not self._health_stop.wait(30):
            with self._lock:
                cameras = list(self.cameras)
                target_fps = ECONOMY_CAMERA_FPS if self.economy_mode else CAMERA_FPS
                max_width = ECONOMY_CAMERA_WIDTH if self.economy_mode else CAMERA_WIDTH
            for index, camera in enumerate(cameras):
                if camera.status()["online"]:
                    continue
                replacement = CameraThread(camera.url, target_fps, max_width)
                with self._lock:
                    if index < len(self.cameras) and self.cameras[index] is camera:
                        self.cameras[index] = replacement
                        replaced = True
                    else:
                        replaced = False
                camera.stop()
                if not replaced:
                    replacement.stop()

    def camera_at(self, camera_id):
        with self._lock:
            if camera_id < 0 or camera_id >= len(self.cameras):
                return None
            return self.cameras[camera_id]

    def status(self):
        with self._lock:
            cameras = list(self.cameras)
            economy_mode = self.economy_mode
        return {
            "cameras": [camera.status() for camera in cameras],
            "economy_mode": economy_mode,
            "recording": self.recorder is not None and self.recording_error is None,
            "recording_directory": str(recordings_directory()),
            "recording_error": self.recording_error,
        }

    def _record_dashboard(self):
        try:
            while not self._recording_stop.wait(1):
                error = self.recorder.pop_error()
                if error:
                    self.recording_error = error
                    logger.error("Erro na gravação: %s", error)
                    return

                image = self._compose_dashboard()
                encoded, png = cv2.imencode(".png", image)
                if not encoded:
                    self.recording_error = "Não foi possível preparar a imagem para gravação."
                    logger.error(self.recording_error)
                    return
                self.recorder.add_png_frame(png.tobytes())
        except (cv2.error, OSError, RuntimeError, ValueError) as error:
            self.recording_error = str(error)
            logger.exception("Falha ao atualizar a gravação.")

    def _compose_dashboard(self):
        with self._lock:
            cameras = list(self.cameras)

        columns = 2 if len(cameras) > 1 else 1
        rows = max(1, math.ceil(len(cameras) / columns))
        canvas = np.zeros(
            (TILE_HEIGHT * rows, TILE_WIDTH * columns, 3),
            dtype=np.uint8,
        )
        canvas[:] = (18, 18, 18)

        if not cameras:
            cv2.putText(
                canvas,
                "Nenhuma camera configurada",
                (32, TILE_HEIGHT // 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            return canvas

        for index, camera in enumerate(cameras):
            frame, _ = camera.get_snapshot()
            x = (index % columns) * TILE_WIDTH
            y = (index // columns) * TILE_HEIGHT
            if frame is None:
                cv2.putText(
                    canvas,
                    f"Camera {index + 1} - Offline",
                    (x + 24, y + TILE_HEIGHT // 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (80, 80, 255),
                    2,
                    cv2.LINE_AA,
                )
                continue

            height, width = frame.shape[:2]
            scale = min(TILE_WIDTH / width, TILE_HEIGHT / height)
            resized = cv2.resize(
                frame,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
            frame_x = x + (TILE_WIDTH - resized.shape[1]) // 2
            frame_y = y + (TILE_HEIGHT - resized.shape[0]) // 2
            canvas[
                frame_y : frame_y + resized.shape[0],
                frame_x : frame_x + resized.shape[1],
            ] = resized
            cv2.putText(
                canvas,
                f"Camera {index + 1}",
                (x + 16, y + 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
        return canvas


service = CameraService()


@asynccontextmanager
async def lifespan(_app):
    service.start()
    try:
        yield
    finally:
        service.stop()


app = FastAPI(title="WebCameras", lifespan=lifespan)


def stream_camera(camera_id):
    offline_image = np.zeros((TILE_HEIGHT, TILE_WIDTH, 3), dtype=np.uint8)
    cv2.putText(
        offline_image,
        "Offline",
        (24, TILE_HEIGHT // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (80, 80, 255),
        2,
        cv2.LINE_AA,
    )
    offline_encoded, offline_image = cv2.imencode(".jpg", offline_image)
    offline_frame = offline_image.tobytes() if offline_encoded else b""
    last_frame_number = -1
    last_offline_sent = 0.0
    current_camera = None
    while True:
        camera = service.camera_at(camera_id)
        if camera is None:
            return
        if camera is not current_camera:
            current_camera = camera
            last_frame_number = -1
        frame_number, jpeg = camera.get_jpeg()
        if jpeg is not None and frame_number != last_frame_number:
            last_frame_number = frame_number
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + jpeg
                + b"\r\n"
            )
        elif jpeg is None and time.monotonic() - last_offline_sent >= 1:
            last_offline_sent = time.monotonic()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + offline_frame
                + b"\r\n"
            )
        time.sleep(0.05)


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML


@app.get("/video/{cam_id}")
def video_feed(cam_id: int):
    camera = service.camera_at(cam_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Câmera não encontrada.")
    return StreamingResponse(
        stream_camera(cam_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/status")
def get_status():
    return service.status()


@app.get("/api/cameras")
def get_cameras():
    return {"cameras": load_config()}


@app.put("/api/cameras")
def update_cameras(configuration: CameraConfiguration):
    cameras = [camera.strip() for camera in configuration.cameras if camera.strip()]
    if any(
        len(camera) > 2048 or any(ord(character) < 32 for character in camera)
        for camera in cameras
    ):
        raise HTTPException(
            status_code=422,
            detail="Cada endereço deve ter até 2048 caracteres e não pode conter controles.",
        )
    save_config(cameras)
    service.set_cameras(cameras)
    return {"cameras": cameras}


@app.put("/api/economy")
def update_economy(configuration: EconomyConfiguration):
    service.set_economy_mode(configuration.enabled)
    return {"economy_mode": configuration.enabled}


INDEX_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WebCameras</title>
  <style>
    :root { color-scheme: dark; font-family: Arial, sans-serif; background: #111827; color: #f3f4f6; }
    * { box-sizing: border-box; }
    body { margin: 0; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 1rem 2rem; background: #1f2937; }
    h1 { margin: 0; font-size: 1.35rem; }
    main { padding: 1.25rem 2rem; }
    .controls { display: flex; flex-wrap: wrap; align-items: center; gap: .75rem; margin-bottom: 1rem; }
    button { border: 0; border-radius: .4rem; padding: .65rem 1rem; background: #2563eb; color: white; cursor: pointer; font-size: .95rem; }
    button:hover { background: #1d4ed8; }
    .status { color: #d1d5db; }
    .error { color: #fca5a5; min-height: 1.25rem; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 480px), 1fr)); gap: 1rem; }
    .camera { overflow: hidden; border: 1px solid #374151; border-radius: .5rem; background: #000; }
    .camera h2 { margin: 0; padding: .65rem .85rem; background: #1f2937; font-size: 1rem; }
    .camera img { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: contain; }
    .empty { color: #9ca3af; padding: 2rem; text-align: center; }
    dialog { width: min(42rem, calc(100% - 2rem)); border: 1px solid #4b5563; border-radius: .6rem; background: #1f2937; color: #f3f4f6; }
    dialog::backdrop { background: #000a; }
    textarea { width: 100%; min-height: 12rem; margin: .75rem 0; padding: .75rem; border: 1px solid #4b5563; border-radius: .35rem; background: #111827; color: #f3f4f6; font: .9rem monospace; }
    .dialog-actions { display: flex; justify-content: flex-end; gap: .5rem; }
    .secondary { background: #4b5563; }
    @media (max-width: 600px) { header, main { padding: 1rem; } }
  </style>
</head>
<body>
  <header><h1>Monitoramento de Câmeras</h1><span id="recording" class="status">Verificando gravação...</span></header>
  <main>
    <div class="controls">
      <button id="edit">Editar links</button>
      <button id="economy">Ativar economia</button>
      <span id="summary" class="status"></span>
    </div>
    <div id="error" class="error" role="status"></div>
    <section id="cameras" class="grid"></section>
  </main>
  <dialog id="editor">
    <form id="camera-form">
      <h2>Links das câmeras</h2>
      <p>Informe um endereço por linha. As alterações também serão salvas no arquivo .env.</p>
      <textarea id="camera-links" aria-label="Endereços das câmeras" spellcheck="false"></textarea>
      <div class="dialog-actions">
        <button type="button" class="secondary" id="cancel">Cancelar</button>
        <button type="submit">Salvar</button>
      </div>
    </form>
  </dialog>
  <script>
    const camerasElement = document.getElementById("cameras");
    const errorElement = document.getElementById("error");
    const editor = document.getElementById("editor");
    let displayedCount = -1;

    async function request(url, options = {}) {
      const response = await fetch(url, {
        ...options,
        headers: { "Content-Type": "application/json", ...options.headers }
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || `Falha HTTP ${response.status}`);
      return body;
    }

    function showError(message) {
      errorElement.textContent = message || "";
    }

    async function refreshStatus() {
      const status = await request("/api/status");
      if (displayedCount !== status.cameras.length) {
        displayedCount = status.cameras.length;
        camerasElement.replaceChildren();
        if (!displayedCount) {
          const empty = document.createElement("p");
          empty.className = "empty";
          empty.textContent = "Nenhuma câmera configurada. Clique em “Editar links”.";
          camerasElement.append(empty);
        }
        status.cameras.forEach((camera, index) => {
          const card = document.createElement("article");
          card.className = "camera";
          const title = document.createElement("h2");
          title.textContent = `Câmera ${index + 1}`;
          const image = document.createElement("img");
          image.src = `/video/${index}`;
          image.alt = `Transmissão da câmera ${index + 1}`;
          card.append(title, image);
          camerasElement.append(card);
        });
      }

      const online = status.cameras.filter(camera => camera.online).length;
      document.getElementById("summary").textContent =
        `${online}/${status.cameras.length} câmera(s) online`;
      const economyButton = document.getElementById("economy");
      economyButton.textContent = status.economy_mode ? "Desativar economia" : "Ativar economia";
      const recording = document.getElementById("recording");
      recording.textContent = status.recording
        ? `Gravando em ${status.recording_directory}`
        : status.recording_error
          ? `Erro na gravação: ${status.recording_error}`
          : "Gravação indisponível";
      recording.style.color = status.recording ? "#86efac" : "#fca5a5";
    }

    document.getElementById("edit").addEventListener("click", async () => {
      try {
        const result = await request("/api/cameras");
        document.getElementById("camera-links").value = result.cameras.join("\\n");
        editor.showModal();
        showError("");
      } catch (error) {
        showError(error.message);
      }
    });

    document.getElementById("cancel").addEventListener("click", () => editor.close());
    document.getElementById("camera-form").addEventListener("submit", async event => {
      event.preventDefault();
      const cameras = document.getElementById("camera-links").value
        .split(/\\r?\\n/).map(camera => camera.trim()).filter(Boolean);
      try {
        await request("/api/cameras", { method: "PUT", body: JSON.stringify({ cameras }) });
        editor.close();
        displayedCount = -1;
        showError("");
        await refreshStatus();
      } catch (error) {
        showError(error.message);
      }
    });

    document.getElementById("economy").addEventListener("click", async () => {
      try {
        const status = await request("/api/status");
        await request("/api/economy", {
          method: "PUT",
          body: JSON.stringify({ enabled: !status.economy_mode })
        });
        await refreshStatus();
        showError("");
      } catch (error) {
        showError(error.message);
      }
    });

    async function pollStatus() {
      try {
        await refreshStatus();
        showError("");
      } catch (error) {
        showError(error.message);
      }
    }
    pollStatus();
    setInterval(pollStatus, 5000);
  </script>
</body>
</html>
"""
