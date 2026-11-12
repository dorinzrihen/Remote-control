package com.dorin.remote

import com.dorin.remote.atv.AtvState
import com.dorin.remote.net.Wol
import com.dorin.remote.tizen.SamsungState
import com.dorin.remote.webos.LgState
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withTimeoutOrNull

enum class TvRoute { LG, SAMSUNG, ATV, NONE }

/**
 * Sends remote commands through the app-wide device clients in [App]. Shared by the remote screen
 * and by the TV widget (home screen and lock screen), which works without the app open.
 * No protocol logic lives here.
 */
class TvControl(private val app: App) {
    private val lg get() = app.lg
    private val samsung get() = app.samsung
    private val atv get() = app.atv

    companion object {
        /** Volume goes to the TV whenever it is reachable: over HDMI ARC the TV forwards it to the soundbar. */
        fun volumeRoute(preferSamsung: Boolean, lg: Boolean, samsung: Boolean, atv: Boolean): TvRoute = when {
            (preferSamsung && samsung) || (!lg && samsung) -> TvRoute.SAMSUNG
            lg -> TvRoute.LG
            atv -> TvRoute.ATV
            else -> TvRoute.NONE
        }

        /** Widgets and the lock screen have no tab: navigation goes to the configured TV, else the Xiaomi. */
        fun navRoute(lg: Boolean, samsung: Boolean, atv: Boolean): TvRoute = when {
            lg -> TvRoute.LG
            samsung -> TvRoute.SAMSUNG
            atv -> TvRoute.ATV
            else -> TvRoute.NONE
        }
    }

    /** True when there is no LG configured but a Samsung is: the remote screen's "TV" is then the Samsung. */
    val samsungIsTheTv: Boolean get() = app.prefs.lgIp.isEmpty() && app.prefs.samsungIp.isNotEmpty()
    val anyTvConfigured: Boolean get() = app.prefs.lgIp.isNotEmpty() || app.prefs.samsungIp.isNotEmpty() ||
        (app.prefs.atvIp.isNotEmpty() && app.prefs.atvPaired)
    val anyConnected: Boolean get() = lg.isConnected || samsung.isConnected || atv.isConnected

    /** Connects every configured client that is not already connected or connecting; never restarts a live session. */
    fun ensureConnected() {
        val p = app.prefs
        if (p.lgIp.isNotEmpty() && (lg.host != p.lgIp || lg.state.value.let { it is LgState.Disconnected || it is LgState.Error }))
            lg.connect(p.lgIp, p.lgKey)
        if (p.samsungIp.isNotEmpty() && (samsung.host != p.samsungIp || samsung.state.value.let { it is SamsungState.Disconnected || it is SamsungState.Error }))
            samsung.connect(p.samsungIp, p.samsungToken)
        if (p.atvIp.isNotEmpty() && p.atvPaired && atv.state.value.let { it is AtvState.Disconnected || it is AtvState.Error })
            atv.connect(p.atvIp)
    }

    /** Waits until any configured device is connected. */
    suspend fun awaitConnected(timeoutMs: Long): Boolean {
        ensureConnected()
        if (anyConnected) return true
        return withTimeoutOrNull(timeoutMs) {
            kotlinx.coroutines.flow.combine(lg.state, samsung.state, atv.state) { _, _, _ -> anyConnected }.first { it }
        } ?: false
    }

    /** VOL_UP / VOL_DOWN / MUTE. Returns null when sent, else a message for the user. */
    fun volume(key: Key, preferSamsung: Boolean = samsungIsTheTv): String? {
        when (volumeRoute(preferSamsung, lg.isConnected, samsung.isConnected, atv.isConnected)) {
            TvRoute.SAMSUNG -> when (key) {
                Key.VOL_UP -> samsung.volumeUp(); Key.VOL_DOWN -> samsung.volumeDown(); else -> samsung.mute()
            }
            TvRoute.LG -> when (key) {
                Key.VOL_UP -> lg.volumeUp(); Key.VOL_DOWN -> lg.volumeDown(); else -> lg.setMute(!lg.muted.value)
            }
            TvRoute.ATV -> atv.key(TvKeys.atvKey(key)!!)
            TvRoute.NONE -> return "Not connected"
        }
        return null
    }

    /** Absolute volume; only the LG reports and accepts a level. */
    fun setVolume(level: Int): String? = if (lg.isConnected) { lg.setVolume(level); null } else "LG TV not connected"

    /** LG keys, including the two that are not pointer-socket buttons. */
    fun lgKey(key: Key) {
        when (key) {
            Key.PLAY_PAUSE -> lg.button("PLAY")
            Key.SEARCH -> lg.launchApp("com.webos.app.voice")
            else -> TvKeys.lgButton(key)?.let { lg.button(it) }
        }
    }

