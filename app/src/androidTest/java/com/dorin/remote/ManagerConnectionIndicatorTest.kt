package com.dorin.remote

import android.graphics.Bitmap
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.Text
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.graphics.toPixelMap
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.test.platform.app.InstrumentationRegistry
import com.dorin.remote.ui.AccentAtv
import com.dorin.remote.ui.ManagerConnectionIndicator
import com.dorin.remote.ui.TextDim
import com.dorin.remote.ui.UniTheme
import com.dorin.remote.wiz.Lights
import com.dorin.remote.wiz.ManagerConnection
import java.io.File
import java.io.IOException
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** Controlled HTTP-client responses only; never requests a real manager or changes saved preferences. */
class ManagerConnectionIndicatorTest {
    @get:Rule val compose = createComposeRule()

    @Test fun freshStatusIsGreenButFailedStatusAndUnknownAreGrey() {
        var fail = false
        val lights = Lights { _, _ ->
            if (fail) throw IOException("Controlled status failure")
            JSONObject("""{"config":{"bulbs":[],"enabled":false},"pilots":{},"systemConfigs":{},"errors":{"test-bulb":"unreachable"}}""")
        }
        val connection = mutableStateOf(ManagerConnection.CHECKING)
        compose.setContent {
            UniTheme { Row { Text("Bulbs"); ManagerConnectionIndicator(connection.value) } }
        }
        assertDot(ManagerConnection.CHECKING, false)
        runBlocking { lights.refresh() }
        compose.runOnIdle { connection.value = lights.managerConnection.current() }
        assertDot(ManagerConnection.CONNECTED, true)
        fail = true
        try { runBlocking { lights.refresh() } } catch (_: IOException) { }
        compose.runOnIdle { connection.value = lights.managerConnection.current() }
        assertDot(ManagerConnection.UNAVAILABLE, false)
    }

    private fun assertDot(state: ManagerConnection, green: Boolean) {
        val image = compose.onNodeWithContentDescription(state.description).assertExists().captureToImage()
        assertEquals(if (green) AccentAtv else TextDim, image.toPixelMap()[image.width / 2, image.height / 2])
        val directory = InstrumentationRegistry.getInstrumentation().targetContext.cacheDir
        File(directory, "manager-indicator-${state.name.lowercase()}.png").outputStream().use {
            image.asAndroidBitmap().compress(Bitmap.CompressFormat.PNG, 100, it)
        }
    }
}
