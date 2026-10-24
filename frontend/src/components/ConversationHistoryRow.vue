<script setup lang="ts">
defineProps<{
  title: string
  subtitle: string
  active?: boolean
  compact?: boolean
  deleteDisabled?: boolean
}>()

defineEmits<{ open: []; rename: []; delete: [] }>()
</script>

<template>
  <div class="conversation-history-row" :class="{ active, compact }">
    <button class="conversation-open" type="button" :title="title" :aria-current="active ? 'true' : undefined" @click="$emit('open')">
      <strong>{{ title }}</strong>
      <small>{{ subtitle }}</small>
    </button>
    <div class="conversation-actions" role="group" :aria-label="`${title}的操作`">
      <button type="button" :aria-label="`重命名对话：${title}`" @click="$emit('rename')">重命名</button>
      <button class="conversation-delete" type="button" :aria-label="`删除对话：${title}`" :disabled="deleteDisabled" :title="deleteDisabled ? '回答完成后可删除' : '删除对话'" @click="$emit('delete')">删除</button>
    </div>
  </div>
</template>

<style scoped>
.conversation-history-row { position: relative; min-width: 0; border-bottom: 1px solid #dedbd2; color: #40594d; }
.conversation-history-row:hover, .conversation-history-row:focus-within, .conversation-history-row.active { background: #edf2ea; }
.conversation-open { display: grid; gap: 5px; width: 100%; min-width: 0; min-height: 65px; padding: 12px 96px 12px 8px; border: 0; color: inherit; background: transparent; cursor: pointer; text-align: left; }
.conversation-open strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; font-weight: 500; }
.conversation-open small { overflow: hidden; color: #65756c; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.conversation-actions { position: absolute; right: 4px; top: 50%; display: flex; gap: 2px; transform: translateY(-50%); opacity: 0; pointer-events: none; }
.conversation-history-row:hover .conversation-actions, .conversation-history-row:focus-within .conversation-actions { opacity: 1; pointer-events: auto; }
.conversation-actions button { min-height: 32px; padding: 5px; border: 0; border-radius: 4px; color: #315d4e; background: transparent; cursor: pointer; font-size: 11px; white-space: nowrap; }
.conversation-actions button:hover { background: #dce7da; }
.conversation-actions .conversation-delete { color: #974c3c; }
.conversation-actions .conversation-delete:hover { background: #f4e5de; }
.conversation-actions button:disabled { opacity: .5; cursor: not-allowed; }
.conversation-history-row.compact { border-bottom: 0; border-radius: 4px; }
.compact .conversation-open { min-height: 46px; padding: 6px 5px; gap: 3px; }
.compact .conversation-open strong { font-size: 12px; }
.compact .conversation-open small { font-size: 9px; }
.compact:hover .conversation-open, .compact:focus-within .conversation-open { padding-right: 82px; }
button:focus-visible { outline: 2px solid #557966; outline-offset: -2px; }
@media (hover: none), (pointer: coarse) {
  .conversation-actions { opacity: 1; pointer-events: auto; }
  .conversation-actions button { min-height: 44px; }
  .compact .conversation-open { min-height: 48px; padding-right: 82px; }
}
</style>
