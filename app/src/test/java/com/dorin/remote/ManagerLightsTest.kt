package com.dorin.remote

import com.dorin.remote.wiz.ButlerClient
import com.dorin.remote.wiz.LightMode
import com.dorin.remote.wiz.Lights
import com.dorin.remote.wiz.BulbsDidNotAnswer
import com.dorin.remote.wiz.lightingCommandFailure
import com.dorin.remote.wiz.ManagerConnection
import java.io.File
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer

/** All lighting tests use fake manager responses or loopback HTTP, never WiZ UDP. */
class ManagerLightsTest {
    private val mac = "aabbccddeeff"
    private fun status(enabled: Boolean = true, on: Boolean = true): JSONObject = JSONObject()
        .put("config", ButlerClient.config(enabled, "22:15", "07:45", "Asia/Jerusalem")
            .put("bulbs", JSONArray().put(JSONObject().put("mac", mac).put("ip", "192.168.1.20").put("room", "Manager room"))))
        .put("pilots", JSONObject().put(mac, JSONObject().put("mac", mac).put("state", on).put("dimming", 20).put("temp", 2700)))
        .put("systemConfigs", JSONObject().put(mac, JSONObject().put("mac", mac).put("moduleName", "ESP24_SHRGBC_01").put("fwVersion", "1.29.0")))
        .put("errors", JSONObject())
        .put("observedAt", JSONObject().put(mac, System.currentTimeMillis() / 1000.0))
        .put("statusAt", System.currentTimeMillis() / 1000.0)

    @Test fun bootstrapOnlyReadsAndAdoptsExistingManagerBulbs() = runBlocking {
        val calls = mutableListOf<String>()
        val lights = Lights { path, body ->
            calls += path
            assertNull(body)
            status()
        }
        assertTrue(lights.bulbs.value.isEmpty())
        assertFalse(lights.loaded.value)
        lights.refresh()
        assertEquals(listOf("/v1/status"), calls)
        assertEquals("Manager room", lights.bulbs.value.single().room)
        assertEquals("22:15", lights.config.value!!.getString("night"))
        assertEquals(LightMode.NIGHT, LightMode.of(lights.pilots.value.getValue(mac)))
        assertEquals("1.29.0", lights.systemConfigs.value.getValue(mac).fwVersion)
    }

    @Test fun emptyManagerResponseIsAuthoritativeRatherThanMergingPhoneCache() = runBlocking {
        val lights = Lights { _, _ -> status().apply { getJSONObject("config").put("bulbs", JSONArray()) } }
        lights.acceptStatus(status())
        lights.refresh()
        assertTrue(lights.bulbs.value.isEmpty())
        assertTrue(lights.pilots.value.isEmpty())
        assertTrue(lights.systemConfigs.value.isEmpty())
    }

    @Test fun statusRejectsMismatchedIdentitiesAndExposesManagerErrors() {
        val snapshot = status()
        snapshot.getJSONObject("pilots").getJSONObject(mac).put("mac", "000000000000")
        snapshot.getJSONObject("systemConfigs").getJSONObject(mac).put("mac", "000000000000")
        snapshot.getJSONObject("errors").put(mac, "MAC mismatch")
        val lights = Lights { _, _ -> snapshot }
        lights.acceptStatus(snapshot)
        assertTrue(lights.pilots.value.isEmpty())
        assertTrue(lights.systemConfigs.value.isEmpty())
        assertTrue(lights.error.value!!.contains("MAC mismatch"))
        assertEquals(ManagerConnection.CONNECTED, lights.managerConnection.current())
    }

    @Test fun staleManagerObservationsAreNotPresentedAsCurrentOnState() {
        val snapshot = status().put("statusAt", 1000.0).put("observedAt", JSONObject().put(mac, 970.0))
        val lights = Lights { _, _ -> snapshot }
        lights.acceptStatus(snapshot)
        assertTrue(lights.pilots.value.isEmpty())
        assertEquals(30, lights.observationAges.value.getValue(mac))
        assertTrue(lights.error.value!!.contains("stale"))
    }

