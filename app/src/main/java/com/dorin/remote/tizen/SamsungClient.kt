package com.dorin.remote.tizen

import android.content.Context
import android.util.Log
import com.dorin.remote.Diag
import com.dorin.remote.net.IconCache
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.Base64
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

sealed class SamsungState {
    object Disconnected : SamsungState()
    object Connecting : SamsungState()
    object WaitingForPrompt : SamsungState() // user must choose "Allow" on the TV
    object Connected : SamsungState()
    data class Error(val message: String) : SamsungState()
}

/** An app installed on the TV. Tizen apps (type 2) launch with DEEP_LINK, web apps with NATIVE_LAUNCH. */
data class SamsungApp(val id: String, val name: String, val type: Int = 2, val iconPath: String = "") {
    val launchType: String get() = if (type == 4) "NATIVE_LAUNCH" else "DEEP_LINK"
}

/** The TV refused us (user pressed Deny). Not retried automatically. */
class SamsungDeniedException(msg: String) : Exception(msg)

/** JSON the TV understands. No Android types, so unit tests can check it. */
object SamsungMsg {
    const val YOUTUBE = "111299001912"
    const val NETFLIX = "11101200001"
    const val BROWSER = "org.tizen.browser"
    const val DEVICE_NAME = "UniRemote"

    fun b64(s: String): String = Base64.getEncoder().encodeToString(s.toByteArray())

    fun wsUrl(ip: String, secure: Boolean, token: String?): String {
        val scheme = if (secure) "wss" else "ws"
        val port = if (secure) 8002 else 8001
        val t = if (token != null && secure) "&token=$token" else ""
        return "$scheme://$ip:$port/api/v2/channels/samsung.remote.control?name=${b64(DEVICE_NAME)}$t"
    }

    private fun control(params: JSONObject) = JSONObject().put("method", "ms.remote.control").put("params", params).toString()
    private fun emit(event: String, data: JSONObject? = null): String {
        val p = JSONObject().put("event", event).put("to", "host")
        if (data != null) p.put("data", data)
        return JSONObject().put("method", "ms.channel.emit").put("params", p).toString()
    }

    fun key(name: String) = control(JSONObject().put("Cmd", "Click").put("DataOfCmd", name).put("Option", "false").put("TypeOfRemote", "SendRemoteKey"))
    fun keyHold(name: String, press: Boolean) = control(JSONObject().put("Cmd", if (press) "Press" else "Release").put("DataOfCmd", name).put("Option", "false").put("TypeOfRemote", "SendRemoteKey"))
    fun text(s: String) = control(JSONObject().put("Cmd", b64(s)).put("DataOfCmd", "base64").put("TypeOfRemote", "SendInputString"))
    fun inputEnd() = control(JSONObject().put("TypeOfRemote", "SendInputEnd"))
    fun mouseMove(dx: Int, dy: Int, time: Long) = control(JSONObject().put("Cmd", "Move")
        .put("Position", JSONObject().put("x", dx).put("y", dy).put("Time", time.toString())).put("TypeOfRemote", "ProcessMouseDevice"))
    fun mouseClick() = control(JSONObject().put("Cmd", "LeftClick").put("TypeOfRemote", "ProcessMouseDevice"))
    fun launch(appId: String, type: String = "DEEP_LINK", meta: String = "") =
        emit("ed.apps.launch", JSONObject().put("appId", appId).put("action_type", type).put("metaTag", meta))
    fun installedApps() = emit("ed.installedApp.get")
    fun icon(path: String) = emit("ed.apps.icon", JSONObject().put("iconPath", path))
}

private const val TAG = "SamsungClient"

/**
 * Samsung Tizen TV (2016 and newer) client over the "samsung.remote.control" WebSocket channel.
 * First connection shows an Allow / Deny prompt on the TV; the TV then returns a token we keep.
 */
