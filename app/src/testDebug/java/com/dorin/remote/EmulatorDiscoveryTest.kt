package com.dorin.remote

import com.dorin.remote.net.EmulatorDiscovery
import org.junit.Assert.*
import org.junit.Test

class EmulatorDiscoveryTest {
    @Test fun onlyVirtualDevicesUseTheHostBridge() {
        assertTrue(EmulatorDiscovery.shouldUseHostBridge("google/sdk_gphone64_x86_64/emulator", "ranchu"))
        assertTrue(EmulatorDiscovery.shouldUseHostBridge("generic/sdk", "goldfish"))
        assertFalse(EmulatorDiscovery.shouldUseHostBridge("google/akita/akita:15/release-keys", "akita"))
        assertFalse(EmulatorDiscovery.shouldUseHostBridge("samsung/device/release-keys", "exynos"))
    }
}
