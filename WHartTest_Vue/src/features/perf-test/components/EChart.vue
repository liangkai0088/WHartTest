<template>
  <div ref="el" :style="{ width: '100%', height }" />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = withDefaults(defineProps<{
  option: Record<string, any>
  height?: string
}>(), { height: '300px' })

const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

onMounted(() => {
  if (!el.value) return
  chart = echarts.init(el.value)
  chart.setOption(props.option)
})

watch(() => props.option, (option) => {
  chart?.setOption(option, { notMerge: true })
}, { deep: true })

onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>
