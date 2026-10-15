# WebCameras

Aplicativo para monitorar câmeras IP por RTSP no computador ou em um celular Android. A versão desktop oferece dois modos: `main.py` exibe várias câmeras em uma grade e `mainlite.py` exibe uma câmera.

## Funcionalidades

- Visualização de até quatro streams RTSP na versão desktop principal.
- Versão Lite para visualizar uma câmera.
- Configuração dos endereços pelo aplicativo ou pelo arquivo `.env` no desktop.
- Gravação da imagem da janela em vídeos MP4/H.264 divididos em segmentos de cinco minutos.
- Remoção das gravações MP4 mais antigas quando o armazenamento ultrapassa o limite configurado, de 5 GB por padrão.
- Aplicativo Android nativo com quatro câmeras, alternância entre substream e stream principal e gravação da tela.

## Versão desktop

### Requisitos

- Python 3.8 ou superior.
- Pacotes listados em [`requirements.txt`](./requirements.txt): PySide6, PyQt5, OpenCV, python-dotenv e imageio-ffmpeg.

Cada interface usa seu próprio toolkit Qt: `main.py` usa PySide6 e `mainlite.py` usa PyQt5.

### Instalação

No Windows, abra o PowerShell na pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

No Linux ou macOS, ative o ambiente com `source .venv/bin/activate` depois de criá-lo com `python -m venv .venv`.

### Configurar as câmeras

Crie um arquivo `.env` na pasta do projeto e informe as URLs RTSP. Exemplo:

```dotenv
CAM1=rtsp://usuario:senha@192.168.1.10:554/onvif2
CAM2=rtsp://usuario:senha@192.168.1.11:554/onvif2
CAM3=rtsp://usuario:senha@192.168.1.12:554/onvif2
CAM4=rtsp://usuario:senha@192.168.1.13:554/onvif2
```

Preencha apenas as câmeras que deseja usar. Também é possível inserir e editar os links pelos botões do aplicativo. O `.env` contém credenciais e está excluído do Git; não o publique nem inclua suas URLs no código.

### Executar

```powershell
python main.py
```

Para abrir a versão Lite:

```powershell
python mainlite.py
```

### Gravações desktop

Ambas as versões gravam a janela do aplicativo na pasta `gravacoes`, ao lado dos arquivos do projeto. Os vídeos são MP4/H.264, capturados a um quadro por segundo e redimensionados para até 1280 pixels de largura. O segmento em andamento é finalizado ao fechar o aplicativo.

O limite padrão de armazenamento é 5 GB. Para alterá-lo, defina a variável de ambiente `RECORDINGS_MAX_GB` antes de executar o aplicativo, usando um número positivo, por exemplo:

```powershell
$env:RECORDINGS_MAX_GB = "2"
python main.py
```

Ao finalizar cada segmento, o aplicativo calcula o espaço ocupado pelos MP4 e remove os mais antigos até o total ficar abaixo do limite.

### Gerar executável Windows

Com as dependências instaladas, gere os executáveis:

```powershell
python -m PyInstaller main.spec
python -m PyInstaller mainlite.spec
```

Os executáveis são criados na pasta `dist`. Mantenha `pycamview.ico`, `main.spec` e `mainlite.spec` junto ao projeto durante a compilação.

## Aplicativo Android

A versão Android fica em [`android/`](./android/). É uma implementação nativa em Kotlin: não instala nem executa diretamente o código Python do desktop.

O APK de depuração já compilado está em:

```text
android\app\build\outputs\apk\debug\app-debug.apk
```

Instale o APK no celular e configure as URLs RTSP no botão **Editar**. O app inicia no substream de menor resolução; use **Substream/Principal** para alternar o perfil. As câmeras deste projeto transmitem H.265/HEVC; se o celular não suportar esse codec, habilite H.264 nas configurações de vídeo da câmera.

Para gravar, toque em **Iniciar gravação** e aceite a solicitação de captura de tela do Android. Os vídeos são MP4/H.264, em segmentos de cinco minutos. As gravações ficam no armazenamento privado do app, em `Android/data/com.marcielbezerra.webcameras/files/Movies/gravacoes`. O limite padrão é 5 GB; os arquivos mais antigos são removidos quando o total excede o limite.

Consulte [`android/README.md`](./android/README.md) para os pré-requisitos, comandos de compilação e opções do APK.

## Licença e créditos

Projeto original: [WebCameras Caseiro](https://github.com/MarcieL-Bezerra/webcameras), de [Marciel Bezerra](https://github.com/MarcieL-Bezerra).
