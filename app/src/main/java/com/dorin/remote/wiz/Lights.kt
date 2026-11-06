package com.dorin.remote.wiz

import com.dorin.remote.Prefs
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import org.json.JSONArray
import org.json.JSONObject

/** A saved bulb. The MAC is its identity; the IP is refreshed from discovery when the router hands out a new one. */
data class Bulb(val mac: String, val ip: String, val room: String)

/** The saved WiZ bulbs, grouped by room, and the commands for them. Lives in App so the 21:00 alarm can use it without the UI. */
class Lights(private val prefs: Prefs) {
    val bulbs = MutableStateFlow(load())
    /** Last state each saved bulb reported, by MAC. A bulb missing here did not answer. */
    val pilots = MutableStateFlow<Map<String, Pilot>>(emptyMap())
    val systemConfigs = MutableStateFlow<Map<String, SystemConfig>>(emptyMap())

    suspend fun readSystemConfigs() {
        systemConfigs.value = eachBulb(bulbs.value) { b -> Wiz.getSystemConfig(b.ip)?.takeIf { it.mac == b.mac } }
    }

    fun add(mac: String, ip: String, room: String) = store(bulbs.value.filterNot { it.mac == mac } + Bulb(mac, ip, room))
    fun remove(mac: String) = store(bulbs.value.filterNot { it.mac == mac })

    /** Asks the whole network. Saved bulbs whose IP changed are updated; returns everything that answered (ip -> state). */
    suspend fun discover(): Map<String, Pilot> {
        val found = Wiz.discover()
        val ipByMac = found.entries.associate { (ip, p) -> p.mac to ip }
        val updated = bulbs.value.map { b -> ipByMac[b.mac]?.let { b.copy(ip = it) } ?: b }
        if (updated != bulbs.value) store(updated)
        val saved = updated.map { it.mac }.toSet()
        pilots.value = pilots.value + found.values.filter { it.mac in saved }.associateBy { it.mac }
        return found
    }

    /** Reads the state of every saved bulb. */
    suspend fun refresh() {
        pilots.value = eachBulb(bulbs.value) { b -> Wiz.getPilot(b.ip)?.takeIf { it.mac == b.mac } }
    }

    /** Sets every bulb in the room; a null mode turns them off. Returns how many bulbs answered. */
    suspend fun setRoom(room: String, mode: LightMode?): Int {
        check(!prefs.butlerPending) { "Butler settings unconfirmed. Load and Save them before sending commands." }
        // Serialize manual intent with the scheduler. If the laptop is down,
        // fail visibly rather than silently send an override it cannot see.
        if (prefs.butlerEnabled) return ButlerClient.room(prefs, room, mode?.name ?: "OFF").also { refresh() }
        val json = if (mode == null) Wiz.setStateJson(false) else Wiz.setModeJson(mode)
        val ok = eachBulb(bulbs.value.filter { it.room == room }) { b -> Wiz.request(b.ip, json) }
        refresh()
        return ok.size
    }

    /** The 21:00 job: bulbs that are on switch to Night, bulbs that are off stay off. Returns how many were switched. */
    suspend fun nightIfOn(): Int {
        val states = eachBulb(bulbs.value) { b -> Wiz.getPilot(b.ip)?.takeIf { it.mac == b.mac } }
        val on = bulbs.value.filter { states[it.mac]?.on == true }
        val json = Wiz.setModeJson(LightMode.NIGHT)
        val ok = eachBulb(on) { b -> Wiz.request(b.ip, json) }
        refresh()
        return ok.size
    }

    /** Flashes a bulb twice so you can tell which one it is, then leaves it as it was. */
    suspend fun blink(ip: String) {
        val was = Wiz.getPilot(ip)?.on ?: true
        repeat(2) {
            Wiz.request(ip, Wiz.setStateJson(!was), tries = 1); delay(600)
            Wiz.request(ip, Wiz.setStateJson(was), tries = 1); delay(600)
        }
    }

    /** Runs [op] on every bulb at once. Bulbs that do not answer get one more try after a network search, in case their IP changed. */
    private suspend fun <T : Any> eachBulb(list: List<Bulb>, op: suspend (Bulb) -> T?): Map<String, T> {
        val done = parallel(list, op)
        val missing = list.filter { it.mac !in done }
        if (missing.isEmpty()) return done
        discover()
        val moved = bulbs.value.filter { b -> missing.any { it.mac == b.mac && it.ip != b.ip } }
        return done + parallel(moved, op)
    }

    private suspend fun <T : Any> parallel(list: List<Bulb>, op: suspend (Bulb) -> T?): Map<String, T> = coroutineScope {
        list.map { b -> async { op(b)?.let { b.mac to it } } }.awaitAll().filterNotNull().toMap()
    }

    private fun load(): List<Bulb> = runCatching {
        val arr = JSONArray(prefs.bulbs ?: return emptyList())
        (0 until arr.length()).map { arr.getJSONObject(it) }.map { Bulb(it.getString("mac"), it.getString("ip"), it.getString("room")) }
    }.getOrDefault(emptyList())

    private fun store(list: List<Bulb>) {
        bulbs.value = list
        prefs.bulbs = JSONArray(list.map { JSONObject().put("mac", it.mac).put("ip", it.ip).put("room", it.room) }).toString()
    }
}
