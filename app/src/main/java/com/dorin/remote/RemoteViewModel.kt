package com.dorin.remote

import android.app.Application
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.dorin.remote.atv.AtvClient
import com.dorin.remote.atv.AtvKeys
import com.dorin.remote.atv.AtvState
import com.dorin.remote.net.Discovery
import com.dorin.remote.net.FoundDevice
import com.dorin.remote.net.Wol
import com.dorin.remote.webos.LgState
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

enum class Target { LG, ATV }

enum class Key {
    UP, DOWN, LEFT, RIGHT, OK, BACK, HOME, MENU, EXIT, INFO,
    PLAY, PAUSE, PLAY_PAUSE, STOP, REWIND, FAST_FORWARD,
    VOL_UP, VOL_DOWN, MUTE, CH_UP, CH_DOWN, SETTINGS, SEARCH,
    RED, GREEN, YELLOW, BLUE,
    N0, N1, N2, N3, N4, N5, N6, N7, N8, N9,
}

/** A button in the shortcuts row. Exactly one of lgId / atvLink / url is used depending on the target. */
data class Shortcut(val label: String, val lgId: String? = null, val atvLink: String? = null, val url: String? = null,
                    val iconKey: String = label, val iconUrl: String? = null)

/** Android TV deep links for well-known LG app ids, so the same shortcut works on the Xiaomi. */
val ATV_LINKS = mapOf(
    "netflix" to "https://www.netflix.com/title",
    "youtube.leanback.v4" to "https://www.youtube.com",
    "amazon" to "https://app.primevideo.com",
    "com.disney.disneyplus-prod" to "https://www.disneyplus.com",
    "spotify-beehive" to "https://open.spotify.com",
)

class RemoteViewModel(app: Application) : AndroidViewModel(app) {
    private val tag = "RemoteVM"
    private val application = app as App
    val prefs = application.prefs
    val lg = application.lg
    val atv = application.atv

    val target = MutableStateFlow(Target.LG)
    val showSetup = MutableStateFlow(prefs.lgIp.isEmpty() && prefs.atvIp.isEmpty())
    val showQuick = MutableStateFlow(false)
    val sleepEnd = SleepTimerService.endTime
    val keyboardOpen = MutableStateFlow(false)
    val messages = MutableSharedFlow<String>(extraBufferCapacity = 4)

    // setup screen state
    val lgIp = MutableStateFlow(prefs.lgIp)
    val atvIp = MutableStateFlow(prefs.atvIp)
    val lgFound = MutableStateFlow<List<FoundDevice>>(emptyList())
    val atvFound = MutableStateFlow<List<FoundDevice>>(emptyList())
    val scanning = MutableStateFlow(false)
    val pairingSession = MutableStateFlow<AtvClient.PairingSession?>(null)
    val pairingError = MutableStateFlow<String?>(null)
    val pairingBusy = MutableStateFlow(false)
    val xiaomiInputId = MutableStateFlow(prefs.xiaomiInputId)
    val pointerSpeed = MutableStateFlow(prefs.pointerSpeed)
    val autoKeyboard = MutableStateFlow(prefs.autoKeyboard)
    val lgShortcutIds = MutableStateFlow(prefs.lgShortcuts)
    val webShortcuts = MutableStateFlow(prefs.webShortcuts)
    val lgApps = MutableStateFlow(loadAppsCache())
    /** Text recognised from the phone microphone, consumed by the keyboard bar. */
    val voiceText = MutableStateFlow<String?>(null)
    // self-update via GitHub Releases
    val update = MutableStateFlow<com.dorin.remote.net.UpdateInfo?>(null)
    val updateProgress = MutableStateFlow<Float?>(null)
    val updateDismissed = MutableStateFlow(false)
    val currentVersion: String = runCatching {
        app.packageManager.getPackageInfo(app.packageName, 0).versionName ?: "0"
    }.getOrDefault("0")
    // YouTube search (done on the phone, playback on the TV)
    val showYouTube = MutableStateFlow(false)
    val ytQuery = MutableStateFlow("")
    val ytResults = MutableStateFlow<List<com.dorin.remote.net.YtVideo>>(emptyList())
    val ytLoading = MutableStateFlow(false)
    val ytError = MutableStateFlow<String?>(null)