    @Test fun allManualModesUseManagerEvenWithTimetableDisabled() = runBlocking {
        val modes = mutableListOf<String>()
        val calls = mutableListOf<String>()
        val lights = Lights { path, body ->
            calls += path
            if (path == "/v1/room") {
                assertEquals("Manager room", body!!.getString("room"))
                modes += body.getString("mode")
                JSONObject().put("answered", 1).put("total", 1)
            } else {
                assertEquals("/v1/status", path)
                assertNull(body)
                status(enabled = false)
            }
        }
        lights.acceptStatus(status(enabled = false))
        lights.setRoom("Manager room", LightMode.REGULAR)
        lights.setRoom("Manager room", LightMode.NIGHT)
        lights.setRoom("Manager room", null)
        lights.command("Manager room", "TOGGLE")
        lights.command("Manager room", "ON")
        lights.command("Manager room", "AUTO")
        assertEquals(listOf("REGULAR", "NIGHT", "OFF", "TOGGLE", "ON", "AUTO"), modes)
        assertEquals(6, calls.count { it == "/v1/status" })
        assertEquals(12, calls.size)
    }

    @Test fun discoveryAddRemoveAndBlinkGoOnlyThroughManager() = runBlocking {
        val calls = mutableListOf<String>()
        val lights = Lights { path, body ->
            calls += path
            assertNotNull(body)
            when (path) {
                "/v1/discover" -> JSONObject().put("status", status()).put("discovered", JSONArray().put(
                    JSONObject().put("mac", mac).put("ip", "192.168.1.20").put("pilot", status().getJSONObject("pilots").getJSONObject(mac))))
                "/v1/bulbs/add" -> {
                    assertEquals(mac, body!!.getString("mac"))
                    assertEquals("Kitchen", body.getString("room"))
                    status()
                }
                "/v1/bulbs/remove", "/v1/bulbs/blink" -> {
                    assertEquals(mac, body!!.getString("mac"))
                    assertFalse(body.has("ip"))
                    status()
                }
                else -> throw AssertionError("Unexpected transport: $path")
            }
        }
        assertEquals(mac, lights.discover().getValue("192.168.1.20").mac)
        lights.add(mac, "192.168.1.20", "Kitchen")
        lights.blink(mac)
        lights.remove(mac)
        assertEquals(listOf("/v1/discover", "/v1/bulbs/add", "/v1/bulbs/blink", "/v1/bulbs/remove"), calls)
    }

    @Test fun failedManagerNeverFallsBackAndClearsStaleOnState() = runBlocking {
        val calls = mutableListOf<String>()
        val lights = Lights { path, _ -> calls += path; throw IllegalStateException("Connection refused") }
        lights.acceptStatus(status())
        try { lights.refresh(); fail("Expected offline error") } catch (_: IllegalStateException) { }
        assertFalse(lights.loaded.value)
        assertEquals(ManagerConnection.UNAVAILABLE, lights.managerConnection.current())
        assertTrue(lights.pilots.value.isEmpty())
        assertEquals(1, lights.bulbs.value.size) // last manager list, explicitly status unknown
        assertTrue(lights.error.value!!.contains("status unavailable"))
        try { lights.setRoom("Manager room", LightMode.NIGHT); fail("Expected command error") } catch (_: IllegalStateException) { }
        assertEquals(listOf("/v1/status", "/v1/room"), calls)
    }

    @Test fun zeroAcknowledgementsAreNotReportedAsSuccess() = runBlocking {
        val calls = mutableListOf<String>()
        val snapshot = status().apply {
            getJSONObject("pilots").remove(mac)
            getJSONObject("errors").put(mac, "MAC mismatch")
        }
        val lights = Lights { path, _ ->
            calls += path
            if (path == "/v1/room") JSONObject().put("answered", 0).put("total", 1).put("errors", JSONObject().put(mac, "MAC mismatch"))
            else snapshot
        }
        val result = lights.command("Manager room", "ON")
        assertEquals(0, result.answered)
        assertEquals("Manager room: requested; bulb not yet confirmed", result.feedback("Manager room"))
        assertEquals(listOf("/v1/room", "/v1/status"), calls)
        assertTrue(lights.loaded.value)
        assertTrue(lights.pilots.value.isEmpty())
        assertTrue(lights.error.value!!.contains("MAC mismatch"))
        assertEquals(ManagerConnection.CONNECTED, lights.managerConnection.current())
    }

    @Test fun unconfirmedCommandDoesNotClaimTheManagerIsDownOrThatNothingWasSent() {
        val feedback = lightingCommandFailure(java.io.IOException("Read timed out"))
        assertTrue(feedback.contains("not confirmed"))
        assertTrue(feedback.contains("Read timed out"))
        assertFalse(feedback.contains("unavailable"))
        assertFalse(feedback.contains("no direct command sent"))
    }

