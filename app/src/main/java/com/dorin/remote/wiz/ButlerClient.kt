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
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/** Authenticated connection to the sole lighting manager, never a UDP fallback. */
object ButlerClient {
    private val http = OkHttpClient.Builder().connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS).callTimeout(35, TimeUnit.SECONDS)
        .followRedirects(false).followSslRedirects(false).build()

    fun config(enabled: Boolean, night: String, morning: String, timezone: String, pollSeconds: Int = 1): JSONObject =
        JSONObject().put("enabled", enabled).put("night", night).put("morning", morning).put("timezone", timezone)
            .put("pollSeconds", pollSeconds)

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

    private suspend fun publicPost(url: String, path: String, body: JSONObject): JSONObject = withContext(Dispatchers.IO) {
        val base = url.trim().trimEnd('/').toHttpUrl()
        val request = Request.Builder().url(base.newBuilder().encodedPath(path).build())
            .post(body.toString().toRequestBody("application/json".toMediaType())).build()
        http.newCall(request).execute().use { response ->
            val result = JSONObject(response.body?.string() ?: "{}")
            check(response.isSuccessful) { result.optString("error", "Butler HTTP ${response.code}") }
            result
        }
    }

    suspend fun pair(url: String, code: String): String {
        require(code.matches(Regex("[0-9]{6}"))) { "Enter the six-digit code shown on the Mac" }
        val token = publicPost(url, "/v1/pair", JSONObject().put("code", code)).getString("token")
        validateConnection(url, token)
        return token
    }

    /** Never send a saved credential to a new address just because mDNS advertised it. */
    suspend fun verifyManager(url: String, token: String): Boolean {
        validateConnection(url, token)
        val nonce = ByteArray(32).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
        val mac = Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(token.toByteArray(), "HmacSHA256")) }
        val expected = mac.doFinal("uniremote-manager-v1:$nonce".toByteArray()).joinToString("") { "%02x".format(it) }
        val proof = publicPost(url, "/v1/identity", JSONObject().put("nonce", nonce)).optString("proof")
        return MessageDigest.isEqual(expected.toByteArray(), proof.toByteArray())
    }

}
