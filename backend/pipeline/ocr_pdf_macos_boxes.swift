// Like ocr_pdf_macos.swift, but prints each recognized line with its position, for tables
// whose columns OCR reads one after another: "page<TAB>x<TAB>y<TAB>width<TAB>height<TAB>text",
// with x/y the line's lower-left corner as a fraction of the page (y grows upwards).
import AppKit
import PDFKit
import Vision

guard CommandLine.arguments.count == 2,
      let document = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[1])) else {
    fputs("usage: swift ocr_pdf_macos_boxes.swift path/to/file.pdf\n", stderr)
    exit(2)
}

for pageIndex in 0..<document.pageCount {
    guard let page = document.page(at: pageIndex) else { continue }
    let bounds = page.bounds(for: .mediaBox)
    let scale = 3200 / max(bounds.width, bounds.height)
    let image = page.thumbnail(of: NSSize(width: bounds.width * scale, height: bounds.height * scale), for: .mediaBox)
    guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        continue
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    do {
        try VNImageRequestHandler(cgImage: cgImage).perform([request])
        for observation in request.results ?? [] {
            if let candidate = observation.topCandidates(1).first {
                let box = observation.boundingBox
                let text = candidate.string.replacingOccurrences(of: "\t", with: " ")
                print(String(format: "%d\t%.4f\t%.4f\t%.4f\t%.4f\t%@", pageIndex + 1, box.minX, box.minY,
                             box.width, box.height, text))
            }
        }
    } catch {
        fputs("OCR failed on page \(pageIndex + 1): \(error)\n", stderr)
        exit(1)
    }
}
