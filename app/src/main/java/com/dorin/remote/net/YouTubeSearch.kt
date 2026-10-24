package com.dorin.remote.net

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

data class YtVideo(val id: String, val title: String, val channel: String, val duration: String, val thumb: String)

/** Searches YouTube from the phone by reading the public results page; no API key needed. */
object YouTubeSearch {
    private val http = OkHttpClient.Builder().connectTimeout(8, TimeUnit.SECONDS).readTimeout(12, TimeUnit.SECONDS).build()
    private const val UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

    private val marker = Regex("""ytInitialData(?:"\])?\s*=\s*\{""")

    suspend fun search(query: String): List<YtVideo> = withContext(Dispatchers.IO) {
        var lastError: Exception? = null
        // YouTube occasionally serves a page variant without the data blob; retry a couple of times.
        repeat(3) { attempt ->
            try {
                val res = fetch(query, attempt)
                if (res.isNotEmpty()) return@withContext res
            } catch (e: Exception) { lastError = e }
        }
        throw lastError ?: IllegalStateException("No results")
    }

    private fun fetch(query: String, attempt: Int): List<YtVideo> {
        val q = URLEncoder.encode(query.trim(), "UTF-8")
        val url = "https://www.youtube.com/results?search_query=$q&hl=en" + if (attempt > 0) "&sp=EgIQAQ%253D%253D" else ""
        val req = Request.Builder().url(url).header("User-Agent", UA).header("Accept-Language", "en,he;q=0.8")
            .header("Cookie", "CONSENT=YES+1; SOCS=CAI; PREF=hl=en").build()
        val html = http.newCall(req).execute().use { it.body?.string() ?: "" }
        val m = marker.find(html) ?: throw IllegalStateException("YouTube page format not recognised (attempt ${attempt + 1})")
        val jsonStart = m.range.last // index of '{'
        val end = html.indexOf(";</script>", jsonStart)
        val data = JSONObject(html.substring(jsonStart, if (end > 0) end else html.length))
        val out = ArrayList<YtVideo>()
        collect(data, out)
        return out.distinctBy { it.id }.take(25)
    }

    private fun collect(node: Any?, out: MutableList<YtVideo>) {
        when (node) {
            is JSONObject -> {
                node.optJSONObject("videoRenderer")?.let { v ->
                    val id = v.optString("videoId")
                    val title = v.optJSONObject("title")?.optJSONArray("runs")?.optJSONObject(0)?.optString("text") ?: ""
                    val channel = v.optJSONObject("ownerText")?.optJSONArray("runs")?.optJSONObject(0)?.optString("text") ?: ""
                    val duration = v.optJSONObject("lengthText")?.optString("simpleText") ?: ""
                    val thumbs = v.optJSONObject("thumbnail")?.optJSONArray("thumbnails")
                    val thumb = thumbs?.optJSONObject(0)?.optString("url") ?: ""
                    if (id.isNotEmpty() && title.isNotEmpty()) out.add(YtVideo(id, title, channel, duration, thumb))
                }
                val keys = node.keys()
                while (keys.hasNext()) collect(node.opt(keys.next()), out)
            }
            is JSONArray -> for (i in 0 until node.length()) collect(node.opt(i), out)
        }
    }

    suspend fun thumbnail(url: String): Bitmap? = withContext(Dispatchers.IO) {
        runCatching {
            http.newCall(Request.Builder().url(url).build()).execute().use { r ->
                r.body?.bytes()?.let { BitmapFactory.decodeByteArray(it, 0, it.size) }
            }
        }.getOrNull()
    }
}
