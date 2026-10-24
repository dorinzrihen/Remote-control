package com.dorin.remote

import com.dorin.remote.atv.AtvPairingMath
import com.dorin.remote.proto.ProtoReader
import com.dorin.remote.proto.ProtoWriter
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate

/** Compares our hand-written protobuf framing against bytes produced by the official Python protobuf library. */
class ProtocolTest {
    private val expected: JSONObject by lazy {
        JSONObject(javaClass.classLoader!!.getResource("expected.json")!!.readText())
    }

    private fun ByteArray.hex() = joinToString("") { "%02x".format(it) }
    private fun String.unhex() = ByteArray(length / 2) { i -> substring(2 * i, 2 * i + 2).toInt(16).toByte() }

    private fun outer(build: ProtoWriter.() -> Unit) = ProtoWriter().varint(1, 2).varint(2, 200).apply(build).toFrame()

    @Test fun pairingRequest() = assertEquals(expected.getString("pairing_request"),
        outer { message(10) { string(1, "atvremote"); string(2, "UniRemote") } }.hex())

    @Test fun options() = assertEquals(expected.getString("options"),
        outer { message(20) { message(1) { varint(1, 3); varint(2, 6) }; varint(3, 1) } }.hex())

    @Test fun configuration() = assertEquals(expected.getString("configuration"),
        outer { message(30) { message(1) { varint(1, 3); varint(2, 6) }; varint(2, 1) } }.hex())

    @Test fun secret() = assertEquals(expected.getString("secret"),
        outer { message(40) { bytes(1, ByteArray(32) { it.toByte() }) } }.hex())

    @Test fun configure() = assertEquals(expected.getString("configure"),
        ProtoWriter().message(1) {
            varint(1, 615)
            message(2) { string(1, "UniRemote"); string(2, "Dorin"); varint(3, 1); string(4, "1"); string(5, "atvremote"); string(6, "1.0.0") }
        }.toFrame().hex())

    @Test fun setActive() = assertEquals(expected.getString("set_active"), ProtoWriter().message(2) { varint(1, 615) }.toFrame().hex())
    @Test fun ping() = assertEquals(expected.getString("ping"), ProtoWriter().message(9) { varint(1, 12345) }.toFrame().hex())
    @Test fun key() = assertEquals(expected.getString("key"), ProtoWriter().message(10) { varint(1, 23); varint(2, 3) }.toFrame().hex())
    @Test fun appLink() = assertEquals(expected.getString("applink"), ProtoWriter().message(90) { string(1, "https://www.youtube.com") }.toFrame().hex())

    @Test fun ime() = assertEquals(expected.getString("ime"),
        ProtoWriter().message(21) {
            varint(1, 7); varint(2, 3)
            message(3) { varint(1, 1); message(2) { varint(1, 4); varint(2, 4); string(3, "hello") } }
        }.toFrame().hex())

    private fun body(key: String): ByteArray {
        val frame = expected.getString(key).unhex()
        val (len, pos) = ProtoReader.readVarint(frame, 0)
        assertEquals(frame.size - pos, len.toInt())
        return frame.copyOfRange(pos, frame.size)
    }

    @Test fun decodeConfigure() {
        val m = ProtoReader.parse(body("in_configure"))
        assertTrue(m.has(1))
        assertEquals(639, m.message(1)!!.int(1))
        assertEquals("MiBox", m.message(1)!!.message(2)!!.string(1))
    }

    @Test fun decodePing() {
        val m = ProtoReader.parse(body("in_ping"))
        assertEquals(42, m.message(8)!!.int(1))
    }

    @Test fun decodeStart() = assertTrue(ProtoReader.parse(body("in_start")).message(40)!!.bool(1))

    @Test fun decodeImeKey() = assertEquals("com.netflix.ninja", ProtoReader.parse(body("in_ime_key")).message(20)!!.message(1)!!.string(12))

    @Test fun decodeImeBatch() {
        val be = ProtoReader.parse(body("in_ime_batch")).message(21)!!
        assertEquals(9, be.int(1)); assertEquals(4, be.int(2))
    }

    @Test fun decodeAcks() {
        assertTrue(ProtoReader.parse(body("in_cfg_ack")).has(31))
        val ack = ProtoReader.parse(body("in_req_ack"))
        assertEquals(200, ack.int(2))
        assertEquals("MiBox", ack.message(11)!!.string(1))
    }

    @Test fun pairingSecretMatchesReference() {
        val cf = CertificateFactory.getInstance("X.509")
        val client = cf.generateCertificate(expected.getString("client_pem").byteInputStream()) as X509Certificate
        val server = cf.generateCertificate(expected.getString("server_pem").byteInputStream()) as X509Certificate
        val secret = AtvPairingMath.computeSecret(client, server, expected.getString("code"))
        assertEquals(expected.getString("secret_hash"), secret.hex())
    }
}
