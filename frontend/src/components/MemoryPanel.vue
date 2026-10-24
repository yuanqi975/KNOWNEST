<template>
  <section class="memory-panel" aria-label="记忆管理">
    <h2>工作空间记忆</h2>
    <p class="intro">已确认的记忆可在此工作空间的对话中复用。自动提取的候选需要你确认。</p>
    <p v-if="error" class="error" role="alert">{{ error }} <button type="button" @click="refresh">重新加载</button></p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <section v-if="context" class="used-memory" aria-label="本轮上下文">
      <h3>本轮上下文</h3>
      <p>{{ context.input_tokens || 0 }} / {{ context.input_limit || 0 }} Token · 摘要覆盖至消息 {{ context.covered_sequence || 0 }}</p>
      <ul v-if="context.memories?.length"><li v-for="item in context.memories" :key="item.id">{{ item.content }}</li></ul>
      <p v-else>本轮没有使用长期记忆。</p>
    </section>
    <form class="memory-form" @submit.prevent="save">
      <h3>{{ editing ? '编辑记忆' : draft ? '从回答保存记忆' : '新增记忆' }}</h3>
      <label for="memory-content">内容</label>
      <textarea id="memory-content" ref="contentInput" v-model="content" rows="4" maxlength="2000" required :disabled="busy" placeholder="例如：回答请优先使用中文，并给出文档依据。" />
      <div class="fields">
        <label for="memory-type">类型<select id="memory-type" v-model="type" :disabled="busy"><option v-for="(label, value) in types" :key="value" :value="value">{{ label }}</option></select></label>
        <label for="memory-scope">生效范围<select id="memory-scope" v-model="scope" :disabled="busy"><option value="">整个工作空间</option><option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">{{ kb.name }}</option></select></label>
      </div>
      <div class="actions"><button class="primary" type="submit" :disabled="busy || !content.trim()">{{ busy ? '处理中…' : editing ? '保存修改' : '保存记忆' }}</button><button v-if="editing || draft" type="button" :disabled="busy" @click="reset">取消编辑</button></div>
    </form>
    <nav class="filters" aria-label="记忆状态"><button v-for="filter in filters" :key="filter.value" type="button" :aria-pressed="tab === filter.value" @click="tab = filter.value">{{ filter.label }} {{ count(filter.value) }}</button></nav>
    <p v-if="loading" role="status">正在加载记忆…</p>
    <p v-else-if="!visible.length" class="intro">{{ tab === 'pending' ? '暂无待确认候选。对话后可刷新查看自动提取结果。' : '暂无记忆。你可以在上方添加，或在对话中明确说“请记住…”。' }}</p>
    <article v-for="item in visible" :key="item.id" class="memory-row">
      <div class="meta"><strong>{{ types[item.type] || item.type }}</strong><span>{{ item.knowledge_base_id ? `知识库：${knowledgeBases?.find(kb => kb.id === item.knowledge_base_id)?.name || item.knowledge_base_id}` : '工作空间内生效' }}</span><span v-if="item.superseded_by">已被替代</span><span v-if="expired(item)">已过期</span></div>
      <p>{{ item.content }}</p>
      <div v-if="item.conflict && item.status === 'pending'" class="conflict"><strong>确认后替代以下记忆</strong><p>{{ item.conflict.content }}</p></div>
      <details v-if="item.sources?.length"><summary>查看来源 {{ item.sources.length }}</summary><blockquote v-for="source in item.sources" :key="source.message_id">{{ source.excerpt }}</blockquote></details>
      <p v-else class="source-label">{{ item.source_type === 'explicit' ? '来自明确的记忆请求' : '手动保存' }}</p>
      <div class="actions">
        <template v-if="item.status === 'pending'"><button class="primary" type="button" :disabled="busy" @click="decide(item, true)">确认记忆</button><button type="button" :disabled="busy" @click="decide(item, false)">拒绝</button></template>
        <button type="button" :disabled="busy" @click="edit(item)">编辑</button>
        <button v-if="deletingId !== item.id" class="destructive" type="button" :disabled="busy" @click="deletingId = item.id">删除</button>
        <template v-else><span>永久删除？</span><button class="destructive" type="button" :disabled="busy" @click="remove(item)">确认删除</button><button type="button" :disabled="busy" @click="deletingId = ''">保留</button></template>
      </div>
    </article>
    <button class="refresh" type="button" :disabled="loading || busy" @click="refresh">刷新记忆</button>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { runtimeApi } from '@/api/python-runtime'
