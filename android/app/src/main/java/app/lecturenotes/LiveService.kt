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

    // 폰 안 받아쓰기 (모델이 있으면). 없으면 서버가 받아쓰고, 그동안 모델을 받아 둔다
    @Volatile private var device: DeviceStt? = null
    private var samplesSeen = 0L      // 강의 시작부터 들은 소리 길이 (문장 시각을 매긴다)
    private var sentenceStart = -1L
    private var levelTick = 0

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
        // 폰 받아쓰기 모델을 읽는 데 1~2초 걸려 화면을 멈추지 않게 따로 돌린다. 준비되는 순간부터 폰이 받아쓴다
        Thread {
            val stt = DeviceStt(this)
            if (!stt.ready()) {
                emit(notice("폰 받아쓰기 모델(약 150MB)을 받는 중이에요. 다 받으면 기다림 없이 바로 받아써요."))
                if (!stt.download()) {
                    emit(notice("받아쓰기 모델을 못 받았어요. 이번에는 서버가 받아써요."))
                    return@Thread
                }
            }
            if (!stopping && stt.start()) {
                device = stt
                queueText("""{"type":"device_stt"}""")
                emit(notice("폰이 바로 받아써요 (한도·기다림 없음)"))
            }
        }.apply { name = "stt-load"; start() }
        connect()
        startRecording()
        return START_STICKY
    }

    private fun startForegroundNotice() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "강의 녹음", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val notice: Notification = Notification.Builder(this, CHANNEL)
            .setContentTitle("강의 녹음 중")
            .setContentText("화면을 꺼도 계속 듣고 필기해요")
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
                    // 폰이 받아쓰면 서버는 녹음 저장만 한다 (받아쓰기 한도를 안 쓴다)
                    if (device != null) webSocket.send("""{"type":"device_stt"}""")
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

    private fun notice(message: String): String = JSONObject().put("type", "notice").put("message", message).toString()

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
                if (n > 0) {
                    // 화면의 실시간 파형용: 0.2초마다 그 조각의 가장 큰 소리 크기(0~1)를 보낸다
                    if (++levelTick % 2 == 0) {
                        var peak = 0
                        var i = 0
                        while (i + 1 < n) {
                            val v = kotlin.math.abs(((buffer[i].toInt() and 0xff) or (buffer[i + 1].toInt() shl 8)).toShort().toInt())
                            if (v > peak) peak = v
                            i += 2
                        }
                        emit("""{"type":"level","v":${peak / 32768f}}""")
                    }
                    queueAudio(buffer.copyOf(n).toByteString())
                    device?.let { hear(it, buffer, n) }
                }
            }
        }.apply { name = "recorder"; start() }
    }

    /** 폰 안 받아쓰기: 들리는 대로 화면에 바로 띄우고, 문장이 끝나면 서버에 보내 필기를 붙이게 한다 */
    private fun hear(stt: DeviceStt, buffer: ByteArray, n: Int) {
        val count = n / 2
        val samples = FloatArray(count) { i ->
            ((buffer[2 * i].toInt() and 0xff) or (buffer[2 * i + 1].toInt() shl 8)).toShort() / 32768f
        }
        val (partial, done) = stt.accept(samples)
        val nowMs = samplesSeen * 1000 / RATE
        samplesSeen += count
        if (partial.isNotEmpty() && sentenceStart < 0) sentenceStart = nowMs
        if (done != null) {
            val start = if (sentenceStart >= 0) sentenceStart else nowMs
            queueText(JSONObject().put("type", "transcript_final").put("text", done)
                .put("start_ms", start).put("end_ms", nowMs).toString())
            emit(JSONObject().put("type", "heard").put("text", done).toString())
            sentenceStart = -1
        } else if (partial.isNotEmpty()) {
            emit(JSONObject().put("type", "heard").put("text", partial).toString())
        }
    }

    private fun shutdown() {
        stopping = true
        try { recorder?.stop() } catch (_: Exception) { }
        recorder?.release()
        recorder = null
        // 녹음 스레드가 받아쓰기 엔진을 쓰는 중일 수 있어, 끝나길 잠깐 기다린 뒤 엔진을 닫는다
        try { thread?.join(800) } catch (_: InterruptedException) { }
        thread = null
        device?.stop()
        device = null
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
