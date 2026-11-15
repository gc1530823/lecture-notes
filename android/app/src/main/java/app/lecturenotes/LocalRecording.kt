package app.lecturenotes

import android.content.Context
import android.webkit.CookieManager
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import org.json.JSONObject
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.util.concurrent.TimeUnit

/**
 * 녹음 오프라인 저장 (안드로이드 앱): 수업 중 마이크 소리를 서버로 보내면서 폰 안(files/rec)에도 전부 적어 둔다.
 * 강의가 끝나면 서버가 받은 길이와 견줘, 연결이 끊겨 5초 넘게 빠졌으면 전체 녹음을 올려 처음부터 다시 정리하게 한다.
 * 그때 인터넷이 없으면 남겨 두었다가 다음에 앱을 열 때 올린다. 다 받았으면 지우고, 7일 지나면 지운다.
 */
class LocalRecording(context: Context, private val sid: String) {
    private val dir = File(context.filesDir, "rec").apply { mkdirs() }
    private val out = BufferedOutputStream(FileOutputStream(File(dir, "$sid.pcm"), true), 1 shl 16)

    @Synchronized fun append(bytes: ByteArray, n: Int) {
        try { out.write(bytes, 0, n) } catch (_: Exception) { }
    }

    /** 강의를 끝낼 때: 파일을 닫고 '다 녹음함' 표시와 서버 주소를 남긴다 */
    @Synchronized fun finish(base: String) {
        try { out.close() } catch (_: Exception) { }
        File(dir, "$sid.done").writeText(base)
    }

    companion object {
        private const val RATE = 16000
        private const val GAP_MS = 5000L
        private const val KEEP_MS = 7L * 24 * 60 * 60 * 1000
        private val client = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.MINUTES).writeTimeout(10, TimeUnit.MINUTES).build()
        @Volatile private var syncing = false

        /** wss://주소/sessions/<id>/stream → (https://주소, id) */
        fun parse(wsUrl: String): Pair<String, String>? {
            val m = Regex("^ws(s?)://([^/]+)(.*)/sessions/([0-9a-f]{32})/").find(wsUrl) ?: return null
            return "http${m.groupValues[1]}://${m.groupValues[2]}${m.groupValues[3]}" to m.groupValues[4]
        }

        private fun request(url: String): Request.Builder {
            val b = Request.Builder().url(url)
            CookieManager.getInstance().getCookie(url)?.let { b.header("Cookie", it) }
            return b
        }

        private fun wavHeader(dataBytes: Long): ByteArray {
            val h = java.nio.ByteBuffer.allocate(44).order(java.nio.ByteOrder.LITTLE_ENDIAN)
            h.put("RIFF".toByteArray()); h.putInt((36 + dataBytes).toInt()); h.put("WAVE".toByteArray())
            h.put("fmt ".toByteArray()); h.putInt(16); h.putShort(1); h.putShort(1); h.putInt(RATE); h.putInt(RATE * 2)
            h.putShort(2); h.putShort(16); h.put("data".toByteArray()); h.putInt(dataBytes.toInt())
            return h.array()
        }

        private fun forget(dir: File, sid: String) {
            File(dir, "$sid.pcm").delete(); File(dir, "$sid.done").delete(); File(dir, "$sid.wav").delete()
        }

        /** 다 녹음한 강의마다: 서버가 다 받았으면 지우고, 빠진 곳이 있으면 전체 녹음을 올린다 (백그라운드 스레드에서). 올린 수를 돌려준다 */
        fun sync(context: Context): Int {
            if (syncing) return 0
            syncing = true
            var uploaded = 0
            try {
                val dir = File(context.filesDir, "rec")
                val done = dir.listFiles { f -> f.name.endsWith(".done") } ?: return 0
                for (marker in done) {
                    val sid = marker.name.removeSuffix(".done")
                    val pcm = File(dir, "$sid.pcm")
                    if (!pcm.exists() || System.currentTimeMillis() - marker.lastModified() > KEEP_MS) { forget(dir, sid); continue }
                    val base = marker.readText().trim()
                    val have = try {
                        client.newCall(request("$base/sessions/$sid/received").build()).execute().use { r ->
                            if (r.code == 404) { forget(dir, sid); null }
                            else if (!r.isSuccessful) null
                            else JSONObject(r.body?.string() ?: "{}").optLong("ms", 0)
                        }
                    } catch (_: Exception) { null } ?: continue   // 인터넷이 없다 → 다음에
                    val mine = pcm.length() * 1000 / (RATE * 2)
                    if (mine - have <= GAP_MS) { forget(dir, sid); continue }
                    // 머리(44바이트)를 붙인 wav 를 만든다 (한 번만)
                    val wav = File(dir, "$sid.wav")
                    if (!wav.exists() || wav.length() != pcm.length() + 44) {
                        RandomAccessFile(wav, "rw").use { w ->
                            w.setLength(0); w.write(wavHeader(pcm.length()))
                            pcm.inputStream().use { input -> val buf = ByteArray(1 shl 16); while (true) { val n = input.read(buf); if (n < 0) break; w.write(buf, 0, n) } }
                        }
                    }
                    val body = MultipartBody.Builder().setType(MultipartBody.FORM)
                        .addFormDataPart("file", "$sid.wav", wav.asRequestBody("audio/wav".toMediaType())).build()
                    val ok = try {
                        client.newCall(request("$base/sessions/$sid/full-audio").post(body).build()).execute().use { it.isSuccessful }
                    } catch (_: Exception) { false }
                    if (ok) { forget(dir, sid); uploaded++ }
                }
            } catch (_: Exception) {
            } finally {
                syncing = false
            }
            return uploaded
        }
    }
}
