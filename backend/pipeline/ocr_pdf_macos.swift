import AppKit
import PDFKit
import Vision

guard CommandLine.arguments.count == 2,
      let document = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[1])) else {
    fputs("usage: swift ocr_pdf_macos.swift path/to/file.pdf\n", stderr)
    exit(2)
}

for pageIndex in 0..<document.pageCount {
    guard let page = document.page(at: pageIndex) else { continue }
    let image = page.thumbnail(of: NSSize(width: 2400, height: 3200), for: .mediaBox)
    guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        continue
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    do {
        try VNImageRequestHandler(cgImage: cgImage).perform([request])
        for observation in request.results ?? [] {
            if let candidate = observation.topCandidates(1).first {
                print(candidate.string)
            }
        }
    } catch {
        fputs("OCR failed on page \(pageIndex + 1): \(error)\n", stderr)
        exit(1)
    }
}
