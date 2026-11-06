package com.dorin.remote

import com.dorin.remote.net.ButlerDiscovery
import com.dorin.remote.wiz.ButlerClient
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.RecordedRequest
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

class ButlerDiscoveryTest {
    @Test fun resolvesAdvertisedIpv4WhenAndroidChoosesIpv6() {
        assertEquals("http://10.100.102.19:8788", ButlerDiscovery.managerUrl("fe80::1", 8788, mapOf("api" to "1", "address" to "10.100.102.19")))
        assertEquals("http://192.168.1.2:8788", ButlerDiscovery.managerUrl("192.168.1.2", 8788, mapOf("api" to "1")))
    }

    @Test fun rejectsUnsupportedApiInvalidPortAndNonLanTargets() {
        for (host in listOf("127.0.0.1", "8.8.8.8", "10.1.2.255", "10.1.2.0", "10.1.2.999", "evil.example", "fe80::1", "10.1.2.3/path")) {
            assertNull(ButlerDiscovery.managerUrl(host, 8788, mapOf("api" to "1")))
        }
        assertNull(ButlerDiscovery.managerUrl("10.1.2.3", 0, mapOf("api" to "1")))
        assertNull(ButlerDiscovery.managerUrl("10.1.2.3", 8788, mapOf("api" to "2")))
    }

    @Test fun pairsWithoutExistingCredentialsAndRejectsBadCodes() = runBlocking {
        MockWebServer().use { server ->
            val token = "x".repeat(32)
            server.enqueue(MockResponse().setBody(JSONObject().put("token", token).toString()))
            assertEquals(token, ButlerClient.pair(server.url("/").toString(), "123456"))
            val request = server.takeRequest()
            assertEquals("/v1/pair", request.path)
            assertNull(request.getHeader("Authorization"))
            assertEquals("123456", JSONObject(request.body.readUtf8()).getString("code"))
            try {
                ButlerClient.pair(server.url("/").toString(), "123")
                fail("Must reject incomplete code")
            } catch (_: IllegalArgumentException) { }
            server.enqueue(MockResponse().setResponseCode(403).setBody("{\"error\":\"Code expired\"}"))
            try {
                ButlerClient.pair(server.url("/").toString(), "654321")
                fail("Must reject expired code")
            } catch (e: IllegalStateException) { assertEquals("Code expired", e.message) }
        }
    }

    @Test fun authenticatesDiscoveryWithoutSendingSavedSecret() = runBlocking {
        val token = "x".repeat(32)
        MockWebServer().use { server ->
            server.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    assertNull(request.getHeader("Authorization"))
                    val body = request.body.readUtf8()
                    assertFalse(body.contains(token))
                    val nonce = JSONObject(body).getString("nonce")
                    assertEquals(64, nonce.length)
                    val mac = Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(token.toByteArray(), "HmacSHA256")) }
                    val proof = mac.doFinal("uniremote-manager-v1:$nonce".toByteArray()).joinToString("") { "%02x".format(it) }
                    return MockResponse().setBody(JSONObject().put("proof", proof).toString())
                }
            }
            assertTrue(ButlerClient.verifyManager(server.url("/").toString(), token))
            server.takeRequest()
            server.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest) = MockResponse().setBody("{\"proof\":\"wrong\"}")
            }
            assertFalse(ButlerClient.verifyManager(server.url("/").toString(), token))
        }
    }
}
