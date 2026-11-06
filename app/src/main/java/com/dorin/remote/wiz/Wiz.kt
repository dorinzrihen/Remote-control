package com.dorin.remote.wiz

/** Display presets; only the manager sends WiZ commands or decides the schedule. */
enum class LightMode(val label: String, val dimming: Int, val temp: Int) {
    REGULAR("Regular", 100, 6500),
    NIGHT("Night", 20, 2700);

    companion object {
        fun of(p: Pilot): LightMode? = if (!p.on) null else entries.firstOrNull { it.dimming == p.dimming && it.temp == p.temp }
    }
}

data class Pilot(val mac: String, val on: Boolean, val dimming: Int?, val temp: Int?)
data class SystemConfig(val mac: String, val moduleName: String, val fwVersion: String)
