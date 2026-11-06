package com.dorin.remote

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Upgrade cleanup only. Never schedules an alarm or performs lighting I/O. */
class NightLightsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) = cancelLegacyAlarm(context)

    companion object {
        fun cancelLegacyAlarm(context: Context) {
            val old = PendingIntent.getBroadcast(
                context, 0, Intent(context, NightLightsReceiver::class.java).setAction("com.dorin.remote.NIGHT_LIGHTS"),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_NO_CREATE,
            ) ?: return
            context.getSystemService(AlarmManager::class.java).cancel(old)
            old.cancel()
        }
    }
}
