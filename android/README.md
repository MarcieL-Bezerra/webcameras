# WebCameras para Android

Esta versão nativa Android mantém a grade de quatro câmeras RTSP do `main.py` e adiciona gravação da tela em arquivos MP4/H.264.

## Dependências

- JDK 17 ou superior.
- Android SDK com a plataforma 36 e Android Build Tools.
- Gradle Wrapper (incluído no projeto).
- Dependências Android baixadas pelo Gradle: AndroidX Core, AndroidX Activity e AndroidX Media3 (ExoPlayer com suporte RTSP).

No Android Studio, abra esta pasta e aguarde a sincronização do Gradle. Para compilar pela linha de comando no Windows, com `JAVA_HOME` e `ANDROID_HOME` configurados:

```powershell
.\gradlew.bat assembleDebug
```

O APK de depuração, assinado para instalação local, será gerado em:

```text
app\build\outputs\apk\debug\app-debug.apk
```

O limite padrão de armazenamento é 5 GB. Para compilar com outro limite inteiro positivo:

```powershell
.\gradlew.bat assembleDebug -PrecordingsMaxGb=2
```

## Uso

1. Instale e abra o APK. O app precisa de acesso à internet para receber as câmeras.
2. Toque em **Editar** e informe até quatro URLs `rtsp://`.
3. Toque em **Iniciar gravação**. No Android 13 ou superior, permita notificações para acompanhar e parar a gravação pela notificação. Em seguida, autorize a captura de tela na solicitação do sistema Android. Se as notificações forem negadas, a gravação ainda pode ser iniciada e parada pelo botão do app.
4. Os MP4 ficam em `Android/data/com.marcielbezerra.webcameras/files/Movies/gravacoes`. Segmentos são finalizados a cada cinco minutos e os mais antigos são removidos quando o total passa do limite configurado.

As gravações ficam no armazenamento privado do app, então não é necessária permissão de armazenamento. O Android solicita a autorização de captura de tela quando a gravação começa; o app não solicita acesso à câmera nem ao microfone.

Por padrão, o app tenta o substream RTSP `/h264/ch1/sub/av_stream`, que oferece imagem menor para reduzir a carga de decodificação e rede nas quatro câmeras. Use o botão **Substream/Principal** para alternar entre essa imagem e o endereço RTSP informado. A codificação do substream depende da configuração de cada câmera; se o aparelho não decodificar HEVC/H.265, configure H.264 nas opções de vídeo da câmera. As URLs configuradas ficam no armazenamento privado do app; o arquivo `.env` do desktop não é incluído no APK.

Os vídeos são gravados em H.264, 5 quadros por segundo, com bitrate de 400 kbit/s e resolução máxima de 1280 pixels no maior lado, para reduzir o tamanho mantendo compatibilidade com celulares. As URLs RTSP são guardadas localmente no armazenamento privado do aplicativo.
