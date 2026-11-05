package com.dorin.remote.wiz

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.SocketTimeoutException

/** A fixed light setting for a room. */
enum class LightMode(val label: String, val dimming: Int, val temp: Int) {
    /** Everyday: full brightness, cool white. */
    REGULAR("Regular", 100, 6500),
    /** Movie / night: dim and warm. */
    NIGHT("Night", 20, 2700);

    companion object {
        /** The mode a bulb is showing, or null when it is off or set to something else (for example from the WiZ app). */
        fun of(p: Pilot): LightMode? = if (!p.on) null else entries.firstOrNull { it.dimming == p.dimming && it.temp == p.temp }
    }
}

/** What a bulb answers to getPilot. temp is null when the bulb shows a colour or a WiZ scene. */
data class Pilot(val mac: String, val on: Boolean, val dimming: Int?, val temp: Int?)

private const val TAG = "Wiz"

/** WiZ bulbs take JSON commands over UDP port 38899 on the local network: no cloud and no pairing. */
object Wiz {
    const val PORT = 38899

    fun getPilotJson(): String = JSONObject().put("method", "getPilot").put("params", JSONObject()).toString()
    fun setModeJson(mode: LightMode): String = setPilot(JSONObject().put("state", true).put("dimming", mode.dimming).put("temp", mode.temp))
    /** The state alone keeps the bulb's last colour and brightness. */
    fun setStateJson(on: Boolean): String = setPilot(JSONObject().put("state", on))
    private fun setPilot(params: JSONObject) = JSONObject().put("method", "setPilot").put("params", params).toString()

    fun parsePilot(text: String): Pilot? = runCatching {
        val r = JSONObject(text).getJSONObject("result")
        Pilot(r.getString("mac"), r.getBoolean("state"), r.optInt("dimming", -1).takeIf { it >= 0 }, r.optInt("temp", -1).takeIf { it > 0 })
    }.getOrNull()

    /** Sends one command and returns the bulb's reply, or null. UDP can drop a packet, so it tries more than once. */
    suspend fun request(ip: String, json: String, timeoutMs: Int = 1000, tries: Int = 2): String? = withContext(Dispatchers.IO) {
        runCatching {
            DatagramSocket().use { s ->
                s.soTimeout = timeoutMs
                val data = json.toByteArray()
                val addr = InetAddress.getByName(ip)
                val buf = ByteArray(1024)
                repeat(tries) {
                    s.send(DatagramPacket(data, data.size, addr, PORT))
                    val p = DatagramPacket(buf, buf.size)
                    try { s.receive(p); return@use String(p.data, 0, p.length) } catch (_: SocketTimeoutException) {}
                }
                null
            }
        }.getOrNull()
    }

    suspend fun getPilot(ip: String): Pilot? = request(ip, getPilotJson())?.let(::parsePilot)

    /** Every WiZ device on the Wi-Fi answers a broadcast getPilot. Returns ip -> state. */
    suspend fun discover(timeoutMs: Long = 2500): Map<String, Pilot> = withContext(Dispatchers.IO) {
        val found = LinkedHashMap<String, Pilot>()
        runCatching {
            DatagramSocket().use { s ->
                s.broadcast = true
                s.soTimeout = 500
                val data = getPilotJson().toByteArray()
                val targets = broadcastAddresses() + InetAddress.getByName("255.255.255.255")
                repeat(2) { targets.forEach { a -> runCatching { s.send(DatagramPacket(data, data.size, a, PORT)) } } }
                val end = System.currentTimeMillis() + timeoutMs
                val buf = ByteArray(1024)
                while (System.currentTimeMillis() < end) {
                    val p = DatagramPacket(buf, buf.size)
                    try { s.receive(p) } catch (_: SocketTimeoutException) { continue }
                    val ip = p.address.hostAddress ?: continue
                    parsePilot(String(p.data, 0, p.length))?.let { found[ip] = it }
                }
            }
        }.onFailure { Log.w(TAG, "discovery failed", it) }
        found
    }

    /** The subnet broadcast address of each network the phone is on (some routers drop 255.255.255.255). */
    private fun broadcastAddresses(): List<InetAddress> = runCatching {
        NetworkInterface.getNetworkInterfaces().toList().filter { it.isUp && !it.isLoopback }
            .flatMap { it.interfaceAddresses }.mapNotNull { it.broadcast }
    }.getOrDefault(emptyList())
}
