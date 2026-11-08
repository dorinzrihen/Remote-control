package com.dorin.remote

import android.app.Application
import com.dorin.remote.atv.AtvClient
import com.dorin.remote.tizen.SamsungClient
import com.dorin.remote.webos.WebOsClient
import com.dorin.remote.wiz.Lights

/** Holds device clients for the process and the TV sleep-timer service. */
class App : Application() {
    lateinit var prefs: Prefs
    lateinit var lg: WebOsClient
    lateinit var atv: AtvClient
    lateinit var samsung: SamsungClient
    lateinit var lights: Lights
    lateinit var tv: TvControl

    override fun onCreate() {
        super.onCreate()
        instance = this
        prefs = Prefs(this)
        NightLightsReceiver.cancelLegacyAlarm(this)
        lg = WebOsClient { key -> prefs.lgKey = key }
        atv = AtvClient(this)
        samsung = SamsungClient(this) { token -> prefs.samsungToken = token }
        lights = Lights(prefs)
        tv = TvControl(this)
    }

    companion object {
        lateinit var instance: App
            private set
    }
}
