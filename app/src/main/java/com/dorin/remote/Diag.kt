package com.dorin.remote

import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Small in-memory log shown in the setup screen so protocol problems can be reported. */
object Diag {
    private const val MAX = 120
    private val fmt = SimpleDateFormat("HH:mm:ss", Locale.US)
    val lines = MutableStateFlow<List<String>>(emptyList())

    @Synchronized
    fun log(tag: String, msg: String) {
        Log.i(tag, msg)
        val line = "${fmt.format(Date())} $tag: $msg"
        lines.value = (lines.value + line).takeLast(MAX)
    }

    fun clear() { lines.value = emptyList() }
}
