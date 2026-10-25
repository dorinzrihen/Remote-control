package com.dorin.remote.ui

import android.view.HapticFeedbackConstants
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.dorin.remote.Target
import kotlin.math.abs

/**
 * LG / Samsung target: one finger = move cursor, tap = click, two fingers = scroll (LG only).
 * Xiaomi target: swipe = d-pad step (repeats while you keep dragging), tap = OK.
 */
@Composable
fun Touchpad(
    modifier: Modifier,
    target: Target,
    speed: Float,
    onMove: (Float, Float) -> Unit,
    onClick: () -> Unit,
    onScroll: (Float) -> Unit,
    onDpad: (dx: Int, dy: Int) -> Unit,
) {
    val view = LocalView.current
    val hint = when (target) {
        Target.LG -> "Touchpad · drag to move the cursor · tap to click · two fingers to scroll"
        Target.SAMSUNG -> "Touchpad · drag to move the cursor · tap to click"
        Target.ATV -> "Touchpad · swipe to move · tap for OK"
    }
    Box(
        modifier = modifier
            .background(Surface1, RoundedCornerShape(20.dp))
            .pointerInput(target, speed) {
                val stepPx = 70.dp.toPx()
                awaitEachGesture {
                    val down = awaitFirstDown()
                    val downTime = System.currentTimeMillis()
                    var moved = 0f
                    var twoFinger = false
                    var restX = 0f
                    var restY = 0f
                    var accX = 0f
                    var accY = 0f
                    var lastScrollY = 0f
                    while (true) {
                        val event = awaitPointerEvent()
                        val pressedPointers = event.changes.filter { it.pressed }
                        if (pressedPointers.isEmpty()) break
                        if (pressedPointers.size >= 2) twoFinger = true
                        val primary = pressedPointers.first()
                        val delta: Offset = primary.positionChange()
                        if (delta != Offset.Zero) {
                            moved += abs(delta.x) + abs(delta.y)
                            val cursor = target == Target.LG || target == Target.SAMSUNG
                            if (twoFinger && target == Target.LG) {
                                lastScrollY += delta.y
                                if (abs(lastScrollY) >= 6f) { onScroll(lastScrollY / 2f); lastScrollY = 0f }
                            } else if (cursor) {
                                val sx = delta.x * speed + restX
                                val sy = delta.y * speed + restY
                                val ix = sx.toInt(); val iy = sy.toInt()
                                restX = sx - ix; restY = sy - iy
                                if (ix != 0 || iy != 0) onMove(ix.toFloat(), iy.toFloat())
                            } else {
                                accX += delta.x; accY += delta.y
                                while (abs(accX) >= stepPx) {
                                    onDpad(if (accX > 0) 1 else -1, 0); accX -= stepPx * (if (accX > 0) 1 else -1)
                                    view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP); accY = 0f
                                }
                                while (abs(accY) >= stepPx) {
                                    onDpad(0, if (accY > 0) 1 else -1); accY -= stepPx * (if (accY > 0) 1 else -1)
                                    view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP); accX = 0f
                                }
                            }
                        }
                        event.changes.forEach { it.consume() }
                    }
                    val tapSlop = 12.dp.toPx()
                    if (!twoFinger && moved < tapSlop && System.currentTimeMillis() - downTime < 350) {
                        view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
                        onClick()
                    }
                }
            },
        contentAlignment = Alignment.BottomCenter,
    ) {
        Text(
            hint,
            color = TextDim,
            fontSize = 11.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxSize().padding(12.dp),
        )
    }
}
