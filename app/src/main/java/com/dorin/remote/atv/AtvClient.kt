package com.dorin.remote.atv

import android.content.Context
import android.util.Log
import com.dorin.remote.Diag
import com.dorin.remote.proto.ProtoMessage
import com.dorin.remote.proto.ProtoReader
import com.dorin.remote.proto.ProtoWriter
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.io.BufferedInputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.security.MessageDigest
import java.security.cert.X509Certificate
import java.security.interfaces.RSAPublicKey
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.SSLSocket

sealed class AtvState {
    object Disconnected : AtvState()
    object Connecting : AtvState()
    data class Connected(val started: Boolean) : AtvState()
    object NeedsPairing : AtvState()
    data class Error(val message: String) : AtvState()
}

private const val TAG = "AtvClient"
private const val REMOTE_PORT = 6466
private const val PAIRING_PORT = 6467

// Feature bits from androidtvremote2.
private const val F_PING = 1
private const val F_KEY = 2
private const val F_IME = 4
private const val F_POWER = 32
private const val F_VOLUME = 64
private const val F_APP_LINK = 512

/**
 * Android TV / Google TV remote protocol v2 client (the one used by the Google TV app).
 */
class AtvClient(private val ctx: Context) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var connectJob: Job? = null
    private var socket: SSLSocket? = null
    private val outbox = Channel<ByteArray>(Channel.UNLIMITED)

    val state = MutableStateFlow<AtvState>(AtvState.Disconnected)
    val currentApp = MutableStateFlow("")
    val volume = MutableStateFlow<Triple<Int, Int, Boolean>?>(null) // level, max, muted

    @Volatile private var activeFeatures = F_PING or F_KEY or F_IME or F_POWER or F_VOLUME or F_APP_LINK
    @Volatile private var imeCounter = 0
    @Volatile private var imeFieldCounter = 0
    @Volatile private var host: String? = null

    val isConnected: Boolean get() = state.value is AtvState.Connected

    fun connect(ip: String) {
        host = ip
        connectJob?.cancel()
        connectJob = scope.launch { runLoop(ip) }
    }

    fun disconnect() {
        connectJob?.cancel()
        connectJob = null
        closeSocket()
        state.value = AtvState.Disconnected
    }

    private fun closeSocket() {
        try { socket?.close() } catch (_: Exception) {}
        socket = null
    }

    private suspend fun runLoop(ip: String) {
        var backoff = 1000L
        while (scope.isActive && connectJob?.isActive == true) {
            state.value = AtvState.Connecting
            try {
                session(ip)
                backoff = 1000L
            } catch (e: SSLHandshakeException) {
                Diag.log(TAG, "TLS handshake rejected: ${e.message} (needs pairing)")
                state.value = AtvState.NeedsPairing
                return
            } catch (e: Exception) {
                Diag.log(TAG, "session ended: ${e.message}")
                state.value = AtvState.Error(e.message ?: "connection failed")
            } finally {
                closeSocket()
            }
            delay(backoff)
            backoff = (backoff * 2).coerceAtMost(15_000L)
        }
    }

    private suspend fun session(ip: String) {
        val factory = AtvCerts.socketFactory(ctx)
        val s = factory.createSocket() as SSLSocket
        s.connect(InetSocketAddress(ip, REMOTE_PORT), 5000)
        s.soTimeout = 20_000
        s.startHandshake()
        socket = s
        // drain stale queued messages
        while (outbox.tryReceive().isSuccess) { /* drop */ }
        val writer = scope.launch {
            val out = s.outputStream
            for (frame in outbox) {
                try { out.write(frame); out.flush() } catch (e: Exception) { Log.w(TAG, "write failed", e); break }
            }
        }
        try {
            readLoop(BufferedInputStream(s.inputStream))
        } finally {
            writer.cancel()
        }
    }

    private fun readLoop(input: InputStream) {
        while (true) {
            val msg = readFrame(input) ?: throw IllegalStateException("connection closed")
            handle(ProtoReader.parse(msg))
        }
    }

    private fun readFrame(input: InputStream): ByteArray? {
        var shift = 0
        var len = 0L
        while (true) {
            val b = input.read()
            if (b < 0) return null
            len = len or ((b and 0x7F).toLong() shl shift)
            if (b and 0x80 == 0) break
            shift += 7
        }
        val buf = ByteArray(len.toInt())
        var off = 0
        while (off < buf.size) {
            val n = input.read(buf, off, buf.size - off)
            if (n < 0) return null
            off += n
        }
        return buf
    }

    private fun handle(msg: ProtoMessage) {
        when {
            msg.has(1) -> { // remote_configure
                val cfg = msg.message(1)!!
                val supported = cfg.int(1)
                Diag.log(TAG, "device features=$supported model=${cfg.message(2)?.string(1)}")
                activeFeatures = activeFeatures and supported
                send(ProtoWriter().message(1) {
                    varint(1, activeFeatures)
                    message(2) {
                        string(1, "UniRemote")
                        string(2, "Dorin")
                        varint(3, 1)
                        string(4, "1")
                        string(5, "atvremote")
                        string(6, "1.0.0")
                    }
                })
            }
            msg.has(2) -> send(ProtoWriter().message(2) { varint(1, activeFeatures) }) // remote_set_active
            msg.has(8) -> send(ProtoWriter().message(9) { varint(1, msg.message(8)!!.int(1)) }) // ping
            msg.has(40) -> { // remote_start
                val started = msg.message(40)!!.bool(1)
                state.value = AtvState.Connected(started)
            }
            msg.has(20) -> { // remote_ime_key_inject -> current app
                val app = msg.message(20)?.message(1)?.string(12) ?: ""
                if (app.isNotEmpty()) currentApp.value = app
            }
            msg.has(21) -> { // remote_ime_batch_edit -> counters for typing
                val be = msg.message(21)!!
                imeCounter = be.int(1)
                imeFieldCounter = be.int(2)
                Diag.log(TAG, "text field on device: ime=$imeCounter field=$imeFieldCounter")
            }
            msg.has(50) -> {
                val v = msg.message(50)!!
                volume.value = Triple(v.int(7), v.int(6), v.bool(8))
            }
            msg.has(3) -> Diag.log(TAG, "device reported an error for the last message")
        }
        if (state.value !is AtvState.Connected && (msg.has(8) || msg.has(20) || msg.has(50))) {
            // Some devices never send remote_start; treat traffic after configure as connected.
            state.value = AtvState.Connected(true)
        }
    }

    private fun send(w: ProtoWriter) {
        outbox.trySend(w.toFrame())
    }

    // ---- public commands ----

    fun key(keyCode: Int, direction: Int = AtvKeys.DIRECTION_SHORT) {
        send(ProtoWriter().message(10) { varint(1, keyCode); varint(2, direction) })
    }

    fun launchApp(link: String) {
        send(ProtoWriter().message(90) { string(1, link) })
    }

    /** Type text into the focused field. Uses the IME path when the device has reported a text field,
     *  otherwise falls back to per-character key codes (ASCII letters/digits only). */
    fun sendText(text: String) {
        if (text.isEmpty()) return
        Diag.log(TAG, "type '${text}' via ${if (imeFieldCounter != 0 || imeCounter != 0) "ime" else "keycodes"}")
        if (imeFieldCounter != 0 || imeCounter != 0) {
            val n = text.length - 1
            send(ProtoWriter().message(21) {
                varint(1, imeCounter)
                varint(2, imeFieldCounter)
                message(3) {
                    varint(1, 1)
                    message(2) { varint(1, n); varint(2, n); string(3, text) }
                }
            })
        } else {
            for (c in text) AtvKeys.forChar(c)?.let { key(it) }
        }
    }

    // ---- pairing ----

    /**
     * Runs the pairing handshake until the TV shows a code. Returns a [PairingSession] that must be
     * completed with the code the user reads off the screen.
     */
    suspend fun startPairing(ip: String): PairingSession = withContext(Dispatchers.IO) {
        disconnect()
        val factory = AtvCerts.socketFactory(ctx)
        val s = factory.createSocket() as SSLSocket
        s.connect(InetSocketAddress(ip, PAIRING_PORT), 5000)
        s.soTimeout = 15_000
        s.startHandshake()
        val input = BufferedInputStream(s.inputStream)
        val out = s.outputStream

        fun outer(build: ProtoWriter.() -> Unit): ByteArray =
            ProtoWriter().varint(1, 2).varint(2, 200).apply(build).toFrame()

        fun read(): ProtoMessage {
            val raw = readFrame(input) ?: throw IllegalStateException("TV closed the connection")
            val m = ProtoReader.parse(raw)
            val status = m.int(2)
            if (status != 200) throw IllegalStateException("pairing status $status")
            return m
        }

        // 1. pairing request
        out.write(outer { message(10) { string(1, "atvremote"); string(2, "UniRemote") } }); out.flush()
        val ack = read()
        if (!ack.has(11)) throw IllegalStateException("expected pairing_request_ack")
        // 2. options
        out.write(outer {
            message(20) {
                message(1) { varint(1, 3); varint(2, 6) } // input encoding: hexadecimal, 6 symbols
                varint(3, 1) // preferred role: input
            }
        }); out.flush()
        val opts = read()
        if (!opts.has(20)) throw IllegalStateException("expected options")
        // 3. configuration
        out.write(outer {
            message(30) {
                message(1) { varint(1, 3); varint(2, 6) }
                varint(2, 1)
            }
        }); out.flush()
        val cfgAck = read()
        if (!cfgAck.has(31)) throw IllegalStateException("expected configuration_ack")

        val clientCert = AtvCerts.clientCertificate(ctx)
        val serverCert = AtvCerts.peerCertificate(s)
        PairingSession(s, input, out, clientCert, serverCert, ::readFrame)
    }

    class PairingSession internal constructor(
        private val socket: SSLSocket,
        private val input: InputStream,
        private val out: OutputStream,
        private val clientCert: X509Certificate,
        private val serverCert: X509Certificate,
        private val readFrame: (InputStream) -> ByteArray?,
    ) {
        suspend fun finish(code: String) = withContext(Dispatchers.IO) {
            try {
                val clean = code.trim().uppercase()
                require(clean.length == 6 && clean.all { it in "0123456789ABCDEF" }) { "Code must be 6 hex characters" }
                val secret = computeSecret(clean)
                if ((secret[0].toInt() and 0xFF) != clean.substring(0, 2).toInt(16)) {
                    throw IllegalArgumentException("Wrong code")
                }
                out.write(ProtoWriter().varint(1, 2).varint(2, 200).message(40) { bytes(1, secret) }.toFrame())
                out.flush()
                withTimeout(10_000) {
                    val raw = readFrame(input) ?: throw IllegalStateException("TV closed the connection")
                    val m = ProtoReader.parse(raw)
                    if (m.int(2) != 200 || !m.has(41)) throw IllegalStateException("TV rejected the code")
                }
            } finally {
                try { socket.close() } catch (_: Exception) {}
            }
        }

        fun cancel() { try { socket.close() } catch (_: Exception) {} }

        private fun computeSecret(code: String): ByteArray = AtvPairingMath.computeSecret(clientCert, serverCert, code)
    }

    fun shutdown() {
        disconnect()
        scope.cancel()
    }
}

/** Secret derivation from the pairing protocol (shared with unit tests). */
object AtvPairingMath {
    fun computeSecret(clientCert: X509Certificate, serverCert: X509Certificate, code: String): ByteArray {
        val md = MessageDigest.getInstance("SHA-256")
        val ck = clientCert.publicKey as RSAPublicKey
        val sk = serverCert.publicKey as RSAPublicKey
        md.update(unsigned(ck.modulus.toByteArray()))
        md.update(unsigned(ck.publicExponent.toByteArray()))
        md.update(unsigned(sk.modulus.toByteArray()))
        md.update(unsigned(sk.publicExponent.toByteArray()))
        md.update(hex(code.substring(2)))
        return md.digest()
    }

    private fun unsigned(b: ByteArray): ByteArray {
        var i = 0
        while (i < b.size - 1 && b[i] == 0.toByte()) i++
        return b.copyOfRange(i, b.size)
    }

    private fun hex(s: String): ByteArray = ByteArray(s.length / 2) { i -> s.substring(2 * i, 2 * i + 2).toInt(16).toByte() }
}
