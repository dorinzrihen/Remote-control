package com.dorin.remote

import com.dorin.remote.wiz.LightMode
import com.dorin.remote.wiz.Pilot
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WizTest {
    @Test fun productionPresets() {
        assertEquals(100, LightMode.REGULAR.dimming)
        assertEquals(6500, LightMode.REGULAR.temp)
        assertEquals(20, LightMode.NIGHT.dimming)
        assertEquals(2700, LightMode.NIGHT.temp)
    }

    @Test fun displayModeUsesManagerObservation() {
        assertEquals(LightMode.NIGHT, LightMode.of(Pilot("x", true, 20, 2700)))
        assertEquals(LightMode.REGULAR, LightMode.of(Pilot("x", true, 100, 6500)))
        assertNull(LightMode.of(Pilot("x", false, 100, 6500)))
        assertNull(LightMode.of(Pilot("x", true, 40, null)))
    }
}
