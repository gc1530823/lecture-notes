package app.lecturenotes

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import org.json.JSONArray
import java.util.Calendar

/**
 * 홈 화면 위젯 "다음 수업": 앱이 시간표를 불러올 때 웹 화면이 넘겨준 시간표(saveTimetable)로
 * 지금 하는 수업, 없으면 가장 가까운 다음 수업을 보여 준다. 누르면 앱 홈(바로 녹음할 수 있는 곳)이 열린다.
 * 인터넷 없이 폰 안에 저장된 시간표만 쓴다. 30분마다, 그리고 시간표가 바뀔 때마다 새로 그린다.
 */
class NextClassWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        for (id in ids) manager.updateAppWidget(id, render(context))
    }

    companion object {
        private val DAYS = arrayOf("월", "화", "수", "목", "금", "토", "일")

        fun refresh(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, NextClassWidget::class.java))
            if (ids.isNotEmpty()) for (id in ids) manager.updateAppWidget(id, render(context))
        }

        private data class Row(val course: String, val weekday: Int, val start: String, val end: String, val place: String)

        private fun rows(context: Context): List<Row> {
            val text = context.getSharedPreferences("settings", Context.MODE_PRIVATE).getString("timetable", null) ?: return emptyList()
            return try {
                val arr = JSONArray(text)
                (0 until arr.length()).map { i ->
                    val o = arr.getJSONObject(i)
                    Row(o.optString("course"), o.optInt("weekday"), o.optString("start"), o.optString("end"), o.optString("place"))
                }
            } catch (e: Exception) { emptyList() }
        }

        /** (라벨, 과목, 언제·어디) */
        private fun pick(list: List<Row>): Triple<String, String, String>? {
            val now = Calendar.getInstance()
            val today = (now.get(Calendar.DAY_OF_WEEK) + 5) % 7          // 0 = 월요일
            val clock = String.format("%02d:%02d", now.get(Calendar.HOUR_OF_DAY), now.get(Calendar.MINUTE))
            val soon = Calendar.getInstance().apply { add(Calendar.MINUTE, 10) }
            val soonClock = String.format("%02d:%02d", soon.get(Calendar.HOUR_OF_DAY), soon.get(Calendar.MINUTE))
            val todays = list.filter { it.weekday == today }.sortedBy { it.start }
            fun where(r: Row, at: String) = if (r.place.isBlank()) at else "$at · ${r.place}"
            todays.firstOrNull { it.start <= soonClock && clock < it.end }?.let { return Triple("지금 수업", it.course, where(it, "${it.start}–${it.end}")) }
            todays.firstOrNull { it.start > clock }?.let { return Triple("다음 수업", it.course, where(it, "오늘 ${it.start}")) }
            for (k in 1..7) {
                val day = (today + k) % 7
                list.filter { it.weekday == day }.minByOrNull { it.start }?.let {
                    return Triple("다음 수업", it.course, where(it, "${if (k == 1) "내일" else DAYS[day] + "요일"} ${it.start}"))
                }
            }
            return null
        }

        private fun render(context: Context): RemoteViews {
            val views = RemoteViews(context.packageName, R.layout.widget_next_class)
            val list = rows(context)
            val found = pick(list)
            if (found == null) {
                views.setTextViewText(R.id.widget_label, "LUNE")
                views.setTextViewText(R.id.widget_course, if (list.isEmpty()) "시간표를 넣어 주세요" else "이번 주 수업이 없어요")
                views.setTextViewText(R.id.widget_when, if (list.isEmpty()) "앱 › 일정 › 시간표 캡처로 넣기" else "푹 쉬어요")
            } else {
                views.setTextViewText(R.id.widget_label, found.first)
                views.setTextViewText(R.id.widget_course, found.second)
                views.setTextViewText(R.id.widget_when, found.third)
            }
            val open = Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            views.setOnClickPendingIntent(R.id.widget_root,
                PendingIntent.getActivity(context, 7, open, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
            return views
        }
    }
}
