import SwiftUI

/// 오른쪽 아래 모서리가 접힌 종이 모양
struct FoldedPaper: Shape {
    var fold: CGFloat = 18

    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.minX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - fold))
        path.addLine(to: CGPoint(x: rect.maxX - fold, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.maxY))
        path.closeSubpath()
        return path
    }
}

/// 접힌 모서리의 뒷면 삼각형
struct FoldCorner: Shape {
    var fold: CGFloat = 18

    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.maxX, y: rect.maxY - fold))
        path.addLine(to: CGPoint(x: rect.maxX - fold, y: rect.maxY - fold))
        path.addLine(to: CGPoint(x: rect.maxX - fold, y: rect.maxY))
        path.closeSubpath()
        return path
    }
}

/// 필기 한 장을 포스트잇으로 그린다.
struct StickyNote: View {
    let annotation: Annotation
    let number: Int
    var isSelected = false

    var body: some View {
        let type = annotation.type
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 5) {
                Image(systemName: type.symbol)
                    .font(.caption.weight(.bold))
                Text(type.label)
                    .font(.caption.weight(.heavy))
                Spacer(minLength: 4)
                if number > 0 {
                    Text("\(number)")
                        .font(.caption2.weight(.heavy))
                        .foregroundStyle(.white)
                        .frame(width: 20, height: 20)
                        .background(type.inkColor, in: Circle())
                }
            }
            .foregroundStyle(type.inkColor)

            Text(annotation.text)
                .font(.system(.subheadline, design: .rounded).weight(.medium))
                .foregroundStyle(Theme.noteInk)
                .lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)

            if type == .tip {
                Text("교수님 말씀이 아니라 AI가 덧붙인 내용이에요")
                    .font(.caption2)
                    .foregroundStyle(Theme.noteInk.opacity(0.5))
            }
            if annotation.editedByUser {
                Label("직접 수정함", systemImage: "pencil")
                    .font(.caption2)
                    .foregroundStyle(Theme.noteInk.opacity(0.5))
            }
        }
        .padding(.horizontal, 14)
        .padding(.top, 16)
        .padding(.bottom, 20)
        .frame(maxWidth: .infinity, minHeight: 118, alignment: .topLeading)
        .background {
            ZStack {
                FoldedPaper()
                    .fill(LinearGradient(colors: [type.noteColor.opacity(0.92), type.noteColor],
                                         startPoint: .top, endPoint: .bottom))
                FoldCorner()
                    .fill(.black.opacity(0.10))
            }
            .shadow(color: .black.opacity(isSelected ? 0.22 : 0.12), radius: isSelected ? 12 : 4,
                    x: 0, y: isSelected ? 10 : 3)
        }
        .overlay(alignment: .top) {
            // 위쪽에 붙인 반투명 테이프
            RoundedRectangle(cornerRadius: 2)
                .fill(.white.opacity(0.55))
                .frame(width: 52, height: 16)
                .rotationEffect(.degrees(-annotation.tilt * 1.5))
                .offset(y: -7)
                .shadow(color: .black.opacity(0.05), radius: 1)
        }
        .rotationEffect(.degrees(isSelected ? 0 : annotation.tilt))
        .scaleEffect(isSelected ? 1.04 : 1)
        .animation(.spring(response: 0.35, dampingFraction: 0.65), value: isSelected)
    }
}

/// 새 포스트잇이 위에서 내려와 "툭" 붙는 등장 효과
struct StickOnModifier: ViewModifier {
    let progress: Double

    func body(content: Content) -> some View {
        content
            .scaleEffect(1 + 0.25 * (1 - progress))
            .rotationEffect(.degrees(10 * (1 - progress)))
            .offset(y: -40 * (1 - progress))
            .opacity(progress)
    }
}

extension AnyTransition {
    static var stickOn: AnyTransition {
        .asymmetric(
            insertion: .modifier(active: StickOnModifier(progress: 0), identity: StickOnModifier(progress: 1)),
            removal: .scale(scale: 0.6).combined(with: .opacity)
        )
    }
}

/// 필기가 없을 때 보여 주는 점선 포스트잇
struct EmptyNote: View {
    let message: String

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "note.text.badge.plus")
                .font(.title2)
                .symbolEffect(.pulse, options: .repeating)
            Text(message)
                .font(.footnote.weight(.medium))
                .multilineTextAlignment(.center)
        }
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, minHeight: 118)
        .background {
            RoundedRectangle(cornerRadius: 6)
                .strokeBorder(style: StrokeStyle(lineWidth: 1.5, dash: [6, 5]))
                .foregroundStyle(.secondary.opacity(0.5))
        }
    }
}
