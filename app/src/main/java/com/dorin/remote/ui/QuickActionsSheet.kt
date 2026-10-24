package com.dorin.remote.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.dorin.remote.RemoteViewModel
import com.dorin.remote.webos.LgState
import kotlinx.coroutines.delay

private val PICTURE_MODES = listOf(
    "Standard" to "normal", "Cinema" to "cinema", "Vivid" to "vivid", "Game" to "game", "Eco" to "eco", "Filmmaker" to "filmMaker",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun QuickActionsSheet(vm: RemoteViewModel, onDismiss: () -> Unit) {
    val lgState by vm.lg.state.collectAsState()
    val backlight by vm.lg.backlight.collectAsState()
    val pictureMode by vm.lg.pictureMode.collectAsState()
    val sleepEnd by vm.sleepEnd.collectAsState()
    val connected = lgState is LgState.Connected
    val ctx = LocalContext.current

    var pendingMinutes by remember { mutableIntStateOf(0) }
    val askNotif = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        if (pendingMinutes > 0) { vm.startSleep(pendingMinutes); pendingMinutes = 0 }
    }
    fun startSleep(min: Int) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            pendingMinutes = min
            askNotif.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else vm.startSleep(min)
    }

    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Surface1) {
        Column(Modifier.padding(horizontal = 20.dp).padding(bottom = 28.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text("Quick actions", color = TextMain, fontSize = 20.sp, fontWeight = FontWeight.Bold)

            // ---- Sleep timer ----
            Text("Sleep timer (turns the TV off)", color = TextDim, fontSize = 13.sp)
            if (sleepEnd != null) {
                var left by remember { mutableStateOf("") }
                LaunchedEffect(sleepEnd) {
                    while (true) {
                        val ms = (sleepEnd ?: 0L) - System.currentTimeMillis()
                        left = if (ms <= 0) "now" else "${ms / 60_000} min ${(ms / 1000) % 60} s"
                        delay(1000)
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("TV turns off in $left", color = AccentAtv, fontSize = 15.sp, modifier = Modifier.weight(1f))
                    PillButton("Cancel", color = Danger, contentColor = Bg) { vm.cancelSleep() }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(15, 30, 60, 90).forEach { m ->
                    PillButton("$m min", modifier = Modifier.weight(1f), color = if (m == 30) Accent else Surface2, contentColor = if (m == 30) Bg else TextMain) { startSleep(m) }
                }
            }

            // ---- Brightness ----
            Text(
                "Brightness (backlight)" + (backlight?.let { "  ·  $it" } ?: if (connected) "" else "  ·  connect to the TV first"),
                color = TextDim, fontSize = 13.sp,
            )
            var slider by remember(backlight) { mutableStateOf((backlight ?: 50).toFloat()) }
            Slider(
                value = slider,
                onValueChange = { slider = it },
                onValueChangeFinished = { vm.setBacklight(slider.toInt()) },
                valueRange = 0f..100f,
                enabled = connected,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(10, 30, 50, 80, 100).forEach { v ->
                    PillButton("$v", modifier = Modifier.weight(1f)) { slider = v.toFloat(); vm.setBacklight(v) }
                }
            }

            // ---- Picture mode ----
            Text("Picture mode" + (pictureMode?.let { "  ·  $it" } ?: ""), color = TextDim, fontSize = 13.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                PICTURE_MODES.take(3).forEach { (label, id) ->
                    PillButton(label, modifier = Modifier.weight(1f), color = if (pictureMode == id) Accent else Surface2, contentColor = if (pictureMode == id) Bg else TextMain) { vm.setPictureMode(id) }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                PICTURE_MODES.drop(3).forEach { (label, id) ->
                    PillButton(label, modifier = Modifier.weight(1f), color = if (pictureMode == id) Accent else Surface2, contentColor = if (pictureMode == id) Bg else TextMain) { vm.setPictureMode(id) }
                }
            }

            // ---- Screen ----
            Text("Screen", color = TextDim, fontSize = 13.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PillButton("Screen off, keep sound", modifier = Modifier.weight(1f)) { vm.screenOff() }
                PillButton("Screen on", modifier = Modifier.weight(1f)) { vm.lg.screenOn() }
            }
            Spacer(Modifier.height(4.dp))
        }
    }
}
