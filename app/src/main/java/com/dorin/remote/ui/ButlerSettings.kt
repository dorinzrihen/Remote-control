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
import androidx.compose.ui.text.input.PasswordVisualTransformation
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
    var url by remember { mutableStateOf(vm.prefs.butlerUrl) }
    var token by remember { mutableStateOf(vm.prefs.butlerToken) }
    var enabled by remember { mutableStateOf(active) }
    var night by remember { mutableStateOf("21:00") }
    var morning by remember { mutableStateOf("06:00") }
    var timezone by remember { mutableStateOf(TimeZone.getDefault().id) }
    var pollSeconds by remember { mutableStateOf("1") }
    LaunchedEffect(Unit) {
        if (vm.prefs.butlerUrl.isNotBlank()) vm.loadButler(vm.prefs.butlerUrl, vm.prefs.butlerToken)
    }
    LaunchedEffect(settings) {
        settings?.let {
            enabled = it.getBoolean("enabled")
            night = it.getString("night"); morning = it.getString("morning"); timezone = it.getString("timezone")
            pollSeconds = it.optInt("pollSeconds", 1).toString()
        }
    }
    Column(Modifier.fillMaxWidth().background(Surface2, RoundedCornerShape(14.dp)).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Laptop timetable (optional)", color = TextMain, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
        Text("Not native WiZ Rhythms. Requires the butler service on an always-on laptop. Nothing is enabled until you Save.", color = TextDim, fontSize = 12.sp)
        Text("${if (active) "Active" else "Inactive"} on this phone. $status", color = TextDim, fontSize = 12.sp)
        OutlinedTextField(url, { url = it }, label = { Text("Butler URL, e.g. http://192.168.1.10:8788") }, singleLine = true, enabled = !busy, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(token, { token = it }, label = { Text("Butler token") }, singleLine = true, enabled = !busy,
            visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Use laptop timetable", color = TextMain, modifier = Modifier.weight(1f))
            Switch(enabled, { enabled = it }, enabled = !busy)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(night, { night = it }, label = { Text("Night HH:MM") }, singleLine = true, enabled = !busy, modifier = Modifier.weight(1f))
            OutlinedTextField(morning, { morning = it }, label = { Text("Day HH:MM") }, singleLine = true, enabled = !busy, modifier = Modifier.weight(1f))
        }
        OutlinedTextField(timezone, { timezone = it }, label = { Text("Home timezone (e.g. Asia/Jerusalem)") }, singleLine = true, enabled = !busy, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(pollSeconds, { pollSeconds = it }, label = { Text("Poll every X seconds (1–300)") }, singleLine = true, enabled = !busy,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth())
        Text("The laptop checks state at this interval; it does not overwrite your choice every poll. Timetable boundaries wake it sooner.", color = TextDim, fontSize = 12.sp)
        Text("Regular: 100%, 6500K. Night: 20%, 2700K. Changes apply to bulbs that are on and to detected wall-switch On events. Manual presets last until the next timetable boundary; Follow timetable resumes sooner. Off bulbs stay off.", color = TextDim, fontSize = 12.sp)
        Text("Load reads laptop settings. Save replaces its bulb list with this phone’s saved bulbs. Disable and Save before editing bulbs or changing laptops. No direct UDP fallback if the laptop is unavailable.", color = TextDim, fontSize = 12.sp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PillButton(if (busy) "Working…" else "Load", modifier = Modifier.weight(1f)) { if (!busy) vm.loadButler(url, token) }
            PillButton("Save", modifier = Modifier.weight(1f), color = Accent, contentColor = Bg) {
                if (!busy) vm.saveButler(url, token, enabled, night, morning, timezone, pollSeconds)
            }
        }
    }
}
