<script setup lang="ts">
import { computed } from 'vue'
import { useSlideContext } from '@slidev/client'

const { $frontmatter } = useSlideContext()
const layout = computed(() => $frontmatter?.layout ?? 'default')
// brilho azul num canto: capítulos e capa à esquerda, conteúdo à direita
const glowLeft = computed(() => ['section', 'cover', 'end'].includes(layout.value))
</script>

<template>
  <div class="exos-bg" :class="{ 'glow-left': glowLeft }">
    <div class="grid-lines" />
    <div class="glow" />
  </div>
</template>

<style scoped>
.exos-bg {
  position: absolute;
  inset: 0;
  background: var(--space);
  overflow: hidden;
  pointer-events: none;
}
.grid-lines {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(59, 102, 149, 0.075) 1px, transparent 1px),
    linear-gradient(90deg, rgba(59, 102, 149, 0.075) 1px, transparent 1px);
  background-size: 122.5px 122.5px;
  background-position: -1px -1px;
}
.glow {
  position: absolute;
  width: 640px;
  height: 460px;
  top: -210px;
  right: -200px;
  background: radial-gradient(closest-side, rgba(58, 155, 253, 0.2), transparent);
}
.glow-left .glow {
  top: auto;
  right: auto;
  bottom: -240px;
  left: -200px;
  background: radial-gradient(closest-side, rgba(58, 155, 253, 0.24), transparent);
}
</style>