    @Test fun acknowledgementSurvivesStatusFailureWithoutRetryingPost() = runBlocking {
        val calls = mutableListOf<String>()
        val lights = Lights { path, _ ->
            calls += path
            if (path == "/v1/room") JSONObject().put("answered", 1).put("total", 1)
            else throw java.io.IOException("Read timed out")
        }
        lights.acceptStatus(status())
        val result = lights.command("Manager room", "TOGGLE")
        assertEquals(1, result.answered)
        assertFalse(result.statusAvailable)
        assertEquals("Manager room: 1 of 1 confirmed; status refresh unavailable", result.feedback("Manager room"))
        assertFalse(lights.loaded.value)
        assertEquals(ManagerConnection.UNAVAILABLE, lights.managerConnection.current())
        assertEquals(listOf("/v1/room", "/v1/status"), calls)
    }

    @Test fun partialAcknowledgementsUseCommandCountsNotLaterStatus() = runBlocking {
        val lights = Lights { path, _ ->
            if (path == "/v1/room") JSONObject().put("answered", 2).put("total", 3) else status()
        }
        val result = lights.command("Manager room", "NIGHT")
        assertEquals("Manager room: 2 of 3 bulbs confirmed", result.feedback("Manager room"))
    }

    @Test fun zeroAcknowledgementsRemainPendingEvenIfStatusRefreshFails() = runBlocking {
        val lights = Lights { path, _ ->
            if (path == "/v1/room") JSONObject().put("answered", 0).put("total", 1)
            else throw java.io.IOException("offline")
        }
        val result = lights.command("Manager room", "AUTO")
        assertEquals(0, result.answered)
        assertEquals("Manager room: requested; bulb not yet confirmed; status refresh unavailable", result.feedback("Manager room"))
        assertFalse(lights.loaded.value)
    }

