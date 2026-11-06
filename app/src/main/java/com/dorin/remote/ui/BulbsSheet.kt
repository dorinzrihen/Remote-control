package com.dorin.remote.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.dorin.remote.RemoteViewModel
import com.dorin.remote.wiz.LightMode
import kotlinx.coroutines.delay

val BulbOn = Color(0xFFE0AF68)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BulbsSheet(vm: RemoteViewModel, onDismiss: () -> Unit) {
    val bulbs by vm.lights.bulbs.collectAsState()
    val pilots by vm.lights.pilots.collectAsState()
    val newBulbs by vm.newBulbs.collectAsState()
    val searching by vm.bulbSearching.collectAsState()
    val butlerEnabled by vm.butlerEnabled.collectAsState()
    val systemConfigs by vm.lights.systemConfigs.collectAsState()
    val loaded by vm.lights.loaded.collectAsState()
    val error by vm.lights.error.collectAsState()
    val observationAges by vm.lights.observationAges.collectAsState()
    LaunchedEffect(Unit) {
        while (true) {
            vm.pollBulbs()
            delay(1_000)
        }
    }

    // Opens fully so the buttons at the bottom are not hidden under the navigation bar.
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Surface1, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 28.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text("Bulbs", color = TextMain, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            if (!loaded) Text("Manager status not loaded. Connect below; no phone-owned bulbs or direct WiZ fallback are used.", color = TextDim, fontSize = 13.sp)
            error?.let { Text(it, color = Danger, fontSize = 12.sp) }
            if (loaded && bulbs.isEmpty()) Text("The manager has no bulbs yet. Set up in the WiZ app, then Find new bulbs to discover through the manager.", color = TextDim, fontSize = 13.sp)

            // ---- Rooms ----
            bulbs.map { it.room }.distinct().forEach { room ->
                val inRoom = bulbs.filter { it.room == room }
                val states = inRoom.mapNotNull { pilots[it.mac] }
                val on = states.any { it.on }
                val mode = states.firstOrNull { it.on }?.let(LightMode::of)
                val status = when {
                    !loaded -> "manager unavailable / status unknown"
                    states.size < inRoom.size -> "${inRoom.size - states.size} unreachable / status unknown"
                    !on -> "off"
                    else -> mode?.label ?: "on"
                }
                Column(Modifier.fillMaxWidth().background(Surface2, RoundedCornerShape(14.dp)).padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(room, color = TextMain, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                            Text("${inRoom.size} bulb${if (inRoom.size == 1) "" else "s"}  ·  $status", color = TextDim, fontSize = 12.sp)
                        }
                        RemoteButton(icon = Icons.Default.PowerSettingsNew, label = "$room on / off", size = 44.dp,
                            color = if (on) BulbOn else Bg, contentColor = if (on) Bg else TextMain) { vm.toggleRoom(room) }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        LightMode.entries.forEach { m ->
                            PillButton(m.label, modifier = Modifier.weight(1f), color = if (mode == m) BulbOn else Bg, contentColor = if (mode == m) Bg else TextMain) {
                                vm.setRoom(room, m)
                            }
                        }
                    }
                    if (butlerEnabled) PillButton("Follow timetable (leave off bulbs off)", modifier = Modifier.fillMaxWidth()) { vm.followTimetable(room) }
                }
            }
            if (bulbs.isNotEmpty()) Text("Regular: 100% cool white  ·  Night: 20% warm", color = TextDim, fontSize = 11.sp)

            ButlerSettings(vm)

            // ---- Saved bulbs ----
            if (bulbs.isNotEmpty()) Text("Saved bulbs", color = TextDim, fontSize = 13.sp)
            bulbs.forEach { b ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("${b.room}  ·  …${b.mac.takeLast(4)}" + if (pilots[b.mac] == null) "  ·  not reachable" else "", color = TextMain, fontSize = 13.sp)
                        systemConfigs[b.mac]?.let { Text("${it.moduleName} · firmware ${it.fwVersion}", color = TextDim, fontSize = 11.sp) }
                        observationAges[b.mac]?.let { Text("Manager last observed ${it}s ago", color = TextDim, fontSize = 11.sp) }
                    }
                    PillButton("Blink") { vm.blinkBulb(b.mac) }
                    Spacer(Modifier.width(6.dp))
                    PillButton("Remove", contentColor = Danger, onLongPress = { vm.removeBulb(b.mac) }) {
                        vm.messages.tryEmit("Hold Remove to delete this bulb from the manager")
                    }
                }
            }

            // ---- Add bulbs ----
            PillButton(if (searching) "Searching…" else "Find new bulbs", modifier = Modifier.fillMaxWidth(), color = Accent, contentColor = Bg) {
                if (!searching) vm.findBulbs()
            }
            newBulbs.forEach { (ip, p) ->
                key(ip) {
                    var room by remember { mutableStateOf(bulbs.lastOrNull()?.room ?: "Living room") }
                    Column(Modifier.fillMaxWidth().background(Surface2, RoundedCornerShape(14.dp)).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("New bulb …${p.mac.takeLast(4)}  ·  $ip  ·  tap Blink to see which one it is", color = TextDim, fontSize = 12.sp)
                        OutlinedTextField(
                            value = room, onValueChange = { room = it }, label = { Text("Room") },
                            singleLine = true, modifier = Modifier.fillMaxWidth(),
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = Accent, unfocusedBorderColor = Bg,
                                focusedTextColor = TextMain, unfocusedTextColor = TextMain, cursorColor = Accent,
                                focusedLabelColor = TextDim, unfocusedLabelColor = TextDim,
                            ),
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            PillButton("Blink", modifier = Modifier.weight(1f), color = Bg) { vm.blinkBulb(p.mac) }
                            PillButton("Add to $room", modifier = Modifier.weight(2f), color = BulbOn, contentColor = Bg) { vm.addBulb(ip, p, room) }
                        }
                    }
                }
            }
        }
    }
}
