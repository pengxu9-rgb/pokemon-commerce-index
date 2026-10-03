// Image-only OCR. No catalog words, custom vocabulary or verdicts are accepted.
import Foundation
import Vision
import ImageIO

func recognize(_ path: String, _ language: String) throws -> [String: Any] {
    let url = URL(fileURLWithPath: path)
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw NSError(domain: "card-ocr", code: 1)
    }
    var regions: [[String: Any]] = []
    let specs: [(String, CGRect)] = [
        ("header", CGRect(x: 0, y: 0.77, width: 1, height: 0.23)),
        ("footer", CGRect(x: 0, y: 0, width: 1, height: 0.16))
    ]
    for (name, region) in specs {
        let request = VNRecognizeTextRequest()
        request.revision = VNRecognizeTextRequestRevision3
        request.recognitionLevel = .accurate
        request.recognitionLanguages = language == "ja" ? ["ja-JP", "en-US"] : ["en-US"]
        request.usesLanguageCorrection = false
        request.automaticallyDetectsLanguage = false
        request.customWords = []
        request.usesCPUOnly = true
        request.regionOfInterest = region
        let handler = VNImageRequestHandler(cgImage: image, options: [:])
        try handler.perform([request])
        var observations: [[String: Any]] = []
        for observation in request.results ?? [] {
            guard let candidate = observation.topCandidates(1).first else { continue }
            let bounds = observation.boundingBox
            var chars: [[String: Any]] = []
            for index in candidate.string.indices {
                let next = candidate.string.index(after: index)
                if let region = try? candidate.boundingBox(for: index..<next) {
                    let box = region.boundingBox
                    chars.append(["text": String(candidate.string[index]),
                                  "box": [box.minX, box.minY, box.width, box.height]])
                }
            }
            observations.append(["text": candidate.string, "confidence": candidate.confidence,
                                 "box": [bounds.minX, bounds.minY, bounds.width, bounds.height],
                                 "characters": chars])
        }
        regions.append(["region": name, "roi": [region.minX, region.minY, region.width, region.height],
                        "observations": observations])
    }
    return ["revision": VNRecognizeTextRequestRevision3,
            "os": ProcessInfo.processInfo.operatingSystemVersionString,
            "language": language, "language_correction": false, "custom_words": [],
            "image_size": [image.width, image.height], "regions": regions]
}

while let line = readLine() {
    autoreleasepool {
        var result: [String: Any] = [:]
        var targetID: String? = nil
        do {
            guard let data = line.data(using: .utf8),
                  let item = try JSONSerialization.jsonObject(with: data) as? [String: String],
                  Set(item.keys) == Set(["target_id", "image_path", "language"]),
                  let path = item["image_path"], let language = item["language"],
                  ["ja", "en"].contains(language) else { throw NSError(domain: "card-ocr", code: 2) }
            targetID = item["target_id"]
            result = ["target_id": item["target_id"]!, "status": "recognized",
                      "ocr": try recognize(path, language)]
        } catch {
            let native = error as NSError
            result = ["status": "ocr_failed", "error": String(describing: error),
                      "error_domain": native.domain, "error_code": native.code,
                      "error_description": native.localizedDescription]
            if let targetID = targetID { result["target_id"] = targetID }
        }
        result["reviewed_at"] = ISO8601DateFormatter().string(from: Date())
        if let body = try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]),
           let text = String(data: body, encoding: .utf8) {
            print(text)
            fflush(stdout)
        }
    }
}
