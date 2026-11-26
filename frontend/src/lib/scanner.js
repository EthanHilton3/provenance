/**
 * Reading barcodes in the browser: the camera, and a photo as the fallback.
 *
 * The decoder is the W3C BarcodeDetector: the browser's own where it has one with the retail formats (Android
 * Chrome), else the barcode-detector ponyfill, which runs zxing-cpp compiled to WebAssembly (the decoder the barcode
 * test used). iPhone Safari has no BarcodeDetector, so it always takes the ponyfill. The ~1 MB .wasm file is served
 * from this app's own build (the library's default is a CDN) and loaded only when the scanner is first used.
 *
 * The camera needs a secure page: https, or localhost on the same machine. A phone opening the dev server by the
 * computer's address over plain http gets no camera; typing the number and picking a photo still work.
 */
import { pickCode } from './barcode.js'

export const FORMATS = ['ean_13', 'upc_a', 'upc_e', 'ean_8']
let detector = null

export function getDetector() {
  detector ??= (async () => {
    const Native = globalThis.BarcodeDetector
    if (Native) {
      try {
        const supported = await Native.getSupportedFormats()
        if (FORMATS.every((f) => supported.includes(f))) return new Native({ formats: FORMATS })
      } catch { /* fall through to the ponyfill */ }
    }
    const [{ BarcodeDetector, prepareZXingModule }, { default: wasmUrl }] = await Promise.all([
      import('barcode-detector/ponyfill'),
      import('zxing-wasm/reader/zxing_reader.wasm?url'),
    ])
    await prepareZXingModule({
      overrides: { locateFile: (path, prefix) => (path.endsWith('.wasm') ? wasmUrl : prefix + path) },
      fireImmediately: true,
    })
    return new BarcodeDetector({ formats: FORMATS })
  })().catch((e) => {
    detector = null // a failed load (offline) can be tried again
    throw e
  })
  return detector
}

/** Why the camera can't be used before even asking: 'insecure' (http on another device), 'unsupported', or null. */
export function cameraBlocker() {
  if (!globalThis.isSecureContext) return 'insecure'
  if (!navigator.mediaDevices?.getUserMedia) return 'unsupported'
  return null
}

/** A getUserMedia error -> 'denied' | 'nocamera' | 'busy' | 'error'. */
export function cameraProblem(err) {
  switch (err?.name) {
    case 'NotAllowedError': case 'SecurityError': case 'PermissionDeniedError': return 'denied'
    case 'NotFoundError': case 'OverconstrainedError': case 'DevicesNotFoundError': return 'nocamera'
    case 'NotReadableError': case 'TrackStartError': case 'AbortError': return 'busy'
    default: return 'error'
  }
}

/** The back camera, as sharp as the phone offers (1D barcodes need the pixels). */
export function openCamera() {
  return navigator.mediaDevices.getUserMedia({
    audio: false,
    video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
  })
}

function scaled(img, max) {
  const w = img.naturalWidth || img.width
  const h = img.naturalHeight || img.height
  const k = max / Math.max(w, h)
  if (k >= 1) return null
  const c = document.createElement('canvas')
  c.width = Math.round(w * k)
  c.height = Math.round(h * k)
  c.getContext('2d').drawImage(img, 0, 0, c.width, c.height)
  return c
}

/**
 * A barcode from a photo file: {code, kind} or null. Tries the full photo, then smaller copies (the barcode test
 * read one more photo after a resize). Throws if the photo can't be opened (HEIC outside Safari, a broken file).
 */
export async function decodePhoto(file) {
  const det = await getDetector()
  const url = URL.createObjectURL(file)
  try {
    const img = new Image()
    img.src = url
    await img.decode()
    for (const source of [img, scaled(img, 1600), scaled(img, 1000)]) {
      if (!source) continue
      const hit = pickCode(await det.detect(source))
      if (hit) return hit
    }
    return null
  } finally {
    URL.revokeObjectURL(url)
  }
}
