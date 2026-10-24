package com.dorin.remote

import android.content.Context

class Prefs(ctx: Context) {
    private val sp = ctx.getSharedPreferences("uniremote", Context.MODE_PRIVATE)

    var lgIp: String
        get() = sp.getString("lg_ip", "") ?: ""
        set(v) = sp.edit().putString("lg_ip", v).apply()
    var lgKey: String?
        get() = sp.getString("lg_key", null)
        set(v) = sp.edit().putString("lg_key", v).apply()
    var lgMac: String?
        get() = sp.getString("lg_mac", null)
        set(v) = sp.edit().putString("lg_mac", v).apply()
    var atvIp: String
        get() = sp.getString("atv_ip", "") ?: ""
        set(v) = sp.edit().putString("atv_ip", v).apply()
    var atvPaired: Boolean
        get() = sp.getBoolean("atv_paired", false)
        set(v) = sp.edit().putBoolean("atv_paired", v).apply()
    var autoKeyboard: Boolean
        get() = sp.getBoolean("auto_keyboard", true)
        set(v) = sp.edit().putBoolean("auto_keyboard", v).apply()
    var pointerSpeed: Float
        get() = sp.getFloat("pointer_speed", 1.6f)
        set(v) = sp.edit().putFloat("pointer_speed", v).apply()
    var lgShortcuts: List<String>
        get() = (sp.getString("lg_shortcuts", null) ?: "netflix,youtube.leanback.v4,tv.freetv.portal").split(",").filter { it.isNotEmpty() }
        set(v) = sp.edit().putString("lg_shortcuts", v.joinToString(",")).apply()
    var lgAppsCache: String?
        get() = sp.getString("lg_apps_cache", null)
        set(v) = sp.edit().putString("lg_apps_cache", v).apply()
    /** "name|url" entries. */
    var webShortcuts: List<Pair<String, String>>
        get() = (sp.getString("web_shortcuts", null) ?: "Stremio|https://web.stremio.com")
            .split("\n").filter { it.contains("|") }.map { it.substringBefore("|") to it.substringAfter("|") }
        set(v) = sp.edit().putString("web_shortcuts", v.joinToString("\n") { "${it.first}|${it.second}" }).apply()
    var xiaomiInputId: String?
        get() = sp.getString("xiaomi_input", null)
        set(v) = sp.edit().putString("xiaomi_input", v).apply()
}
