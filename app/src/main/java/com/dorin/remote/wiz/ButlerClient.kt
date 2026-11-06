package com.dorin.remote.wiz

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import org.json.JSONObject
import java.io.IOException
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

    /** Mutations must never be replayed, including OkHttp's HTTP-status follow-ups. */
    private fun oneShotJson(body: JSONObject): RequestBody {
        val json = body.toString().toRequestBody("application/json".toMediaType())
        return object : RequestBody() {
            override fun contentType() = json.contentType()
            override fun contentLength() = json.contentLength()
            override fun isOneShot() = true
            override fun writeTo(sink: BufferedSink) = json.writeTo(sink)
        }
    }

    suspend fun exchange(url: String, path: String, body: JSONObject? = null): JSONObject = withContext(Dispatchers.IO) {
        validateConnection(url)
        val base = url.trim().trimEnd('/').toHttpUrl()
        val request = Request.Builder().url(base.newBuilder().encodedPath(path).build())
        if (body != null) request.post(oneShotJson(body))
        http.newCall(request.build()).execute().use { response ->
            val result = JSONObject(response.body?.string() ?: "{}")
            if (response.code == 409 && path == "/v1/config") throw TimetableConflict()
            // A timeout/server error cannot establish that a mutation had no effect.
            if (response.code == 408 || response.code >= 500) throw IOException(result.optString("error", "Butler HTTP ${response.code}"))
            if (!response.isSuccessful) throw ButlerRequestRejected(result.optString("error", "Butler HTTP ${response.code}"))
            result
        }
    }

}
