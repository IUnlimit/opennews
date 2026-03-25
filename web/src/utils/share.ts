/**
 * 分享工具 — DOM 截图 + 分享/下载
 */
import { toPng } from 'html-to-image'

/**
 * 将目标 DOM 节点导出为 PNG Blob。
 */
export async function domToPngBlob(el: HTMLElement): Promise<Blob> {
  const dataUrl = await toPng(el, {
    pixelRatio: 2,
    backgroundColor: '#f5f6f8',
    cacheBust: true,
  })
  const res = await fetch(dataUrl)
  return res.blob()
}

/**
 * 生成文件名。
 */
function makeFileName(): string {
  const now = new Date()
  const ts = now.toISOString().replace(/[:.]/g, '-').slice(0, 19)
  return `opennews-share-${ts}.png`
}

/**
 * 尝试使用 Web Share API 分享图片，不支持则回退下载。
 */
export async function shareOrDownload(blob: Blob): Promise<void> {
  const file = new File([blob], makeFileName(), { type: 'image/png' })

  // 优先尝试 Web Share API（移动端）
  if (navigator.share && navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file] })
      return
    } catch {
      // 用户取消或失败，回退下载
    }
  }

  // 回退：下载
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = makeFileName()
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
