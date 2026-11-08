package com.dorin.remote.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.produceState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.dorin.remote.RemoteViewModel
import com.dorin.remote.wiz.BulbRenames
import com.dorin.remote.wiz.LightMode
import com.dorin.remote.wiz.RoomControlChoice
import com.dorin.remote.wiz.ManagerConnection
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

val BulbOn = Color(0xFFE0AF68)

@Composable
fun ManagerConnectionIndicator(connection: ManagerConnection) {
    Box(Modifier.size(8.dp)
        .background(if (connection == ManagerConnection.CONNECTED) AccentAtv else TextDim, CircleShape)
        .semantics { contentDescription = connection.description })
}

@Composable
private fun bulbFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = Accent, unfocusedBorderColor = Bg,
    focusedTextColor = TextMain, unfocusedTextColor = TextMain, cursorColor = Accent,
    focusedLabelColor = TextDim, unfocusedLabelColor = TextDim,
)

/** The Bulbs tab: shown in place of the remote. Polls the manager only while visible. */
@Composable
fun BulbsPane(vm: RemoteViewModel, modifier: Modifier = Modifier) {
    val bulbs by vm.lights.bulbs.collectAsState()
    val pilots by vm.lights.pilots.collectAsState()
    val newBulbs by vm.newBulbs.collectAsState()
    val searching by vm.bulbSearching.collectAsState()
    val butlerEnabled by vm.butlerEnabled.collectAsState()
    val systemConfigs by vm.lights.systemConfigs.collectAsState()
    val loaded by vm.lights.loaded.collectAsState()
    val error by vm.lights.error.collectAsState()
    val observationAges by vm.lights.observationAges.collectAsState()
    val roomControls by vm.lights.roomControls.collectAsState()
    var manageBulbs by remember { mutableStateOf(false) }
    // Held here, above the sections polling can hide, so one failed poll cannot discard typing.
    var renames by remember { mutableStateOf(BulbRenames()) }
    LaunchedEffect(bulbs) { renames = renames.observe(bulbs) }
    val managerConnection by produceState(ManagerConnection.CHECKING, vm.lights) {
        vm.lights.managerConnection.checking()
        coroutineScope {
            launch {
                while (true) {
                    vm.pollBulbs()
                    delay(1_000)
                }
            }
            // Separate from HTTP polling: a stalled request must not leave a stale green dot.
            while (true) {
                value = vm.lights.managerConnection.current()
                delay(250)
            }
        }
    }

    // The activity root already pads for the keyboard, so fields can scroll above it.
    Column(modifier.fillMaxWidth().background(Surface1, RoundedCornerShape(14.dp)).verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Bulbs", color = TextMain, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            ManagerConnectionIndicator(managerConnection)
        }
        error?.let { Text(it, color = Danger, fontSize = 12.sp) }
        if (loaded && bulbs.isEmpty()) Text("No bulbs yet. Tap Manage bulbs to add one.", color = TextDim, fontSize = 13.sp)

        // ---- Rooms ----
        bulbs.map { it.room }.distinct().forEach { room ->
            val inRoom = bulbs.filter { it.room == room }
            val states = inRoom.mapNotNull { pilots[it.mac] }
            val on = states.any { it.on }
            val control = roomControls[room]
            val status = control?.status ?: "status unknown"
            Column(Modifier.fillMaxWidth().background(Surface2, RoundedCornerShape(14.dp)).padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(room, color = TextMain, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                        Text("${inRoom.size} bulb${if (inRoom.size == 1) "" else "s"}  ·  $status", color = TextDim, fontSize = 12.sp)
                    }
                    RemoteButton(icon = Icons.Default.PowerSettingsNew, label = "$room on / off", size = 44.dp,
                        color = if (on) BulbOn else Bg, contentColor = if (on) Bg else TextMain) { vm.toggleRoom(room) }
                }
                Column(Modifier.selectableGroup(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        LightMode.entries.forEach { m ->
                            val selected = control?.selected == if (m == LightMode.REGULAR) RoomControlChoice.REGULAR else RoomControlChoice.NIGHT
                            val action = { vm.setRoom(room, m) }
                            PillButton(m.label, modifier = Modifier.weight(1f).selectable(selected, role = Role.RadioButton, onClick = action),
                                color = if (selected) BulbOn else Bg, contentColor = if (selected) Bg else TextMain, onPress = action)
                        }
                    }
                    if (butlerEnabled) {
                        val selected = control?.selected == RoomControlChoice.FOLLOW
                        val action = { vm.followTimetable(room) }
                        PillButton("Follow timetable", modifier = Modifier.fillMaxWidth().selectable(selected, role = Role.RadioButton, onClick = action),
                            color = if (selected) BulbOn else Bg, contentColor = if (selected) Bg else TextMain, onPress = action)
                    }
                }
            }
        }
        ButlerSettings(vm)

        if (loaded || renames.drafts.isNotEmpty()) {
            PillButton(if (manageBulbs) "Done managing bulbs" else "Manage bulbs", modifier = Modifier.fillMaxWidth()) { manageBulbs = !manageBulbs }
            if (manageBulbs) {
                // ---- Saved bulbs ----
                if (bulbs.isNotEmpty()) Text("Saved bulbs", color = TextDim, fontSize = 13.sp)
                bulbs.forEach { b ->
                    key(b.mac) {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Column {
                                Text("${b.room}  ·  …${b.mac.takeLast(4)}" + if (pilots[b.mac] == null) "  ·  not reachable" else "", color = TextMain, fontSize = 13.sp)
                                systemConfigs[b.mac]?.let { Text("${it.moduleName} · firmware ${it.fwVersion}", color = TextDim, fontSize = 11.sp) }
                                observationAges[b.mac]?.let { Text("Manager last observed ${it}s ago", color = TextDim, fontSize = 11.sp) }
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                PillButton("Rename") { renames = renames.open(b) }
                                PillButton("Blink") { vm.blinkBulb(b.mac) }
                                PillButton("Remove", contentColor = Danger, onLongPress = { vm.removeBulb(b.mac) }) {
                                    vm.messages.tryEmit("Hold Remove to delete this bulb from the manager")
                                }
                            }
                            renames.drafts[b.mac]?.let { draft ->
                                val saving = b.mac in renames.saving
                                val save = {
                                    if (!saving) {
                                        renames = renames.sending(b.mac)
                                        vm.renameBulb(b.mac, draft) { saved -> renames = if (saved) renames.close(b.mac) else renames.failed(b.mac) }
                                    }
                                }
                                // One line, so the buttons cannot end up behind the keyboard.
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    OutlinedTextField(
                                        value = draft, onValueChange = { renames = renames.type(b.mac, it) }, label = { Text("Bulb name") },
                                        singleLine = true, readOnly = saving, modifier = Modifier.weight(1f), colors = bulbFieldColors(),
                                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done), keyboardActions = KeyboardActions(onDone = { save() }),
                                    )
                                    PillButton(if (saving) "Saving…" else "Save", color = BulbOn, contentColor = Bg, onPress = save)
                                    PillButton("Cancel") { if (!saving) renames = renames.close(b.mac) }
                                }
                            }
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
                                singleLine = true, modifier = Modifier.fillMaxWidth(), colors = bulbFieldColors(),
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
}
