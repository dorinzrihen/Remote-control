package com.dorin.remote

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.util.Calendar
import java.util.TimeZone

/** When "night" starts and ends, in the phone's local time. */
object NightTime {
    const val NIGHT_HOUR = 21
    /** A room turned on before this hour (or from NIGHT_HOUR) starts in Night. */
    const val MORNING_HOUR = 6

    fun isNight(hour: Int) = hour >= NIGHT_HOUR || hour < MORNING_HOUR
    fun isNightNow() = isNight(Calendar.getInstance().get(Calendar.HOUR_OF_DAY))

    /** The next NIGHT_HOUR:00 after [now]. Calendar keeps the wall-clock hour across daylight saving changes. */
    fun next(now: Long, tz: TimeZone = TimeZone.getDefault()): Long {
        val c = Calendar.getInstance(tz).apply {
            timeInMillis = now
            set(Calendar.HOUR_OF_DAY, NIGHT_HOUR); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
        }
        if (c.timeInMillis <= now) c.add(Calendar.DAY_OF_MONTH, 1)
        return c.timeInMillis
    }
}

/**
 * At 21:00 every day the bulbs that are on switch to Night (20% warm); bulbs that are off stay off.
 * Whatever is pressed after that stays until the next evening. Re-arms itself after a reboot,
 * an app update or a time zone change. Needs the phone on the home Wi-Fi at 21:00.
 */
class NightLightsReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action != ACTION_NIGHT) { schedule(ctx); return }
        val pending = goAsync()
        scope.launch {
            try {
                val n = withTimeoutOrNull(8_000) { App.instance.lights.nightIfOn() }
                Diag.log("Night", if (n == null) "bulbs did not answer in time" else "$n bulb(s) switched to Night")
            } finally {
                schedule(ctx)
                pending.finish()
            }
        }
    }

    companion object {
        private const val ACTION_NIGHT = "com.dorin.remote.NIGHT_LIGHTS"
        private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

        /** Arms the next 21:00 alarm, or cancels it when the setting is off or no bulbs are saved. */
        fun schedule(ctx: Context) {
            val app = App.instance
            val am = ctx.getSystemService(AlarmManager::class.java)
            val pi = PendingIntent.getBroadcast(
                ctx, 0, Intent(ctx, NightLightsReceiver::class.java).setAction(ACTION_NIGHT),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            if (!app.prefs.autoNight || app.lights.bulbs.value.isEmpty()) { am.cancel(pi); return }
            val at = NightTime.next(System.currentTimeMillis())
            if (Build.VERSION.SDK_INT < 31 || am.canScheduleExactAlarms()) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
            else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
        }
    }
}
