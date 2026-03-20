import { onUnmounted, ref } from 'vue'

const AUTO_REFRESH_INTERVAL = 30_000
const AUTO_REFRESH_SECONDS = AUTO_REFRESH_INTERVAL / 1000

export function useAutoRefresh(callback: () => Promise<void>) {
  let refreshTimer: ReturnType<typeof setInterval> | null = null
  let countdownTimer: ReturnType<typeof setInterval> | null = null
  const secondsLeft = ref(AUTO_REFRESH_SECONDS)

  const start = () => {
    stop()
    secondsLeft.value = AUTO_REFRESH_SECONDS
    refreshTimer = setInterval(async () => {
      await callback()
      secondsLeft.value = AUTO_REFRESH_SECONDS
    }, AUTO_REFRESH_INTERVAL)
    countdownTimer = setInterval(() => {
      if (secondsLeft.value <= 1) {
        secondsLeft.value = AUTO_REFRESH_SECONDS
      } else {
        secondsLeft.value -= 1
      }
    }, 1000)
  }

  const stop = () => {
    if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
    if (countdownTimer) {
      clearInterval(countdownTimer)
      countdownTimer = null
    }
  }

  onUnmounted(stop)

  return { start, stop, secondsLeft }
}
