package com.dorin.remote

import com.dorin.remote.tizen.SamsungApp
import com.dorin.remote.tizen.SamsungMsg
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Checks the JSON sent to a Tizen TV against the shapes documented for the samsung.remote.control channel. */
class SamsungProtocolTest {
    @Test fun wsUrlEncodesNameAndToken() {
        val url = SamsungMsg.wsUrl("10.0.0.5", secure = true, token = "12345678")
        assertEquals("wss://10.0.0.5:8002/api/v2/channels/samsung.remote.control?name=VW5pUmVtb3Rl&token=12345678", url)
        // The insecure port never takes a token.
        assertFalse(SamsungMsg.wsUrl("10.0.0.5", secure = false, token = "12345678").contains("token"))
        assertTrue(SamsungMsg.wsUrl("10.0.0.5", secure = false, token = null).startsWith("ws://10.0.0.5:8001/"))
    }

    @Test fun keyClick() {
        val p = JSONObject(SamsungMsg.key("KEY_VOLUP")).also { assertEquals("ms.remote.control", it.getString("method")) }.getJSONObject("params")
        assertEquals("Click", p.getString("Cmd"))
        assertEquals("KEY_VOLUP", p.getString("DataOfCmd"))
        assertEquals("false", p.getString("Option"))
        assertEquals("SendRemoteKey", p.getString("TypeOfRemote"))
    }

    @Test fun textIsBase64() {
        val p = JSONObject(SamsungMsg.text("hello")).getJSONObject("params")
        assertEquals("aGVsbG8=", p.getString("Cmd"))
        assertEquals("base64", p.getString("DataOfCmd"))
        assertEquals("SendInputString", p.getString("TypeOfRemote"))
        assertEquals("SendInputEnd", JSONObject(SamsungMsg.inputEnd()).getJSONObject("params").getString("TypeOfRemote"))
    }

    @Test fun mouse() {
        val p = JSONObject(SamsungMsg.mouseMove(3, -4, 1700000000000L)).getJSONObject("params")
        assertEquals("Move", p.getString("Cmd"))
        assertEquals("ProcessMouseDevice", p.getString("TypeOfRemote"))
        assertEquals(3, p.getJSONObject("Position").getInt("x"))
        assertEquals(-4, p.getJSONObject("Position").getInt("y"))
        assertEquals("1700000000000", p.getJSONObject("Position").getString("Time"))
        assertEquals("LeftClick", JSONObject(SamsungMsg.mouseClick()).getJSONObject("params").getString("Cmd"))
    }

    @Test fun launchAndApps() {
        val m = JSONObject(SamsungMsg.launch("111299001912", "DEEP_LINK", "v=abc"))
        assertEquals("ms.channel.emit", m.getString("method"))
        val p = m.getJSONObject("params")
        assertEquals("ed.apps.launch", p.getString("event"))
        assertEquals("host", p.getString("to"))
        assertEquals("111299001912", p.getJSONObject("data").getString("appId"))
        assertEquals("DEEP_LINK", p.getJSONObject("data").getString("action_type"))
        assertEquals("v=abc", p.getJSONObject("data").getString("metaTag"))
        assertEquals("ed.installedApp.get", JSONObject(SamsungMsg.installedApps()).getJSONObject("params").getString("event"))
    }

    @Test fun launchTypeByAppType() {
        assertEquals("DEEP_LINK", SamsungApp("1", "Tizen app", 2).launchType)
        assertEquals("NATIVE_LAUNCH", SamsungApp("2", "Web app", 4).launchType)
    }
}