class SamsungClient(
    private val ctx: Context,
    private val onToken: (String) -> Unit,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var connectJob: Job? = null
    private var ws: WebSocket? = null
    private var sessionClosed = CompletableDeferred<Unit>()
    private var connected = CompletableDeferred<JSONObject>()

    @Volatile var token: String? = null
    @Volatile var host: String? = null

    val state = MutableStateFlow<SamsungState>(SamsungState.Disconnected)
    val tvName = MutableStateFlow<String?>(null)
    val macAddress = MutableStateFlow<String?>(null)
    val apps = MutableStateFlow<List<SamsungApp>>(emptyList())

    val isConnected: Boolean get() = state.value is SamsungState.Connected

    private val http: OkHttpClient by lazy {
        val tm = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {}
            override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
        }
        val ssl = SSLContext.getInstance("TLS")
        ssl.init(null, arrayOf<TrustManager>(tm), SecureRandom())
        OkHttpClient.Builder()
            .sslSocketFactory(ssl.socketFactory, tm)
            .hostnameVerifier { _, _ -> true }
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .pingInterval(15, TimeUnit.SECONDS)
            .build()
    }

    fun connect(ip: String, token: String?) {
        host = ip
        this.token = token
        connectJob?.cancel()
        connectJob = scope.launch { runLoop(ip) }
    }

    fun disconnect() {
        connectJob?.cancel()
        connectJob = null
        closeSocket()
        state.value = SamsungState.Disconnected
    }

    private fun closeSocket() {
        try { ws?.close(1000, null) } catch (_: Exception) {}
        ws = null
        synchronized(iconQueue) { iconQueue.clear(); iconInFlight = null }
    }

    private suspend fun runLoop(ip: String) {
        var backoff = 2000L
        while (scope.isActive && connectJob?.isActive == true) {
            state.value = SamsungState.Connecting
            try {
                session(ip)
                backoff = 2000L
            } catch (e: SamsungDeniedException) {
                state.value = SamsungState.Error(e.message ?: "denied")
                return
            } catch (e: Exception) {
                Log.w(TAG, "session ended: ${e.message}")
                if (state.value !is SamsungState.Error) state.value = SamsungState.Error(e.message ?: "connection failed")
            } finally {
                closeSocket()
            }
            delay(backoff)
            backoff = (backoff * 2).coerceAtMost(15_000L)
        }
    }

    private suspend fun session(ip: String) {
        sessionClosed = CompletableDeferred()
        connected = CompletableDeferred()
        deviceInfo(ip)
        val socket = try {
            openSocket(SamsungMsg.wsUrl(ip, secure = true, token = token))
        } catch (e: Exception) {
            Diag.log(TAG, "wss:8002 failed (${e.message}), trying ws:8001")
            openSocket(SamsungMsg.wsUrl(ip, secure = false, token = null))
        }
        ws = socket
        if (token == null) state.value = SamsungState.WaitingForPrompt
        // With a valid token the TV answers at once. Otherwise it is showing the Allow prompt.
        val ev = withTimeoutOrNull(3000) { connected.await() } ?: run {
            state.value = SamsungState.WaitingForPrompt
            Diag.log(TAG, "waiting for Allow on the TV")
            withTimeout(90_000) { connected.await() }
        }
        val newToken = ev.optJSONObject("data")?.optString("token")?.takeIf { it.isNotEmpty() }
        if (newToken != null && newToken != token) { token = newToken; onToken(newToken) }
        state.value = SamsungState.Connected
        Diag.log(TAG, "connected" + (tvName.value?.let { " to $it" } ?: ""))
        socket.send(SamsungMsg.installedApps())
        sessionClosed.await()
        throw IllegalStateException("socket closed")
    }

    /** REST info on port 8001: name, model, MAC (for Wake-on-LAN). Failure is not fatal. */
    private fun deviceInfo(ip: String) {
        runCatching {
            val req = Request.Builder().url("http://$ip:8001/api/v2/").build()
            http.newBuilder().readTimeout(3, TimeUnit.SECONDS).build().newCall(req).execute().use { r ->
                val body = r.body?.string() ?: return
                val dev = JSONObject(body).optJSONObject("device") ?: return
                val name = dev.optString("name").ifEmpty { dev.optString("modelName") }.ifEmpty { null }
                if (name != null) tvName.value = name
                val mac = dev.optString("wifiMac").ifEmpty { null }
                if (mac != null && mac.length >= 17) macAddress.value = mac
                Diag.log(TAG, "device: $name model=${dev.optString("modelName")} power=${dev.optString("PowerState")} tokenAuth=${dev.optString("TokenAuthSupport")}")
            }
        }.onFailure { Diag.log(TAG, "device info failed: ${it.message}") }
    }

    private suspend fun openSocket(url: String): WebSocket {
        val opened = CompletableDeferred<WebSocket>()
        val listener = object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) { opened.complete(webSocket) }
            override fun onMessage(webSocket: WebSocket, text: String) { onMessage(text) }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (!opened.isCompleted) opened.completeExceptionally(t) else closed(t.message ?: "connection lost")
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { closed("closed by TV") }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(1000, null) }
        }
        val socket = http.newWebSocket(Request.Builder().url(url).build(), listener)
        return withTimeout(6000) { opened.await() }
    }

    private fun closed(reason: String) {
        if (!connected.isCompleted) connected.completeExceptionally(IllegalStateException(reason))
        sessionClosed.complete(Unit)
    }

    private fun onMessage(text: String) {
        val msg = runCatching { JSONObject(text) }.getOrNull() ?: return
        when (val event = msg.optString("event")) {
            "ms.channel.connect" -> { Diag.log(TAG, "channel connected"); connected.complete(msg) }
            "ms.channel.unauthorized" -> {
                Diag.log(TAG, "TV denied access")
                state.value = SamsungState.Error("TV denied access. Press Connect again and choose Allow on the TV.")
                if (!connected.isCompleted) connected.completeExceptionally(SamsungDeniedException("TV denied access"))
            }
            "ms.channel.timeOut" -> {
                state.value = SamsungState.Error("No answer on the TV prompt")
                if (!connected.isCompleted) connected.completeExceptionally(IllegalStateException("prompt timed out"))
            }
            "ed.installedApp.get" -> {
                val arr = msg.optJSONObject("data")?.optJSONArray("data") ?: return
                apps.value = (0 until arr.length()).map { arr.getJSONObject(it) }
                    .map { SamsungApp(it.optString("appId"), it.optString("name"), it.optInt("app_type", 2), it.optString("icon")) }
                    .filter { it.id.isNotEmpty() }.sortedBy { it.name.lowercase() }
                Diag.log(TAG, "${apps.value.size} apps on TV")
                fetchIcons(apps.value)
            }
            "ed.apps.icon" -> {
                val b64 = msg.optJSONObject("data")?.optString("imageBase64").orEmpty()
                val app = synchronized(iconQueue) { iconInFlight.also { iconInFlight = null } }
                if (app != null && b64.isNotEmpty()) {
                    runCatching { IconCache.store(ctx, iconKey(app.id), Base64.getDecoder().decode(b64)) }
                        .onFailure { Diag.log(TAG, "icon decode failed for ${app.name}: ${it.message}") }
                }
                nextIcon()
            }
            "ms.channel.clientConnect", "ms.channel.clientDisconnect", "ms.channel.ready" -> {}
            "ms.error" -> Diag.log(TAG, "TV error: ${msg.optJSONObject("data")?.optString("message")}")
            else -> if (event.isNotEmpty()) Diag.log(TAG, "event $event")
        }
    }

    // ---- app icons (base64 over the channel, cached on disk) ----

    private val iconQueue = ArrayDeque<SamsungApp>()
    private var iconInFlight: SamsungApp? = null

    private fun fetchIcons(list: List<SamsungApp>) {
        synchronized(iconQueue) {
            iconQueue.clear()
            iconQueue.addAll(list.filter { it.iconPath.isNotEmpty() && !IconCache.has(ctx, iconKey(it.id)) })
        }
        nextIcon()
    }

    private fun nextIcon() {
        val app = synchronized(iconQueue) {
            if (iconInFlight != null) return
            iconQueue.removeFirstOrNull()?.also { iconInFlight = it }
        } ?: return
        ws?.send(SamsungMsg.icon(app.iconPath)) ?: return
        scope.launch {
            delay(6000)
            val stuck = synchronized(iconQueue) { if (iconInFlight === app) { iconInFlight = null; true } else false }
            if (stuck) nextIcon()
        }
    }

    // ---- public commands ----

    private fun send(json: String) { ws?.send(json) }

    fun key(name: String) = send(SamsungMsg.key(name))
    fun sendText(text: String) = send(SamsungMsg.text(text))
    fun inputEnd() = send(SamsungMsg.inputEnd())
    fun move(dx: Int, dy: Int) = send(SamsungMsg.mouseMove(dx, dy, System.currentTimeMillis()))
    fun click() = send(SamsungMsg.mouseClick())

    fun volumeUp() = key("KEY_VOLUP")
    fun volumeDown() = key("KEY_VOLDOWN")
    fun mute() = key("KEY_MUTE")
    /** KEY_POWER toggles on Tizen TVs. */
    fun powerToggle() = key("KEY_POWER")

    fun launchApp(app: SamsungApp) = send(SamsungMsg.launch(app.id, app.launchType))
    fun launchApp(id: String, type: String = "DEEP_LINK", meta: String = "") = send(SamsungMsg.launch(id, type, meta))
    fun openUrl(url: String) = launchApp(SamsungMsg.BROWSER, "NATIVE_LAUNCH", url)
    fun playYouTube(videoId: String) {
        Diag.log(TAG, "youtube play: $videoId")
        launchApp(SamsungMsg.YOUTUBE, "DEEP_LINK", "v=$videoId")
    }

    fun shutdown() { disconnect(); scope.cancel() }

    companion object {
        fun iconKey(appId: String) = "app:samsung:$appId"
    }
}
