import SwiftUI
import UIKit

/// 앱 전체의 색과 모양. 종이 노트 느낌의 따뜻한 배경 + 인디고 포인트 색.
enum Theme {
    static let accent = Color(red: 0.36, green: 0.33, blue: 0.92)
    static let record = Color(red: 0.94, green: 0.27, blue: 0.29)

    /// 화면 배경: 밝을 때는 미색 종이, 어두울 때는 짙은 회색
    static let paper = adaptive(light: UIColor(red: 0.965, green: 0.953, blue: 0.933, alpha: 1),
                                dark: UIColor(red: 0.08, green: 0.08, blue: 0.09, alpha: 1))
    /// 카드 배경
    static let card = adaptive(light: .white, dark: UIColor(red: 0.15, green: 0.15, blue: 0.17, alpha: 1))
    /// 포스트잇 위 글자는 종이색이 늘 밝으므로 다크 모드에서도 검정
    static let noteInk = Color(red: 0.13, green: 0.12, blue: 0.11)

    static func adaptive(light: UIColor, dark: UIColor) -> Color {
        Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? dark : light })
    }
}

extension AnnotationType {
    /// 포스트잇 종이색 (파스텔)
    var noteColor: Color {
        switch self {
        case .explanation: Color(red: 1.00, green: 0.93, blue: 0.58)
        case .example: Color(red: 0.76, green: 0.94, blue: 0.80)
        case .emphasis: Color(red: 1.00, green: 0.84, blue: 0.66)
        case .exam: Color(red: 1.00, green: 0.75, blue: 0.80)
        case .notice: Color(red: 0.85, green: 0.82, blue: 1.00)
        }
    }

    /// 형광펜·아이콘에 쓰는 진한 색
    var inkColor: Color {
        switch self {
        case .explanation: Color(red: 0.85, green: 0.62, blue: 0.00)
        case .example: Color(red: 0.13, green: 0.62, blue: 0.33)
        case .emphasis: Color(red: 0.93, green: 0.45, blue: 0.07)
        case .exam: Color(red: 0.88, green: 0.18, blue: 0.33)
        case .notice: Color(red: 0.42, green: 0.33, blue: 0.90)
        }
    }
}

extension Annotation {
    /// 포스트잇마다 조금씩 다른 기울기. id로 정해서 다시 그려도 같은 각도가 나온다.
    var tilt: Double {
        [-2.2, 1.6, -1.0, 2.4, -0.5, 1.1][abs(id) % 6]
    }
}

/// 눌렀을 때 살짝 줄어드는 버튼
struct PressableStyle: ButtonStyle {
    var scale: CGFloat = 0.96

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? scale : 1)
            .animation(.spring(response: 0.25, dampingFraction: 0.7), value: configuration.isPressed)
    }
}

/// 둥근 카드 배경
struct CardBackground: ViewModifier {
    var padding: CGFloat = 16

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(Theme.card, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .shadow(color: .black.opacity(0.06), radius: 10, y: 4)
    }
}

extension View {
    func card(padding: CGFloat = 16) -> some View { modifier(CardBackground(padding: padding)) }
}
