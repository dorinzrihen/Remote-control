package com.dorin.remote.net

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import com.dorin.remote.Diag
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

data class UpdateInfo(val version: String, val notes: String, val apkUrl: String, val sizeBytes: Long)

/** Checks GitHub Releases for a newer build and installs it through the system package installer. */
object Updater {
    private const val REPO = "dorinzrihen/Remote-control"
    private val http = OkHttpClient.Builder().connectTimeout(8, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).build()

    suspend fun check(current: String): UpdateInfo? = withContext(Dispatchers.IO) {
        val req = Request.Builder().url("https://api.github.com/repos/$REPO/releases/latest")
            .header("Accept", "application/vnd.github+json").build()
        val body = http.newCall(req).execute().use { r ->
            if (!r.isSuccessful) { Diag.log("Updater", "release check http ${r.code}"); return@withContext null }
            r.body?.string() ?: return@withContext null
        }
        val json = JSONObject(body)
        val tag = json.optString("tag_name").removePrefix("v")
        val assets = json.optJSONArray("assets")
        var apkUrl = ""; var size = 0L
        if (assets != null) for (i in 0 until assets.length()) {
            val a = assets.getJSONObject(i)
            if (a.optString("name").endsWith(".apk")) { apkUrl = a.optString("browser_download_url"); size = a.optLong("size") }
        }
        Diag.log("Updater", "latest release $tag, installed $current")
        if (apkUrl.isEmpty() || !isNewer(tag, current)) null
        else UpdateInfo(tag, json.optString("body"), apkUrl, size)
    }

    fun isNewer(latest: String, current: String): Boolean {
        val a = latest.split('.').map { it.filter(Char::isDigit).toIntOrNull() ?: 0 }
        val b = current.split('.').map { it.filter(Char::isDigit).toIntOrNull() ?: 0 }
        for (i in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrElse(i) { 0 }; val y = b.getOrElse(i) { 0 }
            if (x != y) return x > y
        }
        return false
    }

    /** Downloads the APK into the app cache; [onProgress] gets 0..1. */
    suspend fun download(ctx: Context, info: UpdateInfo, onProgress: (Float) -> Unit): File = withContext(Dispatchers.IO) {
        val dir = File(ctx.cacheDir, "updates").apply { mkdirs() }
        val out = File(dir, "UniRemote-${info.version}.apk")
        http.newCall(Request.Builder().url(info.apkUrl).build()).execute().use { r ->
            if (!r.isSuccessful) throw IllegalStateException("download failed: HTTP ${r.code}")
            val body = r.body ?: throw IllegalStateException("empty download")
            val total = if (body.contentLength() > 0) body.contentLength() else info.sizeBytes
            body.byteStream().use { input ->
                out.outputStream().use { o ->
                    val buf = ByteArray(64 * 1024); var read: Int; var done = 0L
                    while (input.read(buf).also { read = it } >= 0) {
                        o.write(buf, 0, read); done += read
                        if (total > 0) onProgress((done.toFloat() / total).coerceIn(0f, 1f))
                    }
                }
            }
        }
        out
    }

    /** True when the app is allowed to open the installer; otherwise sends the user to the permission screen. */
    fun ensureInstallPermission(ctx: Context): Boolean {
        if (Build.VERSION.SDK_INT < 26 || ctx.packageManager.canRequestPackageInstalls()) return true
        ctx.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${ctx.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        return false
    }

    fun install(ctx: Context, apk: File) {
        val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.fileprovider", apk)
        ctx.startActivity(
            Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
        )
    }
}
