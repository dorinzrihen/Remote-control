package com.dorin.remote.ui

import android.view.HapticFeedbackConstants
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * A remote button: fires on press (not release) for snappy feel, haptic tap, and
 * optional auto-repeat while held (volume, d-pad).
 */
@Composable
fun RemoteButton(
    modifier: Modifier = Modifier,
    size: Dp = 56.dp,
    shape: Shape = CircleShape,
    color: Color = Surface2,
    contentColor: Color = TextMain,
    icon: ImageVector? = null,
    label: String? = null,
    labelSize: Int = 13,
    repeat: Boolean = false,
    enabled: Boolean = true,
    onPress: () -> Unit,
) {
    val view = LocalView.current
    val scope = rememberCoroutineScope()
    var pressed by remember { mutableStateOf(false) }
    Box(
        modifier = modifier
            .size(size)
            .background(if (pressed) color.copy(alpha = 0.6f) else color, shape)
            .pointerInput(enabled, repeat, onPress) {
                if (!enabled) return@pointerInput
                awaitEachGesture {
                    awaitFirstDown()
                    pressed = true
                    view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
                    onPress()
                    var job: Job? = null
                    if (repeat) {
                        job = scope.launch {
                            delay(400)
                            while (isActive) { onPress(); delay(120) }
                        }
                    }
                    waitForUpOrCancellation()
                    job?.cancel()
                    pressed = false
                }
            },
        contentAlignment = Alignment.Center,
    ) {
        if (icon != null) Icon(icon, contentDescription = label, tint = if (enabled) contentColor else TextDim, modifier = Modifier.size(size * 0.45f))
        else if (label != null) Text(label, color = if (enabled) contentColor else TextDim, fontSize = labelSize.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
fun PillButton(
    label: String,
    modifier: Modifier = Modifier,
    color: Color = Surface2,
    contentColor: Color = TextMain,
    icon: ImageVector? = null,
    onPress: () -> Unit,
) {
    val view = LocalView.current
    var pressed by remember { mutableStateOf(false) }
    Box(
        modifier = modifier
            .background(if (pressed) color.copy(alpha = 0.6f) else color, RoundedCornerShape(14.dp))
            .pointerInput(onPress) {
                awaitEachGesture {
                    awaitFirstDown(); pressed = true
                    view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
                    onPress()
                    waitForUpOrCancellation(); pressed = false
                }
            }
            .padding(PaddingValues(horizontal = 12.dp, vertical = 12.dp)),
        contentAlignment = Alignment.Center,
    ) {
        if (icon != null) Icon(icon, contentDescription = label, tint = contentColor, modifier = Modifier.size(22.dp))
        else Text(label, color = contentColor, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
    }
}
