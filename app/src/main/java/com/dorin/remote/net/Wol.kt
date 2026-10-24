package com.dorin.remote.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

object Wol {
    suspend fun send(mac: String, ip: String?) = withContext(Dispatchers.IO) {
        val macBytes = mac.split(":", "-").map { it.toInt(16).toByte() }.toByteArray()
        require(macBytes.size == 6) { "bad MAC" }
        val packet = ByteArray(6 + 16 * 6)
        for (i in 0 until 6) packet[i] = 0xFF.toByte()
        for (i in 0 until 16) System.arraycopy(macBytes, 0, packet, 6 + i * 6, 6)
        DatagramSocket().use { s ->
            s.broadcast = true
            val targets = mutableListOf(InetAddress.getByName("255.255.255.255"))
            ip?.let { targets += InetAddress.getByName(it) }
            // also the /24 broadcast of the TV's subnet
            ip?.substringBeforeLast('.')?.let { targets += InetAddress.getByName("$it.255") }
            for (t in targets) {
                repeat(3) { runCatching { s.send(DatagramPacket(packet, packet.size, t, 9)) } }
            }
        }
    }
}
