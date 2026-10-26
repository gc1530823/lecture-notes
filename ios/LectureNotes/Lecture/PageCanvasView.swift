import PDFKit
import SwiftUI

/// 강의자료 한 페이지 + 필기가 붙은 블록 표시(테두리와 번호 배지).
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
                Image(uiImage: image).resizable()
            } else {
                ProgressView()
            }
        }
        .aspectRatio(page.aspectRatio, contentMode: .fit)
        .overlay { GeometryReader { proxy in marks(in: proxy.size) } }
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .shadow(color: .black.opacity(0.15), radius: 4, y: 2)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .task(id: page.id) { image = await PageRenderer.shared.image(for: pdfPage, pageNo: page.pageNo) }
    }

    /// 필기 번호는 목록과 같게, 이 페이지에서 들어온 순서대로 1부터 매긴다.
    @ViewBuilder
    private func marks(in size: CGSize) -> some View {
        let numbered = Array(annotations.enumerated())
        let blocks = Dictionary(uniqueKeysWithValues: page.blocks.map { ($0.id, $0) })

        ForEach(page.blocks.filter { block in annotations.contains { $0.blockId == block.id } }) { block in
            let color = annotations.first { $0.blockId == block.id }?.type.color ?? .blue
            RoundedRectangle(cornerRadius: 3)
                .fill(color.opacity(0.10))
                .stroke(color.opacity(0.7), lineWidth: 1.5)
                .frame(width: block.w * size.width + 6, height: block.h * size.height + 4)
                .position(x: (block.x + block.w / 2) * size.width, y: (block.y + block.h / 2) * size.height)
        }

        ForEach(numbered, id: \.element.id) { index, annotation in
            let point = badgePosition(for: annotation, index: index, blocks: blocks, in: size)
            Button { selectedAnnotationID = annotation.id } label: {
                Text("\(index + 1)")
                    .font(.caption2.bold())
                    .foregroundStyle(.white)
                    .frame(width: 20, height: 20)
                    .background(annotation.type.color, in: Circle())
                    .overlay {
                        if selectedAnnotationID == annotation.id {
                            Circle().stroke(.primary, lineWidth: 2).frame(width: 26, height: 26)
                        }
                    }
            }
            .position(point)
        }
    }

    private func badgePosition(for annotation: Annotation, index: Int, blocks: [Int: Block], in size: CGSize) -> CGPoint {
        guard let blockID = annotation.blockId, let block = blocks[blockID] else {
            // 블록에 붙지 않은 필기는 페이지 아래 여백에 나란히 둔다
            return CGPoint(x: min(16 + CGFloat(index) * 24, size.width - 12), y: size.height - 14)
        }
        // 같은 블록에 필기가 여러 개면 배지를 옆으로 조금씩 밀어서 겹치지 않게 한다
        let sameBlockBefore = annotations.prefix(index).filter { $0.blockId == blockID }.count
        let x = min(block.x + block.w, 1) * size.width + 10 + CGFloat(sameBlockBefore) * 22
        return CGPoint(x: min(x, size.width - 12), y: max(block.y * size.height, 12))
    }
}

/// PDF 페이지를 이미지로 그려 두고 다시 쓴다.
@MainActor
final class PageRenderer {
    static let shared = PageRenderer()
    private let cache = NSCache<NSString, UIImage>()

    func image(for pdfPage: PDFPage?, pageNo: Int) async -> UIImage? {
        guard let pdfPage, let document = pdfPage.document else { return nil }
        let key = "\(document.documentURL?.lastPathComponent ?? "")#\(pageNo)" as NSString
        if let cached = cache.object(forKey: key) { return cached }

        let bounds = pdfPage.bounds(for: .cropBox)
        let rotated = pdfPage.rotation % 180 != 0
        let aspect = rotated ? bounds.height / bounds.width : bounds.width / bounds.height
        let width: CGFloat = 1200
        let image = pdfPage.thumbnail(of: CGSize(width: width, height: width / aspect), for: .cropBox)
        cache.setObject(image, forKey: key)
        return image
    }
}
