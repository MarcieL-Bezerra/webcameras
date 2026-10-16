package com.marcielbezerra.webcameras

import android.Manifest
import android.app.AlertDialog
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Color
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionParameters
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.mediacodec.MediaCodecSelector
import androidx.media3.exoplayer.rtsp.RtspMediaSource
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView

class MainActivity : ComponentActivity() {
    private val preferences by lazy {
        getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    }
    private val players = mutableListOf<ExoPlayer>()
    private val playerViews = mutableListOf<PlayerView>()
    private val cameraStatuses = mutableListOf<TextView>()
    private val cameraErrors = mutableListOf<String?>()
    private val cameraHasRenderedFrame = mutableListOf(false)
    private lateinit var recordingButton: Button
    private lateinit var economyButton: Button
    private var economyMode = true
    private var recording = false

    private val projectionLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode != RESULT_OK || result.data == null) {
                Toast.makeText(this, "A gravação precisa da autorização da tela.", Toast.LENGTH_LONG)
                    .show()
                return@registerForActivityResult
            }

            val serviceIntent = Intent(this, ScreenRecordingService::class.java).apply {
                putExtra(ScreenRecordingService.EXTRA_RESULT_CODE, result.resultCode)
                putExtra(ScreenRecordingService.EXTRA_RESULT_DATA, result.data)
            }
            try {
                ContextCompat.startForegroundService(this, serviceIntent)
            } catch (error: RuntimeException) {
                Toast.makeText(
                    this,
                    "Não foi possível iniciar a gravação: ${error.localizedMessage}",
                    Toast.LENGTH_LONG,
                ).show()
            }
        }

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (!granted) {
                Toast.makeText(
                    this,
                    "Sem notificações, use o botão do app para parar a gravação.",
                    Toast.LENGTH_LONG,
                ).show()
            }
            requestScreenCapture()
        }

    private val recordingStateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action != ScreenRecordingService.ACTION_STATE) return
            recording = intent.getBooleanExtra(ScreenRecordingService.EXTRA_ACTIVE, false)
            updateRecordingButton()
            intent.getStringExtra(ScreenRecordingService.EXTRA_ERROR)?.let { message ->
                Toast.makeText(this@MainActivity, message, Toast.LENGTH_LONG).show()
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.BLACK)
            ViewCompat.setOnApplyWindowInsetsListener(this) { view, insets ->
                val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
                insets
            }
        }

        val grid = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        repeat(2) { row ->
            val cameraRow = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    0,
                    1f,
                )
            }
            repeat(2) { column ->
                val cameraIndex = row * 2 + column
                cameraRow.addView(
                    createCameraView(cameraIndex),
                    LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f),
                )
            }
            grid.addView(cameraRow)
        }
        root.addView(
            grid,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                0,
                1f,
            ),
        )

        recordingButton = Button(this)
        val controls = LinearLayout(this).apply {
            gravity = Gravity.CENTER
            addControl(this, createButton("Editar", ::showCameraEditor))
            addControl(this, recordingButton.apply { setOnClickListener { toggleRecording() } })
            addControl(this, createButton("", ::toggleEconomyMode).also { economyButton = it })
            addControl(this, createButton("Fechar", ::closeApplication))
        }
        root.addView(
            controls,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ),
        )
        setContentView(root)

        recordingButton.text = "Iniciar gravação"
        updateEconomyButton()
        updateCameras()
    }

    override fun onStart() {
        super.onStart()
        ContextCompat.registerReceiver(
            this,
            recordingStateReceiver,
            IntentFilter(ScreenRecordingService.ACTION_STATE),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
    }

    override fun onStop() {
        unregisterReceiver(recordingStateReceiver)
        super.onStop()
    }

    override fun onResume() {
        super.onResume()
        players.forEach { it.playWhenReady = true }
    }

    override fun onPause() {
        players.forEach { it.playWhenReady = false }
        super.onPause()
    }

    override fun onDestroy() {
        releasePlayers()
        super.onDestroy()
    }

    private fun createCameraView(index: Int): View {
        val container = FrameLayout(this).apply {
            setBackgroundColor(Color.rgb(18, 18, 18))
            val margin = (1 * resources.displayMetrics.density).toInt()
            setPadding(margin, margin, margin, margin)
        }
        val playerView = PlayerView(this).apply {
            useController = false
            resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
            setShowBuffering(PlayerView.SHOW_BUFFERING_WHEN_PLAYING)
            setBackgroundColor(Color.BLACK)
        }
        val status = TextView(this).apply {
            text = "Câmera ${index + 1} não configurada"
            setTextColor(Color.WHITE)
            setBackgroundColor(0x99000000.toInt())
            setPadding(12, 6, 12, 6)
            gravity = Gravity.CENTER
            setOnClickListener { retryCamera(index) }
        }
        container.addView(
            playerView,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )
        container.addView(
            status,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM,
            ),
        )
        playerViews.add(playerView)
        cameraStatuses.add(status)
        cameraErrors.add(null)
        cameraHasRenderedFrame.add(false)
        return container
    }

    private fun createButton(label: String, action: () -> Unit): Button =
        Button(this).apply {
            text = label
            minWidth = 0
            textSize = 12f
            setPadding(2, 0, 2, 0)
            setOnClickListener { action() }
        }

    private fun addControl(layout: LinearLayout, button: Button) {
        layout.addView(button, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
    }

    private fun cameraUrls(): List<String> =
        (1..CAMERA_COUNT).map { index ->
            preferences.getString("CAM$index", "").orEmpty().trim()
        }

    private fun updateCameras() {
        releasePlayers()
        cameraErrors.fill(null)
        cameraHasRenderedFrame.indices.forEach { cameraHasRenderedFrame[it] = false }
        cameraUrls().forEachIndexed { index, url ->
            val status = cameraStatuses[index]
            val playerView = playerViews[index]
            if (url.isEmpty()) {
                status.text = "Câmera ${index + 1} não configurada"
                status.visibility = View.VISIBLE
                playerView.player = null
                return@forEachIndexed
            }

            val codecSelector = if (isAndroidEmulator()) {
                MediaCodecSelector.PREFER_SOFTWARE
            } else {
                MediaCodecSelector.DEFAULT
            }
            val renderersFactory = DefaultRenderersFactory(this)
                .setEnableDecoderFallback(true)
                .setMediaCodecSelector(codecSelector)
            val player = ExoPlayer.Builder(this, renderersFactory).build().apply {
                trackSelectionParameters = selectionParameters()
                addListener(object : Player.Listener {
                    override fun onPlaybackStateChanged(playbackState: Int) {
                        when (playbackState) {
                            Player.STATE_BUFFERING -> {
                                if (cameraErrors[index] == null && !cameraHasRenderedFrame[index]) {
                                    status.text = "Câmera ${index + 1}: conectando..."
                                    status.visibility = View.VISIBLE
                                } else if (cameraErrors[index] == null) {
                                    status.visibility = View.GONE
                                }
                            }
                            Player.STATE_READY -> {
                                cameraErrors[index] = null
                                status.visibility = View.GONE
                            }
                            Player.STATE_IDLE -> {
                                if (cameraErrors[index] == null && cameraHasRenderedFrame[index]) {
                                    status.visibility = View.GONE
                                    return
                                }
                                status.text = cameraErrors[index]
                                    ?: "Câmera ${index + 1}: aguardando stream"
                                status.visibility = View.VISIBLE
                            }
                        }
                    }

                    override fun onPlayerError(error: PlaybackException) {
                        cameraErrors[index] = playbackErrorMessage(index, error)
                        status.text = cameraErrors[index]
                        status.visibility = View.VISIBLE
                    }

                    override fun onRenderedFirstFrame() {
                        cameraHasRenderedFrame[index] = true
                        cameraErrors[index] = null
                        status.visibility = View.GONE
                    }
                })
                setMediaSource(createRtspSource(playbackUrl(url)))
                prepare()
                playWhenReady = true
            }
            players.add(player)
            playerView.player = player
        }
    }

    private fun selectionParameters(): TrackSelectionParameters {
        val builder = TrackSelectionParameters.Builder()
        if (economyMode) {
            builder.setMaxVideoSize(854, 480)
        }
        return builder.build()
    }

    private fun releasePlayers() {
        players.forEach(ExoPlayer::release)
        players.clear()
        playerViews.forEach { it.player = null }
    }

    private fun createRtspSource(url: String): RtspMediaSource =
        RtspMediaSource.Factory()
            .setForceUseRtpTcp(true)
            .setTimeoutMs(RTSP_TIMEOUT_MS)
            .createMediaSource(MediaItem.fromUri(Uri.parse(url)))

    private fun isAndroidEmulator(): Boolean =
        Build.FINGERPRINT.startsWith("google/sdk_gphone") ||
            Build.HARDWARE.contains("goldfish", ignoreCase = true) ||
            Build.HARDWARE.contains("ranchu", ignoreCase = true)

    private fun playbackUrl(url: String): String {
        if (!economyMode) return url
        return Uri.parse(url)
            .buildUpon()
            .encodedPath(SUBSTREAM_PATH)
            .build()
            .toString()
    }

    private fun playbackErrorMessage(index: Int, error: PlaybackException): String {
        if (error.errorCode == PlaybackException.ERROR_CODE_DECODING_FAILED) {
            val isHevc = generateSequence(error as Throwable?) { it.cause }
                .any { it.message?.contains("hevc", ignoreCase = true) == true }
            val codec = if (isHevc) "H.265/HEVC" else "o codec de vídeo"
            return "Câmera ${index + 1}: falha ao decodificar $codec. " +
                "Toque para tentar novamente; se persistir, habilite H.264 na câmera."
        }

        val reason = when (error.errorCode) {
            PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED,
            PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT ->
                "sem conexão RTSP; confira rede e credenciais"
            else -> error.errorCodeName
        }
        return "Câmera ${index + 1}: $reason. Toque para tentar novamente."
    }

    private fun retryCamera(index: Int) {
        val player = players.getOrNull(index) ?: return
        val configuredUrl = cameraUrls().getOrNull(index).orEmpty()
        if (configuredUrl.isEmpty()) return

        cameraErrors[index] = null
        cameraStatuses[index].text = "Câmera ${index + 1}: reconectando..."
        cameraStatuses[index].visibility = View.VISIBLE
        player.stop()
        player.setMediaSource(createRtspSource(playbackUrl(configuredUrl)))
        player.prepare()
        player.playWhenReady = true
    }

    private fun showCameraEditor() {
        val fields = (1..CAMERA_COUNT).map { index ->
            EditText(this).apply {
                hint = "RTSP da câmera $index"
                setSingleLine(true)
                inputType = android.text.InputType.TYPE_CLASS_TEXT or
                    android.text.InputType.TYPE_TEXT_VARIATION_URI
                setText(cameraUrls()[index - 1])
            }
        }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 8, 24, 0)
            fields.forEachIndexed { index, field ->
                addView(field)
                field.contentDescription = "URL RTSP da câmera ${index + 1}"
            }
        }
        val scroll = ScrollView(this).apply { addView(content) }
        AlertDialog.Builder(this)
            .setTitle("Links das câmeras")
            .setView(scroll)
            .setNegativeButton("Cancelar", null)
            .setPositiveButton("Salvar") { _, _ ->
                val invalidUrl = fields.firstOrNull {
                    it.text.isNotBlank() && !it.text.toString().trim().startsWith("rtsp://", true)
                }
                if (invalidUrl != null) {
                    Toast.makeText(this, "Use uma URL iniciada por rtsp://.", Toast.LENGTH_LONG)
                        .show()
                    return@setPositiveButton
                }
                preferences.edit().apply {
                    fields.forEachIndexed { index, field ->
                        putString("CAM${index + 1}", field.text.toString().trim())
                    }
                }.apply()
                updateCameras()
            }
            .show()
    }

    private fun toggleEconomyMode() {
        economyMode = !economyMode
        updateEconomyButton()
        updateCameras()
        Toast.makeText(
            this,
            if (economyMode) {
                "Substream de baixa resolução ativado."
            } else {
                "Stream principal da câmera ativado."
            },
            Toast.LENGTH_SHORT,
        ).show()
    }

    private fun updateEconomyButton() {
        economyButton.text = if (economyMode) "Substream" else "Principal"
    }

    private fun toggleRecording() {
        if (recording) {
            startService(
                Intent(this, ScreenRecordingService::class.java)
                    .setAction(ScreenRecordingService.ACTION_STOP),
            )
            return
        }

        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            requestScreenCapture()
        }
    }

    private fun requestScreenCapture() {
        val manager = getSystemService(MediaProjectionManager::class.java)
        projectionLauncher.launch(manager.createScreenCaptureIntent())
    }

    private fun updateRecordingButton() {
        recordingButton.text = if (recording) "Parar gravação" else "Iniciar gravação"
    }

    private fun closeApplication() {
        stopService(Intent(this, ScreenRecordingService::class.java))
        finish()
    }

    companion object {
        private const val CAMERA_COUNT = 4
        private const val PREFERENCES_NAME = "camera_settings"
        private const val RTSP_TIMEOUT_MS = 15_000L
        private const val SUBSTREAM_PATH = "/h264/ch1/sub/av_stream"
    }
}
