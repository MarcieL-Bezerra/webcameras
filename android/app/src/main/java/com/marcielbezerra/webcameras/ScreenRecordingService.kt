package com.marcielbezerra.webcameras

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.MediaRecorder
import android.media.projection.MediaProjectionManager
import android.media.projection.MediaProjection
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.DisplayMetrics
import android.util.Log
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import java.io.File
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.max
import kotlin.math.min

class ScreenRecordingService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private var projection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var recorder: MediaRecorder? = null
    private var currentPartialFile: File? = null
    private var recordingsDirectory: File? = null
    private var stopping = false
    private var segmentIndex = 0

    private val projectionCallback = object : MediaProjection.Callback() {
        override fun onStop() {
            stopSession(stopProjection = false)
        }
    }

    private val rotateSegment = object : Runnable {
        override fun run() {
            if (stopping || recorder == null) return
            try {
                startNextSegment()
                handler.postDelayed(this, SEGMENT_MILLISECONDS)
            } catch (error: Exception) {
                fail("A gravação foi interrompida: ${error.localizedMessage}", error)
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSession(stopProjection = true)
            return START_NOT_STICKY
        }
        if (projection != null) return START_NOT_STICKY

        val resultCode = intent?.getIntExtra(EXTRA_RESULT_CODE, 0) ?: 0
        val resultData = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent?.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent?.getParcelableExtra(EXTRA_RESULT_DATA)
        }
        if (resultData == null || resultCode == 0) {
            stopSelf(startId)
            return START_NOT_STICKY
        }

        try {
            startInForeground()
            beginRecording(resultCode, resultData)
        } catch (error: Exception) {
            fail("Não foi possível iniciar a gravação: ${error.localizedMessage}", error)
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        stopSession(stopProjection = true)
        super.onDestroy()
    }

    private fun beginRecording(resultCode: Int, resultData: Intent) {
        recordingsDirectory = getRecordingsDirectory()
        pruneOldRecordings()
        val projectionManager = getSystemService(MediaProjectionManager::class.java)
        projection = projectionManager.getMediaProjection(resultCode, resultData)
            ?: throw IOException("O Android não autorizou a captura da tela.")
        projection?.registerCallback(projectionCallback, handler)

        val (width, height, density) = screenDimensions()
        val firstPartialFile = newPartialFile()
        val firstRecorder = createRecorder(firstPartialFile, width, height)
        val display = try {
            projection?.createVirtualDisplay(
                VIRTUAL_DISPLAY_NAME,
                width,
                height,
                density,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                firstRecorder.surface,
                null,
                handler,
            ) ?: throw IOException("Não foi possível capturar a tela.")
        } catch (error: Exception) {
            firstRecorder.release()
            firstPartialFile.delete()
            throw error
        }

        try {
            firstRecorder.start()
        } catch (error: Exception) {
            display.release()
            firstRecorder.release()
            firstPartialFile.delete()
            throw error
        }

        recorder = firstRecorder
        currentPartialFile = firstPartialFile
        virtualDisplay = display
        sendState(active = true)
        handler.postDelayed(rotateSegment, SEGMENT_MILLISECONDS)
    }

    private fun startNextSegment() {
        val (width, height, _) = screenDimensions()
        val display = virtualDisplay
            ?: throw IOException("A captura da tela não está mais ativa.")
        val previousRecorder = recorder
        val previousPartialFile = currentPartialFile
        if (previousRecorder == null) {
            throw IOException("O gravador atual não está mais ativo.")
        }

        display.setSurface(null)
        recorder = null
        currentPartialFile = null
        finalizeRecorder(previousRecorder, previousPartialFile)

        val nextPartialFile = newPartialFile()
        val nextRecorder = createRecorder(nextPartialFile, width, height)
        try {
            display.setSurface(nextRecorder.surface)
            nextRecorder.start()
        } catch (error: Exception) {
            try {
                display.setSurface(null)
            } catch (detachError: Exception) {
                Log.e(TAG, "Não foi possível desconectar o novo gravador.", detachError)
            }
            nextRecorder.release()
            nextPartialFile.delete()
            throw error
        }

        recorder = nextRecorder
        currentPartialFile = nextPartialFile
    }

    private fun createRecorder(outputFile: File, width: Int, height: Int): MediaRecorder {
        val newRecorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(this)
        } else {
            @Suppress("DEPRECATION")
            MediaRecorder()
        }
        try {
            newRecorder.apply {
                setVideoSource(MediaRecorder.VideoSource.SURFACE)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setVideoEncoder(MediaRecorder.VideoEncoder.H264)
                setVideoSize(width, height)
                setVideoFrameRate(VIDEO_FRAME_RATE)
                setVideoEncodingBitRate(VIDEO_BIT_RATE)
                setOutputFile(outputFile.absolutePath)
                prepare()
            }
        } catch (error: Exception) {
            newRecorder.release()
            outputFile.delete()
            throw error
        }
        return newRecorder
    }

    private fun stopSession(stopProjection: Boolean, reportedError: String? = null) {
        if (stopping) return
        stopping = true
        handler.removeCallbacks(rotateSegment)
        var failure: Exception? = null

        try {
            virtualDisplay?.setSurface(null)
        } catch (error: Exception) {
            failure = error
            Log.e(TAG, "Não foi possível desconectar o gravador da tela.", error)
        }
        try {
            finalizeRecorder(recorder, currentPartialFile)
        } catch (error: Exception) {
            if (failure == null) failure = error
            Log.e(TAG, "Erro ao finalizar o arquivo atual.", error)
        } finally {
            recorder = null
            currentPartialFile = null
            virtualDisplay?.release()
            virtualDisplay = null
            projection?.let { currentProjection ->
                currentProjection.unregisterCallback(projectionCallback)
                if (stopProjection) currentProjection.stop()
            }
            projection = null
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
            sendState(
                active = false,
                error = reportedError ?: failure?.let {
                    "Erro ao finalizar a gravação: ${it.localizedMessage}"
                },
            )
            stopSelf()
        }
    }

    private fun finalizeRecorder(activeRecorder: MediaRecorder?, partialFile: File?) {
        if (activeRecorder == null) return

        var stopError: RuntimeException? = null
        try {
            activeRecorder.stop()
        } catch (error: RuntimeException) {
            stopError = error
        } finally {
            activeRecorder.release()
        }

        if (stopError != null) {
            partialFile?.delete()
            throw IOException("O segmento de vídeo não pôde ser finalizado.", stopError)
        }
        if (partialFile == null || !partialFile.exists() || partialFile.length() == 0L) {
            partialFile?.delete()
            return
        }

        val finalFile = File(
            partialFile.parentFile,
            partialFile.name.removeSuffix(PARTIAL_SUFFIX),
        )
        if (!partialFile.renameTo(finalFile)) {
            partialFile.delete()
            throw IOException("Não foi possível salvar ${finalFile.name}.")
        }
        pruneOldRecordings()
    }

    private fun getRecordingsDirectory(): File {
        val baseDirectory = getExternalFilesDir(Environment.DIRECTORY_MOVIES) ?: filesDir
        val directory = File(baseDirectory, RECORDINGS_DIRECTORY)
        if (!directory.exists() && !directory.mkdirs()) {
            throw IOException("Não foi possível criar a pasta de gravações.")
        }
        if (!directory.isDirectory) {
            throw IOException("O caminho das gravações não é uma pasta.")
        }
        return directory
    }

    private fun newPartialFile(): File {
        val directory = recordingsDirectory
            ?: throw IOException("A pasta das gravações não está disponível.")
        val timestamp = SimpleDateFormat(FILE_TIMESTAMP_FORMAT, Locale.US).format(Date())
        val file = File(
            directory,
            "${RECORDING_PREFIX}${timestamp}_${segmentIndex++}.mp4$PARTIAL_SUFFIX",
        )
        if (!file.createNewFile()) {
            throw IOException("Não foi possível criar o arquivo de vídeo.")
        }
        return file
    }

    private fun pruneOldRecordings() {
        val directory = recordingsDirectory ?: return
        val files = directory.listFiles()
            ?: throw IOException("Não foi possível listar os arquivos gravados.")
        files.filter {
            it.isFile &&
                it.name.endsWith(PARTIAL_SUFFIX) &&
                it.absolutePath != currentPartialFile?.absolutePath
        }
            .forEach { if (!it.delete()) throw IOException("Não foi possível remover ${it.name}.") }

        val recordings = files
            .filter { it.isFile && it.name.endsWith(".mp4") }
            .sortedBy(File::lastModified)
        var totalBytes = recordings.sumOf(File::length)
        for (file in recordings) {
            if (totalBytes <= MAX_STORAGE_BYTES) break
            val size = file.length()
            if (!file.delete()) {
                throw IOException("Não foi possível remover a gravação antiga ${file.name}.")
            }
            totalBytes -= size
        }
    }

    private fun screenDimensions(): Triple<Int, Int, Int> {
        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION")
        (getSystemService(WINDOW_SERVICE) as WindowManager).defaultDisplay.getRealMetrics(metrics)
        val scale = min(1f, MAX_FRAME_DIMENSION.toFloat() / max(metrics.widthPixels, metrics.heightPixels))
        val width = (metrics.widthPixels * scale).toInt().coerceAtLeast(2) / 2 * 2
        val height = (metrics.heightPixels * scale).toInt().coerceAtLeast(2) / 2 * 2
        return Triple(width, height, metrics.densityDpi)
    }

    private fun startInForeground() {
        val notification = buildNotification("Gravação de tela iniciando")
        val foregroundType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
        } else {
            0
        }
        ServiceCompat.startForeground(
            this,
            NOTIFICATION_ID,
            notification,
            foregroundType,
        )
    }

    private fun buildNotification(message: String): Notification {
        val stopIntent = Intent(this, ScreenRecordingService::class.java).setAction(ACTION_STOP)
        val pendingStop = PendingIntent.getService(
            this,
            STOP_REQUEST_CODE,
            stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, NOTIFICATION_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.presence_video_online)
            .setContentTitle("WebCameras")
            .setContentText(message)
            .setOngoing(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .addAction(0, "Parar gravação", pendingStop)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            NOTIFICATION_CHANNEL_ID,
            "Gravação da tela",
            NotificationManager.IMPORTANCE_LOW,
        )
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun sendState(active: Boolean, error: String? = null) {
        val stateIntent = Intent(ACTION_STATE)
            .setPackage(packageName)
            .putExtra(EXTRA_ACTIVE, active)
        if (error != null) stateIntent.putExtra(EXTRA_ERROR, error)
        sendBroadcast(stateIntent)
        if (error != null) Log.e(TAG, error)
    }

    private fun fail(message: String, error: Exception) {
        Log.e(TAG, message, error)
        stopSession(stopProjection = true, reportedError = message)
    }

    companion object {
        const val ACTION_STATE = "com.marcielbezerra.webcameras.RECORDING_STATE"
        const val ACTION_STOP = "com.marcielbezerra.webcameras.STOP_RECORDING"
        const val EXTRA_ACTIVE = "recording_active"
        const val EXTRA_ERROR = "recording_error"
        const val EXTRA_RESULT_CODE = "projection_result_code"
        const val EXTRA_RESULT_DATA = "projection_result_data"

        private const val TAG = "ScreenRecordingService"
        private const val NOTIFICATION_CHANNEL_ID = "screen_recording"
        private const val NOTIFICATION_ID = 101
        private const val STOP_REQUEST_CODE = 102
        private const val RECORDINGS_DIRECTORY = "gravacoes"
        private const val RECORDING_PREFIX = "gravacao_"
        private const val PARTIAL_SUFFIX = ".mp4.partial"
        private const val FILE_TIMESTAMP_FORMAT = "yyyyMMdd_HHmmss"
        private const val VIRTUAL_DISPLAY_NAME = "WebCamerasScreenCapture"
        private const val VIDEO_FRAME_RATE = 5
        private const val VIDEO_BIT_RATE = 400_000
        private const val MAX_FRAME_DIMENSION = 1280
        private const val SEGMENT_MILLISECONDS = 5 * 60 * 1000L
        private val MAX_STORAGE_BYTES = BuildConfig.RECORDINGS_MAX_GB * 1024L * 1024L * 1024L
    }
}
