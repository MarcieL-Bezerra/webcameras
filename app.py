import os
import cv2
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Carrega as câmeras do .env
CAMS = []
i = 1
while True:
    cam_url = os.getenv(f"CAM{i}")
    if not cam_url:
        break
    CAMS.append(cam_url.strip())
    i += 1

def gen_frames(camera_url: str):
    # Configura o OpenCV para abrir o stream RTSP
    # Usando CAP_FFMPEG para garantir compatibilidade leve
    cap = cv2.VideoCapture(camera_url, cv2.CAP_FFMPEG)
    
    # DICA DE DESEMPENHO: Ajusta os buffers internos do OpenCV para diminuir lag e CPU
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) 

    while True:
        success, frame = cap.read()
        if not success:
            break
        else:
            # Codifica o frame em JPEG (reduzindo qualidade se quiser economizar ainda mais banda/CPU)
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ret:
                continue
            frame_bytes = buffer.tobytes()
            
            # Formato padrão para streaming de vídeo MJPEG via HTTP
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                   
    cap.release()

@app.get("/video/{cam_id}")
def video_feed(cam_id: int):
    """Rota que retorna o vídeo da câmera selecionada pelo ID (Ex: localhost:8000/video/0)"""
    if cam_id < 0 or cam_id >= len(CAMS):
        return Response(status_code=404, content="Câmera não encontrada")
    
    return StreamingResponse(gen_frames(CAMS[cam_id]), 
                             media_type='multipart/x-mixed-replace; boundary=frame')

@app.get("/")
def index():
    """Página HTML minimalista para exibir os vídeos no navegador"""
    # Cria dinamicamente as tags <img> com base nas câmeras disponíveis
    images_html = "".join([
        f'<div><h3>Câmera {i+1}</h3><img src="/video/{i}" width="640" height="480" /></div>' 
        for i in range(len(CAMS))
    ])
    
    html_content = f"""
    <html>
        <head><title>WebCameras</title></head>
        <body style="font-family: Arial, sans-serif; background: #222; color: #fff; text-align: center;">
            <h1>Monitoramento de Câmeras</h1>
            <div style="display: flex; flex-wrap: wrap; justify-content: center; gap: 20px;">
                {images_html}
            </div>
        </body>
    </html>
    """
    return Response(content=html_content, media_type="text/html")
