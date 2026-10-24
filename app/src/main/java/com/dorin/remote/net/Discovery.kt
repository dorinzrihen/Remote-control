package com.dorin.remote.net

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.SocketTimeoutException
import java.util.concurrent.ConcurrentHashMap

data class FoundDevice(val ip: String, val name: String)

private const val TAG = "Discovery"

object Discovery {

    /** Find LG webOS TVs with an SSDP M-SEARCH. */
    suspend fun findLgTvs(ctx: Context, timeoutMs: Long = 3000): List<FoundDevice> = withContext(Dispatchers.IO) {
        val wifi = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        val lock = wifi.createMulticastLock("uniremote-ssdp").apply { setReferenceCounted(false); acquire() }
        val found = LinkedHashMap<String, FoundDevice>()
        try {
            DatagramSocket().use { socket ->
                socket.soTimeout = 1000
                val msg = "M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\nST: urn:lge-com:service:webos-second-screen:1\r\n\r\n"
                val data = msg.toByteArray()
                val group = InetAddress.getByName("239.255.255.250")
                repeat(2) { socket.send(DatagramPacket(data, data.size, group, 1900)) }
                val end = System.currentTimeMillis() + timeoutMs
                val buf = ByteArray(2048)
                while (System.currentTimeMillis() < end) {
                    val p = DatagramPacket(buf, buf.size)
                    try { socket.receive(p) } catch (_: SocketTimeoutException) { continue }
                    val text = String(p.data, 0, p.length)
                    if (!text.contains("webos", ignoreCase = true) && !text.contains("LGE", ignoreCase = true)) continue
                    val ip = p.address.hostAddress ?: continue
                    val server = text.lines().firstOrNull { it.startsWith("SERVER", true) }?.substringAfter(":")?.trim()
                    found.putIfAbsent(ip, FoundDevice(ip, server?.take(40) ?: "LG webOS TV"))
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "ssdp failed", e)
        } finally { lock.release() }
        found.values.toList()
    }

    /** Find Android TV / Google TV devices advertising the remote service over mDNS. */
    suspend fun findAndroidTvs(ctx: Context, timeoutMs: Long = 4000): List<FoundDevice> = withContext(Dispatchers.IO) {
        val nsd = ctx.applicationContext.getSystemService(Context.NSD_SERVICE) as NsdManager
        val found = ConcurrentHashMap<String, FoundDevice>()
        val listener = object : NsdManager.DiscoveryListener {
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) { Log.w(TAG, "nsd start failed $errorCode") }
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {}
            override fun onDiscoveryStarted(serviceType: String) {}
            override fun onDiscoveryStopped(serviceType: String) {}
            override fun onServiceLost(serviceInfo: NsdServiceInfo) {}
            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                @Suppress("DEPRECATION")
                nsd.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                    override fun onResolveFailed(si: NsdServiceInfo, errorCode: Int) {}
                    override fun onServiceResolved(si: NsdServiceInfo) {
                        val ip = si.host?.hostAddress ?: return
                        if (ip.contains(':')) return // skip IPv6
                        found[ip] = FoundDevice(ip, si.serviceName)
                    }
                })
            }
        }
        try {
            nsd.discoverServices("_androidtvremote2._tcp.", NsdManager.PROTOCOL_DNS_SD, listener)
            delay(timeoutMs)
        } catch (e: Exception) {
            Log.w(TAG, "nsd failed", e)
        } finally {
            runCatching { nsd.stopServiceDiscovery(listener) }
        }
        found.values.toList()
    }
}
