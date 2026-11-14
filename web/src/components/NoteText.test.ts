import { describe, expect, it } from "vitest";
import { splitNote } from "./NoteText";

describe("splitNote", () => {
  it("제목: 낱말 나열 → 제목 + 칩", () => {
    const n = splitNote("교착 상태 네 조건: 상호 배제·점유와 대기·비선점·순환 대기");
    expect(n.title).toBe("교착 상태 네 조건");
    expect(n.chips).toBe(true);
    expect(n.items).toEqual(["상호 배제", "점유와 대기", "비선점", "순환 대기"]);
  });
  it("Q/A 와 (1)(2) 번호 → 질문 제목 + 앞 문장 + 목록 + 마무리", () => {
    const n = splitNote("Q. 교착상태 쉽게정리\nA. 교착 상태는 네 가지 조건이 모두 만족될 때 발생해요: (1) 한 번에 하나만 사용할 수 있는 상호 배제, (2) 이미 가진 자원을 놓지 않고 다른 자원을 기다리는 점유와 대기, (3) 다른 프로세스가 가진 자원을 강제로 뺏을 수 없는 비선점, (4) 이런 기다림 관계가 원형으로 이어지는 순환 대기. 이 네 조건이 모두 있을 때만 교착 상태가 생깁니다.");
    expect(n.q).toBe(true);
    expect(n.title).toBe("교착상태 쉽게정리");
    expect(n.intro).toBe("교착 상태는 네 가지 조건이 모두 만족될 때 발생해요");
    expect(n.items).toHaveLength(4);
    expect(n.items[3]).toBe("이런 기다림 관계가 원형으로 이어지는 순환 대기");
    expect(n.outro).toBe("이 네 조건이 모두 있을 때만 교착 상태가 생깁니다.");
  });
  it("시각의 쌍점은 제목으로 자르지 않는다", () => {
    expect(splitNote("수업은 09:00 에 시작한다고 하셨다.").title).toBe("");
  });
  it("과제 공지", () => {
    const n = splitNote("과제 3번: 은행원 알고리즘 손으로 풀기, 다음 주 금요일까지 LMS 제출");
    expect(n.title).toBe("과제 3번");
    expect(n.chips).toBe(false);
  });
});