    init {
        connectAll()
        viewModelScope.launch {
            runCatching { com.dorin.remote.net.Updater.check(currentVersion) }
                .onSuccess { update.value = it }
                .onFailure { Log.w(tag, "update check failed: ${it.message}") }
        }
        viewModelScope.launch {
            lg.apps.collect { list ->
                if (list.isNotEmpty()) {
                    lgApps.value = list
                    prefs.lgAppsCache = org.json.JSONArray(list.map { org.json.JSONObject().put("id", it.id).put("title", it.title).put("icon", it.icon ?: "") }).toString()
                }
            }
        }
        viewModelScope.launch {
            lg.macAddress.collect { mac -> if (mac != null) prefs.lgMac = mac }
        }
        viewModelScope.launch {
            // Auto-open the phone keyboard when the LG TV focuses a text field.
            combine(lg.keyboardFocused, target, autoKeyboard) { f, t, a -> f && a && t == Target.LG }
                .collect { if (it) keyboardOpen.value = true }
        }
        viewModelScope.launch {
            // Follow the TV: when it shows the Xiaomi HDMI input, route navigation to the box.
            lg.currentApp.collect { appId ->
                val xi = xiaomiInputId.value ?: return@collect
                val input = lg.inputs.value.firstOrNull { it.id == xi } ?: return@collect
                if (appId == input.appId) target.value = Target.ATV
                else if (appId.isNotEmpty() && target.value == Target.ATV) target.value = Target.LG
            }
        }
    }

    fun connectAll() {
        if (prefs.lgIp.isNotEmpty()) lg.connect(prefs.lgIp, prefs.lgKey) else lg.disconnect()
        if (prefs.atvIp.isNotEmpty() && prefs.atvPaired) atv.connect(prefs.atvIp) else atv.disconnect()
    }

    fun reconnect() {
        if (lg.state.value !is LgState.Connected && prefs.lgIp.isNotEmpty()) lg.connect(prefs.lgIp, prefs.lgKey)
        if (atv.state.value !is AtvState.Connected && prefs.atvIp.isNotEmpty() && prefs.atvPaired) atv.connect(prefs.atvIp)
    }

    private fun say(msg: String) { messages.tryEmit(msg) }

    // ---------- routing ----------

    fun press(key: Key) {
        when (key) {
            Key.VOL_UP, Key.VOL_DOWN, Key.MUTE -> {
                // Volume goes to the TV whenever it is reachable: over HDMI ARC the TV forwards it to the soundbar.
                if (lg.isConnected) {
                    when (key) {
                        Key.VOL_UP -> lg.volumeUp()
                        Key.VOL_DOWN -> lg.volumeDown()
                        else -> lg.setMute(!lg.muted.value)
                    }
                } else if (atv.isConnected) atv.key(atvKey(key)!!)
                else say("Not connected")
                return
            }
            else -> {}
        }
        when (target.value) {
            Target.LG -> {
                if (!lg.isConnected) { say("LG TV not connected"); return }
                lgButton(key)
            }
            Target.ATV -> {
                if (!atv.isConnected) { say("Xiaomi not connected"); return }
                atvKey(key)?.let { atv.key(it) } ?: say("Not available on Xiaomi")
            }
        }
    }

    private fun lgButton(key: Key) {
        val name = when (key) {
            Key.UP -> "UP"; Key.DOWN -> "DOWN"; Key.LEFT -> "LEFT"; Key.RIGHT -> "RIGHT"; Key.OK -> "ENTER"
            Key.BACK -> "BACK"; Key.HOME -> "HOME"; Key.MENU -> "MENU"; Key.EXIT -> "EXIT"; Key.INFO -> "INFO"
            Key.PLAY -> "PLAY"; Key.PAUSE -> "PAUSE"; Key.STOP -> "STOP"; Key.REWIND -> "REWIND"; Key.FAST_FORWARD -> "FASTFORWARD"
            Key.CH_UP -> "CHANNELUP"; Key.CH_DOWN -> "CHANNELDOWN"; Key.SETTINGS -> "MENU"
            Key.RED -> "RED"; Key.GREEN -> "GREEN"; Key.YELLOW -> "YELLOW"; Key.BLUE -> "BLUE"
            Key.N0 -> "0"; Key.N1 -> "1"; Key.N2 -> "2"; Key.N3 -> "3"; Key.N4 -> "4"
            Key.N5 -> "5"; Key.N6 -> "6"; Key.N7 -> "7"; Key.N8 -> "8"; Key.N9 -> "9"
            Key.PLAY_PAUSE -> { lg.button("PLAY"); return }
            Key.SEARCH -> { lg.launchApp("com.webos.app.voice"); return }
            Key.VOL_UP, Key.VOL_DOWN, Key.MUTE -> return
        }
        lg.button(name)
    }

