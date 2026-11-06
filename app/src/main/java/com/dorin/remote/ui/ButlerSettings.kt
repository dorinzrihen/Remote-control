package com.dorin.remote.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.dorin.remote.RemoteViewModel

@Composable
fun ButlerSettings(vm: RemoteViewModel) {
    val active by vm.butlerEnabled.collectAsState()
    val busy by vm.butlerBusy.collectAsState()
    val status by vm.butlerStatus.collectAsState()
    val settings by vm.butlerSettings.collectAsState()
    val editor by vm.timetableEditor.collectAsState()
    val loaded by vm.lights.loaded.collectAsState()
    val managers by vm.foundButlers.collectAsState()
    val selected by vm.selectedButlerUrl.collectAsState()
    val discoveryStatus by vm.butlerDiscoveryStatus.collectAsState()
    var showConnection by remember { mutableStateOf(false) }
    var showTimetable by remember { mutableStateOf(false) }
    var url by remember { mutableStateOf(vm.prefs.butlerUrl) }
    val draft = editor?.draft
    LaunchedEffect(Unit) {
        if (vm.prefs.butlerUrl.isNotBlank()) vm.loadButler(vm.prefs.butlerUrl)
    }
    LaunchedEffect(Unit) { vm.discoverButlers() }
    Column(Modifier.fillMaxWidth().background(Surface2, RoundedCornerShape(14.dp)).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Lighting manager", color = TextMain, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
        Text(status, color = TextDim, fontSize = 12.sp)
        if (!loaded || managers.size > 1) {
            Text(discoveryStatus, color = TextDim, fontSize = 12.sp)
            if (managers.size > 1) managers.forEach { manager ->
                PillButton(manager.name, modifier = Modifier.fillMaxWidth(), color = if (selected == manager.url) Accent else Bg,
                    contentColor = if (selected == manager.url) Bg else TextMain) { if (!busy) vm.loadButler(manager.url) }
            }
        }
        if (loaded) {
            Text(if (active) "Night ${settings?.optString("night")} · Day ${settings?.optString("morning")}" else "Timetable off", color = TextDim, fontSize = 12.sp)
            PillButton(if (showTimetable) "Hide timetable" else "Edit timetable") { showTimetable = !showTimetable }
        }
        if (draft != null && showTimetable) {
            if (editor?.conflict == true) {
                Text("Timetable changed on another phone. Your edits are kept.", color = TextDim, fontSize = 12.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    PillButton("Reload settings") { if (!busy) vm.reloadTimetable() }
                    PillButton("Reapply my edits") { if (!busy) vm.reapplyTimetable() }
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Timetable", color = TextMain, modifier = Modifier.weight(1f))
                Switch(draft.enabled, { vm.editTimetable(draft.copy(enabled = it)) }, enabled = !busy)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(draft.night, { vm.editTimetable(draft.copy(night = it)) }, label = { Text("Night HH:MM") }, singleLine = true, enabled = !busy, modifier = Modifier.weight(1f))
                OutlinedTextField(draft.morning, { vm.editTimetable(draft.copy(morning = it)) }, label = { Text("Day HH:MM") }, singleLine = true, enabled = !busy, modifier = Modifier.weight(1f))
            }
            OutlinedTextField(draft.timezone, { vm.editTimetable(draft.copy(timezone = it)) }, label = { Text("Timezone") }, singleLine = true, enabled = !busy, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(draft.pollSeconds, { vm.editTimetable(draft.copy(pollSeconds = it)) }, label = { Text("Poll interval (seconds)") }, singleLine = true, enabled = !busy,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth())
            Text("Regular: 100% cool · Night: 20% warm. Off bulbs stay off.", color = TextDim, fontSize = 12.sp)
            PillButton(if (busy) "Saving…" else "Save timetable", modifier = Modifier.fillMaxWidth(), color = Accent, contentColor = Bg) {
                if (!busy) vm.saveButler(vm.prefs.butlerUrl, draft.enabled, draft.night, draft.morning, draft.timezone, draft.pollSeconds)
            }
        }
        PillButton(if (showConnection) "Hide connection" else "Advanced connection") {
            if (!showConnection) url = vm.prefs.butlerUrl
            showConnection = !showConnection
        }
        if (showConnection) {
            OutlinedTextField(url, { url = it }, label = { Text("Manager URL") }, singleLine = true, enabled = !busy, modifier = Modifier.fillMaxWidth())
            PillButton(if (busy) "Connecting…" else "Connect", modifier = Modifier.fillMaxWidth()) {
                if (!busy) vm.loadButler(url)
            }
        }
    }
}
