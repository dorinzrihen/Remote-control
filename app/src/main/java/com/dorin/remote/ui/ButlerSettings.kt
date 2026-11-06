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
import java.util.TimeZone

@Composable
fun ButlerSettings(vm: RemoteViewModel) {
    val active by vm.butlerEnabled.collectAsState()
    val busy by vm.butlerBusy.collectAsState()
    val status by vm.butlerStatus.collectAsState()
    val settings by vm.butlerSettings.collectAsState()
    val loaded by vm.lights.loaded.collectAsState()
    val managers by vm.foundButlers.collectAsState()
    val selected by vm.selectedButlerUrl.collectAsState()
    val discoveryStatus by vm.butlerDiscoveryStatus.collectAsState()
    var showConnection by remember { mutableStateOf(false) }
    var showTimetable by remember { mutableStateOf(false) }
    var url by remember { mutableStateOf(vm.prefs.butlerUrl) }
    var enabled by remember { mutableStateOf(active) }
    var night by remember { mutableStateOf("21:00") }
    var morning by remember { mutableStateOf("06:00") }
    var timezone by remember { mutableStateOf(TimeZone.getDefault().id) }
    var pollSeconds by remember { mutableStateOf("1") }
    LaunchedEffect(Unit) {
        if (vm.prefs.butlerUrl.isNotBlank()) vm.loadButler(vm.prefs.butlerUrl)
    }
    LaunchedEffect(Unit) { vm.discoverButlers() }
    LaunchedEffect(settings) {
        settings?.let {
            enabled = it.getBoolean("enabled")
            night = it.getString("night"); morning = it.getString("morning"); timezone = it.getString("timezone")
            pollSeconds = it.optInt("pollSeconds", 1).toString()
        }
    }
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
            Text(if (active) "Night $night · Day $morning" else "Timetable off", color = TextDim, fontSize = 12.sp)
            PillButton(if (showTimetable) "Hide timetable" else "Edit timetable") { showTimetable = !showTimetable }
        }
        if (loaded && showTimetable) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Timetable", color = TextMain, modifier = Modifier.weight(1f))
                Switch(enabled, { enabled = it }, enabled = !busy)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(night, { night = it }, label = { Text("Night HH:MM") }, singleLine = true, enabled = !busy, modifier = Modifier.weight(1f))
                OutlinedTextField(morning, { morning = it }, label = { Text("Day HH:MM") }, singleLine = true, enabled = !busy, modifier = Modifier.weight(1f))
            }
            OutlinedTextField(timezone, { timezone = it }, label = { Text("Timezone") }, singleLine = true, enabled = !busy, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(pollSeconds, { pollSeconds = it }, label = { Text("Poll interval (seconds)") }, singleLine = true, enabled = !busy,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth())
            Text("Regular: 100% cool · Night: 20% warm. Off bulbs stay off.", color = TextDim, fontSize = 12.sp)
            PillButton(if (busy) "Saving…" else "Save timetable", modifier = Modifier.fillMaxWidth(), color = Accent, contentColor = Bg) {
                if (!busy) vm.saveButler(vm.prefs.butlerUrl, enabled, night, morning, timezone, pollSeconds)
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