    private fun atvKey(key: Key): Int? = when (key) {
        Key.UP -> AtvKeys.DPAD_UP; Key.DOWN -> AtvKeys.DPAD_DOWN; Key.LEFT -> AtvKeys.DPAD_LEFT; Key.RIGHT -> AtvKeys.DPAD_RIGHT
        Key.OK -> AtvKeys.DPAD_CENTER; Key.BACK -> AtvKeys.BACK; Key.HOME -> AtvKeys.HOME; Key.MENU -> AtvKeys.MENU
        Key.EXIT -> AtvKeys.BACK; Key.INFO -> AtvKeys.INFO
        Key.PLAY -> AtvKeys.MEDIA_PLAY; Key.PAUSE -> AtvKeys.MEDIA_PAUSE; Key.PLAY_PAUSE -> AtvKeys.MEDIA_PLAY_PAUSE
        Key.STOP -> AtvKeys.MEDIA_STOP; Key.REWIND -> AtvKeys.MEDIA_REWIND; Key.FAST_FORWARD -> AtvKeys.MEDIA_FAST_FORWARD
        Key.VOL_UP -> AtvKeys.VOLUME_UP; Key.VOL_DOWN -> AtvKeys.VOLUME_DOWN; Key.MUTE -> AtvKeys.VOLUME_MUTE
        Key.CH_UP -> AtvKeys.CHANNEL_UP; Key.CH_DOWN -> AtvKeys.CHANNEL_DOWN; Key.SETTINGS -> AtvKeys.SETTINGS
        Key.SEARCH -> AtvKeys.SEARCH
        Key.N0 -> AtvKeys.KEY_0; Key.N1 -> AtvKeys.KEY_0 + 1; Key.N2 -> AtvKeys.KEY_0 + 2; Key.N3 -> AtvKeys.KEY_0 + 3
        Key.N4 -> AtvKeys.KEY_0 + 4; Key.N5 -> AtvKeys.KEY_0 + 5; Key.N6 -> AtvKeys.KEY_0 + 6; Key.N7 -> AtvKeys.KEY_0 + 7
        Key.N8 -> AtvKeys.KEY_0 + 8; Key.N9 -> AtvKeys.KEY_0 + 9
        Key.RED, Key.GREEN, Key.YELLOW, Key.BLUE -> null
    }

    // ---------- touchpad ----------

    fun pointerMove(dx: Float, dy: Float) {
        if (target.value == Target.LG) lg.move(dx.toInt(), dy.toInt())
    }

    fun pointerClick() {
        when (target.value) {
            Target.LG -> lg.click()
            Target.ATV -> atv.key(AtvKeys.DPAD_CENTER)
        }
    }

    fun pointerScroll(dy: Float) {
        if (target.value == Target.LG) lg.scroll(0, dy.toInt())
    }

    // ---------- power / input ----------

    fun lgPower() {
        viewModelScope.launch {
            if (lg.isConnected) {
                lg.powerOff(); say("TV off")
            } else {
                val mac = prefs.lgMac
                if (mac == null) { say("TV MAC unknown yet. Connect once while it is on.") ; return@launch }
                runCatching { Wol.send(mac, prefs.lgIp) }
                say("Wake-on-LAN sent")
                reconnect()
            }
        }
    }

    fun atvPower() {
        if (atv.isConnected) atv.key(AtvKeys.POWER) else say("Xiaomi not connected")
    }

    fun switchLgInput(id: String) {
        lg.switchInput(id)
        if (id == xiaomiInputId.value) target.value = Target.ATV
    }

    fun goToXiaomi() {
        val id = xiaomiInputId.value
        if (id != null && lg.isConnected) lg.switchInput(id)
        target.value = Target.ATV
    }

