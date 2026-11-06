package com.dorin.remote.wiz

import org.json.JSONObject

/** Only phone-editable timetable fields participate; bulb ownership stays with the manager. */
data class Timetable(val enabled: Boolean, val night: String, val morning: String, val timezone: String, val pollSeconds: String) {
    fun json(): JSONObject = ButlerClient.config(enabled, night, morning, timezone, pollSeconds.toInt())

    companion object {
        fun from(config: JSONObject) = Timetable(config.getBoolean("enabled"), config.getString("night"),
            config.getString("morning"), config.getString("timezone"), config.optInt("pollSeconds", 1).toString())
    }
}

data class TimetableEditor(val baseline: Timetable, val draft: Timetable = baseline, val latest: Timetable = baseline,
                           val rejected: Boolean = false) {
    val dirty: Boolean get() = draft != baseline
    val conflict: Boolean get() = rejected || (dirty && latest != baseline)
    fun observe(current: Timetable): TimetableEditor = if (!dirty && !rejected) TimetableEditor(current) else copy(latest = current)
    fun reload() = TimetableEditor(latest)
    /** Explicitly keep the draft on top of the latest manager settings. Save still checks again. */
    fun reapply() = copy(baseline = latest, rejected = false)
}

class TimetableConflict : IllegalStateException("Timetable changed on another phone")

/** Fresh check before POST; expectedConfig additionally permits atomic server-side comparison. */
suspend fun saveTimetable(editor: TimetableEditor, exchange: suspend (String, JSONObject?) -> JSONObject,
                          observe: (JSONObject) -> Unit): JSONObject {
    val current = exchange("/v1/status", null)
    observe(current)
    if (Timetable.from(current.getJSONObject("config")) != editor.baseline) throw TimetableConflict()
    return exchange("/v1/config", editor.draft.json().put("expectedConfig", editor.baseline.json()))
}
