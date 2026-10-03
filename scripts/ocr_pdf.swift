// macOS-native OCR for image-only PDFs; no cloud calls or Python OCR stack.
import AppKit
import PDFKit
import Vision

guard CommandLine.arguments.count == 2,
      let document = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[1])) else {
    fputs("Cannot read PDF\n", stderr)
    exit(1)
}
for i in 0..<document.pageCount {
    guard let page = document.page(at: i) else { continue }
    let image = page.thumbnail(of: NSSize(width: 1800, height: 2400), for: .mediaBox)
    guard let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["es-ES", "en-US", "pt-PT"]
    request.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: cg).perform([request])
    let rows = (request.results ?? []).sorted {
        if abs($0.boundingBox.midY - $1.boundingBox.midY) < 0.006 {
            return $0.boundingBox.minX < $1.boundingBox.minX
        }
        return $0.boundingBox.midY > $1.boundingBox.midY
    }
    for row in rows {
        if let text = row.topCandidates(1).first?.string { print(text) }
    }
}
