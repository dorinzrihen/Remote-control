package com.dorin.remote.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.VolumeOff
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.FastForward
import androidx.compose.material.icons.filled.FastRewind
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Input
import androidx.compose.material.icons.filled.Keyboard
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowLeft
import androidx.compose.material.icons.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Tv
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import android.content.Intent
import android.speech.RecognizerIntent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import com.dorin.remote.Key
import com.dorin.remote.RemoteViewModel
import com.dorin.remote.Target
import com.dorin.remote.SAMSUNG_HDMI_KEYS
import com.dorin.remote.atv.AtvState
import com.dorin.remote.tizen.SamsungState
import com.dorin.remote.webos.LgState

fun Target.accent(): Color = when (this) { Target.LG -> Accent; Target.SAMSUNG -> AccentSamsung; Target.ATV -> AccentAtv }

@Composable
fun RemoteScreen(vm: RemoteViewModel) {
    val target by vm.target.collectAsState()
    val lgState by vm.lg.state.collectAsState()
    val atvState by vm.atv.state.collectAsState()
    val samsungState by vm.samsung.state.collectAsState()
    val targets by vm.targets.collectAsState()
    val keyboardOpen by vm.keyboardOpen.collectAsState()
    val speed by vm.pointerSpeed.collectAsState()
    val inputs by vm.lg.inputs.collectAsState()
    val volume by vm.lg.volume.collectAsState()
    val muted by vm.lg.muted.collectAsState()
    val accent = target.accent()
    val tvIsSamsung = remember(target, targets) { vm.tvTarget() == Target.SAMSUNG }

    Column(Modifier.fillMaxSize().padding(horizontal = 14.dp, vertical = 8.dp)) {
        // Header: status + settings
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (Target.LG in targets) {
                StatusDot("LG TV", lgState is LgState.Connected, lgState is LgState.Connecting || lgState is LgState.WaitingForPrompt, Accent)
                Spacer(Modifier.width(14.dp))
            }
            if (Target.SAMSUNG in targets) {
                StatusDot("Samsung", samsungState is SamsungState.Connected, samsungState is SamsungState.Connecting || samsungState is SamsungState.WaitingForPrompt, AccentSamsung)
                Spacer(Modifier.width(14.dp))
            }
            if (Target.ATV in targets) StatusDot("Xiaomi", atvState is AtvState.Connected, atvState is AtvState.Connecting, AccentAtv)
            Spacer(Modifier.weight(1f))
            if (volume != null && !tvIsSamsung) Text(if (muted) "muted" else "vol $volume", color = TextDim, fontSize = 12.sp)
            IconButton(onClick = { vm.showSetup.value = true }) { Icon(Icons.Default.Settings, "Settings", tint = TextDim) }
        }

        // Update banner
        val update by vm.update.collectAsState()
        val updateProgress by vm.updateProgress.collectAsState()
        val updateDismissed by vm.updateDismissed.collectAsState()
        if (update != null && !updateDismissed) {
            Row(
                Modifier.fillMaxWidth().background(Color(0xFF2A3A2E), RoundedCornerShape(12.dp)).padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("Version ${update!!.version} is available", color = AccentAtv, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                    val p = updateProgress
                    Text(
                        if (p != null) "Downloading… ${(p * 100).toInt()}%" else update!!.notes.lines().firstOrNull { it.isNotBlank() } ?: "Tap Update to install",
                        color = TextDim, fontSize = 11.sp, maxLines = 1,
                    )
                }
                if (updateProgress == null) {
                    PillButton("Update", color = AccentAtv, contentColor = Bg) { vm.installUpdate() }
                    Spacer(Modifier.width(6.dp))
                    PillButton("", icon = Icons.Default.Close) { vm.updateDismissed.value = true }
                }
            }
            Spacer(Modifier.height(8.dp))
        }

        // Target switch
        Row(Modifier.fillMaxWidth().background(Surface1, RoundedCornerShape(14.dp)).padding(4.dp)) {
            targets.forEach { t ->
                TargetTab(t.label, target == t, t.accent(), Modifier.weight(1f)) {
                    if (t == Target.ATV) vm.goToXiaomi() else vm.target.value = t
                }
            }
        }
        Spacer(Modifier.height(8.dp))

        // Voice: phone speech recognition -> keyboard bar
        val ctx = androidx.compose.ui.platform.LocalContext.current
        val voice = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
            val text = res.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
            if (!text.isNullOrBlank()) vm.onVoiceResult(text)
        }
        fun startVoice() {
            val i = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_PROMPT, "Say what to type or search")
            try { voice.launch(i) } catch (e: Exception) { vm.messages.tryEmit("No speech recognition on this phone") }
        }

        // Power / input / keyboard row
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
            RemoteButton(icon = Icons.Default.PowerSettingsNew, label = "TV power", size = 46.dp, contentColor = Danger) { vm.tvPower() }
            if (Target.ATV in targets) RemoteButton(icon = Icons.Default.Tv, label = "Xiaomi power", size = 46.dp, contentColor = AccentAtv) { vm.atvPower() }
            Box {
                var open by remember { mutableStateOf(false) }
                RemoteButton(icon = Icons.Default.Input, label = "Input", size = 46.dp) { open = true }
                DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                    if (tvIsSamsung) {
                        DropdownMenuItem(text = { Text("Source menu") }, onClick = { open = false; vm.switchSamsungInput("KEY_SOURCE") })
                        DropdownMenuItem(text = { Text("TV") }, onClick = { open = false; vm.switchSamsungInput("KEY_TV") })
                        SAMSUNG_HDMI_KEYS.forEach { (key, label) ->
                            DropdownMenuItem(text = { Text(label) }, onClick = { open = false; vm.switchSamsungInput(key) })
                        }
                    } else {
                        if (inputs.isEmpty()) DropdownMenuItem(text = { Text("Connect to LG TV first") }, onClick = { open = false })
                        inputs.forEach { i ->
                            DropdownMenuItem(text = { Text(i.label.ifEmpty { i.id }) }, onClick = { open = false; vm.switchLgInput(i.id) })
                        }
                    }
                }
            }
            RemoteButton(icon = Icons.Default.Keyboard, label = "Keyboard", size = 46.dp, color = if (keyboardOpen) accent else Surface2, contentColor = if (keyboardOpen) Bg else TextMain) {
                vm.keyboardOpen.value = !keyboardOpen
            }
            RemoteButton(icon = Icons.Default.Mic, label = "Voice", size = 46.dp) { startVoice() }
            RemoteButton(icon = Icons.Default.Bolt, label = "Quick actions", size = 46.dp, contentColor = Color(0xFFE0AF68)) { vm.showQuick.value = true }
        }
        Spacer(Modifier.height(8.dp))

        // Touchpad
        Touchpad(
            modifier = Modifier.fillMaxWidth().weight(1f),
            target = target,
            speed = speed,
            onMove = vm::pointerMove,
            onClick = vm::pointerClick,
            onScroll = vm::pointerScroll,
            onDpad = { dx, dy ->
                when {
                    dx > 0 -> vm.press(Key.RIGHT); dx < 0 -> vm.press(Key.LEFT)
                    dy > 0 -> vm.press(Key.DOWN); dy < 0 -> vm.press(Key.UP)
                }
            },
        )
        Spacer(Modifier.height(8.dp))

        if (keyboardOpen) {
            KeyboardBar(vm, accent, target)
            Spacer(Modifier.height(8.dp))
        }

        // D-pad with back/home on the sides
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceEvenly) {
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
                RemoteButton(icon = Icons.AutoMirrored.Filled.ArrowBack, label = "Back", size = 52.dp) { vm.press(Key.BACK) }
                RemoteButton(icon = Icons.Default.Menu, label = "Menu", size = 52.dp) { vm.press(Key.MENU) }
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                RemoteButton(icon = Icons.Default.KeyboardArrowUp, label = "Up", size = 54.dp, repeat = true) { vm.press(Key.UP) }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RemoteButton(icon = Icons.Default.KeyboardArrowLeft, label = "Left", size = 54.dp, repeat = true) { vm.press(Key.LEFT) }
                    Spacer(Modifier.width(6.dp))
                    RemoteButton(label = "OK", size = 64.dp, color = accent, contentColor = Bg, labelSize = 16) { vm.press(Key.OK) }
                    Spacer(Modifier.width(6.dp))
                    RemoteButton(icon = Icons.Default.KeyboardArrowRight, label = "Right", size = 54.dp, repeat = true) { vm.press(Key.RIGHT) }
                }
                RemoteButton(icon = Icons.Default.KeyboardArrowDown, label = "Down", size = 54.dp, repeat = true) { vm.press(Key.DOWN) }
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
                RemoteButton(icon = Icons.Default.Home, label = "Home", size = 52.dp) { vm.press(Key.HOME) }
                RemoteButton(label = "EXIT", size = 52.dp, labelSize = 11) { vm.press(Key.EXIT) }
            }
        }
        Spacer(Modifier.height(10.dp))

        // Volume + media
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceEvenly) {
            RemoteButton(icon = Icons.Default.Remove, label = "Volume down", size = 50.dp, repeat = true) { vm.press(Key.VOL_DOWN) }
            RemoteButton(icon = if (muted) Icons.AutoMirrored.Filled.VolumeOff else Icons.AutoMirrored.Filled.VolumeUp, label = "Mute", size = 44.dp, contentColor = if (muted) Danger else TextMain) { vm.press(Key.MUTE) }
            RemoteButton(icon = Icons.Default.Add, label = "Volume up", size = 50.dp, repeat = true) { vm.press(Key.VOL_UP) }
            Spacer(Modifier.width(8.dp))
            RemoteButton(icon = Icons.Default.FastRewind, label = "Rewind", size = 44.dp) { vm.press(Key.REWIND) }
            RemoteButton(icon = Icons.Default.PlayArrow, label = "Play", size = 44.dp) { vm.press(Key.PLAY) }
            RemoteButton(icon = Icons.Default.Pause, label = "Pause", size = 44.dp) { vm.press(Key.PAUSE) }
            RemoteButton(icon = Icons.Default.FastForward, label = "Forward", size = 44.dp) { vm.press(Key.FAST_FORWARD) }
        }
        Spacer(Modifier.height(10.dp))

        // Shortcuts (configured in Settings)
        val lgShortcutIds by vm.lgShortcutIds.collectAsState()
        val webShortcuts by vm.webShortcuts.collectAsState()
        val lgApps by vm.lgApps.collectAsState()
        val samsungShortcutIds by vm.samsungShortcutIds.collectAsState()
        val samsungApps by vm.samsungApps.collectAsState()
        val shortcuts = remember(target, lgShortcutIds, samsungShortcutIds, webShortcuts, lgApps, samsungApps) { vm.shortcutsFor(target) }
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            shortcuts.forEach { sc -> ShortcutButton(sc) { vm.launch(sc) } }
            if (shortcuts.isEmpty()) Text("Choose shortcuts in Settings", color = TextDim, fontSize = 12.sp)
        }
    }

    val showQuick by vm.showQuick.collectAsState()
    if (showQuick) QuickActionsSheet(vm) { vm.showQuick.value = false }
    val showYouTube by vm.showYouTube.collectAsState()
    if (showYouTube) YouTubeSheet(vm) { vm.showYouTube.value = false }
}

