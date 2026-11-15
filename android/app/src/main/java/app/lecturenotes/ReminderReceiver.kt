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

        // 정한 시각에 한 번 뜨는 알림 (할 일 마감 하루 전·당일, 수업 시작 5분 전). 웹 화면이 앱을 열 때마다 새로 맞춘다
        private const val NOTICES = "notices"

        fun setNotices(context: Context, json: String) {
            val alarms = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            val prefs = context.getSharedPreferences(NOTICES, Context.MODE_PRIVATE)
            val old = org.json.JSONArray(prefs.getString("list", "[]"))
            for (i in 0 until old.length()) alarms.cancel(noticeIntent(context, old.getJSONObject(i).getInt("id")))
            prefs.edit().putString("list", json).apply()
            scheduleNotices(context)
        }

        fun scheduleNotices(context: Context) {
            val alarms = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            val list = org.json.JSONArray(context.getSharedPreferences(NOTICES, Context.MODE_PRIVATE).getString("list", "[]"))
            val now = System.currentTimeMillis()
            for (i in 0 until list.length()) {
                val n = list.getJSONObject(i)
                val at = n.getLong("at")
                if (at > now) alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, noticeIntent(context, n.getInt("id")))
            }
        }

        private fun noticeIntent(context: Context, id: Int): PendingIntent =
            PendingIntent.getBroadcast(context, 1000 + id, Intent(context, ReminderReceiver::class.java).setAction("notice").putExtra("id", id),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

        private fun pending(context: Context): PendingIntent =
            PendingIntent.getBroadcast(context, 7, Intent(context, ReminderReceiver::class.java).setAction("remind"),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            schedule(context)
            scheduleNotices(context)
            return
        }
        if (intent.action == "notice") {
            val id = intent.getIntExtra("id", -1)
            val list = org.json.JSONArray(context.getSharedPreferences(NOTICES, Context.MODE_PRIVATE).getString("list", "[]"))
            val n = (0 until list.length()).map { list.getJSONObject(it) }.firstOrNull { it.getInt("id") == id } ?: return
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel("due", "마감·수업 알림", NotificationManager.IMPORTANCE_HIGH))
            val open = PendingIntent.getActivity(context, 2000 + id,
                Intent(context, MainActivity::class.java).putExtra("open", n.optString("open", "")), PendingIntent.FLAG_IMMUTABLE)
            manager.notify(1000 + id, Notification.Builder(context, "due")
                .setContentTitle(n.getString("title")).setContentText(n.optString("text", ""))
                .setSmallIcon(R.drawable.ic_notify).setContentIntent(open).setAutoCancel(true).build())
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
