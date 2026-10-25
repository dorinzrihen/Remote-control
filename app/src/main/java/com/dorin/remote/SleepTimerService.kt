package com.dorin.remote

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import com.dorin.remote.atv.AtvKeys
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch

/** Counts down in a foreground notification, then turns the TV (and the Xiaomi) off. */
class SleepTimerService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var job: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CANCEL -> { finish(); return START_NOT_STICKY }
            else -> {
                val minutes = intent?.getIntExtra(EXTRA_MINUTES, 30) ?: 30
                val end = System.currentTimeMillis() + minutes * 60_000L
                endTime.value = end
                startInForeground(buildNotification(minutes * 60_000L))
                job?.cancel()
                job = scope.launch {
                    while (true) {
                        val left = end - System.currentTimeMillis()
                        if (left <= 0) break
                        notify(buildNotification(left))
                        delay(minOf(30_000L, left))
                    }
                    fire()
                    finish()
                }
            }
        }
        return START_NOT_STICKY
    }

    private fun fire() {
        val app = App.instance
        Diag.log("Sleep", "timer expired, turning TV off")
        app.lg.powerOff()
        if (app.samsung.isConnected) app.samsung.powerToggle()
        if (app.atv.isConnected) app.atv.key(AtvKeys.SLEEP)
    }

    private fun finish() {
        job?.cancel(); job = null
        endTime.value = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun startInForeground(n: Notification) {
        if (Build.VERSION.SDK_INT >= 34) startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(NOTIF_ID, n)
    }

    private fun notify(n: Notification) {
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(NOTIF_ID, n)
    }

    private fun buildNotification(leftMs: Long): Notification {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        if (nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "Sleep timer", NotificationManager.IMPORTANCE_LOW))
        }
        val mins = (leftMs + 59_999) / 60_000
        val cancel = PendingIntent.getService(
            this, 1, Intent(this, SleepTimerService::class.java).setAction(ACTION_CANCEL),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentTitle("TV turns off in $mins min")
            .setContentText("UniRemote sleep timer")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .addAction(Notification.Action.Builder(null, "Cancel", cancel).build())
            .build()
    }

    override fun onDestroy() {
        scope.cancel()
        endTime.value = null
        super.onDestroy()
    }

    companion object {
        const val ACTION_CANCEL = "cancel"
        const val EXTRA_MINUTES = "minutes"
        private const val CHANNEL = "sleep"
        private const val NOTIF_ID = 7

        /** Epoch millis when the TV will be turned off, or null when no timer runs. */
        val endTime = MutableStateFlow<Long?>(null)

        fun start(ctx: Context, minutes: Int) {
            val i = Intent(ctx, SleepTimerService::class.java).putExtra(EXTRA_MINUTES, minutes)
            ctx.startForegroundService(i)
        }

        fun cancel(ctx: Context) {
            ctx.startService(Intent(ctx, SleepTimerService::class.java).setAction(ACTION_CANCEL))
        }
    }
}
