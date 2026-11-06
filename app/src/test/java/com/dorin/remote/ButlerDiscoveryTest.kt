package com.dorin.remote

import com.dorin.remote.net.ButlerDiscovery
import com.dorin.remote.net.FoundButler
import org.junit.Assert.*
import org.junit.Test

class ButlerDiscoveryTest {
    @Test fun soleManagerConnectsAutomaticallyButSeveralRequireSelection() {
        val manager = FoundButler("Butler Lights", "http://10.100.102.19:8788")
        assertNull(ButlerDiscovery.automaticManager(emptyList()))
        assertEquals(manager, ButlerDiscovery.automaticManager(listOf(manager)))
        assertNull(ButlerDiscovery.automaticManager(listOf(manager, FoundButler("Other", "http://10.100.102.20:8788"))))
    }
    @Test fun resolvesAdvertisedIpv4WhenAndroidChoosesIpv6() {
        assertEquals("http://10.100.102.19:8788", ButlerDiscovery.managerUrl("fe80::1", 8788, mapOf("api" to "1", "auth" to "none", "address" to "10.100.102.19")))
        assertEquals("http://192.168.1.2:8788", ButlerDiscovery.managerUrl("192.168.1.2", 8788, mapOf("api" to "1")))
    }

    @Test fun rejectsUnsupportedApiInvalidPortAndNonLanTargets() {
        for (host in listOf("127.0.0.1", "8.8.8.8", "10.1.2.255", "10.1.2.0", "10.1.2.999", "evil.example", "fe80::1", "10.1.2.3/path")) {
            assertNull(ButlerDiscovery.managerUrl(host, 8788, mapOf("api" to "1")))
        }
        assertNull(ButlerDiscovery.managerUrl("10.1.2.3", 0, mapOf("api" to "1")))
        assertNull(ButlerDiscovery.managerUrl("10.1.2.3", 8788, mapOf("api" to "2")))
    }

    @Test fun freshInstallAndSameServiceAtNewAddressNeverNeedApproval() {
        val url = "http://10.100.102.19:8788"
        assertTrue(ButlerDiscovery.canUseManager("", "", url, "Butler Lights", false))
        assertTrue(ButlerDiscovery.canUseManager("", "", url, "Butler Lights", true))
        assertTrue(ButlerDiscovery.canUseManager(url, "", "$url/", "Butler Lights", true))
        assertTrue(ButlerDiscovery.canUseManager("http://10.100.102.18:8788", "Butler Lights", url, "Butler Lights", true))
    }

    @Test fun differentManagerCannotLeaveOldTimetableRunning() {
        val old = "http://10.100.102.19:8788"
        val next = "http://10.100.102.20:8788"
        assertFalse(ButlerDiscovery.canUseManager(old, "Butler Lights", next, "Other manager", true))
        assertFalse(ButlerDiscovery.canUseManager(old, "Butler Lights", next, "", true))
        assertTrue(ButlerDiscovery.canUseManager(old, "Butler Lights", next, "Other manager", false))
    }
}
