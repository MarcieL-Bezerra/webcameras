import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from math import isfinite

import cv2
import imageio_ffmpeg
import numpy as np


DEFAULT_MAX_STORAGE_GB = 5
SEGMENT_SECONDS = 5 * 60
CAPTURE_FPS = 1
MAX_FRAME_WIDTH = 1280
BYTES_PER_GB = 1024**3


def recordings_directory():
    app_directory = (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__))
    )
    return os.path.join(app_directory, "gravacoes")


def get_storage_limit_bytes():
    value = os.getenv("RECORDINGS_MAX_GB", str(DEFAULT_MAX_STORAGE_GB))
    try:
        gigabytes = float(value)
    except ValueError as error:
        raise ValueError("RECORDINGS_MAX_GB precisa ser um número maior que zero.") from error

    if not isfinite(gigabytes) or gigabytes <= 0:
        raise ValueError("RECORDINGS_MAX_GB precisa ser um número maior que zero.")
    return int(gigabytes * BYTES_PER_GB)


class ScreenRecorder:
    def __init__(self, directory):
        self.directory = directory
        self.max_storage_bytes = get_storage_limit_bytes()
        os.makedirs(self.directory, exist_ok=True)
        self._prune_recordings()

        self._frames = queue.Queue(maxsize=1)
        self._errors = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def add_png_frame(self, image_data):
        if self._stop_event.is_set():
            return

        frame = cv2.imdecode(
            np.frombuffer(image_data, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        if frame is None:
            self._errors.put("Não foi possível ler a captura da tela.")
            self._stop_event.set()
            return

        height, width = frame.shape[:2]
        if width > MAX_FRAME_WIDTH:
            scale = MAX_FRAME_WIDTH / width
            frame = cv2.resize(
                frame,
                (MAX_FRAME_WIDTH, max(2, int(height * scale) // 2 * 2)),
                interpolation=cv2.INTER_AREA,
            )

        try:
            self._frames.put_nowait((frame, time.monotonic()))
        except queue.Full:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frames.put_nowait((frame, time.monotonic()))
            except queue.Full:
                pass

    def pop_error(self):
        try:
            return self._errors.get_nowait()
        except queue.Empty:
            return None

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=60)
        if self._thread.is_alive():
            raise RuntimeError("A gravação não foi finalizada dentro do tempo esperado.")

    def _run(self):
        process = None
        temporary_path = None
        final_path = None
        segment_started = None
        frame_size = None
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            while not self._stop_event.is_set() or not self._frames.empty():
                try:
                    frame, captured_at = self._frames.get(timeout=0.2)
                except queue.Empty:
                    continue

                height, width = frame.shape[:2]
                current_size = (width - width % 2, height - height % 2)
                if current_size != (width, height):
                    frame = cv2.resize(frame, current_size, interpolation=cv2.INTER_AREA)

                if process and (
                    captured_at - segment_started >= SEGMENT_SECONDS
                    or current_size != frame_size
                ):
                    self._finish_segment(process, temporary_path, final_path)
                    process = None

                if process is None:
                    process, temporary_path, final_path = self._start_segment(
                        ffmpeg,
                        current_size,
                    )
                    segment_started = captured_at
                    frame_size = current_size

                if process.poll() is not None:
                    raise RuntimeError("O codificador de vídeo foi encerrado inesperadamente.")
                try:
                    process.stdin.write(frame.tobytes())
                except (BrokenPipeError, OSError) as error:
                    raise RuntimeError("Não foi possível gravar os frames do vídeo.") from error

            if process:
                self._finish_segment(process, temporary_path, final_path)
        except Exception as error:
            self._errors.put(str(error))
            self._stop_event.set()
            if process:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
            if temporary_path and os.path.exists(temporary_path):
                os.remove(temporary_path)

    def _start_segment(self, ffmpeg, frame_size):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        final_path = os.path.join(self.directory, f"gravacao_{timestamp}.mp4")
        temporary_path = final_path + ".part"
        width, height = frame_size
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "bgr24",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            str(CAPTURE_FPS),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-f",
            "mp4",
            temporary_path,
        ]
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            raise RuntimeError(f"Não foi possível iniciar o codificador de vídeo: {error}") from error
        return process, temporary_path, final_path

    def _finish_segment(self, process, temporary_path, final_path):
        process.stdin.close()
        _, stderr = process.communicate(timeout=30)
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(message or "Falha ao finalizar o arquivo de vídeo.")

        if os.path.getsize(temporary_path) == 0:
            os.remove(temporary_path)
            return

        os.replace(temporary_path, final_path)
        self._prune_recordings()

    def _prune_recordings(self):
        recordings = []
        total_bytes = 0
        for entry in os.scandir(self.directory):
            if entry.is_file() and entry.name.lower().endswith(".mp4"):
                size = entry.stat().st_size
                recordings.append((entry.stat().st_mtime, entry.path, size))
                total_bytes += size

        for _, path, size in sorted(recordings):
            if total_bytes <= self.max_storage_bytes:
                break
            os.remove(path)
            total_bytes -= size
