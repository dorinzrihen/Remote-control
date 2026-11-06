package com.dorin.remote.net

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume

data class FoundButler(val name: String, val url: String)

/** DNS-SD finds managers only; WiZ bulb discovery remains on the manager. */
class ButlerDiscovery(context: Context) {
    private val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager

    @Suppress("DEPRECATION")
    fun discover() = callbackFlow<List<FoundButler>> {
        val found = linkedMapOf<String, FoundButler>()
        val advertised = java.util.Collections.synchronizedSet(mutableSetOf<String>())
        val pending = Channel<NsdServiceInfo>(32)
        val multicast = wifi.createMulticastLock("butler-discovery").apply { setReferenceCounted(false); acquire() }
        val worker = launch {
            for (service in pending) {
                val resolved = withTimeoutOrNull(5_000) {
                    suspendCancellableCoroutine<NsdServiceInfo?> { continuation ->
                        try {
                            nsd.resolveService(service, object : NsdManager.ResolveListener {
                                override fun onResolveFailed(info: NsdServiceInfo, error: Int) {
                                    if (continuation.isActive) continuation.resume(null)
                                }
                                override fun onServiceResolved(info: NsdServiceInfo) {
                                    if (continuation.isActive) continuation.resume(info)
                                }
                            })
                        } catch (_: IllegalArgumentException) { if (continuation.isActive) continuation.resume(null) }
                    }
                } ?: continue
                val attributes = resolved.attributes.mapValues { it.value.toString(Charsets.UTF_8) }
                val url = managerUrl(resolved.host?.hostAddress, resolved.port, attributes) ?: continue
                if (service.serviceName !in advertised) continue
                found[service.serviceName] = FoundButler(service.serviceName, url)
                trySend(found.values.toList())
            }
        }
        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(type: String) {}
            override fun onDiscoveryStopped(type: String) {}
            override fun onStartDiscoveryFailed(type: String, error: Int) { close(IllegalStateException("Manager search failed ($error)")) }
            override fun onStopDiscoveryFailed(type: String, error: Int) {}
            override fun onServiceFound(info: NsdServiceInfo) { advertised.add(info.serviceName); pending.trySend(info) }
            override fun onServiceLost(info: NsdServiceInfo) {
                advertised.remove(info.serviceName)
                // Callbacks run on NSD's thread, so serialize map updates with resolutions.
                launch { found.remove(info.serviceName); trySend(found.values.toList()) }
            }
        }
        try {
            nsd.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, listener)
        } catch (error: RuntimeException) { close(error) }
        awaitClose {
            runCatching { nsd.stopServiceDiscovery(listener) }
            pending.close()
            worker.cancel()
            if (multicast.isHeld) multicast.release()
        }
    }

    companion object {
        const val SERVICE_TYPE = "_uniremote._tcp."

        /** A TXT address handles IPv6-first resolution when the API binds IPv4. */
        fun managerUrl(host: String?, port: Int, attributes: Map<String, String>): String? {
            if (attributes["api"] != "1" || port !in 1..65535) return null
            val address = attributes["address"] ?: host ?: return null
            val parts = address.split('.')
            if (parts.size != 4 || parts.any { it.isEmpty() || it.any { c -> c !in '0'..'9' } }) return null
            val bytes = parts.map { it.toIntOrNull() ?: return null }
            if (bytes.any { it !in 0..255 }) return null
            val private = bytes[0] == 10 || (bytes[0] == 172 && bytes[1] in 16..31) || (bytes[0] == 192 && bytes[1] == 168)
            if (!private || bytes[3] in listOf(0, 255)) return null
            return "http://${bytes.joinToString(".")}:$port"
        }
    }
}
