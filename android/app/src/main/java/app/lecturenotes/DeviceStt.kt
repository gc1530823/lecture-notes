package app.lecturenotes

import android.content.Context
import com.k2fsa.sherpa.onnx.EndpointConfig
import com.k2fsa.sherpa.onnx.EndpointRule
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineRecognizerConfig
import com.k2fsa.sherpa.onnx.OnlineStream
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * 폰 안 받아쓰기: 한국어 실시간(스트리밍) 음성 인식 모델을 폰에서 돌린다 → 인터넷 한도도, 녹음 길이 제한도, 기다림도 없다.
 *
 * - 모델: sherpa-onnx 한국어 스트리밍 Zipformer (k2-fsa, Apache 2.0, 한국어 대화 음성 KsponSpeech로 학습). 약 150MB를
 *   처음 한 번 Hugging Face에서 받아 앱 저장소에 둔다. 받는 동안·못 받으면 예전처럼 서버가 받아쓴다.
 * - 말하는 동안 글자가 바로바로 나오고(0.3~0.6초), 문장이 끝나면(쉼) 서버에 문장으로 보내 필기를 붙이게 한다.
 */
class DeviceStt(private val context: Context) {

    companion object {
        private const val BASE = "https://huggingface.co/k2-fsa/sherpa-onnx-streaming-zipformer-korean-2024-06-16/resolve/main/"
        private val FILES = listOf(
            "encoder-epoch-99-avg-1.int8.onnx",
            "decoder-epoch-99-avg-1.onnx",
            "joiner-epoch-99-avg-1.int8.onnx",
            "tokens.txt",
        )
        @Volatile private var downloading = false
    }

    private val dir = File(context.filesDir, "stt-ko")
    private var recognizer: OnlineRecognizer? = null
    private var stream: OnlineStream? = null

    fun ready(): Boolean = FILES.all { File(dir, it).length() > 0 } && File(dir, "done").exists()

    /** 모델을 받아 둔다 (이미 있으면 아무것도 안 함). 다른 스레드에서 부른다. 받으면 true. */
    fun download(onProgress: (Int) -> Unit = {}): Boolean {
        if (ready()) return true
        if (downloading) return false
        downloading = true
        try {
            dir.mkdirs()
            FILES.forEachIndexed { i, name ->
                val target = File(dir, name)
                if (target.length() > 0) return@forEachIndexed
                val part = File(dir, "$name.part")
                val conn = URL(BASE + name).openConnection() as HttpURLConnection
                conn.instanceFollowRedirects = true
                conn.connectTimeout = 20_000
                conn.readTimeout = 60_000
                conn.inputStream.use { input -> part.outputStream().use { input.copyTo(it, 1 shl 16) } }
                if (!part.renameTo(target)) return false
                onProgress((i + 1) * 100 / FILES.size)
            }
            File(dir, "done").writeText("ok")
            return true
        } catch (e: Exception) {
            return false
        } finally {
            downloading = false
        }
    }

    fun start(): Boolean {
        if (!ready()) return false
        return try {
            val config = OnlineRecognizerConfig(
                featConfig = FeatureConfig(sampleRate = 16000, featureDim = 80),
                modelConfig = OnlineModelConfig(
                    transducer = OnlineTransducerModelConfig(
                        encoder = File(dir, FILES[0]).path,
                        decoder = File(dir, FILES[1]).path,
                        joiner = File(dir, FILES[2]).path,
                    ),
                    tokens = File(dir, FILES[3]).path,
                    numThreads = 2,
                    modelType = "zipformer",
                ),
                // 강의는 말이 길게 이어진다: 0.8초 쉬면 문장 끝, 아무리 길어도 15초에서 끊어 필기를 붙인다
                endpointConfig = EndpointConfig(
                    rule1 = EndpointRule(false, 2.4f, 0.0f),
                    rule2 = EndpointRule(true, 0.8f, 0.0f),
                    rule3 = EndpointRule(false, 0.0f, 15.0f),
                ),
                enableEndpoint = true,
            )
            recognizer = OnlineRecognizer(null, config)
            stream = recognizer!!.createStream()
            true
        } catch (e: Throwable) {
            recognizer = null
            false
        }
    }

    /**
     * 소리 조각을 넣는다. 지금까지 들은 글(중간 결과)과, 문장이 끝났으면 끝난 문장을 돌려준다.
     * @return Pair(지금 화면에 보일 글, 끝난 문장 또는 null)
     */
    fun accept(samples: FloatArray): Pair<String, String?> {
        val r = recognizer ?: return "" to null
        val s = stream ?: return "" to null
        s.acceptWaveform(samples, 16000)
        while (r.isReady(s)) r.decode(s)
        val text = r.getResult(s).text.trim()
        if (r.isEndpoint(s)) {
            r.reset(s)
            return "" to text.ifEmpty { null }
        }
        return text to null
    }

    fun stop() {
        stream?.release()
        recognizer?.release()
        stream = null
        recognizer = null
    }
}
