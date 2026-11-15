// 마감·수업 알림 (안드로이드 앱): 할 일 마감 하루 전 저녁 8시 · 당일 아침 8시, 수업 시작 5분 전.
// 앱을 열 때마다 할 일·시간표로 다음 7일 치를 다시 맞춘다 (앱이 AlarmManager 로 띄운다). 설정에서 끌 수 있다.
import { getJSON } from "../api/useApi";
import { android } from "./live";
import { getPrefs } from "./prefs";

interface Notice { id: number; title: string; text: string; at: number; open: string }

const at = (d: Date, h: number, m = 0) => { const x = new Date(d); x.setHours(h, m, 0, 0); return x.getTime(); };

export async function refreshNotices() {
  const app = android();
  if (!app?.setNotices) return;
  const prefs = getPrefs();
  const now = Date.now();
  const list: Notice[] = [];
  let id = 1;
  if (prefs.dueAlarm !== false) {
    const tasks = await getJSON<{ title: string; done: boolean; due_date?: string | null; course: string }[]>("/tasks").catch(() => []);
    for (const t of tasks) {
      if (t.done || !t.due_date) continue;
      const due = new Date(t.due_date + "T00:00:00");
      const eve = new Date(due); eve.setDate(eve.getDate() - 1);
      list.push({ id: id++, title: `내일 마감: ${t.title}`, text: `${t.course} · 끝냈으면 앱에서 체크해요`, at: at(eve, 20), open: "tasks" });
      list.push({ id: id++, title: `오늘 마감: ${t.title}`, text: t.course, at: at(due, 8), open: "tasks" });
    }
  }
  if (prefs.classAlarm !== false) {
    const rows = await getJSON<{ course: string; weekday: number; start: string; place: string }[]>("/timetable").catch(() => []);
    for (let d = 0; d < 7; d++) {
      const day = new Date(now); day.setDate(day.getDate() + d);
      const wd = (day.getDay() + 6) % 7;
      for (const r of rows.filter((x) => x.weekday === wd)) {
        const [h, m] = r.start.split(":").map(Number);
        list.push({ id: id++, title: `곧 ${r.course} 수업`, text: `${r.start}${r.place ? ` · ${r.place}` : ""} · 눌러서 녹음 준비`, at: at(day, h, m) - 5 * 60000, open: "timetable" });
      }
    }
  }
  app.setNotices(JSON.stringify(list.filter((n) => n.at > now).slice(0, 60)));
}
