package com.dorin.remote.wiz

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class ButlerRequestRejected(message: String) : IllegalStateException(message)

/** Home-LAN connection to the sole lighting manager, never a UDP fallback. */
object ButlerClient {
    private val http = OkHttpClient.Builder().connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS).callTimeout(35, TimeUnit.SECONDS)
        .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false).build()

    fun config(enabled: Boolean, night: String, morning: String, timezone: String, pollSeconds: Int = 1): JSONObject =
        JSONObject().put("enabled", enabled).put("night", night).put("morning", morning).put("timezone", timezone)
            .put("pollSeconds", pollSeconds)

    fun validateConnection(url: String) {
        val base = url.trim().trimEnd('/').toHttpUrl()
        require(base.scheme in listOf("http", "https") && base.username.isEmpty() && base.password.isEmpty() && base.encodedPath == "/" && base.query == null && base.fragment == null) {
            "Use the butler base URL, e.g. http://192.168.1.10:8788"
        }
    }

    suspend fun exchange(url: String, path: String, body: JSONObject? = null): JSONObject = withContext(Dispatchers.IO) {
        validateConnection(url)
        val base = url.trim().trimEnd('/').toHttpUrl()
        val request = Request.Builder().url(base.newBuilder().encodedPath(path).build())
        if (body != null) request.post(body.toString().toRequestBody("application/json".toMediaType()))
        http.newCall(request.build()).execute().use { response ->
            val result = JSONObject(response.body?.string() ?: "{}")
            if (response.code == 409 && path == "/v1/config") throw TimetableConflict()
            if (!response.isSuccessful) throw ButlerRequestRejected(result.optString("error", "Butler HTTP ${response.code}"))
            result
        }
    }

}
