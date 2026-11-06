package com.dorin.remote.wiz

enum class ManagerConnection(val description: String) {
    CHECKING("Checking manager"),
    CONNECTED("Manager connected"),
    UNAVAILABLE("Manager unavailable"),
}

/** Fresh HTTP status, independent of Bonjour, timetable settings and individual bulb errors. */
class ManagerConnectionStatus(private val now: () -> Long = { System.nanoTime() / 1_000_000 }) {
    private var state = ManagerConnection.CHECKING
    private var lastSuccess = 0L

    fun checking() { state = ManagerConnection.CHECKING }
    fun connected() { lastSuccess = now(); state = ManagerConnection.CONNECTED }
    fun unavailable() { state = ManagerConnection.UNAVAILABLE }

    fun current(): ManagerConnection = if (state == ManagerConnection.CONNECTED && now() - lastSuccess > 5_000) {
        ManagerConnection.CHECKING
    } else state
}
