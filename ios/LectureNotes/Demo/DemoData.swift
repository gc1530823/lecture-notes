import SwiftUI
import UIKit

/// 서버 없이 화면을 띄우기 위한 예시 데이터.
/// 앱을 `-demoScreen list|lecture|recording|summary` 인자로 실행하면 이 데이터로 그 화면을 연다.
/// CI는 이 모드로 시뮬레이터 스크린샷을 찍는다.
enum DemoData {
    static let sessionID = "demo-session"
    static let pdfFileName = "demo-lecture.pdf"
    static let pageSize = CGSize(width: 960, height: 540)

    /// 슬라이드마다 (글자 크기, 문장) 목록. PDF를 그릴 때와 블록 좌표를 만들 때 같은 값을 쓴다.
    static let slides: [[(CGFloat, String)]] = [
        [(40, "경사하강법 (Gradient Descent)"),
         (26, "손실 함수의 기울기 반대 방향으로 이동"),
         (26, "학습률 η가 한 번에 이동하는 크기를 정한다"),
         (26, "θ ← θ − η · ∇L(θ)")],
        [(40, "역전파 (Backpropagation)"),
         (26, "연쇄 법칙으로 각 가중치의 기울기를 계산"),
         (26, "출력층에서 입력층 방향으로 오차를 전달")],
        [(40, "과적합과 정규화"),
         (26, "학습 데이터에만 지나치게 맞춰지는 현상"),
         (26, "L2 정규화, 드롭아웃, 조기 종료")],
    ]

    static var document: LocalDocument {
        let pages = slides.enumerated().map { index, lines in
            Page(id: index + 1, pageNo: index + 1, width: pageSize.width, height: pageSize.height,
                 blocks: lines.enumerated().map { line, item in
                     let rect = lineRect(slide: index, line: line)
                     return Block(id: (index + 1) * 10 + line,
                                  x: rect.minX / pageSize.width, y: rect.minY / pageSize.height,
                                  w: rect.width / pageSize.width, h: rect.height / pageSize.height,
                                  text: item.1)
                 })
        }
        let lecture = LectureDocument(id: "demo-document", title: "머신러닝 3주차", pageCount: pages.count,
                                      keywords: ["경사하강법", "학습률", "역전파"], pages: pages)
        return LocalDocument(document: lecture, pdfFileName: pdfFileName, sessions: [
            SavedSession(id: sessionID, startedAt: Date(timeIntervalSince1970: 1_792_400_000),
                         recordingFileName: "demo.m4a"),
        ])
    }

    static let annotations: [Annotation] = [
        Annotation(id: 1, sessionId: sessionID, pageNo: 1, blockId: 10, type: .example,
                   text: "산에서 눈 감고 가장 가파른 쪽으로 한 걸음씩 내려가는 것과 같음", startMs: 4_000, editedByUser: false),
        Annotation(id: 2, sessionId: sessionID, pageNo: 1, blockId: 12, type: .explanation,
                   text: "η가 너무 크면 최솟값을 지나쳐 발산, 너무 작으면 학습이 매우 느림", startMs: 21_000, editedByUser: false),
        Annotation(id: 3, sessionId: sessionID, pageNo: 1, blockId: 12, type: .exam,
                   text: "중간고사 출제: 학습률이 클 때와 작을 때의 차이", startMs: 38_000, editedByUser: false),
        Annotation(id: 4, sessionId: sessionID, pageNo: 1, blockId: nil, type: .notice,
                   text: "과제 2: 경사하강법 직접 구현, 다음 주 금요일까지", startMs: 55_000, editedByUser: true),
        Annotation(id: 5, sessionId: sessionID, pageNo: 2, blockId: 21, type: .emphasis,
                   text: "결국 연쇄 법칙을 반복해서 쓰는 것뿐 — 꼭 기억", startMs: 80_000, editedByUser: false),
    ]

    static let summary = LectureSummary(
        overview: "경사하강법으로 손실을 줄이는 원리와 학습률의 역할을 다루고, 역전파로 기울기를 계산하는 방법을 배웠다. 학습률이 클 때와 작을 때의 차이는 중간고사에 나온다.",
        pages: [
            PageSummary(pageNo: 1, summary: "기울기 반대 방향으로 조금씩 이동해 손실을 줄인다. 학습률이 이동 크기를 정한다."),
            PageSummary(pageNo: 2, summary: "역전파는 연쇄 법칙을 반복 적용해 출력층에서 입력층으로 기울기를 전달한다."),
        ],
        quiz: [
            QuizItem(pageNo: 1, question: "학습률이 너무 클 때 생기는 현상은?",
                     choices: ["학습이 매우 느려진다", "최솟값을 지나쳐 발산한다", "기울기가 0이 된다", "과적합이 사라진다"],
                     answerIndex: 1, explanation: "한 번에 너무 멀리 이동해서 최솟값을 계속 지나친다."),
            QuizItem(pageNo: 2, question: "역전파가 기울기를 계산할 때 쓰는 원리는?",
                     choices: ["연쇄 법칙", "베이즈 정리", "중심 극한 정리", "라그랑주 승수법"],
                     answerIndex: 0, explanation: "합성 함수의 미분인 연쇄 법칙을 층마다 반복한다."),
        ]
    )

    /// 슬라이드 한 줄이 PDF에서 차지하는 영역 (왼쪽 위 원점)
    static func lineRect(slide: Int, line: Int) -> CGRect {
        let items = slides[slide]
        var y: CGFloat = 60
        for index in 0..<line { y += items[index].0 * 1.3 + (index == 0 ? 36 : 22) }
        let (size, text) = items[line]
        let width = (text as NSString).size(withAttributes: attributes(size: size, bold: line == 0)).width
        return CGRect(x: 64, y: y, width: width, height: size * 1.3)
    }

    static func attributes(size: CGFloat, bold: Bool) -> [NSAttributedString.Key: Any] {
        [.font: UIFont.systemFont(ofSize: size, weight: bold ? .bold : .regular), .foregroundColor: UIColor.black]
    }

    /// 예시 강의자료 PDF를 앱 Documents 폴더에 만든다.
    static func writePDF(to url: URL) {
        let renderer = UIGraphicsPDFRenderer(bounds: CGRect(origin: .zero, size: pageSize))
        let data = renderer.pdfData { context in
            for (index, lines) in slides.enumerated() {
                context.beginPage()
                UIColor(red: 0.16, green: 0.35, blue: 0.75, alpha: 1).setFill()
                UIRectFill(CGRect(x: 0, y: 0, width: pageSize.width, height: 12))
                for (line, item) in lines.enumerated() {
                    let rect = lineRect(slide: index, line: line)
                    (item.1 as NSString).draw(at: rect.origin, withAttributes: attributes(size: item.0, bold: line == 0))
                }
            }
        }
        try? data.write(to: url, options: .atomic)
    }
}
