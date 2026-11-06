package com.dorin.remote.net

import android.os.Build
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Only debug emulators use the host's read-only SSDP bridge; phones keep native discovery. */
object EmulatorDiscovery {
    internal fun shouldUseHostBridge(fingerprint: String, hardware: String): Boolean =
        fingerprint.startsWith("generic") || hardware in setOf("ranchu", "goldfish")

    private val isEmulator: Boolean
        get() = shouldUseHostBridge(Build.FINGERPRINT, Build.HARDWARE)

    suspend fun find(kind: String): List<FoundDevice>? = withContext(Dispatchers.IO) {
        if (!isEmulator || kind !in setOf("lg", "samsung")) return@withContext null
        val connection = URL("http://127.0.0.1:18765/discover/$kind").openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 500
            connection.readTimeout = 5000
            val body = JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
            val devices = body.getJSONArray("devices")
            List(devices.length()) { index ->
                val device = devices.getJSONObject(index)
                FoundDevice(device.getString("ip"), device.getString("name"))
            }
        } catch (e: Exception) {
            Log.i("Discovery", "Host SSDP bridge unavailable; falling back to native discovery", e)
            null
        } finally {
            connection.disconnect()
        }
    }
}
