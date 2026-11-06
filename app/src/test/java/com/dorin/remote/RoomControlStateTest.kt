package com.dorin.remote

import com.dorin.remote.wiz.*
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class RoomControlStateTest {
    private val macs = listOf("aabb00000001", "aabb00000002")
    private fun pilots(mode: LightMode = LightMode.NIGHT, on: Boolean = true) = macs.associateWith {
        Pilot(it, on, mode.dimming, mode.temp)
    }
    private val held = macs.associateWith { 1100.0 }
    private fun state(mode: LightMode = LightMode.NIGHT, enabled: Boolean = true, holds: Map<String, Double>? = held,
                      states: Map<String, Pilot> = pilots(mode), loaded: Boolean = true, at: Double? = 1000.0) =
        roomControlState(macs, states, loaded, enabled, holds, at)

    @Test fun manualPresetsAreMutuallyExclusive() {
        assertEquals(RoomControlChoice.REGULAR, state(LightMode.REGULAR).selected)
        assertEquals(RoomControlChoice.NIGHT, state().selected)
    }

    @Test fun followingAtNightAndDayDoesNotSelectManualPreset() {
        for (mode in LightMode.entries) {
            val result = state(mode, holds = emptyMap())
            assertEquals(RoomControlChoice.FOLLOW, result.selected)
            assertEquals("Following · ${mode.label}", result.status)
        }
    }

    @Test fun disabledScheduleNeverClaimsFollowing() {
        assertEquals(RoomControlChoice.NIGHT, state(enabled = false, holds = emptyMap()).selected)
        assertEquals(RoomControlChoice.REGULAR, state(LightMode.REGULAR, enabled = false).selected)
    }

    @Test fun offBulbsCanFollowWithoutClaimingTheyAreOn() {
        val off = pilots(on = false)
        assertEquals("Following · off", state(holds = emptyMap(), states = off).status)
        assertEquals(RoomControlChoice.FOLLOW, state(holds = emptyMap(), states = off).selected)
        assertEquals("off", state(states = off).status)
        assertNull(state(states = off).selected)
    }

    @Test fun partialHoldsAreMixedRegardlessOfMatchingPilots() {
        val result = state(holds = held.filterKeys { it == macs.first() })
        assertNull(result.selected)
        assertTrue(result.status.startsWith("Mixed"))
    }

    @Test fun mixedPilotsNeverUseFirstOnBulbAsRoomPreset() {
        val mixed = pilots() + pilots(LightMode.REGULAR).filterKeys { it == macs.first() }
        assertEquals("Mixed", state(states = mixed).status)
        assertNull(state(states = mixed).selected)
        val partlyOff = pilots() + pilots(on = false).filterKeys { it == macs.first() }
        assertEquals("Mixed", state(states = partlyOff).status)
        assertNull(state(states = partlyOff).selected)
        assertEquals("Following · Mixed", state(states = mixed, holds = emptyMap()).status)
    }

    @Test fun unreachableUnavailableAndMissingMetadataMakeNoActiveClaims() {
        assertNull(state(states = pilots().filterKeys { it == macs.first() }).selected)
        assertTrue(state(states = emptyMap()).status.contains("unreachable"))
        assertNull(state(loaded = false).selected)
        assertNull(state(holds = null).selected)
        assertNull(state(at = null).selected)
        assertNull(state(holds = mapOf(macs.first() to Double.NaN)).selected)
        assertNull(roomControlState(macs, pilots(), true, null, emptyMap(), 1000.0).selected)
    }

    @Test fun expiredHoldsUseManagerTimeNotPhoneTime() {
        assertEquals(RoomControlChoice.FOLLOW, state(holds = macs.associateWith { 999.0 }).selected)
        assertEquals(RoomControlChoice.FOLLOW, state(holds = macs.associateWith { 1000.0 }).selected)
        assertEquals(RoomControlChoice.NIGHT, state(at = 1099.0).selected)
    }

    private fun snapshot(holds: Map<String, Double> = emptyMap()): JSONObject = JSONObject()
        .put("config", JSONObject().put("enabled", true).put("pollSeconds", 1).put("bulbs", JSONArray(macs.map {
            JSONObject().put("mac", it).put("room", "Room").put("ip", "192.168.50.11")
        })))
        .put("pilots", JSONObject(pilots().mapValues { (_, p) ->
            JSONObject().put("mac", p.mac).put("state", p.on).put("dimming", p.dimming).put("temp", p.temp)
        }))
        .put("systemConfigs", JSONObject()).put("errors", JSONObject())
        .put("holds", JSONObject(holds)).put("statusAt", 1000.0)
        .put("observedAt", JSONObject(macs.associateWith { 1000.0 }))

    @Test fun refreshReopenAndUnavailableReplaceReportedControlState() = runBlocking {
        var response = snapshot(held)
        val lights = Lights { _, _ -> response }
        lights.refresh()
        assertEquals(RoomControlChoice.NIGHT, lights.roomControls.value.getValue("Room").selected)
        response = snapshot()
        lights.refresh()
        assertEquals(RoomControlChoice.FOLLOW, lights.roomControls.value.getValue("Room").selected)
        val reopened = Lights { _, _ -> response }
        reopened.refresh()
        assertEquals(lights.roomControls.value, reopened.roomControls.value)
        lights.unavailable("offline")
        assertNull(lights.roomControls.value.getValue("Room").selected)
        lights.refresh()
        assertEquals(RoomControlChoice.FOLLOW, lights.roomControls.value.getValue("Room").selected)
    }

    @Test fun staleAndErroredPilotsCannotShowSelectedControl() {
        val lights = Lights { _, _ -> snapshot() }
        lights.acceptStatus(snapshot().put("observedAt", JSONObject(macs.associateWith { 970.0 })))
        assertNull(lights.roomControls.value.getValue("Room").selected)
        lights.acceptStatus(snapshot().put("errors", JSONObject().put(macs.first(), "unreachable")))
        assertNull(lights.roomControls.value.getValue("Room").selected)
        lights.acceptStatus(snapshot().apply { remove("holds") })
        assertNull(lights.roomControls.value.getValue("Room").selected)
    }
}
