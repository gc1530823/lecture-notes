import PDFKit
import SwiftUI

/// 강의자료 한 페이지 + 필기가 붙은 문단의 형광펜과 포스트잇 깃발.
struct PageCanvasView: View {
    let page: Page
    let pdfPage: PDFPage?
    let annotations: [Annotation]
    @Binding var selectedAnnotationID: Int?

    @State private var image: UIImage?

    var body: some View {
        ZStack {
            Color.white
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .transition(.opacity)
            } else {
                ProgressView()
            }
        }
        .aspectRatio(page.aspectRatio, contentMode: .fit)
        .overlay { GeometryReader { proxy in marks(in: proxy.size) } }
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(.black.opacity(0.06))
        }
        .shadow(color: .black.opacity(0.10), radius: 14, y: 6)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .task(id: page.id) {
            let rendered = await PageRenderer.shared.image(for: pdfPage, pageNo: page.pageNo)
            withAnimation(.easeOut(duration: 0.25)) { image = rendered }
        }
    }

    /// 깃발 번호는 아래 포스트잇과 같게, 이 페이지에서 들어온 순서대로 1부터 매긴다.
    @ViewBuilder
    private func marks(in size: CGSize) -> some View {
        let numbered = Array(annotations.enumerated())
        let blocks = Dictionary(uniqueKeysWithValues: page.blocks.map { ($0.id, $0) })
        let marked = page.blocks.filter { block in annotations.contains { $0.blockId == block.id } }

        ForEach(marked) { block in
            let type = annotations.last { $0.blockId == block.id }?.type ?? .explanation
            let isSelected = annotations.contains { $0.blockId == block.id && $0.id == selectedAnnotationID }
            Highlighter(color: type.inkColor, emphasized: isSelected)
                .frame(width: block.w * size.width + 8, height: block.h * size.height * 0.9)
                .position(x: (block.x + block.w / 2) * size.width, y: (block.y + block.h * 0.55) * size.height)
        }

        ForEach(numbered, id: \.element.id) { index, annotation in
            Button {
                withAnimation(.spring(response: 0.35, dampingFraction: 0.7)) {
                    selectedAnnotationID = selectedAnnotationID == annotation.id ? nil : annotation.id
                }
            } label: {
                NoteFlag(annotation: annotation, number: index + 1, isSelected: selectedAnnotationID == annotation.id)
            }
            .buttonStyle(PressableStyle(scale: 0.85))
            .position(flagPosition(for: annotation, index: index, blocks: blocks, in: size))
            .transition(.scale(scale: 0.2).combined(with: .opacity))
        }
    }

    private func flagPosition(for annotation: Annotation, index: Int, blocks: [Int: Block], in size: CGSize) -> CGPoint {
        guard let blockID = annotation.blockId, let block = blocks[blockID] else {
            // 문단에 붙지 않은 필기는 페이지 아래 여백에 나란히 둔다
            let unattached = annotations.prefix(index).filter { $0.blockId == nil || blocks[$0.blockId!] == nil }.count
            return CGPoint(x: min(26 + CGFloat(unattached) * 34, size.width - 20), y: size.height - 18)
        }
        // 같은 문단에 필기가 여러 개면 깃발을 옆으로 이어 붙인다
        let sameBlockBefore = annotations.prefix(index).filter { $0.blockId == blockID }.count
        let x = min(block.x + block.w, 1) * size.width + 20 + CGFloat(sameBlockBefore) * 30
        return CGPoint(x: min(x, size.width - 18), y: max((block.y + block.h / 2) * size.height, 16))
    }
}

/// 문단에 형광펜이 왼쪽에서 오른쪽으로 그어지는 효과
private struct Highlighter: View {
    let color: Color
    let emphasized: Bool
    @State private var drawn = false

    var body: some View {
        RoundedRectangle(cornerRadius: 4, style: .continuous)
            .fill(color.opacity(emphasized ? 0.36 : 0.22))
            .blendMode(.multiply)
            .scaleEffect(x: drawn ? 1 : 0.001, anchor: .leading)
            .rotationEffect(.degrees(-0.6))
            .onAppear {
                withAnimation(.easeOut(duration: 0.55).delay(0.1)) { drawn = true }
            }
            .animation(.easeInOut(duration: 0.25), value: emphasized)
            .allowsHitTesting(false)
    }
}

/// 페이지 위의 작은 포스트잇 깃발 (번호 표시)
private struct NoteFlag: View {
    let annotation: Annotation
    let number: Int
    let isSelected: Bool

    var body: some View {
        Text("\(number)")
            .font(.system(size: 12, weight: .heavy, design: .rounded))
            .foregroundStyle(Theme.noteInk)
            .frame(width: 24, height: 22)
            .background {
                FoldedPaper(fold: 6)
                    .fill(annotation.type.noteColor)
                    .overlay(alignment: .leading) {
                        Rectangle().fill(annotation.type.inkColor).frame(width: 3)
                    }
                    .clipShape(FoldedPaper(fold: 6))
                    .shadow(color: .black.opacity(0.25), radius: isSelected ? 5 : 1.5, y: isSelected ? 3 : 1)
            }
            .rotationEffect(.degrees(annotation.tilt * 2))
            .scaleEffect(isSelected ? 1.3 : 1)
            .overlay {
                if isSelected {
                    Circle()
                        .stroke(annotation.type.inkColor.opacity(0.5), lineWidth: 2)
                        .frame(width: 40, height: 40)
                        .phaseAnimator([false, true]) { ring, expanded in
                            ring.scaleEffect(expanded ? 1.25 : 0.9).opacity(expanded ? 0 : 1)
                        } animation: { _ in .easeOut(duration: 1.1) }
                }
            }
            .frame(width: 34, height: 34)
            .contentShape(Rectangle())
    }
}

/// PDF 페이지를 이미지로 그려 두고 다시 쓴다.
@MainActor
final class PageRenderer {
    static let shared = PageRenderer()
    private let cache = NSCache<NSString, UIImage>()

    /// 목록 썸네일처럼 PDF 문서를 따로 들고 있지 않을 때: 문서를 열어 둔 채로 그린다
    func image(for document: PDFDocument?, pageIndex: Int, width: CGFloat) async -> UIImage? {
        guard let document, let page = document.page(at: pageIndex) else { return nil }
        return await image(for: page, pageNo: pageIndex + 1, width: width)
    }

    func image(for pdfPage: PDFPage?, pageNo: Int, width: CGFloat = 1200) async -> UIImage? {
        guard let pdfPage else { return nil }
        let name = pdfPage.document?.documentURL?.lastPathComponent ?? "\(ObjectIdentifier(pdfPage).hashValue)"
        let key = "\(name)#\(pageNo)@\(Int(width))" as NSString
        if let cached = cache.object(forKey: key) { return cached }

        let bounds = pdfPage.bounds(for: .cropBox)
        let rotated = pdfPage.rotation % 180 != 0
        let aspect = rotated ? bounds.height / bounds.width : bounds.width / bounds.height
        let image = pdfPage.thumbnail(of: CGSize(width: width, height: width / aspect), for: .cropBox)
        cache.setObject(image, forKey: key)
        return image
    }
}
