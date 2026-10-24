package com.dorin.remote

import android.app.Application
import com.dorin.remote.atv.AtvClient
import com.dorin.remote.webos.WebOsClient

/** Holds the device clients for the whole process so the sleep-timer service can use them too. */
class App : Application() {
    lateinit var prefs: Prefs
    lateinit var lg: WebOsClient
    lateinit var atv: AtvClient

    override fun onCreate() {
        super.onCreate()
        instance = this
        prefs = Prefs(this)
        lg = WebOsClient { key -> prefs.lgKey = key }
        atv = AtvClient(this)
    }

    companion object {
        lateinit var instance: App
            private set
    }
}
