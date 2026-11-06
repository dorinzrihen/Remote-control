package com.dorin.remote.wiz

import com.dorin.remote.Prefs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** Explicitly configured LAN fallback, not WiZ cloud access or native Rhythms. */
object ButlerClient {
    private val http = OkHttpClient.Builder().connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS).callTimeout(35, TimeUnit.SECONDS)
        .followRedirects(false).followSslRedirects(false).build()

    fun config(enabled: Boolean, night: String, morning: String, timezone: String, bulbs: List<Bulb>, pollSeconds: Int = 1): JSONObject =
        JSONObject().put("enabled", enabled).put("night", night).put("morning", morning).put("timezone", timezone)
            .put("pollSeconds", pollSeconds)
            .put("bulbs", JSONArray(bulbs.map { JSONObject().put("mac", it.mac).put("ip", it.ip).put("room", it.room) }))

    fun validateConnection(url: String, token: String) {
        val base = url.trim().trimEnd('/').toHttpUrl()
        require(base.scheme in listOf("http", "https") && base.username.isEmpty() && base.password.isEmpty() && base.encodedPath == "/" && base.query == null && base.fragment == null) {
            "Use the butler base URL, e.g. http://192.168.1.10:8788"
        }
        require(token.length >= 32 && token.all { it.code in 33..126 }) { "Enter the butler token (at least 32 ASCII characters)" }
    }

    suspend fun exchange(url: String, token: String, path: String, body: JSONObject? = null): JSONObject = withContext(Dispatchers.IO) {
        validateConnection(url, token)
        val base = url.trim().trimEnd('/').toHttpUrl()
        val request = Request.Builder().url(base.newBuilder().encodedPath(path).build()).header("Authorization", "Bearer $token")
        if (body != null) request.post(body.toString().toRequestBody("application/json".toMediaType()))
        http.newCall(request.build()).execute().use { response ->
            val result = JSONObject(response.body?.string() ?: "{}")
            check(response.isSuccessful) { result.optString("error", "Butler HTTP ${response.code}") }
            result
        }
    }

    suspend fun room(prefs: Prefs, room: String, mode: String): Int = exchange(
        prefs.butlerUrl, prefs.butlerToken, "/v1/room", JSONObject().put("room", room).put("mode", mode),
    ).getInt("answered")
}
