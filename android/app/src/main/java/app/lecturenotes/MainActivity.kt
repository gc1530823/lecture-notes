package app.lecturenotes

import android.Manifest
import android.annotation.SuppressLint
import android.app.AlertDialog
import android.app.DownloadManager
import android.content.ContentValues
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.print.PrintAttributes
import android.print.PrintManager
import android.provider.MediaStore
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebResourceError
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import org.json.JSONObject

/**
 * 강의노트 안드로이드 앱: 화면은 서버의 웹앱(/web/)을 그대로 띄우고, 녹음·서버 연결은 LiveService가 맡는다.
 * 웹앱은 window.AndroidLive가 있으면 브라우저 마이크 대신 이 앱의 녹음을 쓴다 (web/src/lib/live.ts).
 */
class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var pendingStart: String? = null
    private val prefs by lazy { getSharedPreferences("settings", MODE_PRIVATE) }

    private val pickFiles = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val uris = WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
        fileCallback?.onReceiveValue(uris)
        fileCallback = null
    }

    private val askPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        val url = pendingStart
        pendingStart = null
        if (url == null) return@registerForActivityResult
        if (granted[Manifest.permission.RECORD_AUDIO] == true || hasMic()) startService(url)
        else toast("마이크 권한이 있어야 녹음할 수 있어요")
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        setContentView(web)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
            allowFileAccess = false
        }
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)
        web.addJavascriptInterface(Bridge(), "AndroidLive")
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                // 같은 서버(와 GitHub 로그인)는 앱 안에서, 나머지 링크는 브라우저로
                val host = request.url.host ?: return false
                val server = Uri.parse(server() ?: "").host
                if (host == server || host.endsWith("github.com") || host.endsWith("githubusercontent.com")) return false
                startActivity(Intent(Intent.ACTION_VIEW, request.url))
                return true
            }

            // 서버에 닿지 않으면(컴퓨터가 꺼졌거나, 무료 터널 주소가 바뀌었을 때) 빈 화면 대신 주소를 다시 묻는다
            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) runOnUiThread { cannotReach() }
            }

            override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, response: WebResourceResponse) {
                // 530·502·503·504: 터널은 살아 있는데 서버(컴퓨터)가 꺼져 있다
                if (request.isForMainFrame && response.statusCode in setOf(502, 503, 504, 530)) runOnUiThread { cannotReach() }
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                return try {
                    pickFiles.launch(params.createIntent()); true
                } catch (e: Exception) {
                    fileCallback = null; false
                }
            }

            override fun onPermissionRequest(request: PermissionRequest) {
                // 브라우저 마이크로 녹음하는 경우(예전 방식)도 허락한다
                runOnUiThread { request.grant(request.resources) }
            }
        }
        web.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ -> download(url, userAgent, contentDisposition, mimeType) }

        LiveService.onEvent = { text -> web.evaluateJavascript("window.__androidLiveEvent && window.__androidLiveEvent(${JSONObject.quote(text)})", null) }

        if (openLink(intent)) return
        val saved = server()
        val start = if (intent?.getStringExtra("open") == "review") "#/review" else ""
        if (saved == null) askServer() else web.loadUrl(appUrl(saved) + start)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        openLink(intent)
    }

    /** 친구에게 받은 서버 링크로 열렸으면: 그 서버를 저장하고 연다 */
    private fun openLink(intent: Intent?): Boolean {
        val link = intent?.data ?: return false
        if (intent.action != Intent.ACTION_VIEW || link.scheme != "https" || link.host.isNullOrEmpty()) return false
        val url = "https://${link.host}"
        prefs.edit().putString("server", url).apply()
        web.loadUrl(appUrl(url))
        return true
    }

    private var reachDialog: AlertDialog? = null

    private fun cannotReach() {
        if (reachDialog?.isShowing == true) return
        reachDialog = AlertDialog.Builder(this)
            .setTitle("서버에 연결할 수 없어요")
            .setMessage("서버 컴퓨터가 꺼져 있거나 주소가 바뀌었을 수 있어요. 새 주소를 받았다면 바꿔 주세요.")
            .setPositiveButton("다시 시도") { _, _ -> web.reload() }
            .setNeutralButton("주소 바꾸기") { _, _ -> askServer() }
            .show()
    }

    override fun onDestroy() {
        LiveService.onEvent = null
        super.onDestroy()
    }

    @Deprecated("뒤로 가기: 웹앱 안에서 먼저 뒤로")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    private fun server(): String? = prefs.getString("server", null)

    private fun appUrl(server: String) = server.trimEnd('/') + "/web/"

    /** 처음 켤 때(또는 바꿀 때): 강의노트 서버 주소 (예: Codespaces의 8000번 포트 주소) */
    private fun askServer() {
        val input = EditText(this).apply {
            hint = "https://….trycloudflare.com"
            setText(server() ?: "https://")
            setSingleLine()
        }
        AlertDialog.Builder(this)
            .setTitle("서버 주소")
            .setMessage("서버를 켠 사람에게 받은 주소를 넣어 주세요. (주소 링크를 카톡에서 누르면 자동으로 들어가요)")
            .setView(input)
            .setCancelable(server() != null)
            .setPositiveButton("열기") { _, _ ->
                var url = input.text.toString().trim().trimEnd('/')
                if (!url.startsWith("http")) url = "https://$url"
                url = url.removeSuffix("/web").removeSuffix("/app")
                prefs.edit().putString("server", url).apply()
                web.loadUrl(appUrl(url))
            }
            .show()
    }

    private fun hasMic() = ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private fun startService(wsUrl: String) {
        val intent = Intent(this, LiveService::class.java).putExtra(LiveService.EXTRA_URL, wsUrl)
        ContextCompat.startForegroundService(this, intent)
    }

    private fun download(url: String, userAgent: String, contentDisposition: String?, mimeType: String?) {
        if (url.startsWith("blob:") || url.startsWith("data:")) {
            toast("이 파일은 앱에서 바로 받을 수 없어요")
            return
        }
        val name = URLUtil.guessFileName(url, contentDisposition, mimeType)
        val request = DownloadManager.Request(Uri.parse(url))
            .setTitle(name)
            .setMimeType(mimeType)
            .addRequestHeader("User-Agent", userAgent)
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
        CookieManager.getInstance().getCookie(url)?.let { request.addRequestHeader("Cookie", it) }
        (getSystemService(DOWNLOAD_SERVICE) as DownloadManager).enqueue(request)
        toast("내려받는 중: $name")
    }

    private fun toast(text: String) = Toast.makeText(this, text, Toast.LENGTH_SHORT).show()

    /** 웹앱이 부르는 기능들 (window.AndroidLive.*) */
    inner class Bridge {
        @JavascriptInterface fun version(): String = "1"

        /** 녹음 시작: 서버 WebSocket 주소를 받아 서비스를 켠다 */
        @JavascriptInterface fun start(wsUrl: String) = runOnUiThread {
            val needed = mutableListOf(Manifest.permission.RECORD_AUDIO)
            if (Build.VERSION.SDK_INT >= 33) needed += Manifest.permission.POST_NOTIFICATIONS
            if (hasMic()) startService(wsUrl) else { pendingStart = wsUrl; askPermissions.launch(needed.toTypedArray()) }
        }

        @JavascriptInterface fun send(text: String) = LiveService.send(text)

        @JavascriptInterface fun stop() = runOnUiThread {
            startService(Intent(this@MainActivity, LiveService::class.java).setAction(LiveService.ACTION_STOP))
        }

        @JavascriptInterface fun isRecording(): Boolean = LiveService.running != null

        /** 웹앱이 만든 글 파일(족보 공유 등)을 내려받기 폴더에 저장 */
        @JavascriptInterface fun saveFile(name: String, mime: String, text: String) = runOnUiThread {
            try {
                val values = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, name)
                    put(MediaStore.Downloads.MIME_TYPE, mime)
                }
                if (Build.VERSION.SDK_INT >= 29) {
                    val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: throw IllegalStateException()
                    contentResolver.openOutputStream(uri)?.use { it.write(text.toByteArray()) }
                } else {
                    val dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                    java.io.File(dir, name).writeText(text)
                }
                toast("내려받기 폴더에 저장했어요: $name")
            } catch (e: Exception) {
                toast("저장하지 못했어요")
            }
        }

        /** 족보 노트 등 인쇄·PDF로 저장 */
        @JavascriptInterface fun print(title: String) = runOnUiThread {
            val manager = getSystemService(PRINT_SERVICE) as PrintManager
            manager.print(title, web.createPrintDocumentAdapter(title), PrintAttributes.Builder().build())
        }

        @JavascriptInterface fun changeServer() = runOnUiThread { askServer() }

        @JavascriptInterface fun keepScreenOn(on: Boolean) = runOnUiThread { web.keepScreenOn = on }

        /** 매일 hour:minute에 띄울 복습·시험 알림 글 (앱을 열 때마다 웹 화면이 최신 숫자로 바꾼다) */
        @JavascriptInterface fun setReminder(title: String, text: String, hour: Int, minute: Int) = runOnUiThread {
            if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
                askPermissions.launch(arrayOf(Manifest.permission.POST_NOTIFICATIONS))
            }
            ReminderReceiver.save(this@MainActivity, title, text, hour, minute)
        }

        @JavascriptInterface fun cancelReminder() = runOnUiThread { ReminderReceiver.cancel(this@MainActivity) }
    }
}
