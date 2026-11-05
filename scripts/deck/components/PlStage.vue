<script setup lang="ts">
// Liga a classe is-on quando o slide fica ativo: barras, cortinas e números
// animam a cada entrada no slide (e saem prontos no export).
import { ref, watch } from 'vue'
import { useIsSlideActive, useNav } from '@slidev/client'

const active = useIsSlideActive()
const { isPrintMode } = useNav()
const on = ref(false)

watch(active, (v) => {
  if (v)
    requestAnimationFrame(() => requestAnimationFrame(() => (on.value = true)))
  else
    on.value = false
}, { immediate: true })
</script>

<template>
  <div class="pl-stage" :class="{ 'is-on': on || isPrintMode }">
    <slot />
  </div>
</template>
