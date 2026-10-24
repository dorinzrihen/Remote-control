package com.dorin.remote.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.dorin.remote.RemoteViewModel
import com.dorin.remote.atv.AtvState
import com.dorin.remote.webos.LgState

@Composable
fun SetupScreen(vm: RemoteViewModel) {
    val lgIp by vm.lgIp.collectAsState()
    val atvIp by vm.atvIp.collectAsState()
    val lgState by vm.lg.state.collectAsState()
    val atvState by vm.atv.state.collectAsState()
    val lgFound by vm.lgFound.collectAsState()
    val atvFound by vm.atvFound.collectAsState()
    val scanning by vm.scanning.collectAsState()
    val session by vm.pairingSession.collectAsState()
    val pairingError by vm.pairingError.collectAsState()
    val pairingBusy by vm.pairingBusy.collectAsState()
    val inputs by vm.lg.inputs.collectAsState()
    val xiaomiInput by vm.xiaomiInputId.collectAsState()
    val speed by vm.pointerSpeed.collectAsState()
    val autoKb by vm.autoKeyboard.collectAsState()
    val mac by vm.lg.macAddress.collectAsState()
    val tvName by vm.lg.tvName.collectAsState()

    var lgIpEdit by remember(lgIp) { mutableStateOf(lgIp) }
    var atvIpEdit by remember(atvIp) { mutableStateOf(atvIp) }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Setup", color = TextMain, fontSize = 24.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            Button(onClick = { vm.showSetup.value = false }, colors = ButtonDefaults.buttonColors(containerColor = Accent, contentColor = Bg)) { Text("Done") }
        }
        Spacer(Modifier.height(10.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = vm::scan, enabled = !scanning) { Text(if (scanning) "Scanning…" else "Scan the network") }
            if (scanning) { Spacer(Modifier.width(10.dp)); CircularProgressIndicator(Modifier.width(20.dp).height(20.dp), strokeWidth = 2.dp) }
        }
        Text("Phone, TV and Xiaomi must be on the same Wi-Fi.", color = TextDim, fontSize = 12.sp)

        // ---------------- LG ----------------
        Section("LG TV (webOS)", Accent) {
            StatusLine(when (lgState) {
                is LgState.Connected -> "Connected" + (tvName?.let { " · $it" } ?: "")
                is LgState.Connecting -> "Connecting…"
                is LgState.WaitingForPrompt -> "Look at the TV and press Yes / Accept"
                is LgState.Error -> "Error: ${(lgState as LgState.Error).message}"
                else -> "Not connected"
            }, lgState is LgState.Connected)
            lgFound.forEach { d -> FoundRow(d.name, d.ip) { lgIpEdit = d.ip } }
            OutlinedTextField(
                value = lgIpEdit, onValueChange = { lgIpEdit = it }, label = { Text("TV IP address") },
                singleLine = true, modifier = Modifier.fillMaxWidth(), colors = fieldColors(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { vm.saveLg(lgIpEdit) }, colors = ButtonDefaults.buttonColors(containerColor = Accent, contentColor = Bg)) { Text("Connect") }
                TextButton(onClick = vm::forgetLg) { Text("Forget pairing", color = TextDim) }
            }
            Text("First time: the TV shows a prompt. Press Yes with the LG remote.", color = TextDim, fontSize = 12.sp)
            if (mac != null) Text("MAC $mac (used to turn the TV on)", color = TextDim, fontSize = 12.sp)

            Spacer(Modifier.height(8.dp))
            Text("Which TV input is the Xiaomi on?", color = TextMain, fontSize = 14.sp)
            Box {
                var open by remember { mutableStateOf(false) }
                OutlinedButton(onClick = { open = true }, enabled = inputs.isNotEmpty()) {
                    Text(inputs.firstOrNull { it.id == xiaomiInput }?.label ?: xiaomiInput ?: if (inputs.isEmpty()) "Connect to TV first" else "Choose input")
                }
                DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                    inputs.forEach { i -> DropdownMenuItem(text = { Text("${i.label}  (${i.id})") }, onClick = { open = false; vm.setXiaomiInput(i.id) }) }
                    DropdownMenuItem(text = { Text("None") }, onClick = { open = false; vm.setXiaomiInput(null) })
                }
            }
            Text("The app then switches to Xiaomi mode automatically when the TV shows that input.", color = TextDim, fontSize = 12.sp)
        }

        // ---------------- Xiaomi ----------------
        Section("Xiaomi streamer (Android TV)", AccentAtv) {
            StatusLine(when (atvState) {
                is AtvState.Connected -> "Connected"
                is AtvState.Connecting -> "Connecting…"
                is AtvState.NeedsPairing -> "Not paired. Press Pair."
                is AtvState.Error -> "Error: ${(atvState as AtvState.Error).message}"
                else -> if (vm.prefs.atvPaired) "Not connected" else "Not paired yet"
            }, atvState is AtvState.Connected)
            atvFound.forEach { d -> FoundRow(d.name, d.ip) { atvIpEdit = d.ip } }
            OutlinedTextField(
                value = atvIpEdit, onValueChange = { atvIpEdit = it }, label = { Text("Xiaomi IP address") },
                singleLine = true, modifier = Modifier.fillMaxWidth(), colors = fieldColors(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { vm.startPairing(atvIpEdit) }, enabled = !pairingBusy,
                    colors = ButtonDefaults.buttonColors(containerColor = AccentAtv, contentColor = Bg)) { Text(if (vm.prefs.atvPaired) "Pair again" else "Pair") }
            }
            if (pairingError != null) Text(pairingError!!, color = Danger, fontSize = 12.sp)
            Text("Pairing shows a 6-character code on the TV screen. Type it here once.", color = TextDim, fontSize = 12.sp)
        }

        // ---------------- Shortcuts ----------------
        val lgApps by vm.lgApps.collectAsState()
        val chosen by vm.lgShortcutIds.collectAsState()
        val web by vm.webShortcuts.collectAsState()
        Section("Shortcut buttons", Accent) {
            Text(
                if (lgApps.isEmpty()) "Connect to the LG TV once to load its app list." else "Tick the TV apps you want as buttons:",
                color = TextDim, fontSize = 12.sp,
            )
            lgApps.forEach { app ->
                Row(
                    Modifier.fillMaxWidth().clickable {
                        vm.setLgShortcuts(if (app.id in chosen) chosen - app.id else chosen + app.id)
                    }.padding(vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    androidx.compose.material3.Checkbox(checked = app.id in chosen, onCheckedChange = null)
                    Spacer(Modifier.width(6.dp))
                    Text(app.title, color = TextMain, fontSize = 14.sp, modifier = Modifier.weight(1f))
                    Text(app.id, color = TextDim, fontSize = 10.sp)
                }
            }
            Spacer(Modifier.height(6.dp))
            Text("Website buttons (open in the TV browser):", color = TextDim, fontSize = 12.sp)
            web.forEachIndexed { i, (name, url) ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(name, color = TextMain, fontSize = 14.sp)
                    Spacer(Modifier.width(8.dp))
                    Text(url, color = TextDim, fontSize = 11.sp, modifier = Modifier.weight(1f), maxLines = 1)
                    TextButton(onClick = { vm.setWebShortcuts(web.filterIndexed { j, _ -> j != i }) }) { Text("Remove", color = Danger) }
                }
            }
            var newName by remember { mutableStateOf("") }
            var newUrl by remember { mutableStateOf("") }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(value = newName, onValueChange = { newName = it }, label = { Text("Name") }, singleLine = true, modifier = Modifier.weight(0.8f), colors = fieldColors())
                OutlinedTextField(value = newUrl, onValueChange = { newUrl = it }, label = { Text("https://…") }, singleLine = true, modifier = Modifier.weight(1.4f), colors = fieldColors())
            }
            OutlinedButton(onClick = {
                if (newName.isNotBlank() && newUrl.isNotBlank()) {
                    val u = if (newUrl.startsWith("http")) newUrl.trim() else "https://" + newUrl.trim()
                    vm.setWebShortcuts(web + (newName.trim() to u)); newName = ""; newUrl = ""
                }
            }) { Text("Add website button") }
        }

        // ---------------- Options ----------------
        Section("Options", TextDim) {
            Text("Cursor speed", color = TextMain, fontSize = 14.sp)
            Slider(value = speed, onValueChange = vm::setPointerSpeed, valueRange = 0.5f..4f)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Open phone keyboard when the LG TV asks for text", color = TextMain, fontSize = 14.sp, modifier = Modifier.weight(1f))
                Switch(checked = autoKb, onCheckedChange = vm::setAutoKeyboard)
            }
        }

        // ---------------- Diagnostics ----------------
        val log by com.dorin.remote.Diag.lines.collectAsState()
        val clipboard = androidx.compose.ui.platform.LocalClipboardManager.current
        Text("UniRemote ${vm.currentVersion} · updates come from github.com/dorinzrihen/Remote-control", color = TextDim, fontSize = 11.sp, modifier = Modifier.padding(top = 12.dp))
        Section("Diagnostics log", TextDim) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { clipboard.setText(androidx.compose.ui.text.AnnotatedString(log.joinToString("\n"))) }) { Text("Copy log") }
                TextButton(onClick = { com.dorin.remote.Diag.clear() }) { Text("Clear", color = TextDim) }
            }
            Text(
                if (log.isEmpty()) "Nothing yet." else log.takeLast(25).joinToString("\n"),
                color = TextDim, fontSize = 11.sp, fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
            )
        }

        Spacer(Modifier.height(10.dp))
        Text(
            "Soundbar: it has no Wi-Fi, so volume and mute go through the TV over HDMI ARC. " +
                "Make sure the TV's sound output is set to the soundbar (HDMI ARC).",
            color = TextDim, fontSize = 12.sp,
        )
        Spacer(Modifier.height(30.dp))
    }

    if (session != null) {
        var code by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { vm.cancelPairing() },
            title = { Text("Code on the TV") },
            text = {
                Column {
                    Text("Type the 6-character code shown on the Xiaomi screen.")
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = code, onValueChange = { code = it.uppercase().take(6) }, singleLine = true,
                        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters),
                    )
                    if (pairingError != null) Text(pairingError!!, color = Danger)
                }
            },
            confirmButton = { Button(onClick = { vm.finishPairing(code) }, enabled = code.length == 6 && !pairingBusy) { Text("Pair") } },
            dismissButton = { TextButton(onClick = { vm.cancelPairing() }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = Accent, unfocusedBorderColor = Surface2,
    focusedTextColor = TextMain, unfocusedTextColor = TextMain, cursorColor = Accent,
    focusedLabelColor = TextDim, unfocusedLabelColor = TextDim,
)

@Composable
private fun Section(title: String, color: Color, content: @Composable () -> Unit) {
    Spacer(Modifier.height(16.dp))
    Column(
        Modifier.fillMaxWidth().background(Surface1, RoundedCornerShape(16.dp)).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(title, color = color, fontSize = 16.sp, fontWeight = FontWeight.Bold)
        content()
    }
}

@Composable
private fun StatusLine(text: String, ok: Boolean) {
    Text(text, color = if (ok) AccentAtv else TextDim, fontSize = 13.sp)
}

@Composable
private fun FoundRow(name: String, ip: String, onPick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().background(Surface2, RoundedCornerShape(10.dp)).clickable(onClick = onPick).padding(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(name, color = TextMain, fontSize = 13.sp, modifier = Modifier.weight(1f))
        Text(ip, color = TextDim, fontSize = 13.sp)
    }
}