    private fun loadAppsCache(): List<com.dorin.remote.webos.LgApp> = runCatching {
        val arr = org.json.JSONArray(prefs.lgAppsCache ?: return emptyList())
        (0 until arr.length()).map { arr.getJSONObject(it) }.map { com.dorin.remote.webos.LgApp(it.getString("id"), it.getString("title"), it.optString("icon").ifEmpty { null }) }
    }.getOrDefault(emptyList())

    /** Shortcut buttons for the current target. */
    fun shortcutsFor(t: Target): List<Shortcut> {
        val apps = lgApps.value.associateBy { it.id }
        val appButtons = lgShortcutIds.value.mapNotNull { id ->
            val app = apps[id]
            val title = app?.title ?: ATV_LINKS.keys.firstOrNull { it == id }?.let { id.substringBefore('.').replaceFirstChar(Char::uppercase) } ?: id
            when (t) {
                Target.LG -> Shortcut(title, lgId = id, iconKey = "app:$id", iconUrl = app?.icon)
                Target.ATV -> ATV_LINKS[id]?.let { Shortcut(title, atvLink = it, iconKey = "app:$id", iconUrl = app?.icon) }
            }
        }
        return appButtons + webShortcuts.value.map {
            Shortcut(it.first, url = it.second, iconKey = "web:${it.second}", iconUrl = com.dorin.remote.net.IconCache.faviconUrl(it.second))
        }
    }

    fun launch(sc: Shortcut) {
        when (target.value) {
            Target.LG -> when {
                sc.lgId != null -> lg.launchApp(sc.lgId)
                sc.url != null -> lg.openUrl(sc.url)
            }
            Target.ATV -> when {
                sc.atvLink != null -> atv.launchApp(sc.atvLink)
                sc.url != null -> atv.launchApp(sc.url)
            }
        }
    }

    /** Opens the YouTube sheet and runs the search on the phone. */
    fun searchYouTube(query: String) {
        showYouTube.value = true
        youtubeSearch(query)
    }

    fun youtubeSearch(query: String) {
        ytQuery.value = query
        if (query.isBlank()) return
        viewModelScope.launch {
            ytLoading.value = true; ytError.value = null
            try {
                ytResults.value = com.dorin.remote.net.YouTubeSearch.search(query)
                if (ytResults.value.isEmpty()) ytError.value = "No results"
            } catch (e: Exception) {
                Log.w(tag, "youtube search failed", e)
                ytError.value = "Search failed: ${e.message}"
            } finally { ytLoading.value = false }
        }
    }

    fun playYouTube(v: com.dorin.remote.net.YtVideo) {
        when (target.value) {
            Target.LG -> lg.playYouTube(v.id)
            Target.ATV -> atv.launchApp("https://www.youtube.com/watch?v=${v.id}")
        }
        say("Playing on TV: ${v.title}")
    }

    fun setLgShortcuts(ids: List<String>) { prefs.lgShortcuts = ids; lgShortcutIds.value = ids }
    fun setWebShortcuts(list: List<Pair<String, String>>) { prefs.webShortcuts = list; webShortcuts.value = list }

    fun installUpdate() {
        val info = update.value ?: return
        val ctx = getApplication<Application>()
        if (!com.dorin.remote.net.Updater.ensureInstallPermission(ctx)) {
            say("Allow UniRemote to install updates, then press Update again")
            return
        }
        viewModelScope.launch {
            try {
                updateProgress.value = 0f
                val apk = com.dorin.remote.net.Updater.download(ctx, info) { updateProgress.value = it }
                updateProgress.value = null
                com.dorin.remote.net.Updater.install(ctx, apk)
            } catch (e: Exception) {
                updateProgress.value = null
                say("Update failed: ${e.message}")
            }
        }
    }

    fun onVoiceResult(text: String) {
        voiceText.value = text
        keyboardOpen.value = true
    }

    // ---------- keyboard ----------

    private var typed = ""

