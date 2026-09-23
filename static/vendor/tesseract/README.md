# Vendored OCR engine (free, runs in the browser)

Used only by the race-weekend screenshot importer. Loaded on demand; nothing here runs during normal navigation.
Screenshots are processed in the visitor's browser and never uploaded.

| File | Source | Licence |
|---|---|---|
| tesseract.min.js, worker.min.js | tesseract.js 5.1.1 (npm) | Apache-2.0 |
| tesseract-core-lstm.wasm.js, tesseract-core-simd-lstm.wasm.js | tesseract.js-core 5.1.1 (npm) | Apache-2.0 |
| lang/eng.traineddata.gz | @tesseract.js-data/eng 1.0.0, 4.0.0_best_int | Apache-2.0 (Tesseract tessdata) |

To update: `npm install tesseract.js@<version> @tesseract.js-data/eng` and copy the same files.
