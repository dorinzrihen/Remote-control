package com.dorin.remote

import com.dorin.remote.wiz.ManagerConnection
import com.dorin.remote.wiz.ManagerConnectionStatus
import org.junit.Assert.*
import org.junit.Test

class ManagerConnectionTest {
    @Test fun statusMustBeFreshAndReopenMustCheckAgain() {
        var now = 100L
        val status = ManagerConnectionStatus { now }
        assertEquals(ManagerConnection.CHECKING, status.current())
        status.connected()
        assertEquals(ManagerConnection.CONNECTED, status.current())
        now += 5_001
        assertEquals(ManagerConnection.CHECKING, status.current())
        status.connected()
        assertEquals(ManagerConnection.CONNECTED, status.current())
        status.checking()
        assertEquals(ManagerConnection.CHECKING, status.current())
        status.unavailable()
        assertEquals(ManagerConnection.UNAVAILABLE, status.current())
        status.connected()
        assertEquals(ManagerConnection.CONNECTED, status.current())
    }
}
