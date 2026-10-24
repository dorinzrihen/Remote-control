package com.dorin.remote.atv

import android.content.Context
import org.bouncycastle.asn1.x500.X500Name
import org.bouncycastle.cert.X509v3CertificateBuilder
import org.bouncycastle.cert.jcajce.JcaX509CertificateConverter
import org.bouncycastle.cert.jcajce.JcaX509v3CertificateBuilder
import org.bouncycastle.jce.provider.BouncyCastleProvider
import org.bouncycastle.operator.jcajce.JcaContentSignerBuilder
import java.io.File
import java.math.BigInteger
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.Date
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * Generates and persists the self-signed client certificate that identifies this
 * phone to the Android TV. The pairing secret is derived from this cert, so it
 * must stay the same across app restarts.
 */
object AtvCerts {
    private const val ALIAS = "atvclient"
    private const val PASS = "uniremote"
    private val bc = BouncyCastleProvider()

    private fun file(ctx: Context) = File(ctx.filesDir, "atv_client.p12")

    @Synchronized
    fun loadOrCreate(ctx: Context): KeyStore {
        val ks = KeyStore.getInstance("PKCS12")
        val f = file(ctx)
        if (f.exists()) {
            f.inputStream().use { ks.load(it, PASS.toCharArray()) }
            if (ks.containsAlias(ALIAS)) return ks
        }
        ks.load(null, null)
        val (pair, cert) = generate()
        ks.setKeyEntry(ALIAS, pair.private, PASS.toCharArray(), arrayOf(cert))
        f.outputStream().use { ks.store(it, PASS.toCharArray()) }
        return ks
    }

    fun clientCertificate(ctx: Context): X509Certificate =
        loadOrCreate(ctx).getCertificate(ALIAS) as X509Certificate

    private fun generate(): Pair<KeyPair, X509Certificate> {
        val kpg = KeyPairGenerator.getInstance("RSA")
        kpg.initialize(2048, SecureRandom())
        val pair = kpg.generateKeyPair()
        val name = X500Name("CN=atvremote, O=UniRemote")
        val now = System.currentTimeMillis()
        val builder: X509v3CertificateBuilder = JcaX509v3CertificateBuilder(
            name,
            BigInteger.valueOf(now),
            Date(now - 86_400_000L),
            Date(now + 10L * 365 * 86_400_000L),
            name,
            pair.public,
        )
        val signer = JcaContentSignerBuilder("SHA256withRSA").setProvider(bc).build(pair.private)
        val cert = JcaX509CertificateConverter().setProvider(bc).getCertificate(builder.build(signer))
        return pair to cert
    }

    /** SSL socket factory presenting our client cert and trusting any server cert (TV certs are self-signed). */
    fun socketFactory(ctx: Context): SSLSocketFactory {
        val ks = loadOrCreate(ctx)
        val kmf = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm())
        kmf.init(ks, PASS.toCharArray())
        val sslContext = SSLContext.getInstance("TLS")
        sslContext.init(kmf.keyManagers, arrayOf<TrustManager>(TrustAll), SecureRandom())
        return sslContext.socketFactory
    }

    fun peerCertificate(socket: SSLSocket): X509Certificate =
        socket.session.peerCertificates[0] as X509Certificate

    object TrustAll : X509TrustManager {
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}
        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {}
        override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
    }
}