    /** A navigation / media key for "the TV" (no tab): goes to the first connected device. */
    fun tvKey(key: Key): String? {
        if (key == Key.VOL_UP || key == Key.VOL_DOWN || key == Key.MUTE) return volume(key)
        return keyTo(navRoute(lg.isConnected, samsung.isConnected, atv.isConnected), key)
    }

    /** A navigation / media key for one device. Returns null when sent, else a message for the user. */
    fun keyTo(route: TvRoute, key: Key): String? {
        when (route) {
            TvRoute.LG -> if (lg.isConnected) lgKey(key) else return "LG TV not connected"
            TvRoute.SAMSUNG -> if (samsung.isConnected) TvKeys.samsungKey(key)?.let { samsung.key(it) } ?: return "Not available on Samsung"
                else return "Samsung TV not connected"
            TvRoute.ATV -> if (atv.isConnected) TvKeys.atvKey(key)?.let { atv.key(it) } ?: return "Not available on Xiaomi"
                else return "Xiaomi not connected"
            TvRoute.NONE -> return "Not connected"
        }
        return null
    }

    fun isConnected(route: TvRoute): Boolean = when (route) {
        TvRoute.LG -> lg.isConnected
        TvRoute.SAMSUNG -> samsung.isConnected
        TvRoute.ATV -> atv.isConnected
        TvRoute.NONE -> false
    }

    /** Connects every configured device, then waits up to [timeoutMs] for [route] in particular. */
    suspend fun awaitRoute(route: TvRoute, timeoutMs: Long): Boolean {
        ensureConnected()
        if (isConnected(route)) return true
        val flow = when (route) {
            TvRoute.LG -> lg.state
            TvRoute.SAMSUNG -> samsung.state
            TvRoute.ATV -> atv.state
            TvRoute.NONE -> return false
        }
        return withTimeoutOrNull(timeoutMs) { flow.first { isConnected(route) } } != null
    }

    /**
     * True when the LG TV answers a request within [timeoutMs]. A connection that sat in a frozen
     * (cached) app process can look connected while the TV has already dropped it.
     */
    suspend fun lgAnswers(timeoutMs: Long): Boolean = lg.isConnected &&
        withTimeoutOrNull(timeoutMs) { runCatching { lg.request("ssap://audio/getVolume") }.isSuccess } == true

    /** Drops the LG connection and dials again (same TV, same pairing key). */
    fun reconnectLg() {
        if (app.prefs.lgIp.isNotEmpty()) lg.connect(app.prefs.lgIp, app.prefs.lgKey)
    }

    /**
     * Dials [route] again right away unless it is connected or waiting for the user on the TV. A tap must
     * not wait for a client's retry back-off, or for a dial that started while Android was blocking the
     * network of the cached (background) app and is now stuck until its timeout.
     */
    fun redialIfDown(route: TvRoute) {
        val p = app.prefs
        when (route) {
            TvRoute.LG -> if (lg.state.value.let { it !is LgState.Connected && it !is LgState.WaitingForPrompt }) reconnectLg()
            TvRoute.SAMSUNG -> if (p.samsungIp.isNotEmpty() && samsung.state.value.let { it !is SamsungState.Connected && it !is SamsungState.WaitingForPrompt })
                samsung.connect(p.samsungIp, p.samsungToken)
            TvRoute.ATV -> if (p.atvIp.isNotEmpty() && p.atvPaired && atv.state.value.let { it !is AtvState.Connected && it !is AtvState.NeedsPairing })
                atv.connect(p.atvIp)
            TvRoute.NONE -> {}
        }
    }

    /** LG power: off when connected, else Wake-on-LAN. Returns the message to show. */
    suspend fun lgPower(): String {
        if (lg.isConnected) { lg.powerOff(); return "TV off" }
        val mac = app.prefs.lgMac ?: return "TV MAC unknown yet. Connect once while it is on."
        runCatching { Wol.send(mac, app.prefs.lgIp) }
        ensureConnected()
        return "Wake-on-LAN sent"
    }

    suspend fun samsungPower(): String {
        // The TV keeps the connection open in network standby, so KEY_POWER both turns it off and on.
        if (samsung.isConnected) { samsung.powerToggle(); return "Power sent to Samsung TV" }
        val mac = app.prefs.samsungMac ?: return "TV MAC unknown yet. Connect once while it is on."
        runCatching { Wol.send(mac, app.prefs.samsungIp) }
        ensureConnected()
        return "Wake-on-LAN sent"
    }

    /** The power button of "the TV" (LG unless only a Samsung is set up). */
    suspend fun tvPower(): String = if (samsungIsTheTv) samsungPower() else lgPower()
}