    fun keyboardText(newText: String) {
        val old = typed
        typed = newText
        val common = old.commonPrefixWith(newText).length
        val removed = old.length - common
        val added = newText.substring(common)
        when (target.value) {
            Target.LG -> viewModelScope.launch {
                var err: String? = null
                if (removed > 0) err = lg.deleteChars(removed)
                if (added.isNotEmpty()) err = lg.insertText(added) ?: err
                if (err != null) sayOnce("TV: $err")
            }
            Target.ATV -> {
                repeat(removed) { atv.key(AtvKeys.DEL) }
                if (added.isNotEmpty()) atv.sendText(added)
            }
        }
    }

    private var lastSaid = 0L
    private fun sayOnce(msg: String) {
        val now = System.currentTimeMillis()
        if (now - lastSaid > 4000) { lastSaid = now; say(msg) }
    }

    fun keyboardEnter() {
        when (target.value) {
            Target.LG -> viewModelScope.launch { lg.sendEnter()?.let { sayOnce("TV: $it") } }
            Target.ATV -> atv.key(AtvKeys.ENTER)
        }
        typed = ""
    }

    // ---------- quick actions ----------

    fun setBacklight(value: Int) {
        viewModelScope.launch {
            runCatching { lg.setPictureSetting("backlight", value.toString()) }
                .onFailure { say("Could not set brightness: ${it.message}") }
        }
    }

    fun setPictureMode(mode: String) {
        viewModelScope.launch {
            runCatching { lg.setPictureSetting("pictureMode", mode) }
                .onFailure { say("Could not set picture mode: ${it.message}") }
        }
    }

    fun screenOff() { lg.screenOff(); say("Screen off (sound stays on). Press any button to wake it.") }

    fun startSleep(minutes: Int) {
        SleepTimerService.start(getApplication(), minutes)
        say("TV turns off in $minutes min")
    }

    fun cancelSleep() { SleepTimerService.cancel(getApplication()) }

    fun keyboardReset() { typed = "" }

    // ---------- setup ----------

    fun scan() {
        viewModelScope.launch {
            scanning.value = true
            try {
                val ctx = getApplication<Application>()
                lgFound.value = Discovery.findLgTvs(ctx)
                atvFound.value = Discovery.findAndroidTvs(ctx)
                if (lgFound.value.isEmpty() && atvFound.value.isEmpty()) say("Nothing found. Type the IPs manually.")
            } finally { scanning.value = false }
        }
    }

    fun saveLg(ip: String) {
        val clean = ip.trim()
        if (clean != prefs.lgIp) { prefs.lgKey = null; prefs.lgMac = null }
        prefs.lgIp = clean
        lgIp.value = clean
        if (clean.isNotEmpty()) lg.connect(clean, prefs.lgKey) else lg.disconnect()
    }

    fun forgetLg() { prefs.lgKey = null; saveLg(lgIp.value) }

    fun startPairing(ip: String) {
        val clean = ip.trim()
        if (clean.isEmpty()) { say("Enter the Xiaomi IP first"); return }
        prefs.atvIp = clean
        atvIp.value = clean
        pairingError.value = null
        pairingBusy.value = true
        viewModelScope.launch {
            try {
                pairingSession.value = atv.startPairing(clean)
            } catch (e: Exception) {
                Log.w(tag, "pairing start failed", e)
                pairingError.value = "Could not start pairing: ${e.message}"
            } finally { pairingBusy.value = false }
        }
    }

    fun finishPairing(code: String) {
        val session = pairingSession.value ?: return
        pairingBusy.value = true
        viewModelScope.launch {
            try {
                session.finish(code)
                prefs.atvPaired = true
                pairingSession.value = null
                pairingError.value = null
                say("Paired with Xiaomi")
                atv.connect(prefs.atvIp)
            } catch (e: Exception) {
                Log.w(tag, "pairing failed", e)
                pairingError.value = e.message ?: "Pairing failed"
                pairingSession.value = null
            } finally { pairingBusy.value = false }
        }
    }

    fun cancelPairing() {
        pairingSession.value?.cancel()
        pairingSession.value = null
    }

    fun setXiaomiInput(id: String?) { prefs.xiaomiInputId = id; xiaomiInputId.value = id }
    fun setPointerSpeed(v: Float) { prefs.pointerSpeed = v; pointerSpeed.value = v }
    fun setAutoKeyboard(v: Boolean) { prefs.autoKeyboard = v; autoKeyboard.value = v }

    override fun onCleared() {
        // Clients live in App so the sleep timer keeps working after the screen closes.
    }
}
