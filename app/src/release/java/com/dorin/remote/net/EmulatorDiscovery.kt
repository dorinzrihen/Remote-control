package com.dorin.remote.net

/** Release apps never contact an emulator discovery bridge. */
object EmulatorDiscovery {
    @Suppress("UNUSED_PARAMETER")
    suspend fun find(kind: String): List<FoundDevice>? = null
}