const props = defineProps<{ workspaceId: string; kbId: string; knowledgeBases?: Array<{ id: string; name: string }>; sessionId: string; demo?: boolean; draft?: { content: string; messageId: string } | null }>()
const emit = defineEmits<{ changed: []; resetDraft: [] }>()
const types: Record<string, string> = { profile: '个人信息', preference: '回答偏好', fact: '项目事实', task: '长期任务', interest: '关注主题' }
const filters = [{ value: 'active', label: '有效' }, { value: 'pending', label: '待确认' }, { value: 'other', label: '其他' }]
const tab = ref('active'), content = ref(''), type = ref('fact'), scope = ref('')
const rows = ref<any[]>([]), context = ref<any>(null), editing = ref<any>(null)
const loading = ref(false), busy = ref(false), error = ref(''), notice = ref(''), deletingId = ref('')
const contentInput = ref<HTMLTextAreaElement>()
const expired = (item: any) => item.expires_at && Date.parse(item.expires_at) <= Date.now()
const matches = (item: any, filter: string) => filter === 'other' ? item.status === 'rejected' || item.superseded_by || expired(item) : item.status === filter && !item.superseded_by && !expired(item)
const visible = computed(() => rows.value.filter(item => matches(item, tab.value)))
const count = (filter: string) => rows.value.filter(item => matches(item, filter)).length
async function refresh() {
  if (props.demo) { rows.value = []; return }
  loading.value = true; error.value = ''
  try {
    rows.value = await runtimeApi.memories(props.workspaceId)
    context.value = props.sessionId ? await runtimeApi.conversationContext(props.sessionId) : null
  } catch (e: any) { error.value = e.message } finally { loading.value = false }
}
function reset() { editing.value = null; content.value = ''; type.value = 'fact'; scope.value = ''; emit('resetDraft') }
function edit(item: any) { editing.value = item; content.value = item.content; type.value = item.type; scope.value = item.knowledge_base_id || ''; contentInput.value?.focus() }
async function mutate(action: () => Promise<unknown>, message: string) {
  if (props.demo) { error.value = '演示模式不会修改真实记忆'; return false }
  busy.value = true; error.value = ''; notice.value = ''
  try { await action(); notice.value = message; await refresh(); emit('changed'); return true }
  catch (e: any) { error.value = `${e.message}；请刷新后核对最新内容。`; return false }
  finally { busy.value = false }
}
async function save() {
  const payload = { content: content.value.trim(), type: type.value, knowledge_base_id: scope.value || null }
  const ok = await mutate(() => editing.value
    ? runtimeApi.updateMemory(editing.value.id, { ...payload, version: editing.value.version })
    : runtimeApi.createMemory(props.workspaceId, { ...payload, source_message_id: props.draft?.messageId || null }), '记忆已保存')
  if (ok) reset()
}
async function decide(item: any, confirm: boolean) { await mutate(() => confirm ? runtimeApi.confirmMemory(item.id, item.version) : runtimeApi.rejectMemory(item.id, item.version), confirm ? '记忆已确认' : '候选已拒绝') }
async function remove(item: any) { if (await mutate(() => runtimeApi.deleteMemory(item.id), '记忆已删除')) deletingId.value = '' }
watch(() => props.draft, draft => { if (draft) { content.value = draft.content.slice(0, 2000); scope.value = props.kbId; editing.value = null } }, { immediate: true })
watch(() => props.workspaceId, () => { reset(); void refresh() })
onMounted(refresh)
</script>

<style scoped>
.memory-panel{color:#314b3e;font-size:13px;line-height:1.65}.memory-panel h2{margin:10px 0 14px;font-size:25px}.memory-panel h3{margin:0 0 10px;font-size:15px}.intro,.source-label,.meta,.used-memory>p{color:#566b5d}.intro{margin:0 0 22px}.used-memory{padding:0 0 22px;margin-bottom:22px;border-bottom:1px solid #d6d6c9}.used-memory ul{padding-left:20px}.memory-form{padding-bottom:24px}.memory-form>label{display:block;margin-bottom:5px}.memory-form textarea,.memory-form select{box-sizing:border-box;width:100%;padding:9px;border:1px solid #b7c3b6;border-radius:5px;background:#fffdf8;color:#263f33;font:inherit;caret-color:#315d4e}.memory-form textarea{resize:vertical}.fields{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px}.fields label{display:grid;gap:5px}.actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:12px}.memory-panel button{padding:7px 11px;border:1px solid #b7c3b6;border-radius:5px;background:#fffdf8;color:#315d4e;font:inherit;cursor:pointer}.memory-panel button:hover{background:#e7eee2}.memory-panel button:focus-visible,.memory-panel textarea:focus-visible,.memory-panel select:focus-visible,.memory-panel summary:focus-visible{outline:2px solid #315d4e;outline-offset:3px}.memory-panel button:disabled{opacity:.55;cursor:default}.memory-panel .primary{background:#315d4e;color:#fff;border-color:#315d4e}.memory-panel .primary:hover{background:#244737}.memory-panel .destructive{color:#8a382c;border-color:#cba79c}.filters{display:flex;flex-wrap:wrap;gap:7px;padding-bottom:18px;border-bottom:1px solid #d6d6c9}.filters button[aria-pressed=true]{background:#e0eadc;border-color:#6e8b72}.memory-row{padding:20px 0;border-bottom:1px solid #d6d6c9}.memory-row>p{white-space:pre-wrap;overflow-wrap:anywhere;margin:9px 0}.meta{display:flex;flex-wrap:wrap;gap:10px;font-size:12px}.meta strong{color:#315d4e}.conflict{padding:12px;background:#f6ecda;color:#6c4b24}.conflict p{margin:6px 0 0;overflow-wrap:anywhere}.memory-row summary{cursor:pointer;color:#315d4e}.memory-row blockquote{margin:10px 0;padding:10px;background:#eef1e6;white-space:pre-wrap;overflow-wrap:anywhere}.error{padding:12px;background:#f8e9e2;color:#8a382c}.notice{color:#315d4e}.refresh{margin-top:22px}@media(max-width:480px){.fields{grid-template-columns:1fr}}
</style>
