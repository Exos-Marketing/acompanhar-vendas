<script setup lang="ts">
import { computed } from 'vue'
import { useSlideContext } from '@slidev/client'

const { $page, $nav, $frontmatter } = useSlideContext()
const layout = computed(() => $frontmatter?.layout ?? 'default')
const hidden = computed(() => ['cover', 'end'].includes(layout.value))
const chapter = computed(() => $frontmatter?.chapter ?? '')
const total = computed(() => $nav.value.total)
const pct = computed(() => Math.min(100, ($page.value / total.value) * 100))
const pad = (n: number) => String(n).padStart(2, '0')
</script>

<template>
  <div v-if="!hidden" class="chrome">
    <div class="chapter">{{ chapter }}</div>
    <div class="foot">
      <span class="foot-title">__RODAPE__</span>
      <span class="track"><span class="fill" :style="{ width: pct + '%' }" /></span>
      <span class="page">{{ pad($page) }} / {{ pad(total) }}</span>
    </div>
  </div>
</template>

<style scoped>
.chrome {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 10;
}
.brand {
  position: absolute;
  top: 1.05rem;
  left: 3.2rem;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.brand img {
  width: 15px;
  height: 15px;
  object-fit: contain;
}
.brand span {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 0.7rem;
  letter-spacing: 0.14em;
  color: var(--ink);
}
.chapter {
  position: absolute;
  top: 1.12rem;
  left: 3.2rem;
  font-family: var(--font-mono);
  font-size: 0.56rem;
  letter-spacing: 0.26em;
  text-transform: uppercase;
  color: var(--muted);
}
.foot {
  position: absolute;
  left: 3.2rem;
  right: 3.2rem;
  bottom: 1rem;
  display: flex;
  align-items: center;
  gap: 1rem;
  font-family: var(--font-mono);
  font-size: 0.52rem;
  letter-spacing: 0.12em;
  color: var(--faint);
}
.foot-title {
  text-transform: uppercase;
}
.track {
  flex: 1;
  height: 1.5px;
  background: var(--border);
  position: relative;
  overflow: hidden;
}
.fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  background: var(--blue);
}
.page {
  color: var(--muted);
  font-size: 0.58rem;
}
</style>
