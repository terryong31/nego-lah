// Photo staging for the admin listing form.
//
// The grid's order IS the listing's order — the first tile becomes the
// storefront thumbnail — so this owns an ordered list rather than a Set, and
// reordering is a first-class operation.
//
// The one thing worth being careful about: a newly picked photo is previewed
// through `URL.createObjectURL`, and the browser holds that blob alive until
// something revokes it. An existing photo is a stored public URL and must NOT
// be revoked. That distinction is what `kind` is for, and why removal goes
// through `removeImage`/`releaseImages` rather than splicing the array.

/**
 * A photo staged in the grid. A `new` one carries the File to upload and an
 * object URL for the preview, which must be revoked when it leaves the list; an
 * `existing` one carries the listing's stored public URL, which must not be.
 */
export type PendingImage
  = | { id: string, kind: 'new', file: File, url: string }
    | { id: string, kind: 'existing', url: string }

// Extensions the browser may hand over with no MIME type at all. Chrome and
// Firefox report `type: ''` for .heic/.heif — the format most phone photos
// actually arrive in — so a `type.startsWith('image/')` filter silently
// swallowed every iPhone photo dropped onto the grid (SPEC-054). The server
// still decides what a file really is; this only decides what to offer it.
const IMAGE_EXTENSIONS = /\.(jpe?g|png|gif|webp|heic|heif|avif|bmp|tiff?)$/i

export function isImageFile(file: File): boolean {
  if (file.type) return file.type.startsWith('image/')
  return IMAGE_EXTENSIONS.test(file.name || '')
}

export function makePendingImage(file: File): PendingImage {
  return {
    id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
    kind: 'new',
    file,
    // Guard for non-browser environments (SSR, test harnesses without the API).
    url: typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : ''
  }
}

export function makeExistingImage(url: string): PendingImage {
  return { id: `existing-${url}`, kind: 'existing', url }
}

export function useItemImages() {
  const images = ref<PendingImage[]>([])
  const dragIndex = ref<number | null>(null)

  /** Revoke a preview URL — only ever the object URLs we created ourselves. */
  function release(img: PendingImage) {
    if (img.kind === 'new' && img.url && typeof URL.revokeObjectURL === 'function') {
      URL.revokeObjectURL(img.url)
    }
  }

  function releaseImages() {
    for (const img of images.value) release(img)
    images.value = []
  }

  function setFromFiles(files: File[]) {
    releaseImages()
    images.value = files.map(makePendingImage)
  }

  function setFromUrls(urls: string[]) {
    releaseImages()
    images.value = urls.map(makeExistingImage)
  }

  function moveImage(from: number, to: number) {
    if (to < 0 || to >= images.value.length) return
    const next = [...images.value]
    const [moved] = next.splice(from, 1)
    if (moved) next.splice(to, 0, moved)
    images.value = next
  }

  function removeImage(index: number) {
    const img = images.value[index]
    if (!img) return
    release(img)
    images.value = images.value.filter((_, i) => i !== index)
  }

  function dropOn(index: number) {
    if (dragIndex.value === null || dragIndex.value === index) return
    moveImage(dragIndex.value, index)
    dragIndex.value = null
  }

  function addImages(newFiles: File[]) {
    images.value = [...images.value, ...newFiles.map(makePendingImage)]
  }

  function onAddFiles(event: Event) {
    const input = event.target as HTMLInputElement
    addImages(Array.from(input.files || []))
    input.value = ''
  }

  function onDropFiles(event: DragEvent) {
    // An in-grid reorder drag has no files attached — let dropOn handle it.
    const dropped = Array.from(event.dataTransfer?.files || []).filter(isImageFile)
    if (dropped.length) addImages(dropped)
  }

  /** The Files behind the currently staged new photos, in display order. */
  function newFiles(): File[] {
    return images.value.flatMap(img => (img.kind === 'new' ? [img.file] : []))
  }

  return {
    images,
    dragIndex,
    releaseImages,
    setFromFiles,
    setFromUrls,
    moveImage,
    removeImage,
    dropOn,
    addImages,
    onAddFiles,
    onDropFiles,
    newFiles
  }
}
