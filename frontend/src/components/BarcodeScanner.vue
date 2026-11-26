<!--
  Live barcode scan from the back camera. Starts only when tapped (the permission prompt then makes sense), reads
  about eight frames a second, and emits `code` ({code, kind}) once two frames in a row agree on a valid barcode.
  The camera is released as soon as a code is read, the page is hidden or left.
  Problems (no https, permission denied, no camera, camera busy) are explained here; the page around it always has
  the typed-number and photo fallbacks.
-->
<template>
  <div class="scanner">
    <div v-show="live" class="viewport">
      <video ref="video" playsinline muted autoplay disablepictureinpicture aria-label="Camera preview" />
      <div class="aim" aria-hidden="true" />
      <p class="hint" aria-live="polite">{{ state === 'starting' ? 'Starting the camera…' : 'Hold the barcode inside the box' }}</p>
    </div>

    <button v-if="live" type="button" class="btn btn-soft btn-block" @click="stop">Stop camera</button>
    <button v-else type="button" class="btn btn-primary btn-block" :disabled="disabled || blocked" @click="start">
      <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" d="M4 8V5h3M17 5h3v3M20 16v3h-3M7 19H4v-3M7 9v6M10 9v6M13 9v6M16 9v6"/></svg>
      Scan with camera
    </button>

    <p v-if="problem" class="notice notice-warn small" role="status">{{ PROBLEMS[problem] }}</p>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { agree, pickCode } from '../lib/barcode'
import { cameraBlocker, cameraProblem, getDetector, openCamera } from '../lib/scanner'

defineProps({ disabled: Boolean })
const emit = defineEmits(['code'])

const PROBLEMS = {
  insecure: 'The camera only works on a secure page (https). Type the number or pick a photo of the barcode instead.',
  unsupported: "This browser can't use the camera here. Type the number or pick a photo of the barcode instead.",
  denied: 'Camera access is turned off for this site. On iPhone: tap aA in the address bar › Website Settings › Camera › Allow, then try again. Or type the number or pick a photo.',
  nocamera: 'No camera was found. Type the number or pick a photo of the barcode instead.',
  busy: 'The camera is in use by another app or tab. Close it and try again.',
  decoder: "The barcode reader didn't load. Check your connection and try again, or type the number.",
  error: "The camera didn't start. Try again, or type the number or pick a photo.",
}

const video = ref(null)
const state = ref('idle') // idle | starting | scanning
const problem = ref('')
const live = computed(() => state.value !== 'idle')
const blocked = computed(() => problem.value === 'insecure' || problem.value === 'unsupported')

let stream = null
let timer = null
let run = 0 // bumped on every start/stop, so a slow start that was cancelled stops itself
let canvas = null

onMounted(() => { problem.value = cameraBlocker() || '' })

async function start() {
  problem.value = cameraBlocker() || ''
  if (problem.value) return
  const mine = ++run
  state.value = 'starting'
  try {
    const s = await openCamera() // first, straight from the tap: the permission prompt shows now
    if (mine !== run) return s.getTracks().forEach((t) => t.stop())
    stream = s
  } catch (e) {
    state.value = 'idle'
    problem.value = cameraProblem(e)
    return
  }
  let det
  try {
    det = await getDetector()
  } catch {
    stop()
    problem.value = 'decoder'
    return
  }
  if (mine !== run) return
  video.value.srcObject = stream
  try {
    await video.value.play()
  } catch { /* autoplay of a muted inline video is allowed; frames still arrive */ }
  state.value = 'scanning'
  let seen = { last: null, count: 0 }

  const tick = async () => {
    if (mine !== run) return
    const v = video.value
    if (v && v.readyState >= 2 && v.videoWidth) {
      try {
        seen = agree(seen, pickCode(await det.detect(frame(v))))
      } catch { /* one bad frame: keep going */ }
      if (mine !== run) return
      if (seen.accepted) {
        stop()
        emit('code', seen.accepted)
        return
      }
    }
    timer = setTimeout(tick, 120)
  }
  tick()
}

/** The frame, scaled down to at most 1280 px wide: enough for a retail barcode, quick enough for a phone. */
function frame(v) {
  const k = Math.min(1, 1280 / v.videoWidth)
  canvas ??= document.createElement('canvas')
  canvas.width = Math.round(v.videoWidth * k)
  canvas.height = Math.round(v.videoHeight * k)
  canvas.getContext('2d', { willReadFrequently: true }).drawImage(v, 0, 0, canvas.width, canvas.height)
  return canvas
}

function stop() {
  run++
  clearTimeout(timer)
  stream?.getTracks().forEach((t) => t.stop())
  stream = null
  if (video.value) video.value.srcObject = null
  state.value = 'idle'
}

function onHidden() {
  if (document.hidden && live.value) stop()
}
document.addEventListener('visibilitychange', onHidden)
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onHidden)
  stop()
})

defineExpose({ start, stop })
</script>

<style scoped>
.scanner { display: grid; gap: 10px; }
.viewport { position: relative; overflow: hidden; border-radius: 12px; background: #000; aspect-ratio: 4 / 3; }
video { width: 100%; height: 100%; object-fit: cover; display: block; }
.aim {
  position: absolute; left: 10%; right: 10%; top: 32%; bottom: 32%;
  border: 2px solid rgba(255, 255, 255, 0.9); border-radius: 10px;
  box-shadow: 0 0 0 100vmax rgba(0, 0, 0, 0.35);
}
.hint {
  position: absolute; left: 0; right: 0; bottom: 10px; margin: 0; text-align: center;
  color: #fff; font-size: 0.9rem; text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
}
</style>