    @Test fun readOnlyStatusRecoversFromDisconnectedConnection() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AFTER_REQUEST))
        server.enqueue(MockResponse().setBody(status().toString()))
        server.start()
        try {
            val result = ButlerClient.exchange(server.url("/").toString(), "/v1/status")
            assertTrue(result.has("config"))
            assertEquals(2, server.requestCount)
            repeat(2) {
                val request = server.takeRequest()
                assertEquals("GET", request.method)
                assertEquals("/v1/status", request.path)
            }
        } finally { server.shutdown() }
    }

    @Test fun readOnlyStatusRecoveryIsBounded() = runBlocking {
        val server = MockWebServer()
        repeat(2) { server.enqueue(MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AFTER_REQUEST)) }
        server.start()
        try {
            try {
                ButlerClient.exchange(server.url("/").toString(), "/v1/status")
                fail("Expected unavailable status after two attempts")
            } catch (_: java.io.IOException) { }
            assertEquals(2, server.requestCount)
        } finally { server.shutdown() }
    }

    @Test fun httpPostDisconnectDoesNotAutomaticallyResendCommand() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AFTER_REQUEST))
        server.enqueue(MockResponse().setBody("""{"answered":1,"total":1}"""))
        server.start()
        try {
            try {
                ButlerClient.exchange(server.url("/").toString(), "/v1/room", JSONObject().put("room", "Fake room").put("mode", "TOGGLE"))
                fail("Expected unknown outcome after disconnect")
            } catch (e: java.io.IOException) {
                assertTrue(lightingCommandFailure(e).contains("outcome unknown"))
            }
            assertEquals(1, server.requestCount)
        } finally { server.shutdown() }
    }

    @Test fun postTimeoutIsUnknownAndNeverRetried() = runBlocking {
        var calls = 0
        val lights = Lights { _, _ -> calls++; throw java.net.SocketTimeoutException("Read timed out") }
        try { lights.command("Manager room", "TOGGLE"); fail("Expected unknown outcome") }
        catch (e: java.net.SocketTimeoutException) {
            assertTrue(lightingCommandFailure(e).contains("not confirmed"))
        }
        assertEquals(1, calls)
    }

    @Test fun everyMutationIsSentOnceDespite503RetryAfterZero() = runBlocking {
        for (path in listOf("/v1/room", "/v1/config", "/v1/discover", "/v1/bulbs/add", "/v1/bulbs/remove", "/v1/bulbs/blink")) {
            val server = MockWebServer()
            server.enqueue(MockResponse().setResponseCode(503).setHeader("Retry-After", "0").setBody("{}"))
            server.enqueue(MockResponse().setBody("""{"answered":1,"total":1}"""))
            server.start()
            try {
                try {
                    ButlerClient.exchange(server.url("/").toString(), path, JSONObject().put("mode", "TOGGLE"))
                    fail("503 must not replay $path")
                } catch (e: java.io.IOException) {
                    assertTrue(lightingCommandFailure(e).contains("outcome unknown"))
                    assertTrue(e.message!!.contains("503"))
                }
                assertEquals(path, 1, server.requestCount)
                val request = server.takeRequest()
                assertEquals("POST", request.method)
                assertEquals(path, request.path)
                assertEquals("TOGGLE", JSONObject(request.body.readUtf8()).getString("mode"))
            } finally { server.shutdown() }
        }
    }

    @Test fun timeoutAndAuthenticationResponsesNeverReplayMutation() = runBlocking {
        for (code in listOf(408, 401, 407)) {
            val server = MockWebServer()
            server.enqueue(MockResponse().setResponseCode(code).setHeader("Retry-After", "0")
                .setHeader("WWW-Authenticate", "Basic realm=manager").setHeader("Proxy-Authenticate", "Basic realm=manager").setBody("{}"))
            server.enqueue(MockResponse().setBody("""{"answered":1,"total":1}"""))
            server.start()
            try {
                try {
                    ButlerClient.exchange(server.url("/").toString(), "/v1/room", JSONObject().put("mode", "TOGGLE"))
                    fail("$code must not replay TOGGLE")
                } catch (e: Exception) {
                    assertTrue(e is java.io.IOException || e is com.dorin.remote.wiz.ButlerRequestRejected)
                    if (code == 408) assertTrue(lightingCommandFailure(e).contains("outcome unknown"))
                }
                assertEquals("HTTP $code", 1, server.requestCount)
                assertEquals("POST", server.takeRequest().method)
            } finally { server.shutdown() }
        }
    }

    @Test fun httpRequestsNeedNoCredentialsForAnyEndpointAndExposeServerErrors() = runBlocking {
        val server = MockWebServer()
        repeat(6) { server.enqueue(MockResponse().setBody("{}")) }
        server.enqueue(MockResponse().setResponseCode(400).setBody("""{"error":"MAC mismatch"}"""))
        server.start()
        try {
            val url = server.url("/").toString()
            ButlerClient.exchange(url, "/v1/status")
            for (path in listOf("/v1/config", "/v1/discover", "/v1/bulbs/add", "/v1/bulbs/remove", "/v1/bulbs/blink")) {
                ButlerClient.exchange(url, path, JSONObject())
            }
            try { ButlerClient.exchange(url, "/v1/room", JSONObject()); fail("Expected server error") }
            catch (e: com.dorin.remote.wiz.ButlerRequestRejected) {
                assertEquals("MAC mismatch", e.message)
                assertEquals("Lighting request rejected: MAC mismatch", lightingCommandFailure(e))
            }
            assertEquals(7, server.requestCount)
            val requests = (0 until 7).map { server.takeRequest() }
            assertEquals("GET", requests.first().method)
            assertEquals("/v1/status", requests.first().path)
            assertTrue(requests.drop(1).all { it.method == "POST" })
            requests.forEach { assertNull(it.getHeader("Authorization")) }
        } finally { server.shutdown() }
    }

    @Test fun androidLightingHasNoUdpTransportOrActivePhoneScheduler() {
        val main = File("src/main")
        val lighting = File(main, "java/com/dorin/remote/wiz").walkTopDown().filter { it.extension == "kt" }.joinToString("\n") { it.readText() }
        for (forbidden in listOf("DatagramSocket", "DatagramPacket", "38899", "Wiz.request", "Wiz.getPilot", "Wiz.discover", "nightIfOn")) {
            assertFalse("Android lighting contains $forbidden", lighting.contains(forbidden))
        }
        val receiver = File(main, "java/com/dorin/remote/NightLightsReceiver.kt").readText()
        assertTrue(receiver.contains("FLAG_NO_CREATE"))
        assertTrue(receiver.contains(".cancel(old)"))
        assertFalse(receiver.contains(".schedule("))
        assertFalse(receiver.contains(".lights"))
        assertFalse(receiver.contains(".setExact"))
        val manifest = File(main, "AndroidManifest.xml").readText()
        assertFalse(manifest.contains("EXACT_ALARM"))
        assertFalse(manifest.contains("BOOT_COMPLETED"))
        assertTrue(manifest.contains("MY_PACKAGE_REPLACED"))
        val sheet = File(main, "java/com/dorin/remote/ui/BulbsSheet.kt").readText()
        assertTrue(sheet.contains("delay(1_000)"))
        assertFalse(sheet.contains("autoNight"))
    }
}
