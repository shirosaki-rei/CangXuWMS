<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    shape-rendering="geometricPrecision"
    aria-hidden="true"
  >
    <defs>
      <clipPath :id="clipId">
        <rect x="3" y="3" width="18" height="18" rx="3" />
      </clipPath>
    </defs>
    <!-- 高亮格：AI 推荐 / 已占用的库位 -->
    <rect
      x="12" y="12" width="9" height="9"
      fill="currentColor" :clip-path="`url(#${clipId})`"
    />
    <!-- 库位外框 -->
    <rect
      x="3" y="3" width="18" height="18" rx="3"
      stroke="currentColor" stroke-width="2.2"
    />
    <!-- 内分隔：2×2 -->
    <path d="M12 3v18M3 12h18" stroke="currentColor" stroke-width="2.2" />
  </svg>
</template>

<script setup lang="ts">
import { useId } from 'vue'

withDefaults(defineProps<{ size?: number }>(), { size: 24 })

const clipId = `bm-${useId()}`
</script>
