package com.dorin.remote.webos

import android.util.Log
import com.dorin.remote.Diag
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
import org.json.JSONArray
import org.json.JSONObject
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

sealed class LgState {
    object Disconnected : LgState()
    object Connecting : LgState()
    object WaitingForPrompt : LgState() // user must press "Yes" on the TV
    object Connected : LgState()
    data class Error(val message: String) : LgState()
}

data class LgInput(val id: String, val label: String, val appId: String)
data class LgApp(val id: String, val title: String, val icon: String? = null)

private const val TAG = "WebOsClient"

/**
 * LG webOS TV client: SSAP WebSocket (port 3000 / 3001) plus the pointer input socket
 * used for cursor movement, clicks, scrolling and remote buttons.
 */
class WebOsClient(
    private val onClientKey: (String) -> Unit,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var connectJob: Job? = null
    private var ws: WebSocket? = null
    private var pointerWs: WebSocket? = null
    private val pending = ConcurrentHashMap<String, CompletableDeferred<JSONObject>>()
    private val subscriptions = ConcurrentHashMap<String, (JSONObject) -> Unit>()
    private val counter = AtomicInteger(1)
    private var sessionClosed = CompletableDeferred<Unit>()

    @Volatile var clientKey: String? = null
    @Volatile var host: String? = null

    val state = MutableStateFlow<LgState>(LgState.Disconnected)
    val inputs = MutableStateFlow<List<LgInput>>(emptyList())
    val volume = MutableStateFlow<Int?>(null)
    val muted = MutableStateFlow(false)
    val keyboardFocused = MutableStateFlow(false)
    val currentApp = MutableStateFlow("")
    val macAddress = MutableStateFlow<String?>(null)
    val tvName = MutableStateFlow<String?>(null)
    val backlight = MutableStateFlow<Int?>(null)
    val apps = MutableStateFlow<List<LgApp>>(emptyList())
    val pictureMode = MutableStateFlow<String?>(null)

    val isConnected: Boolean get() = state.value is LgState.Connected

    private val http: OkHttpClient by lazy {
        val tm = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {}
            override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
        }
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf<TrustManager>(tm), SecureRandom())
        OkHttpClient.Builder()
            .sslSocketFactory(ctx.socketFactory, tm)
            .hostnameVerifier { _, _ -> true }
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .pingInterval(15, TimeUnit.SECONDS)
            .build()
    }

    fun connect(ip: String, key: String?) {
        host = ip
        clientKey = key
        connectJob?.cancel()
        connectJob = scope.launch { runLoop(ip) }
    }

    fun disconnect() {
        connectJob?.cancel()
        connectJob = null
        closeSockets()
        state.value = LgState.Disconnected
    }

    private fun closeSockets() {
        try { pointerWs?.close(1000, null) } catch (_: Exception) {}
        try { ws?.close(1000, null) } catch (_: Exception) {}
        pointerWs = null
        ws = null
        pending.values.forEach { it.cancel() }
        pending.clear()
        subscriptions.clear()
    }

    private suspend fun runLoop(ip: String) {
        var backoff = 2000L
        while (scope.isActive && connectJob?.isActive == true) {
            state.value = LgState.Connecting
            try {
                session(ip)
                backoff = 2000L
            } catch (e: Exception) {
                Log.w(TAG, "session ended: ${e.message}")
                if (state.value !is LgState.Error) state.value = LgState.Error(e.message ?: "connection failed")
            } finally {
                closeSockets()
            }
            delay(backoff)
            backoff = (backoff * 2).coerceAtMost(15_000L)
        }
    }

    private suspend fun session(ip: String) {
        sessionClosed = CompletableDeferred()
        val socket = openMain(ip)
        ws = socket
        // Newer firmware wants hello + system info before registration.
        socket.send(JSONObject().put("id", "hello").put("type", "hello").put("payload", JSONObject()).toString())
        socket.send(JSONObject().put("id", "get_sys_info").put("type", "request")
            .put("uri", "ssap://system/getSystemInfo").put("payload", JSONObject()).toString())
        val regId = "register_0"
        val regDeferred = CompletableDeferred<JSONObject>()
        pending[regId] = regDeferred
        socket.send(registrationMessage(regId).toString())

        // wait for "registered" (pending is re-armed on the PROMPT response)
        val registered = withTimeout(120_000) { regDeferred.await() }
        val key = registered.optJSONObject("payload")?.optString("client-key").takeUnless { it.isNullOrEmpty() }
            ?: throw IllegalStateException("TV did not return a client key")
        if (key != clientKey) { clientKey = key; onClientKey(key) }

        // pointer socket
        val sock = request("ssap://com.webos.service.networkinput/getPointerInputSocket")
        val path = sock.optString("socketPath")
        if (path.isNotEmpty()) pointerWs = openPointer(path)

        state.value = LgState.Connected
        afterConnect()
        sessionClosed.await()
        throw IllegalStateException("socket closed")
    }

    private suspend fun afterConnect() {
        runCatching { request("ssap://system/getSystemInfo") }.getOrNull()?.let {
            tvName.value = it.optString("modelName").ifEmpty { null }
        }
        runCatching { request("ssap://com.webos.service.connectionmanager/getinfo") }.getOrNull()?.let { info ->
            val mac = info.optJSONObject("wifiInfo")?.optString("macAddress").takeUnless { it.isNullOrEmpty() }
                ?: info.optJSONObject("wiredInfo")?.optString("macAddress").takeUnless { it.isNullOrEmpty() }
            if (mac != null) macAddress.value = mac
        }
        runCatching { request("ssap://tv/getExternalInputList") }.getOrNull()?.let { res ->
            val arr = res.optJSONArray("devices") ?: JSONArray()
            inputs.value = (0 until arr.length()).map { i ->
                val o = arr.getJSONObject(i)
                LgInput(o.optString("id"), o.optString("label"), o.optString("appId"))
            }
        }
        runCatching { request("ssap://com.webos.applicationManager/listLaunchPoints") }.getOrNull()?.let { res ->
            val arr = res.optJSONArray("launchPoints") ?: JSONArray()
            apps.value = (0 until arr.length()).map { i ->
                val o = arr.getJSONObject(i)
                val icon = o.optString("largeIcon").ifEmpty { o.optString("icon") }.ifEmpty { null }
                LgApp(o.optString("id"), o.optString("title"), icon)
            }.filter { it.id.isNotEmpty() }.sortedBy { it.title.lowercase() }
            Diag.log(TAG, "${apps.value.size} apps on TV")
        }
        subscribe("ssap://audio/getStatus") { p ->
            volume.value = p.optInt("volume", volume.value ?: 0)
            muted.value = p.optBoolean("mute", muted.value)
        }
        subscribe("ssap://com.webos.applicationManager/getForegroundAppInfo") { p ->
            currentApp.value = p.optString("appId")
        }
        subscribe("ssap://com.webos.service.ime/registerRemoteKeyboard") { p ->
            val w = p.optJSONObject("currentWidget")
            if (w != null) {
                keyboardFocused.value = w.optBoolean("focus", false)
                Diag.log(TAG, "keyboard: $w")
            } else Diag.log(TAG, "keyboard event: $p")
        }
        subscribe("ssap://settings/getSystemSettings", JSONObject().put("category", "picture")
            .put("keys", JSONArray(listOf("backlight", "brightness", "pictureMode")))) { p ->
            val st = p.optJSONObject("settings") ?: return@subscribe
            st.optString("backlight").toIntOrNull()?.let { backlight.value = it }
            st.optString("pictureMode").ifEmpty { null }?.let { pictureMode.value = it }
        }
    }

    private fun registrationMessage(id: String): JSONObject {
        val perms = JSONArray(listOf(
            "APP_TO_APP", "CLOSE", "CONTROL_AUDIO", "CONTROL_DISPLAY", "CONTROL_INPUT_JOYSTICK",
            "CONTROL_INPUT_MEDIA_PLAYBACK", "CONTROL_INPUT_MEDIA_RECORDING", "CONTROL_INPUT_TEXT",
            "CONTROL_INPUT_TV", "CONTROL_MOUSE_AND_KEYBOARD", "CONTROL_POWER", "CONTROL_TV_SCREEN",
            "LAUNCH", "LAUNCH_WEBAPP", "READ_APP_STATUS", "READ_COUNTRY_INFO", "READ_CURRENT_CHANNEL",
            "READ_INPUT_DEVICE_LIST", "READ_INSTALLED_APPS", "READ_LGE_SDX", "READ_LGE_TV_INPUT_EVENTS",
            "READ_NETWORK_STATE", "READ_NOTIFICATIONS", "READ_POWER_STATE", "READ_RUNNING_APPS",
            "READ_SETTINGS", "READ_TV_CHANNEL_LIST", "READ_TV_CURRENT_TIME", "READ_UPDATE_INFO", "SEARCH",
            "TEST_OPEN", "TEST_PROTECTED", "TEST_SECURE", "UPDATE_FROM_REMOTE_APP",
            "WRITE_NOTIFICATION_ALERT", "WRITE_NOTIFICATION_TOAST", "WRITE_SETTINGS",
        ))
        val manifest = JSONObject()
            .put("appVersion", "1.1")
            .put("manifestVersion", 1)
            .put("permissions", perms)
        val payload = JSONObject()
            .put("forcePairing", false)
            .put("manifest", manifest)
            .put("pairingType", "PROMPT")
        clientKey?.let { payload.put("client-key", it) }
        return JSONObject().put("type", "register").put("id", id).put("payload", payload)
    }

    private suspend fun openMain(ip: String): WebSocket {
        return try {
            openSocket("ws://$ip:3000", ::onMainMessage)
        } catch (e: Exception) {
            Log.i(TAG, "ws:3000 failed (${e.message}), trying wss:3001")
            openSocket("wss://$ip:3001", ::onMainMessage)
        }
    }

    private suspend fun openPointer(path: String): WebSocket = openSocket(path) { _ -> }

    private suspend fun openSocket(url: String, onMessage: (String) -> Unit): WebSocket {
        val opened = CompletableDeferred<WebSocket>()
        val listener = object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) { opened.complete(webSocket) }
            override fun onMessage(webSocket: WebSocket, text: String) { onMessage(text) }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (!opened.isCompleted) opened.completeExceptionally(t) else sessionClosed.complete(Unit)
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { sessionClosed.complete(Unit) }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(1000, null) }
        }
        val socket = http.newWebSocket(Request.Builder().url(url).build(), listener)
        return withTimeout(6000) { opened.await() }
    }

    private fun onMainMessage(text: String) {
        val msg = runCatching { JSONObject(text) }.getOrNull() ?: return
        val id = msg.optString("id")
        val type = msg.optString("type")
        val payload = msg.optJSONObject("payload") ?: JSONObject()
        if (id == "register_0") {
            when (type) {
                "response" -> if (payload.optString("pairingType") == "PROMPT") { state.value = LgState.WaitingForPrompt; Diag.log(TAG, "TV shows pairing prompt") }
                "registered" -> { Diag.log(TAG, "registered"); pending.remove(id)?.complete(msg) }
                "error" -> {
                    Diag.log(TAG, "registration error: ${msg.optString("error")}")
                    state.value = LgState.Error("TV refused: ${msg.optString("error")}")
                    pending.remove(id)?.completeExceptionally(IllegalStateException(msg.optString("error")))
                }
            }
            return
        }
        subscriptions[id]?.let { it(payload); return }
        pending.remove(id)?.let { d ->
            if (type == "error") { Diag.log(TAG, "error for $id: ${msg.optString("error")}"); d.completeExceptionally(IllegalStateException(msg.optString("error"))) }
            else d.complete(payload)
        } ?: if (type == "error") Diag.log(TAG, "error: ${msg.optString("error")}") else Unit
    }

    // ---- SSAP requests ----

    suspend fun request(uri: String, payload: JSONObject = JSONObject()): JSONObject {
        val socket = ws ?: throw IllegalStateException("not connected")
        val id = "req_${counter.getAndIncrement()}"
        val d = CompletableDeferred<JSONObject>()
        pending[id] = d
        socket.send(JSONObject().put("id", id).put("type", "request").put("uri", uri).put("payload", payload).toString())
        return try {
            withTimeout(8000) { d.await() }
        } finally { pending.remove(id) }
    }

    /** Fire-and-forget request. */
    fun send(uri: String, payload: JSONObject = JSONObject()) {
        val socket = ws ?: return
        val id = "req_${counter.getAndIncrement()}"
        socket.send(JSONObject().put("id", id).put("type", "request").put("uri", uri).put("payload", payload).toString())
    }

    private fun subscribe(uri: String, payload: JSONObject = JSONObject(), handler: (JSONObject) -> Unit) {
        val socket = ws ?: return
        val id = "sub_${counter.getAndIncrement()}"
        subscriptions[id] = handler
        socket.send(JSONObject().put("id", id).put("type", "subscribe").put("uri", uri)
            .put("payload", payload.put("subscribe", true)).toString())
    }

    /**
     * Calls an internal luna:// API through the alert mechanism (the trick used by every webOS
     * library): an alert whose button runs the luna call, which we immediately close.
     */
    suspend fun luna(uri: String, params: JSONObject) {
        val lunaUri = "luna://$uri"
        val action = JSONObject().put("uri", lunaUri).put("params", params)
        val payload = JSONObject()
            .put("message", " ")
            .put("buttons", JSONArray().put(JSONObject().put("label", "").put("onClick", lunaUri).put("params", params)))
            .put("onclose", action)
            .put("onfail", action)
        val res = request("ssap://system.notifications/createAlert", payload)
        val alertId = res.optString("alertId")
        if (alertId.isNotEmpty()) request("ssap://system.notifications/closeAlert", JSONObject().put("alertId", alertId))
    }

    suspend fun setPictureSetting(key: String, value: String) {
        Diag.log(TAG, "set picture $key=$value")
        luna("com.webos.settingsservice/setSystemSettings",
            JSONObject().put("category", "picture").put("settings", JSONObject().put(key, value)))
    }

    fun screenOff() = send("ssap://com.webos.service.tvpower/power/turnOffScreen")
    fun screenOn() = send("ssap://com.webos.service.tvpower/power/turnOnScreen")

    // ---- pointer socket (mouse / buttons) ----

    private fun pointer(msg: String) { pointerWs?.send(msg) }

    fun button(name: String) = pointer("type:button\nname:$name\n\n")
    fun move(dx: Int, dy: Int, drag: Boolean = false) = pointer("type:move\ndx:$dx\ndy:$dy\ndown:${if (drag) 1 else 0}\n\n")
    fun click() = pointer("type:click\n\n")
    fun scroll(dx: Int, dy: Int) = pointer("type:scroll\ndx:$dx\ndy:$dy\n\n")

    // ---- convenience ----

    fun volumeUp() = send("ssap://audio/volumeUp")
    fun volumeDown() = send("ssap://audio/volumeDown")
    fun setMute(mute: Boolean) = send("ssap://audio/setMute", JSONObject().put("mute", mute))
    fun powerOff() = send("ssap://system/turnOff")
    fun launchApp(id: String) = send("ssap://system.launcher/launch", JSONObject().put("id", id))
    fun launchApp(id: String, params: JSONObject) = send("ssap://system.launcher/launch", JSONObject().put("id", id).put("params", params))
    /** Opens a URL in the TV's web browser. */
    fun openUrl(url: String) = send("ssap://system.launcher/open", JSONObject().put("target", url))
    /** Verified on webOS 26: contentTarget "v=<id>" plays the video. */
    fun playYouTube(videoId: String) {
        Diag.log(TAG, "youtube play: $videoId")
        launchApp("youtube.leanback.v4", JSONObject().put("contentTarget", "v=$videoId"))
    }
    fun switchInput(id: String) = send("ssap://tv/switchInput", JSONObject().put("inputId", id))
    suspend fun insertText(text: String): String? = imeCall("ssap://com.webos.service.ime/insertText", JSONObject().put("text", text).put("replace", false))
    suspend fun deleteChars(count: Int): String? = imeCall("ssap://com.webos.service.ime/deleteCharacters", JSONObject().put("count", count))
    suspend fun sendEnter(): String? = imeCall("ssap://com.webos.service.ime/sendEnterKey")

    /** Returns null on success or the TV's error text. */
    private suspend fun imeCall(uri: String, payload: JSONObject = JSONObject()): String? = try {
        val r = request(uri, payload)
        if (r.optBoolean("returnValue", true)) null else (r.optString("errorText").ifEmpty { "returnValue=false" })
    } catch (e: Exception) {
        Diag.log(TAG, "${uri.substringAfterLast('/')} failed: ${e.message}")
        e.message ?: "failed"
    }
    fun toast(text: String) = send("ssap://system.notifications/createToast", JSONObject().put("message", text))
    fun play() = send("ssap://media.controls/play")
    fun pause() = send("ssap://media.controls/pause")
    fun rewind() = send("ssap://media.controls/rewind")
    fun fastForward() = send("ssap://media.controls/fastForward")

    fun shutdown() { disconnect(); scope.cancel() }
}
