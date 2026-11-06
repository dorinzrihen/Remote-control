package com.dorin.remote

import com.dorin.remote.wiz.ButlerClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ButlerTest {
    @Test fun configOnlySavesTimetableNeverPhoneBulbs() {
        val c = ButlerClient.config(true, "21:00", "06:00", "Asia/Jerusalem")
        assertTrue(c.getBoolean("enabled"))
        assertEquals("21:00", c.getString("night"))
        assertEquals("06:00", c.getString("morning"))
        assertEquals("Asia/Jerusalem", c.getString("timezone"))
        assertEquals(1, c.getInt("pollSeconds"))
        assertFalse(c.has("bulbs"))
        assertFalse(c.has("setSchdPset"))
    }

    @Test fun customTimetableAndPollingAreUploadedNotHardcoded() {
        val c = ButlerClient.config(true, "22:15", "07:45", "Europe/Berlin", 17)
        assertEquals("22:15", c.getString("night"))
        assertEquals("07:45", c.getString("morning"))
        assertEquals("Europe/Berlin", c.getString("timezone"))
        assertEquals(17, c.getInt("pollSeconds"))
    }

    @Test fun rejectsCredentialsInUrl() {
        try {
            ButlerClient.validateConnection("http://user:password@192.168.1.2:8788", "x".repeat(32))
            throw AssertionError("Must reject URL credentials")
        } catch (_: IllegalArgumentException) { }
    }

    @Test fun rejectsShortToken() {
        try {
            ButlerClient.validateConnection("http://192.168.1.2:8788", "short")
            throw AssertionError("Must reject short token")
        } catch (_: IllegalArgumentException) { }
    }
}
