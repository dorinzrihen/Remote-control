package com.dorin.remote.widget

import com.dorin.remote.Key
import com.dorin.remote.TvRoute

/** The six buttons of the TV widget, and nothing else. */
enum class WidgetCommand(val key: Key) {
    VOL_UP(Key.VOL_UP), VOL_DOWN(Key.VOL_DOWN), UP(Key.UP), DOWN(Key.DOWN), LEFT(Key.LEFT), RIGHT(Key.RIGHT);

    val isVolume: Boolean get() = this == VOL_UP || this == VOL_DOWN

    companion object {
        fun parse(name: String?): WidgetCommand? = entries.firstOrNull { it.name == name }
    }
}

/** Pure decisions for the TV widget, kept free of Android types so they are unit-tested. */
object WidgetLogic {
    /** Connection wait per tap: a frozen app process may need to dial the TV again. */
    const val CONNECT_TIMEOUT_MS = 5_000L
    /** How long a reused LG connection may take to answer before it is treated as dead and redialled. */
    const val PROBE_TIMEOUT_MS = 1_200L
    /** Taps closer together than this reuse the connection without asking the TV first. */
    const val PROBE_AFTER_IDLE_MS = 20_000L

    /** "The TV", as on the remote screen: LG unless only a Samsung is set up; the Xiaomi only when it is alone. */
    fun tvRoute(lg: Boolean, samsung: Boolean, atv: Boolean): TvRoute = when {
        lg -> TvRoute.LG
        samsung -> TvRoute.SAMSUNG
        atv -> TvRoute.ATV
        else -> TvRoute.NONE
    }

    /**
     * Where a press goes. Volume always goes to the TV (it forwards to the soundbar over HDMI ARC).
     * Arrows follow the remote screen's rule: while the LG TV shows the Xiaomi's HDMI input, they go to the Xiaomi.
     */
    fun route(command: WidgetCommand, lg: Boolean, samsung: Boolean, atv: Boolean, lgShowsXiaomi: Boolean): TvRoute {
        val tv = tvRoute(lg, samsung, atv)
        if (command.isVolume) return tv
        return if (tv == TvRoute.LG && lgShowsXiaomi && atv) TvRoute.ATV else tv
    }

    /** True when a reused LG connection should be checked before sending (it may have died while the app was frozen). */
    fun shouldProbe(connectedBeforeTap: Boolean, lastSuccessMs: Long, nowMs: Long): Boolean =
        connectedBeforeTap && nowMs - lastSuccessMs >= PROBE_AFTER_IDLE_MS

    fun deviceName(route: TvRoute): String = when (route) {
        TvRoute.LG -> "LG TV"
        TvRoute.SAMSUNG -> "Samsung TV"
        TvRoute.ATV -> "Xiaomi"
        TvRoute.NONE -> "No TV set up"
    }

    /** The widget's one read-only line: device, then the volume (LG reports it) or what went wrong. */
    fun label(route: TvRoute, volume: Int?, problem: String?): String {
        val name = deviceName(route)
        return when {
            route == TvRoute.NONE -> "Set up a TV in UniRemote"
            problem != null -> "$name  ·  $problem"
            volume != null -> "$name  ·  Volume $volume"
            else -> name
        }
    }
}
