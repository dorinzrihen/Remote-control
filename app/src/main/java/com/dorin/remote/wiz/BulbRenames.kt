package com.dorin.remote.wiz

/** Text being typed on this phone, by MAC. A bulb's saved name only ever comes from the manager. */
data class BulbRenames(val drafts: Map<String, String> = emptyMap(), val saving: Set<String> = emptySet()) {
    fun open(bulb: Bulb) = if (bulb.mac in drafts) this else copy(drafts = drafts + (bulb.mac to bulb.room))
    fun type(mac: String, text: String) = if (mac in drafts && mac !in saving) copy(drafts = drafts + (mac to text)) else this
    fun sending(mac: String) = copy(saving = saving + mac)
    fun failed(mac: String) = copy(saving = saving - mac)
    fun close(mac: String) = copy(drafts = drafts - mac, saving = saving - mac)
    /** Manager updates never touch typed text; only a bulb that no longer exists loses its form. */
    fun observe(saved: List<Bulb>): BulbRenames {
        val macs = saved.map { it.mac }.toSet()
        return copy(drafts = drafts.filterKeys { it in macs })
    }
}
