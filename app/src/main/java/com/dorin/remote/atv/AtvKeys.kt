package com.dorin.remote.atv

/** Android key codes from remotemessage.proto / android keycodes.h. */
object AtvKeys {
    const val HOME = 3
    const val BACK = 4
    const val KEY_0 = 7
    const val DPAD_UP = 19
    const val DPAD_DOWN = 20
    const val DPAD_LEFT = 21
    const val DPAD_RIGHT = 22
    const val DPAD_CENTER = 23
    const val VOLUME_UP = 24
    const val VOLUME_DOWN = 25
    const val POWER = 26
    const val KEY_A = 29
    const val TAB = 61
    const val SPACE = 62
    const val ENTER = 66
    const val DEL = 67
    const val MENU = 82
    const val SEARCH = 84
    const val MEDIA_PLAY_PAUSE = 85
    const val MEDIA_STOP = 86
    const val MEDIA_NEXT = 87
    const val MEDIA_PREVIOUS = 88
    const val MEDIA_REWIND = 89
    const val MEDIA_FAST_FORWARD = 90
    const val MEDIA_PLAY = 126
    const val MEDIA_PAUSE = 127
    const val VOLUME_MUTE = 164
    const val INFO = 165
    const val CHANNEL_UP = 166
    const val CHANNEL_DOWN = 167
    const val GUIDE = 172
    const val SETTINGS = 176
    const val TV_INPUT = 178
    const val ASSIST = 219
    const val SLEEP = 223
    const val WAKEUP = 224

    const val DIRECTION_START_LONG = 1
    const val DIRECTION_END_LONG = 2
    const val DIRECTION_SHORT = 3

    /** Map a typed character to a keycode when possible (fallback typing path). */
    fun forChar(c: Char): Int? = when {
        c in 'a'..'z' -> KEY_A + (c - 'a')
        c in 'A'..'Z' -> KEY_A + (c - 'A')
        c in '0'..'9' -> KEY_0 + (c - '0')
        c == ' ' -> SPACE
        c == '\n' -> ENTER
        else -> null
    }
}
