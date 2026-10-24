package com.dorin.remote.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Bg = Color(0xFF0E0F13)
val Surface1 = Color(0xFF181A21)
val Surface2 = Color(0xFF232630)
val Accent = Color(0xFF7AA2F7)
val AccentAtv = Color(0xFF9ECE6A)
val TextMain = Color(0xFFE6E8EF)
val TextDim = Color(0xFF8A90A3)
val Danger = Color(0xFFF7768E)

@Composable
fun UniTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Accent,
            onPrimary = Bg,
            background = Bg,
            surface = Surface1,
            onSurface = TextMain,
            surfaceVariant = Surface2,
            onSurfaceVariant = TextDim,
            secondary = AccentAtv,
            error = Danger,
        ),
        content = content,
    )
}
