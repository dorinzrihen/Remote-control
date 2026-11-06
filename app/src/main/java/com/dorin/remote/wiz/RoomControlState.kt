package com.dorin.remote.wiz

enum class RoomControlChoice { REGULAR, NIGHT, FOLLOW }

data class RoomControlState(val selected: RoomControlChoice? = null, val status: String)

/** Pure display logic: manager time/holds decide ownership, never local tap memory. */
fun roomControlState(
    macs: List<String>,
    pilots: Map<String, Pilot>,
    loaded: Boolean,
    enabled: Boolean?,
    holds: Map<String, Double>?,
    statusAt: Double?,
): RoomControlState {
    if (!loaded) return RoomControlState(status = "manager unavailable / status unknown")
    val states = macs.mapNotNull { pilots[it] }
    if (states.size < macs.size) return RoomControlState(status = "${macs.size - states.size} unreachable / status unknown")
    if (states.isEmpty()) return RoomControlState(status = "status unknown")
    val physical = states.map { if (!it.on) "off" else LightMode.of(it)?.label ?: "on" }.distinct()
    val appearance = physical.singleOrNull() ?: "Mixed"
    if (enabled == null || holds == null || statusAt == null || !statusAt.isFinite() || holds.values.any { !it.isFinite() }) {
        return RoomControlState(status = "control mode unknown · $appearance")
    }
    val held = macs.count { (holds[it] ?: 0.0) > statusAt }
    if (enabled && held == 0) return RoomControlState(RoomControlChoice.FOLLOW, "Following · $appearance")
    if (enabled && held < macs.size) return RoomControlState(status = "Mixed · manual / following")
    val selected = when (appearance) {
        "Regular" -> RoomControlChoice.REGULAR
        "Night" -> RoomControlChoice.NIGHT
        else -> null
    }
    return RoomControlState(selected, appearance)
}
