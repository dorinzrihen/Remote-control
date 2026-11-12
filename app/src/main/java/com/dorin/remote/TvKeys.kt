package com.dorin.remote

import com.dorin.remote.atv.AtvKeys

/** Remote-key names per device, shared by the remote screen, widgets, notification and tile. */
object TvKeys {
    /** LG pointer-socket button name; null for keys the LG handles another way (volume, play/pause, search). */
    fun lgButton(key: Key): String? = when (key) {
        Key.UP -> "UP"; Key.DOWN -> "DOWN"; Key.LEFT -> "LEFT"; Key.RIGHT -> "RIGHT"; Key.OK -> "ENTER"
        Key.BACK -> "BACK"; Key.HOME -> "HOME"; Key.MENU -> "MENU"; Key.EXIT -> "EXIT"; Key.INFO -> "INFO"
        Key.PLAY -> "PLAY"; Key.PAUSE -> "PAUSE"; Key.STOP -> "STOP"; Key.REWIND -> "REWIND"; Key.FAST_FORWARD -> "FASTFORWARD"
        Key.CH_UP -> "CHANNELUP"; Key.CH_DOWN -> "CHANNELDOWN"; Key.SETTINGS -> "MENU"
        Key.RED -> "RED"; Key.GREEN -> "GREEN"; Key.YELLOW -> "YELLOW"; Key.BLUE -> "BLUE"
        Key.N0 -> "0"; Key.N1 -> "1"; Key.N2 -> "2"; Key.N3 -> "3"; Key.N4 -> "4"
        Key.N5 -> "5"; Key.N6 -> "6"; Key.N7 -> "7"; Key.N8 -> "8"; Key.N9 -> "9"
        Key.PLAY_PAUSE, Key.SEARCH, Key.VOL_UP, Key.VOL_DOWN, Key.MUTE -> null
    }

    /** Tizen remote key names. */
    fun samsungKey(key: Key): String? = when (key) {
        Key.UP -> "KEY_UP"; Key.DOWN -> "KEY_DOWN"; Key.LEFT -> "KEY_LEFT"; Key.RIGHT -> "KEY_RIGHT"; Key.OK -> "KEY_ENTER"
        Key.BACK -> "KEY_RETURN"; Key.HOME -> "KEY_HOME"; Key.MENU -> "KEY_MENU"; Key.EXIT -> "KEY_EXIT"; Key.INFO -> "KEY_INFO"
        Key.PLAY -> "KEY_PLAY"; Key.PAUSE -> "KEY_PAUSE"; Key.PLAY_PAUSE -> "KEY_PLAY"; Key.STOP -> "KEY_STOP"
        Key.REWIND -> "KEY_REWIND"; Key.FAST_FORWARD -> "KEY_FF"
        Key.VOL_UP -> "KEY_VOLUP"; Key.VOL_DOWN -> "KEY_VOLDOWN"; Key.MUTE -> "KEY_MUTE"
        Key.CH_UP -> "KEY_CHUP"; Key.CH_DOWN -> "KEY_CHDOWN"; Key.SETTINGS -> "KEY_MENU"
        Key.RED -> "KEY_RED"; Key.GREEN -> "KEY_GREEN"; Key.YELLOW -> "KEY_YELLOW"; Key.BLUE -> "KEY_CYAN"
        Key.N0 -> "KEY_0"; Key.N1 -> "KEY_1"; Key.N2 -> "KEY_2"; Key.N3 -> "KEY_3"; Key.N4 -> "KEY_4"
        Key.N5 -> "KEY_5"; Key.N6 -> "KEY_6"; Key.N7 -> "KEY_7"; Key.N8 -> "KEY_8"; Key.N9 -> "KEY_9"
        Key.SEARCH -> null
    }

    fun atvKey(key: Key): Int? = when (key) {
        Key.UP -> AtvKeys.DPAD_UP; Key.DOWN -> AtvKeys.DPAD_DOWN; Key.LEFT -> AtvKeys.DPAD_LEFT; Key.RIGHT -> AtvKeys.DPAD_RIGHT
        Key.OK -> AtvKeys.DPAD_CENTER; Key.BACK -> AtvKeys.BACK; Key.HOME -> AtvKeys.HOME; Key.MENU -> AtvKeys.MENU
        Key.EXIT -> AtvKeys.BACK; Key.INFO -> AtvKeys.INFO
        Key.PLAY -> AtvKeys.MEDIA_PLAY; Key.PAUSE -> AtvKeys.MEDIA_PAUSE; Key.PLAY_PAUSE -> AtvKeys.MEDIA_PLAY_PAUSE
        Key.STOP -> AtvKeys.MEDIA_STOP; Key.REWIND -> AtvKeys.MEDIA_REWIND; Key.FAST_FORWARD -> AtvKeys.MEDIA_FAST_FORWARD
        Key.VOL_UP -> AtvKeys.VOLUME_UP; Key.VOL_DOWN -> AtvKeys.VOLUME_DOWN; Key.MUTE -> AtvKeys.VOLUME_MUTE
        Key.CH_UP -> AtvKeys.CHANNEL_UP; Key.CH_DOWN -> AtvKeys.CHANNEL_DOWN; Key.SETTINGS -> AtvKeys.SETTINGS
        Key.SEARCH -> AtvKeys.SEARCH
        Key.N0 -> AtvKeys.KEY_0; Key.N1 -> AtvKeys.KEY_0 + 1; Key.N2 -> AtvKeys.KEY_0 + 2; Key.N3 -> AtvKeys.KEY_0 + 3
        Key.N4 -> AtvKeys.KEY_0 + 4; Key.N5 -> AtvKeys.KEY_0 + 5; Key.N6 -> AtvKeys.KEY_0 + 6; Key.N7 -> AtvKeys.KEY_0 + 7
        Key.N8 -> AtvKeys.KEY_0 + 8; Key.N9 -> AtvKeys.KEY_0 + 9
        Key.RED, Key.GREEN, Key.YELLOW, Key.BLUE -> null
    }
}
