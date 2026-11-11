package app.lecturenotes

import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.app.Notification
import java.util.Calendar

/**
 * 복습·시험 알림: 매일 정해 둔 시각(기본 저녁 8시)에 "오늘 복습 N장 · 중간고사 D-3" 같은 알림을 띄운다.
 * 알림 글은 앱을 열 때마다 웹 화면이 최신 숫자로 바꿔 둔다 (setReminder). 폰을 다시 켜면 다시 맞춘다.
 */
class ReminderReceiver : BroadcastReceiver() {

    companion object {
        private const val CHANNEL = "review"
        private const val PREFS = "reminder"

        fun save(context: Context, title: String, text: String, hour: Int, minute: Int) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString("title", title).putString("text", text).putInt("hour", hour).putInt("minute", minute).apply()
            schedule(context)
        }

        fun cancel(context: Context) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().clear().apply()
            (context.getSystemService(Context.ALARM_SERVICE) as AlarmManager).cancel(pending(context))
        }

        fun schedule(context: Context) {
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            if (!prefs.contains("title")) return
            val next = Calendar.getInstance().apply {
                set(Calendar.HOUR_OF_DAY, prefs.getInt("hour", 20))
                set(Calendar.MINUTE, prefs.getInt("minute", 0))
                set(Calendar.SECOND, 0)
                if (timeInMillis <= System.currentTimeMillis()) add(Calendar.DAY_OF_YEAR, 1)
            }
            // 정확한 알람 권한이 없어도 되는 "대략 그 시각" 반복 알람 (배터리에 좋다)
            (context.getSystemService(Context.ALARM_SERVICE) as AlarmManager)
                .setInexactRepeating(AlarmManager.RTC_WAKEUP, next.timeInMillis, AlarmManager.INTERVAL_DAY, pending(context))
        }

        private fun pending(context: Context): PendingIntent =
            PendingIntent.getBroadcast(context, 7, Intent(context, ReminderReceiver::class.java).setAction("remind"),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            schedule(context)
            return
        }
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val title = prefs.getString("title", null) ?: return
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "복습·시험 알림", NotificationManager.IMPORTANCE_DEFAULT))
        val open = PendingIntent.getActivity(context, 0,
            Intent(context, MainActivity::class.java).putExtra("open", "review"), PendingIntent.FLAG_IMMUTABLE)
        val notice = Notification.Builder(context, CHANNEL)
            .setContentTitle(title)
            .setContentText(prefs.getString("text", ""))
            .setSmallIcon(R.drawable.ic_notify)
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        manager.notify(2, notice)
    }
}
