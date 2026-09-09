import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useItemImages } from '~/composables/useItemImages'

// Photo staging for the admin listing form (SPEC-037), lifted out of
// AdminItems.vue along with the form itself.
//
// The grid's order IS the listing's order — the first tile becomes the
// storefront thumbnail — so ordering is the substance of these tests, not a
// detail. The other half is object-URL hygiene: a newly picked photo is
// previewed through URL.createObjectURL and the blob stays alive until it is
// revoked, while a stored photo's public URL must never be revoked.

function makeFile(name = 'photo.png'): File {
  return new File(['fake-bytes'], name, { type: 'image/png' })
}

/** Identify each staged photo: a new one by filename, a stored one by its URL. */
function names(images: { kind: string, url: string, file?: File }[]) {
  return images.map(i => (i.kind === 'new' ? i.file!.name : i.url))
}

const STORED = ['https://cdn.test/a.jpg', 'https://cdn.test/b.jpg']

beforeEach(() => {
  // jsdom/Node's URL.createObjectURL rejects File instances built across
  // realms as "not a Blob". A test-environment shim, not a change to what is
  // being asserted.
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-url')
})

describe('composables/useItemImages', () => {
  describe('ordering', () => {
    it('addImages appends to the end, keeping the existing thumbnail first', () => {
      const { images, addImages } = useItemImages()
      addImages([makeFile('a.png'), makeFile('b.png')])

      addImages([makeFile('c.png')])

      expect(names(images.value)).toEqual(['a.png', 'b.png', 'c.png'])
    })

    it('moveImage reorders and can promote a later photo to the thumbnail slot', () => {
      const { images, addImages, moveImage } = useItemImages()
      addImages([makeFile('a.png'), makeFile('b.png'), makeFile('c.png')])

      moveImage(2, 0)

      expect(names(images.value)).toEqual(['c.png', 'a.png', 'b.png'])
    })

    it('moveImage ignores out-of-range targets', () => {
      const { images, addImages, moveImage } = useItemImages()
      addImages([makeFile('a.png'), makeFile('b.png')])

      moveImage(0, -1)
      moveImage(1, 2)

      expect(names(images.value)).toEqual(['a.png', 'b.png'])
    })

    it('a stored photo can be reordered against a newly added one', () => {
      const { images, setFromUrls, addImages, moveImage } = useItemImages()
      setFromUrls(STORED)
      addImages([makeFile('fresh.png')])

      moveImage(2, 0)

      expect(names(images.value)).toEqual(['fresh.png', ...STORED])
    })
  })

  describe('drag and drop', () => {
    it('dropOn moves the dragged photo onto the drop target', () => {
      const { images, addImages, dragIndex, dropOn } = useItemImages()
      addImages([makeFile('a.png'), makeFile('b.png'), makeFile('c.png')])

      dragIndex.value = 0
      dropOn(2)

      expect(names(images.value)).toEqual(['b.png', 'c.png', 'a.png'])
      expect(dragIndex.value).toBeNull()
    })

    it('dropOn does nothing without an active drag, or when dropped on itself', () => {
      const { images, addImages, dragIndex, dropOn } = useItemImages()
      addImages([makeFile('a.png'), makeFile('b.png')])

      dropOn(1)
      expect(names(images.value)).toEqual(['a.png', 'b.png'])

      dragIndex.value = 1
      dropOn(1)
      expect(names(images.value)).toEqual(['a.png', 'b.png'])
    })

    it('onDropFiles ignores a reorder drag, which carries no files', () => {
      const { images, addImages, onDropFiles } = useItemImages()
      addImages([makeFile('a.png')])

      onDropFiles({ dataTransfer: { files: [] } } as unknown as DragEvent)

      expect(names(images.value)).toEqual(['a.png'])
    })

    it('onDropFiles accepts dropped images and rejects other file types', () => {
      const { images, onDropFiles } = useItemImages()
      const pdf = new File(['x'], 'doc.pdf', { type: 'application/pdf' })

      onDropFiles({
        dataTransfer: { files: [makeFile('shot.png'), pdf] }
      } as unknown as DragEvent)

      expect(names(images.value)).toEqual(['shot.png'])
    })

    it('onDropFiles accepts a HEIC photo the browser gives no MIME type for', () => {
      // SPEC-054: Chrome and Firefox report an empty `type` for .heic, so the
      // `type.startsWith('image/')` filter silently swallowed every iPhone
      // photo dropped onto the grid. The extension is the only signal left.
      const { images, onDropFiles } = useItemImages()
      const heic = new File(['x'], 'IMG_0042.HEIC', { type: '' })

      onDropFiles({ dataTransfer: { files: [heic] } } as unknown as DragEvent)

      expect(names(images.value)).toEqual(['IMG_0042.HEIC'])
    })

    it('onDropFiles still rejects a typeless file that is not an image', () => {
      const { images, onDropFiles } = useItemImages()
      const blob = new File(['x'], 'archive.zip', { type: '' })

      onDropFiles({ dataTransfer: { files: [blob] } } as unknown as DragEvent)

      expect(images.value).toEqual([])
    })
  })

  describe('object-URL hygiene', () => {
    it('removeImage drops the photo and revokes its preview URL', () => {
      const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
      const { images, addImages, removeImage } = useItemImages()
      addImages([makeFile('a.png'), makeFile('b.png')])

      removeImage(0)

      expect(names(images.value)).toEqual(['b.png'])
      expect(revoke).toHaveBeenCalledWith('blob:mock-url')
      revoke.mockRestore()
    })

    it('removeImage never revokes a stored photo\'s URL', () => {
      const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
      const { images, setFromUrls, removeImage } = useItemImages()
      setFromUrls(STORED)

      removeImage(0)

      expect(names(images.value)).toEqual([STORED[1]])
      expect(revoke).not.toHaveBeenCalled()
      revoke.mockRestore()
    })

    it('removeImage is a no-op for an index that does not exist', () => {
      const { images, addImages, removeImage } = useItemImages()
      addImages([makeFile('a.png')])

      removeImage(5)

      expect(names(images.value)).toEqual(['a.png'])
    })

    it('releaseImages revokes staged previews but leaves stored URLs alone', () => {
      const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
      const { images, setFromUrls, addImages, releaseImages } = useItemImages()
      setFromUrls(STORED)
      addImages([makeFile('extra.png')])

      releaseImages()

      expect(revoke).toHaveBeenCalledTimes(1)
      expect(revoke).toHaveBeenCalledWith('blob:mock-url')
      expect(images.value).toEqual([])
      revoke.mockRestore()
    })

    it('setFromFiles releases what was staged before replacing it', () => {
      const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
      const { images, addImages, setFromFiles } = useItemImages()
      addImages([makeFile('old.png')])

      setFromFiles([makeFile('new.png')])

      expect(revoke).toHaveBeenCalledTimes(1)
      expect(names(images.value)).toEqual(['new.png'])
      revoke.mockRestore()
    })
  })

  describe('newFiles', () => {
    it('returns only the newly picked Files, in display order', () => {
      const { setFromUrls, addImages, moveImage, newFiles } = useItemImages()
      setFromUrls(STORED)
      addImages([makeFile('one.png'), makeFile('two.png')])
      moveImage(3, 0)

      expect(newFiles().map(f => f.name)).toEqual(['two.png', 'one.png'])
    })

    it('is empty when every staged photo is a stored one', () => {
      const { setFromUrls, newFiles } = useItemImages()
      setFromUrls(STORED)

      expect(newFiles()).toEqual([])
    })
  })
})
