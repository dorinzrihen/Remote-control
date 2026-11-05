package com.dorin.remote

import com.dorin.remote.wiz.LightMode
import com.dorin.remote.wiz.Pilot
import com.dorin.remote.wiz.Wiz
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Calendar
import java.util.TimeZone

/** WiZ UDP messages and the 21:00 night schedule. */
class WizTest {
    private fun assertJson(expected: String, actual: String) =
        assertTrue("$actual != $expected", JSONObject(expected).similar(JSONObject(actual)))

    @Test fun regular() = assertJson("""{"method":"setPilot","params":{"state":true,"dimming":100,"temp":6500}}""", Wiz.setModeJson(LightMode.REGULAR))
    @Test fun night() = assertJson("""{"method":"setPilot","params":{"state":true,"dimming":20,"temp":2700}}""", Wiz.setModeJson(LightMode.NIGHT))
    @Test fun off() = assertJson("""{"method":"setPilot","params":{"state":false}}""", Wiz.setStateJson(false))
    @Test fun getPilot() = assertJson("""{"method":"getPilot","params":{}}""", Wiz.getPilotJson())

    @Test fun parseWhite() {
        val p = Wiz.parsePilot("""{"method":"getPilot","env":"pro","result":{"mac":"aabbccddeeff","rssi":-62,"state":true,"sceneId":0,"temp":2700,"dimming":20}}""")
        assertEquals(Pilot("aabbccddeeff", true, 20, 2700), p)
        assertEquals(LightMode.NIGHT, LightMode.of(p!!))
    }

    @Test fun parseColourIsNoMode() {
        val p = Wiz.parsePilot("""{"method":"getPilot","env":"pro","result":{"mac":"aabbccddeeff","state":true,"sceneId":0,"r":255,"g":0,"b":0,"dimming":100}}""")!!
        assertNull(p.temp)
        assertNull(LightMode.of(p))
    }

    @Test fun offIsNoMode() = assertNull(LightMode.of(Pilot("x", false, 100, 6500)))
    @Test fun errorReply() = assertNull(Wiz.parsePilot("""{"method":"getPilot","env":"pro","error":{"code":-32601,"message":"Method not found"}}"""))

    @Test fun nightHours() {
        assertTrue(NightTime.isNight(21)); assertTrue(NightTime.isNight(23)); assertTrue(NightTime.isNight(0)); assertTrue(NightTime.isNight(5))
        assertFalse(NightTime.isNight(6)); assertFalse(NightTime.isNight(12)); assertFalse(NightTime.isNight(20))
    }

    private val tz = TimeZone.getTimeZone("Europe/Berlin")
    private fun at(y: Int, m: Int, d: Int, h: Int, min: Int) = Calendar.getInstance(tz).apply { clear(); set(y, m - 1, d, h, min) }.timeInMillis

    @Test fun nextNightSameDay() = assertEquals(at(2026, 11, 5, 21, 0), NightTime.next(at(2026, 11, 5, 20, 59), tz))
    @Test fun nextNightAfterFiring() = assertEquals(at(2026, 11, 6, 21, 0), NightTime.next(at(2026, 11, 5, 21, 0), tz))
    @Test fun nextNightAfterMidnight() = assertEquals(at(2026, 11, 6, 21, 0), NightTime.next(at(2026, 11, 6, 1, 30), tz))

    /** Central Europe moves the clocks forward on 28 March 2027: the alarm must still be 21:00 on the wall. */
    @Test fun nextNightAcrossDaylightSaving() {
        val next = NightTime.next(at(2027, 3, 27, 21, 0), tz)
        assertEquals(at(2027, 3, 28, 21, 0), next)
        assertEquals(21, Calendar.getInstance(tz).apply { timeInMillis = next }.get(Calendar.HOUR_OF_DAY))
        assertEquals(23 * 3600_000L, next - at(2027, 3, 27, 21, 0))
    }
}
