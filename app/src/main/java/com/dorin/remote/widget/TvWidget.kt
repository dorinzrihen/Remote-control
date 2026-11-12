package com.dorin.remote.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.widget.RemoteViews
import com.dorin.remote.App
import com.dorin.remote.Diag
import com.dorin.remote.R
import com.dorin.remote.TvRoute
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull

/**
 * The TV widget: Volume +/− and the four arrows. Works on the home screen and on the Android 16
 * QPR2+ lock screen. Every button is a *broadcast* PendingIntent to [TvWidgetProvider], never an
 * activity, so a tap runs while the phone is locked: no unlock prompt, no app window. The receiver
 * keeps itself alive with goAsync(), (re)connects through the app's existing TV clients ([App.tv])
 * and sends the key. No foreground service or notification is needed.
 */
class TvWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        manager.updateAppWidget(ids, TvWidget.views(context))
    }

    override fun onAppWidgetOptionsChanged(context: Context, manager: AppWidgetManager, id: Int, options: Bundle) {
        manager.updateAppWidget(id, TvWidget.views(context))
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == TvWidget.ACTION_PRESS) {
            val command = WidgetCommand.parse(intent.getStringExtra(TvWidget.EXTRA_COMMAND)) ?: return
            val result = goAsync()
            TvWidget.press(context.applicationContext as App, command) { result.finish() }
            return
        }
        super.onReceive(context, intent)
    }
}

object TvWidget {
    const val ACTION_PRESS = "com.dorin.remote.widget.PRESS"
    const val EXTRA_COMMAND = "command"
    private const val TAG = "TvWidget"
    /** Stay well inside the 10 s a foreground broadcast may run for. */
    private const val PRESS_BUDGET_MS = 8_000L

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    /** Taps are sent one at a time, in order. */
    private val sending = Mutex()
    @Volatile private var lastSuccessMs = 0L
    @Volatile private var problem: String? = null

    private val BUTTONS = mapOf(
        R.id.w_vol_up to WidgetCommand.VOL_UP, R.id.w_vol_down to WidgetCommand.VOL_DOWN,
        R.id.w_up to WidgetCommand.UP, R.id.w_down to WidgetCommand.DOWN,
        R.id.w_left to WidgetCommand.LEFT, R.id.w_right to WidgetCommand.RIGHT,
    )

    fun views(ctx: Context): RemoteViews = RemoteViews(ctx.packageName, R.layout.widget_tv).apply {
        val app = ctx.applicationContext as App
        val route = tvRoute(app)
        val volume = if (route == TvRoute.LG && app.lg.isConnected) app.lg.volume.value else null
        setTextViewText(R.id.w_label, WidgetLogic.label(route, volume, problem))
        for ((id, command) in BUTTONS) setOnClickPendingIntent(id, pressIntent(ctx, command))
    }

    private fun pressIntent(ctx: Context, command: WidgetCommand): PendingIntent {
        val intent = Intent(ctx, TvWidgetProvider::class.java)
            .setAction(ACTION_PRESS)
            .putExtra(EXTRA_COMMAND, command.name)
            // Foreground broadcast queue: lower latency, and a 10 s budget for goAsync().
            .addFlags(Intent.FLAG_RECEIVER_FOREGROUND)
        return PendingIntent.getBroadcast(ctx, command.ordinal, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    fun updateAll(ctx: Context) {
        val manager = AppWidgetManager.getInstance(ctx)
        val ids = manager.getAppWidgetIds(ComponentName(ctx, TvWidgetProvider::class.java))
        if (ids.isNotEmpty()) manager.updateAppWidget(ids, views(ctx))
    }

    fun press(app: App, command: WidgetCommand, done: () -> Unit) {
        scope.launch {
            try {
                val sent = withTimeoutOrNull(PRESS_BUDGET_MS) { sending.withLock { problem = send(app, command); true } }
                if (sent == null) problem = "not reachable"
            } catch (e: Exception) {
                problem = e.message ?: "failed"
            } finally {
                Diag.log(TAG, "$command -> ${problem ?: "sent"}")
                runCatching { updateAll(app) }
                done()
            }
        }
    }

    private fun tvRoute(app: App): TvRoute = WidgetLogic.tvRoute(app.prefs.lgIp.isNotEmpty(), app.prefs.samsungIp.isNotEmpty(), atvConfigured(app))

    private fun atvConfigured(app: App) = app.prefs.atvIp.isNotEmpty() && app.prefs.atvPaired

    /** The remote screen's rule: the LG TV shows the Xiaomi's HDMI input. */
    private fun lgShowsXiaomi(app: App): Boolean {
        val id = app.prefs.xiaomiInputId ?: return false
        val input = app.lg.inputs.value.firstOrNull { it.id == id } ?: return false
        return app.lg.currentApp.value == input.appId
    }

    /** Sends one press. Returns null when sent, else a short message for the widget's label. */
    private suspend fun send(app: App, command: WidgetCommand): String? {
        val p = app.prefs
        val route = WidgetLogic.route(command, p.lgIp.isNotEmpty(), p.samsungIp.isNotEmpty(), atvConfigured(app), lgShowsXiaomi(app))
        if (route == TvRoute.NONE) return null // the label already says "Set up a TV in UniRemote"
        val tv = app.tv
        val wasConnected = tv.isConnected(route)
        if (!wasConnected) {
            tv.redialIfDown(route)
        } else if (route == TvRoute.LG && WidgetLogic.shouldProbe(true, lastSuccessMs, SystemClock.elapsedRealtime()) &&
            !tv.lgAnswers(WidgetLogic.PROBE_TIMEOUT_MS)) {
            Log.i(TAG, "LG connection went stale while the app was idle; reconnecting")
            tv.reconnectLg()
        }
        if (!tv.awaitRoute(route, WidgetLogic.CONNECT_TIMEOUT_MS)) return "not reachable"
        val volumeBefore = app.lg.volume.value
        val error = if (command.isVolume) tv.volume(command.key, preferSamsung = route == TvRoute.SAMSUNG) else tv.keyTo(route, command.key)
        if (error != null) return error
        lastSuccessMs = SystemClock.elapsedRealtime()
        // Give the queued frame time to leave before the process may be frozen again; for LG volume,
        // wait for the TV to report the new level so the label shows it.
        if (command.isVolume && route == TvRoute.LG) withTimeoutOrNull(800) { app.lg.volume.first { it != volumeBefore } }
        else delay(150)
        return null
    }
}
