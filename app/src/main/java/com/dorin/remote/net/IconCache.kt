package com.dorin.remote.net

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

/** Downloads app icons once and keeps them on disk, so shortcut buttons keep their logos when the TV is off. */
object IconCache {
    private val http = OkHttpClient.Builder().connectTimeout(4, TimeUnit.SECONDS).readTimeout(6, TimeUnit.SECONDS).build()
    private val mem = ConcurrentHashMap<String, Bitmap>()
    /** Bumped whenever an icon arrives later (Samsung sends them over the channel), so buttons redraw. */
    val version = kotlinx.coroutines.flow.MutableStateFlow(0)

    private fun file(ctx: Context, key: String): File {
        val dir = File(ctx.filesDir, "icons").apply { mkdirs() }
        val h = MessageDigest.getInstance("MD5").digest(key.toByteArray()).joinToString("") { "%02x".format(it) }
        return File(dir, "$h.png")
    }

    /** [key] identifies the icon (app id or URL); [url] is where to fetch it if not cached yet. */
    suspend fun get(ctx: Context, key: String, url: String?): Bitmap? = withContext(Dispatchers.IO) {
        mem[key]?.let { return@withContext it }
        val f = file(ctx, key)
        if (f.exists()) BitmapFactory.decodeFile(f.path)?.let { mem[key] = it; return@withContext it }
        if (url.isNullOrEmpty()) return@withContext null
        runCatching {
            http.newCall(Request.Builder().url(url).build()).execute().use { r ->
                val bytes = r.body?.bytes() ?: return@use null
                val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return@use null
                f.outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
                mem[key] = bmp
                bmp
            }
        }.getOrNull()
    }

    fun has(ctx: Context, key: String): Boolean = mem.containsKey(key) || file(ctx, key).exists()

    /** Stores icon bytes that arrived some other way than a URL (e.g. base64 from a Samsung TV). */
    fun store(ctx: Context, key: String, bytes: ByteArray) {
        val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return
        file(ctx, key).outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
        mem[key] = bmp
        version.value = version.value + 1
    }

    fun faviconUrl(siteUrl: String): String {
        val host = runCatching { java.net.URI(siteUrl).host }.getOrNull() ?: siteUrl
        return "https://www.google.com/s2/favicons?domain=$host&sz=128"
    }
}