@Composable
private fun StatusDot(label: String, connected: Boolean, busy: Boolean, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(9.dp).background(if (connected) color else if (busy) Color(0xFFE0AF68) else Color(0xFF444857), CircleShape))
        Spacer(Modifier.width(6.dp))
        Text(label, color = if (connected) TextMain else TextDim, fontSize = 13.sp)
    }
}

@Composable
private fun TargetTab(label: String, selected: Boolean, color: Color, modifier: Modifier, onClick: () -> Unit) {
    Box(
        modifier.background(if (selected) color else Color.Transparent, RoundedCornerShape(11.dp))
            .clickable(onClick = onClick)
            .padding(vertical = 10.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = if (selected) Bg else TextDim, fontWeight = FontWeight.Bold, fontSize = 14.sp)
    }
}

@Composable
private fun KeyboardBar(vm: RemoteViewModel, accent: Color, target: Target) {
    var text by remember { mutableStateOf("") }
    val focus = remember { FocusRequester() }
    val tvFocused by vm.lg.keyboardFocused.collectAsState()
    val voiceText by vm.voiceText.collectAsState()
    LaunchedEffect(Unit) { vm.keyboardReset(); focus.requestFocus() }
    LaunchedEffect(voiceText) {
        val v = voiceText ?: return@LaunchedEffect
        text = v; vm.keyboardText(v); vm.voiceText.value = null
    }
    if (target == Target.LG) {
        Text(
            if (tvFocused) "TV text field is ready" else "No text field is active on the TV. Click into a search box on the TV first (its keyboard should appear).",
            color = if (tvFocused) AccentAtv else Color(0xFFE0AF68), fontSize = 11.sp,
            modifier = Modifier.padding(bottom = 4.dp),
        )
    } else if (target == Target.SAMSUNG) {
        Text(
            "Open a text field on the TV first (its keyboard should appear). Enter sends the text.",
            color = TextDim, fontSize = 11.sp, modifier = Modifier.padding(bottom = 4.dp),
        )
    }
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(
            value = text,
            onValueChange = { text = it; vm.keyboardText(it) },
            modifier = Modifier.weight(1f).focusRequester(focus),
            singleLine = true,
            placeholder = { Text("Type on the TV…", color = TextDim) },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = { vm.keyboardEnter(); text = "" }),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = accent, unfocusedBorderColor = Surface2,
                focusedTextColor = TextMain, unfocusedTextColor = TextMain, cursorColor = accent,
            ),
        )
        Spacer(Modifier.width(8.dp))
        PillButton("Enter", color = accent, contentColor = Bg) { vm.keyboardEnter(); text = "" }
        Spacer(Modifier.width(6.dp))
        PillButton("", icon = Icons.Default.Close) { vm.keyboardOpen.value = false }
    }
    Row(Modifier.fillMaxWidth().padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        PillButton(if (text.isBlank()) "Search YouTube" else "Search YouTube for \"$text\"", modifier = Modifier.weight(1f), color = Color(0xFF3A2A2E), contentColor = Color(0xFFFF6B6B)) {
            vm.searchYouTube(text)
        }
    }
}


