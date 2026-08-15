# 🎥 WebCameras Caseiro

Uma aplicação Python minimalista e eficiente para visualizar até 4 streams de vídeo RTSP simultaneamente em tela cheia.

---

## ✨ Funcionalidades

* 📺 **Visualização em Grade**: Exibe até 4 câmeras simultaneamente.
* 🖥️ **Tela Cheia Nativa**: Abre automaticamente em modo fullscreen para monitoramento.
* ⚙️ **Configuração Dinâmica**: Altere as URLs RTSP em tempo de execução através do botão "Editar links".
* 💼 **Portabilidade**: Suporte para geração de executável `.exe` independente.

---

## 🛠️ Pré-requisitos

* **Python 3.8** ou superior instalado.
    
* Libs python inclusas no requirements.txt:
    * PySide6
    * opencv-python
    * python-dotenv

* Opcional (.exe):
    * PyInstaller


---

## 🚀 Instalação e Configuração

Siga os passos abaixo para configurar o ambiente localmente:

### 1. Clonar e Configurar o Ambiente Virtual
```bash
# Clone o repositório (substitua pela sua URL)
git clone https://github.com/MarcieL-Bezerra/webcameras.git
cd webcameras

# Crie o ambiente virtual
python -m venv .venv

# Ative o ambiente virtual
# No Windows:
.\\.venv\\Scripts\\activate
# No Linux/Mac:
source .venv/bin/activate

# Instale as dependências
pip install -r requirements.txt
```

### 2. Configurar as Câmeras
Crie o arquivo de configuração `.env` a partir do modelo de exemplo:

```
.env

CAM1=rtsp://usuario:senha@ipdacamera:554/onvif2
CAM2=rtsp://usuario:senha@ipdacamera:554/onvif2
CAM3=rtsp://usuario:senha@ipdacamera:554/onvif2
CAM4=rtsp://usuario:senha@ipdacamera:554/onvif2

```
* Observação geralmente as informações de usuarios e senhas bem como IP são localizadas no app das câmeras.


Abra o arquivo `.env` gerado e insira as suas URLs RTSP nas variáveis `CAM1`, `CAM2`, `CAM3` e `CAM4`.

---

## 💻 Como Executar

Com o ambiente ativo e configurado, inicie a aplicação com o comando:

```bash
python main.py
```

### 💡 Dicas de Uso
* Clique no botão **"Editar links"** na interface para atualizar as URLs das câmeras sem precisar reiniciar o app.

---

## 📦 Gerando um Executável (.exe)

Caso queira compilar a aplicação em um arquivo único executável para Windows, utilize o PyInstaller:

```bash
pip install PyInstaller

python -m PyInstaller --onefile --windowed main.py

```
O arquivo final estará disponível dentro da pasta `dist/`.

## 📄 Licença e Créditos

Este projeto é open-source. Você é livre para usar, modificar e distribuir o código, desde que inclua os créditos originais linkando para este repositório:

📦 **Projeto Original:** [WebCameras Caseiro](https://github.com/MarcieL-Bezerra/webcameras)  
👤 **Autor:** [Marciel Bezerra](https://github.com/MarcieL-Bezerra)