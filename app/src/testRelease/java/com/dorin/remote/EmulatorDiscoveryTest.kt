package com.dorin.remote

import com.dorin.remote.net.EmulatorDiscovery
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class EmulatorDiscoveryTest {
    @Test fun releaseNeverUsesTheHostBridge() = runBlocking {
        assertNull(EmulatorDiscovery.find("lg"))
        assertNull(EmulatorDiscovery.find("samsung"))
    }
}