@Composable
private fun ShortcutButton(sc: com.dorin.remote.Shortcut, onPress: () -> Unit) {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val view = androidx.compose.ui.platform.LocalView.current
    val iconVersion by com.dorin.remote.net.IconCache.version.collectAsState()
    val bmp by androidx.compose.runtime.produceState<android.graphics.Bitmap?>(null, sc.iconKey, sc.iconUrl, iconVersion) {
        value = com.dorin.remote.net.IconCache.get(ctx, sc.iconKey, sc.iconUrl)
    }
    var pressed by remember { mutableStateOf(false) }
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .width(72.dp)
            .background(if (pressed) Surface2.copy(alpha = 0.6f) else Surface2, RoundedCornerShape(14.dp))
            .pointerInput(onPress) {
                awaitEachGesture {
                    awaitFirstDown(); pressed = true
                    view.performHapticFeedback(android.view.HapticFeedbackConstants.KEYBOARD_TAP)
                    onPress()
                    waitForUpOrCancellation(); pressed = false
                }
            }
            .padding(vertical = 8.dp, horizontal = 4.dp),
    ) {
        Box(Modifier.size(40.dp).clip(RoundedCornerShape(10.dp)).background(Bg), contentAlignment = Alignment.Center) {
            val b = bmp
            if (b != null) androidx.compose.foundation.Image(b.asImageBitmap(), contentDescription = sc.label, modifier = Modifier.size(40.dp),
                contentScale = androidx.compose.ui.layout.ContentScale.Crop)
            else Text(sc.label.take(1).uppercase(), color = TextMain, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        }
        Spacer(Modifier.height(4.dp))
        Text(sc.label, color = TextMain, fontSize = 11.sp, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
    }
}
