package com.dorin.remote

import com.dorin.remote.widget.WidgetCommand
import com.dorin.remote.widget.WidgetLogic
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class WidgetLogicTest {
    @Test fun commandsAreExactlyVolumeAndArrows() {
        assertEquals(listOf(Key.VOL_UP, Key.VOL_DOWN, Key.UP, Key.DOWN, Key.LEFT, Key.RIGHT), WidgetCommand.entries.map { it.key })
        assertEquals(WidgetCommand.LEFT, WidgetCommand.parse("LEFT"))
        assertNull(WidgetCommand.parse("OK"))
        assertNull(WidgetCommand.parse(null))
    }

    @Test fun theTvIsLgThenSamsungThenXiaomi() {
        assertEquals(TvRoute.LG, WidgetLogic.tvRoute(lg = true, samsung = true, atv = true))
        assertEquals(TvRoute.SAMSUNG, WidgetLogic.tvRoute(lg = false, samsung = true, atv = true))
        assertEquals(TvRoute.ATV, WidgetLogic.tvRoute(lg = false, samsung = false, atv = true))
        assertEquals(TvRoute.NONE, WidgetLogic.tvRoute(lg = false, samsung = false, atv = false))
    }

    @Test fun volumeAlwaysGoesToTheTv() {
        for (showsXiaomi in listOf(false, true)) {
            assertEquals(TvRoute.LG, WidgetLogic.route(WidgetCommand.VOL_UP, lg = true, samsung = false, atv = true, lgShowsXiaomi = showsXiaomi))
            assertEquals(TvRoute.SAMSUNG, WidgetLogic.route(WidgetCommand.VOL_DOWN, lg = false, samsung = true, atv = true, lgShowsXiaomi = showsXiaomi))
        }
    }

    @Test fun arrowsFollowTheXiaomiInputLikeTheRemoteScreen() {
        assertEquals(TvRoute.LG, WidgetLogic.route(WidgetCommand.UP, lg = true, samsung = false, atv = true, lgShowsXiaomi = false))
        assertEquals(TvRoute.ATV, WidgetLogic.route(WidgetCommand.UP, lg = true, samsung = false, atv = true, lgShowsXiaomi = true))
        // Without a paired Xiaomi the arrows stay on the TV.
        assertEquals(TvRoute.LG, WidgetLogic.route(WidgetCommand.RIGHT, lg = true, samsung = false, atv = false, lgShowsXiaomi = true))
        assertEquals(TvRoute.SAMSUNG, WidgetLogic.route(WidgetCommand.LEFT, lg = false, samsung = true, atv = true, lgShowsXiaomi = false))
        assertEquals(TvRoute.ATV, WidgetLogic.route(WidgetCommand.DOWN, lg = false, samsung = false, atv = true, lgShowsXiaomi = false))
    }

    @Test fun probeOnlyReusedIdleConnections() {
        val idle = WidgetLogic.PROBE_AFTER_IDLE_MS
        assertFalse(WidgetLogic.shouldProbe(connectedBeforeTap = false, lastSuccessMs = 0, nowMs = 10 * idle))
        assertTrue(WidgetLogic.shouldProbe(connectedBeforeTap = true, lastSuccessMs = 0, nowMs = idle))
        assertFalse(WidgetLogic.shouldProbe(connectedBeforeTap = true, lastSuccessMs = 1_000, nowMs = 1_000 + idle - 1))
    }

    @Test fun label() {
        assertEquals("LG TV  ·  Volume 12", WidgetLogic.label(TvRoute.LG, 12, null))
        assertEquals("LG TV  ·  not reachable", WidgetLogic.label(TvRoute.LG, 12, "not reachable"))
        assertEquals("Samsung TV", WidgetLogic.label(TvRoute.SAMSUNG, null, null))
        assertEquals("Set up a TV in UniRemote", WidgetLogic.label(TvRoute.NONE, null, "x"))
    }

    /** Scope guard: the widget has exactly six buttons, and nothing in it can open an activity (that would need unlocking). */
    @Test fun widgetHasOnlyTheSixButtonsAndNoActivityIntents() {
        val layout = File("src/main/res/layout/widget_tv.xml").readText()
        val buttons = Regex("""<ImageButton android:id="@\+id/(\w+)"""").findAll(layout).map { it.groupValues[1] }.toSet()
        assertEquals(setOf("w_vol_up", "w_vol_down", "w_up", "w_down", "w_left", "w_right"), buttons)
        val code = File("src/main/java/com/dorin/remote/widget/TvWidget.kt").readText()
        assertFalse(code.contains("getActivity"))
        assertFalse(code.contains("startActivity"))
        assertFalse(code.contains("startForegroundService"))
    }
}
