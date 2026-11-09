package app.lecturenotes

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.webkit.CookieManager
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.util.ArrayDeque
import java.util.concurrent.TimeUnit

/**
 * 강의 녹음 서비스: 화면이 꺼지거나 다른 앱으로 가도 녹음과 서버 연결을 이어 간다 (웹앱만으로는 안 되던 것).
 *
 * - 마이크 소리를 16kHz 16비트 모노 PCM으로 0.1초씩 서버 WebSocket에 보낸다 (웹앱과 같은 규약).
 * - 서버가 보내는 이벤트(필기·용어·쪽 추정…)는 화면(웹앱)으로 넘긴다. 화면이 꺼져 있던 동안 놓친 것은 웹앱이 다시 불러온다.
 * - 연결이 끊기면 다시 잇고, 끊긴 동안의 소리(최대 60초)와 메시지를 모아 두었다가 보낸다.
 */
class LiveService : Service() {

    companion object {
        const val EXTRA_URL = "url"
        const val ACTION_STOP = "stop"
        private const val CHANNEL = "recording"
        private const val RATE = 16000
        private const val CHUNK_BYTES = RATE * 2 / 10 // 0.1초
        private const val MAX_BACKLOG = 600 // 0.1초 × 600 = 60초

        /** 화면(MainActivity)이 받는 이벤트 통로 */
        @Volatile var onEvent: ((String) -> Unit)? = null
        @Volatile var running: LiveService? = null

        fun send(text: String) { running?.queueText(text) }
    }

    private val client = OkHttpClient.Builder().pingInterval(20, TimeUnit.SECONDS).readTimeout(0, TimeUnit.MILLISECONDS).build()
    private val main = Handler(Looper.getMainLooper())
    private var url: String = ""
    private var socket: WebSocket? = null
    private var open = false
    private var stopping = false
    private var recorder: AudioRecord? = null
    private var thread: Thread? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private val audioBacklog = ArrayDeque<ByteString>()
    private val textBacklog = ArrayDeque<String>()
    private var lastPage = 1

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            shutdown()
            return START_NOT_STICKY
        }
        val target = intent?.getStringExtra(EXTRA_URL) ?: return START_NOT_STICKY
        if (running != null && url == target) return START_STICKY
        url = target
        running = this
        startForegroundNotice()
        acquireWakeLock()
        connect()
        startRecording()
        return START_STICKY
    }

    private fun startForegroundNotice() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "강의 녹음", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val notice: Notification = Notification.Builder(this, CHANNEL)
            .setContentTitle("강의노트 녹음 중")
            .setContentText("화면을 꺼도 필기가 계속 붙어요")
            .setSmallIcon(R.drawable.ic_notify)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1, notice, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(1, notice)
        }
    }

    private fun acquireWakeLock() {
        val power = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "lecturenotes:recording").apply { acquire(4 * 60 * 60 * 1000L) }
    }

    private fun connect() {
        if (stopping) return
        val builder = Request.Builder().url(url)
        // Codespaces 같은 비공개 주소는 로그인 쿠키가 있어야 열린다 (웹앱 화면에서 로그인한 것을 그대로 쓴다)
        val httpUrl = url.replaceFirst("ws", "http")
        CookieManager.getInstance().getCookie(httpUrl)?.let { builder.header("Cookie", it) }
        socket = client.newWebSocket(builder.build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                synchronized(this@LiveService) {
                    open = true
                    // 서버는 연결마다 상태를 새로 만들므로 보던 쪽부터 알린다
                    webSocket.send(JSONObject().put("type", "page_view").put("page", lastPage).put("initial", true).toString())
                    while (textBacklog.isNotEmpty()) webSocket.send(textBacklog.removeFirst())
                    while (audioBacklog.isNotEmpty()) webSocket.send(audioBacklog.removeFirst())
                }
                emit("""{"type":"native_status","connected":true}""")
            }

            override fun onMessage(webSocket: WebSocket, text: String) = emit(text)

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = reconnect()

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                emit("""{"type":"native_status","connected":false}""")
                reconnect()
            }
        })
    }

    private fun reconnect() {
        synchronized(this) { open = false }
        if (!stopping) main.postDelayed({ connect() }, 1500)
    }

    private fun emit(text: String) {
        val handler = onEvent ?: return
        main.post { handler(text) }
    }

    @Synchronized
    fun queueText(text: String) {
        try {
            val json = JSONObject(text)
            if (json.optString("type") == "page_view") lastPage = json.optInt("page", lastPage)
        } catch (_: Exception) { }
        if (open) socket?.send(text) else textBacklog.addLast(text)
    }

    @Synchronized
    private fun queueAudio(bytes: ByteString) {
        if (open && socket?.send(bytes) == true) return
        audioBacklog.addLast(bytes)
        while (audioBacklog.size > MAX_BACKLOG) audioBacklog.removeFirst()
    }

    @SuppressLint("MissingPermission") // 화면이 녹음 전에 권한을 받는다
    private fun startRecording() {
        val min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val record = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, RATE, AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT, maxOf(min, CHUNK_BYTES * 4))
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            emit("""{"type":"error","message":"마이크를 열 수 없어요. 설정에서 마이크 권한을 확인해 주세요."}""")
            return
        }
        recorder = record
        record.startRecording()
        thread = Thread {
            val buffer = ByteArray(CHUNK_BYTES)
            while (!stopping) {
                val n = record.read(buffer, 0, buffer.size)
                if (n > 0) queueAudio(buffer.copyOf(n).toByteString())
            }
        }.apply { name = "recorder"; start() }
    }

    private fun shutdown() {
        stopping = true
        try { recorder?.stop() } catch (_: Exception) { }
        recorder?.release()
        recorder = null
        thread = null
        // 마지막 필기를 받을 시간을 웹앱이 이미 기다렸으므로 바로 닫는다
        socket?.close(1000, "끝")
        socket = null
        wakeLock?.let { if (it.isHeld) it.release() }
        running = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        if (!stopping) shutdown()
        super.onDestroy()
    }
}
