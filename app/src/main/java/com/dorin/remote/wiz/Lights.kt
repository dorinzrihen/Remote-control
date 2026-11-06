package com.dorin.remote.wiz

import com.dorin.remote.Prefs
import kotlinx.coroutines.flow.MutableStateFlow
import org.json.JSONObject

/** Bulb identity and address supplied by the manager, never a phone-owned list. */
data class Bulb(val mac: String, val ip: String, val room: String)

/** HTTP-only lighting client. There is deliberately no bulb network transport on Android. */
class Lights(private val exchange: suspend (String, JSONObject?) -> JSONObject) {
    constructor(prefs: Prefs) : this({ path, body -> ButlerClient.exchange(prefs.butlerUrl, path, body) })

    val bulbs = MutableStateFlow<List<Bulb>>(emptyList())
    val pilots = MutableStateFlow<Map<String, Pilot>>(emptyMap())
    val systemConfigs = MutableStateFlow<Map<String, SystemConfig>>(emptyMap())
    val observationAges = MutableStateFlow<Map<String, Int>>(emptyMap())
    val config = MutableStateFlow<JSONObject?>(null)
    val error = MutableStateFlow<String?>(null)
    val loaded = MutableStateFlow(false)
    val managerConnection = ManagerConnectionStatus()
    val roomControls = MutableStateFlow<Map<String, RoomControlState>>(emptyMap())

    /** Only selected manager responses replace these views. No prefs.bulbs bootstrap. */
    fun acceptStatus(status: JSONObject) {
        val settings = status.getJSONObject("config")
        val list = settings.getJSONArray("bulbs")
        val saved = (0 until list.length()).map { list.getJSONObject(it) }.map {
            Bulb(it.getString("mac").lowercase(), it.getString("ip"), it.getString("room"))
        }
        val states = status.getJSONObject("pilots")
        val systems = status.getJSONObject("systemConfigs")
        val errors = status.getJSONObject("errors")
        val observedAt = status.optJSONObject("observedAt") ?: JSONObject()
        val statusAt = status.optDouble("statusAt", System.currentTimeMillis() / 1000.0)
        val maximumAge = maxOf(5, settings.optInt("pollSeconds", 1) * 3)
        observationAges.value = saved.mapNotNull { b ->
            if (!observedAt.has(b.mac)) null else b.mac to (statusAt - observedAt.getDouble(b.mac)).toInt().coerceAtLeast(0)
        }.toMap()
        bulbs.value = saved
        pilots.value = saved.mapNotNull { b ->
            states.optJSONObject(b.mac)?.takeIf {
                it.optString("mac").lowercase() == b.mac && !errors.has(b.mac) && (observationAges.value[b.mac] ?: Int.MAX_VALUE) <= maximumAge
            }?.let {
                b.mac to Pilot(b.mac, it.getBoolean("state"), it.optInt("dimming", -1).takeIf { n -> n >= 0 }, it.optInt("temp", -1).takeIf { n -> n > 0 })
            }
        }.toMap()
        systemConfigs.value = saved.mapNotNull { b ->
            systems.optJSONObject(b.mac)?.takeIf { it.optString("mac").lowercase() == b.mac }?.let {
                b.mac to SystemConfig(b.mac, it.optString("moduleName"), it.optString("fwVersion"))
            }
        }.toMap()
        config.value = settings
        val holds = status.optJSONObject("holds")?.let { values ->
            values.keys().asSequence().associate { it.lowercase() to values.optDouble(it, Double.NaN) }
        }
        roomControls.value = saved.groupBy { it.room }.mapValues { (_, roomBulbs) ->
            roomControlState(roomBulbs.map { it.mac }, pilots.value, true,
                if (settings.has("enabled")) settings.getBoolean("enabled") else null,
                holds, if (status.has("statusAt")) status.optDouble("statusAt", Double.NaN) else null)
        }
        val reported = errors.keys().asSequence().map { "…${it.takeLast(4)}: ${errors.getString(it)}" }.toList()
        val stale = saved.filter { states.has(it.mac) && (observationAges.value[it.mac] ?: Int.MAX_VALUE) > maximumAge }
            .map { "…${it.mac.takeLast(4)}: manager observation stale / age unknown" }
        error.value = (reported + stale).takeIf { it.isNotEmpty() }?.joinToString("; ")
        loaded.value = true
        managerConnection.connected()
    }

    fun unavailable(message: String) {
        managerConnection.unavailable()
        loaded.value = false
        pilots.value = emptyMap()
        roomControls.value = bulbs.value.map { it.room }.distinct().associateWith {
            RoomControlState(status = "manager unavailable / status unknown")
        }
        error.value = "Manager unavailable: $message. No direct bulb command was sent."
    }

    suspend fun refresh() {
        try { acceptStatus(exchange("/v1/status", null)) }
        catch (e: Exception) { unavailable(e.message ?: "Connection failed"); throw e }
    }

    suspend fun add(mac: String, ip: String, room: String) {
        acceptStatus(exchange("/v1/bulbs/add", JSONObject().put("mac", mac).put("ip", ip).put("room", room)))
    }

    suspend fun remove(mac: String) {
        acceptStatus(exchange("/v1/bulbs/remove", JSONObject().put("mac", mac)))
    }

    suspend fun discover(): Map<String, Pilot> {
        val result = exchange("/v1/discover", JSONObject())
        acceptStatus(result.getJSONObject("status"))
        val found = result.getJSONArray("discovered")
        return (0 until found.length()).mapNotNull { index ->
            val bulb = found.getJSONObject(index)
            val mac = bulb.getString("mac").lowercase()
            val p = bulb.getJSONObject("pilot")
            if (p.getString("mac").lowercase() != mac) null else bulb.getString("ip") to
                Pilot(mac, p.getBoolean("state"), p.optInt("dimming", -1).takeIf { it >= 0 }, p.optInt("temp", -1).takeIf { it > 0 })
        }.toMap()
    }

    suspend fun command(room: String, mode: String): Int {
        val result = exchange("/v1/room", JSONObject().put("room", room).put("mode", mode))
        refresh()
        val ok = result.getInt("answered")
        if (ok == 0) throw BulbsDidNotAnswer(room, result.optJSONObject("errors")?.toString() ?: "No bulbs acknowledged the manager command")
        check(ok > 0) { "Invalid acknowledgement count from the lighting manager" }
        return ok
    }

    suspend fun setRoom(room: String, mode: LightMode?): Int = command(room, mode?.name ?: "OFF")

    suspend fun blink(mac: String) {
        acceptStatus(exchange("/v1/bulbs/blink", JSONObject().put("mac", mac)))
    }
}
