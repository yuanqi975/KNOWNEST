<template>
  <div class="knownest" @keydown.esc="closeOverlays">
    <header class="topbar">
      <div class="brand"><span class="brand-mark">K</span><strong>KNOWNEST</strong><span class="brand-sub">企业知识工作台</span></div>
      <div class="crumb">知识库 / {{ selectedKbName }}</div>
      <div class="top-actions"><span class="service"><i :class="serviceState"></i>{{ serviceLabel }}</span><button class="quiet-button" type="button" @click="toggleDemo">{{ demoMode ? '演示数据' : '退出登录' }}</button></div>
    </header>

    <div class="app-shell">
      <aside class="sidebar" aria-label="主导航">
        <section class="hierarchy-workspace">
          <div class="hierarchy-label"><span>工作空间</span></div>
          <button class="workspace-switcher" type="button" @click="workspaceMenuOpen = !workspaceMenuOpen" :aria-expanded="workspaceMenuOpen">
            <span>{{ workspaces.find(space => space.id === workspaceId)?.name || '选择工作空间' }}</span><span class="tree-chevron">⌄</span>
          </button>
          <div v-if="workspaceMenuOpen" class="workspace-menu"><button v-for="space in workspaces" :key="space.id" type="button" :class="{ active: space.id === workspaceId }" @click="selectWorkspace(space.id)">{{ space.name }}</button></div>
          <button class="hierarchy-create" type="button" @click="createWorkspace"><svg class="mini-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10" /></svg>新建工作空间</button>
        </section>
        <section class="knowledge-tree" aria-label="知识库层级">
          <div class="hierarchy-label"><span>知识库</span><small>{{ knowledgeBases.length }} 个</small></div>
          <div v-for="kb in knowledgeBases" :key="kb.id" class="knowledge-node">
            <button class="knowledge-row" :class="{ active: kb.id === kbId }" type="button" @click="selectKnowledgeBase(kb.id)"><span class="tree-chevron" :class="{ open: kb.id === kbId && knowledgeTreeOpen }">⌄</span><span class="knowledge-name">{{ kb.name }}</span><small v-if="kb.id === kbId">当前</small></button>
            <div v-if="kb.id === kbId && knowledgeTreeOpen" class="knowledge-children">
              <div class="chunking-entry-wrap tree-chunking">
                <button class="chunking-entry tree-chunking-button" :class="{ active: chunkingOpen }" type="button" aria-haspopup="dialog" :aria-expanded="chunkingOpen" @click="toggleChunkingMenu"><svg class="mini-icon" viewBox="0 0 18 18" aria-hidden="true"><path d="M4 3h10v12H4zM7 6h4M7 9h4M7 12h2" /></svg><span>文档处理</span><small>切分策略</small></button>
                <div v-if="chunkingOpen" class="chunking-popover" role="dialog" aria-label="文档切分策略"><strong>文档切分策略</strong><p>影响新上传文档；已有文档需重新索引</p><div class="chunking-options"><label v-for="option in chunkingStrategyOptions" :key="option.value" class="chunking-option"><input type="radio" name="tree-chunking-strategy" :value="option.value" :checked="chunkingConfig.strategy === option.value" @change="selectChunkingStrategy(option.value)" /><span>{{ option.label }}</span></label></div><button class="chunking-advanced" type="button" @click="openChunkingSettings">查看高级设置</button></div>
              </div>
              <button class="knowledge-child" :class="{ active: drawer === 'documents' }" type="button" @click="openDrawer('documents')"><svg class="tree-icon" viewBox="0 0 18 18" aria-hidden="true"><path d="M4 2.5h7l3 3V15.5H4zM11 2.5v3h3M6.5 9h5M6.5 12h5" /></svg><span>文档</span><b>{{ documents.length }}</b></button>
              <button class="knowledge-child" :class="{ active: drawer === 'memory' }" type="button" @click="openDrawer('memory')"><svg class="tree-icon" viewBox="0 0 18 18" aria-hidden="true"><path d="M9 2.8l1.1 1.9 2.2.4-.9 2 1.4 1.7-1.9 1.2.1 2.2-2-.2-1.7 1.4-1.2-1.9-2.2.1.2-2-1.4-1.7 1.9-1.2-.1-2.2 2 .2z" /><circle cx="9" cy="8.5" r="1.5" /></svg><span>记忆</span><b>{{ memories.length }}</b></button>
              <button class="knowledge-child" :class="{ active: drawer === 'sessions' || activeSessionId }" type="button" @click="openDrawer('sessions')"><svg class="tree-icon" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="6.5" /><path d="M6.5 9h5M9 6.5v5" /></svg><span>对话记录</span><b>{{ sessions.length }}</b></button>
              <div v-if="sessions.length" class="session-tree-list"><button v-for="session in sessions.slice(0, 4)" :key="session.id" class="session-tree-row" :class="{ active: session.id === activeSessionId }" type="button" @click="restoreSession(session)"><span>{{ session.title || '未命名对话' }}</span><small>{{ formatDate(session.updated_at || session.created_at) }}</small></button></div>
              <button class="new-conversation-link" type="button" @click="startNewConversation"><svg class="mini-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10" /></svg>新建对话</button>
            </div>
          </div>
          <button class="hierarchy-create" type="button" @click="createKnowledgeBase"><svg class="mini-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10" /></svg>新建知识库</button>
        </section>
        <section class="recent compact-recent"><label>最近文档</label><button v-for="document in documents.slice(0, 3)" :key="document.id" type="button" @click="openDocument(document)"><span class="file-mark">{{ (document.file_type || '').replace('.', '').toUpperCase() || 'DOC' }}</span><span class="recent-name">{{ document.filename }}</span><small :class="`status-${document.status}`">{{ statusLabel(document.status) }}</small></button><button class="upload-link" type="button" @click="openUpload"><svg class="mini-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10" /></svg>上传文档</button><input ref="fileInput" type="file" hidden multiple accept=".pdf,.md,.markdown,.txt,.docx" @change="handleFiles" /></section>
        <div class="sidebar-foot"><button class="mcp-bottom-link" type="button" @click="openDrawer('mcp')"><svg class="nav-icon" viewBox="0 0 18 18" aria-hidden="true"><path d="M5 3.5h8v4H5zM3 10.5h5v4H3zM10 10.5h5v4h-5zM9 7.5v3M5.5 10.5V9M12.5 10.5V9" /></svg><span>MCP 管理</span><b v-if="mcpServers.length">{{ mcpServers.length }}</b></button></div>
      </aside>
      <main class="chat-column">
        <header class="conversation-toolbar">
          <div class="conversation-context"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3.5h10l4 4v13H5zM15 3.5v4h4M8 12h8M8 16h8" /></svg><div><h1>{{ currentSession?.title || '基于已索引的知识库进行问答' }}</h1><p>{{ selectedKbName }} · 当前使用 {{ documents.length }} 个文档作为知识来源</p></div></div><span class="chunking-status">切分：{{ chunkingStrategyLabel }}</span>
          <button class="document-link" type="button" @click="openDrawer('documents')">文档 {{ documents.length }}</button>
        </header>
        <div class="mode-bar" role="tablist" aria-label="回答模式"><button :class="{ active: mode === 'rag' }" type="button" role="tab" :aria-selected="mode === 'rag'" @click="switchMode('rag')">普通 RAG</button><button :class="{ active: mode === 'agent' }" type="button" role="tab" :aria-selected="mode === 'agent'" @click="switchMode('agent')">智能回答</button><span><svg viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="6.5" /><path d="M9 8v4M9 5.5h.01" /></svg>{{ mode === 'agent' ? '可使用已启用的 MCP 工具' : '只基于当前知识库检索回答' }}</span><span v-if="streaming" class="live-stream-badge"><i></i>实时输出</span></div>
        <section ref="messageList" class="message-list" aria-live="polite"><div v-if="!messages.length" class="empty-state"><span class="empty-mark">K</span><h2>从你的文档中找到答案</h2><p>选择回答方式后开始提问，答案与可打开的原文依据会出现在这里。</p></div><article v-for="message in messages" :key="message.id" :class="['message', message.role, { 'message--streaming': message.pending }]" :aria-busy="message.pending || undefined"><div class="message-meta"><span>{{ message.role === 'user' ? '你的问题' : message.mode === 'agent' ? '智能回答' : '知识库回答' }}</span><span v-if="message.pending" class="streaming-label"><span class="streaming-dot" aria-hidden="true"></span>{{ message.content ? '正在输出' : '正在准备' }}</span></div><template v-if="message.role === 'assistant'"><div class="answer-body"><template v-for="(block, blockIndex) in answerBlocks(message.content || '')" :key="`${message.id}-${blockIndex}`"><h2 v-if="block.kind === 'heading'">{{ block.content }}</h2><p v-else>{{ block.content }}</p></template><p v-if="message.pending && !message.content" class="answer-placeholder">正在整理可验证的回答<span class="loading-ellipsis" aria-hidden="true">…</span></p><span v-if="message.pending && message.content" class="stream-cursor" aria-label="正在生成"></span></div></template><p v-else>{{ message.content }}</p><div v-if="message.events?.length" class="event-list"><span v-for="event in message.events" :key="event">{{ event }}</span></div><div v-if="message.citations?.length" class="citation-list"><button v-for="citation in message.citations" :key="citation.chunk_id" type="button" @click="openCitation(citation)">[{{ citation.citation_index }}] {{ citation.filename }}</button></div></article></section>
        <footer class="chat-composer" aria-label="提问区"><div class="composer-surface"><button class="attach-button" type="button" aria-label="上传文档" title="上传文档" @click="openUpload"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7.5 10.8l4.9-4.9a2.7 2.7 0 113.8 3.8l-6.6 6.6a4.2 4.2 0 11-5.9-5.9l6.1-6.1" /></svg></button><textarea ref="questionInput" v-model="question" rows="1" maxlength="12000" :disabled="streaming" :placeholder="mode === 'rag' ? '基于当前知识库提问…' : '提出任务，智能回答会结合知识库与已启用的工具…'" @keydown.enter.exact.prevent="ask" @keydown.enter.shift.stop></textarea><span class="composer-count">{{ question.length.toLocaleString() }} / 12,000</span><button class="send-button" :disabled="streaming || !question.trim() || !kbId" type="button" aria-label="发送问题" @click="ask"><svg viewBox="0 0 18 18" aria-hidden="true"><path d="M3 9h11M9.5 4.5L14 9l-4.5 4.5" /></svg></button></div><div v-if="streaming" class="run-bar"><span class="spinner"></span>{{ runStatus }}<button type="button" @click="cancelRequest">取消执行</button></div><div v-if="requestError" class="request-error" role="alert">{{ requestError }}<button type="button" @click="retryLast">重试</button></div></footer>
      </main>

      <aside class="evidence-panel" aria-label="来源与证据"><div class="evidence-title"><div class="evidence-heading"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3.5h10l4 4v13H5zM15 3.5v4h4M8 12h8M8 16h5" /></svg><div><span class="eyebrow">可追溯来源</span><h2>来源与证据</h2></div></div><span class="evidence-status">{{ streaming ? '执行中' : '已准备' }}</span></div><div v-if="!trace.length" class="evidence-placeholder">检索片段、Agent 工具调用和引用会按顺序显示在这里。</div><template v-else><article v-for="(item, index) in trace" :key="item.id" :class="['source-card', { 'source-card--trace': !item.citation }]" :aria-label="item.citation ? `检索来源：${item.citation.filename || '文档'}` : item.title"><div class="source-card-head"><span class="source-index">{{ String(index + 1).padStart(2, '0') }}</span><div class="source-file"><span class="file-icon">W</span><div><strong>{{ item.citation?.filename || item.title }}</strong><small v-if="item.citation">{{ sourceMeta(item.citation) }}</small><small v-else>工作流记录</small></div></div><div v-if="item.citation?.rank != null" class="source-rank"><small>检索排名</small><b>第 {{ item.citation.rank }} 位</b></div></div><template v-if="item.citation"><blockquote>“{{ item.citation.quoted_text || item.detail }}<span v-if="item.citation.quote_truncated || (item.citation.quoted_text || '').length === 500">…</span>”</blockquote><small v-if="item.citation.quote_truncated || (item.citation.quoted_text || '').length === 500" class="evidence-preview-note">命中片段预览 · 显示前 500 字</small><div class="source-actions"><button class="source-open" type="button" @click="openCitation(item.citation)">查看完整片段</button><button v-if="item.citation.document_id" class="source-open" type="button" @click="openOriginal(item.citation)">打开整份原文</button></div></template><p v-else class="trace-detail">{{ item.detail }}</p></article></template><div class="evidence-foot"><span>{{ citationCount }} 个片段 · 来源可追溯</span><button type="button" @click="openDrawer('evidence')">展开查看</button></div></aside>
    </div>

    <div v-if="drawer" class="drawer-layer" @click.self="closeDrawer"><aside class="drawer" role="dialog" aria-modal="true" :aria-label="drawerTitle"><button ref="drawerClose" class="drawer-close" type="button" aria-label="关闭抽屉" @click="closeDrawer"><svg viewBox="0 0 18 18" aria-hidden="true"><path d="M4 4l10 10M14 4L4 14" /></svg></button>
      <template v-if="drawer === 'documents'"><span class="eyebrow">文档管理</span><h2>文档</h2><p class="drawer-note">仅展示当前知识库真实返回的文档与索引状态。</p><button v-for="document in documents" :key="document.id" class="document-row" type="button" @click="openDocument(document)"><span class="file-mark">{{ (document.file_type || '').replace('.', '').toUpperCase() || 'DOC' }}</span><span><strong>{{ document.filename }}</strong><small>{{ statusLabel(document.status) }}</small></span><svg class="row-arrow" viewBox="0 0 18 18" aria-hidden="true"><path d="M6 3l6 6-6 6" /></svg></button><button class="primary-button" type="button" @click="openUpload">上传文档</button></template>
      <template v-else-if="drawer === 'document-detail'"><span class="eyebrow">文档详情</span><h2 class="breakable">{{ selectedDocument?.filename }}</h2><div v-if="documentLoading" class="drawer-note">正在加载文档详情…</div><template v-else-if="documentDetail"><dl class="detail-list"><div><dt>文件类型</dt><dd>{{ documentDetail.file_type }}</dd></div><div><dt>文件大小</dt><dd>{{ formatBytes(documentDetail.file_size) }}</dd></div><div><dt>索引状态</dt><dd><span :class="`status-${documentDetail.status}`">{{ statusLabel(documentDetail.status) }}</span></dd></div><div><dt>创建时间</dt><dd>{{ formatDate(documentDetail.created_at) }}</dd></div><div><dt>更新时间</dt><dd>{{ formatDate(documentDetail.updated_at) }}</dd></div><div><dt>所属知识库</dt><dd>{{ selectedKbName }}</dd></div></dl><div class="drawer-actions"><button class="outline-button" type="button" @click="previewDocument">预览原文</button><button class="outline-button" type="button" @click="reindexDocument">重新索引</button></div><button class="danger-button" type="button" @click="drawer = 'delete-document'">删除文档</button></template></template>
      <template v-else-if="drawer === 'delete-document'"><span class="eyebrow danger-eyebrow">不可逆操作</span><h2>删除文档</h2><div class="danger-box"><strong>确定要删除 {{ selectedDocument?.filename }} 吗？</strong><p>此操作会同时移除文档、切片、向量和本地源文件，并可能使历史引用无法打开。</p></div><div class="drawer-actions"><button class="outline-button" type="button" @click="drawer = 'document-detail'">取消</button><button class="danger-button" type="button" :disabled="deleting" @click="deleteDocument">{{ deleting ? '删除中…' : '确认删除' }}</button></div></template>
      <template v-else-if="drawer === 'preview'"><span class="eyebrow">原文预览</span><h2 class="breakable">{{ preview?.filename || '原文预览' }}</h2><p class="drawer-note">{{ preview?.highlightStart != null ? '已定位到命中的原文位置。' : '来自后端解析结果。' }}</p><p v-if="previewLoading" class="drawer-note">正在加载原文…</p><p v-if="previewError" class="request-error" role="alert">{{ previewError }}</p><pre v-if="preview?.content" ref="previewTextElement" class="preview-text"><template v-if="preview.highlightStart != null && preview.highlightEnd != null">{{ preview.content.slice(0, preview.highlightStart) }}<mark ref="previewHighlightElement">{{ preview.content.slice(preview.highlightStart, preview.highlightEnd) }}</mark>{{ preview.content.slice(preview.highlightEnd) }}</template><template v-else>{{ preview.content }}</template></pre><p v-else-if="!previewLoading && !previewError" class="drawer-note">暂无可预览内容。</p></template>
      <template v-else-if="drawer === 'sessions'"><span class="eyebrow">历史对话</span><h2>对话记录</h2><p class="drawer-note">同一会话可在普通 RAG 与智能回答之间继续。</p><button v-for="session in sessions" :key="session.id" class="session-row" type="button" @click="restoreSession(session)"><strong>{{ session.title || '未命名对话' }}</strong><small>{{ formatDate(session.created_at) }} · {{ session.mode === 'conversation' ? '连续会话' : session.mode === 'agent' ? '智能回答' : '普通 RAG' }}</small></button><p v-if="!sessions.length" class="drawer-note">还没有历史对话。</p></template>
      <template v-else-if="drawer === 'chunking'"><span class="eyebrow">知识库 / 文档处理</span><h2>文档切分策略</h2><p class="drawer-note">所选策略用于切分检索子块；父块按同一策略切分并在命中后扩展回答上下文。大小和重叠均以字符计，已有文档需要重新索引。</p><div class="chunking-settings"><label>策略<select v-model="chunkingConfig.strategy"><option v-for="option in chunkingStrategyOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label><label>{{ chunkingConfig.enable_parent_child ? '子块大小（字符）' : '切片大小（字符）' }}<input v-model.number="chunkingConfig.chunk_size" type="number" min="100" :max="chunkingConfig.enable_parent_child ? chunkingConfig.parent_chunk_size : 10000" /></label><label v-if="chunkingConfig.enable_parent_child">父块大小（字符）<input v-model.number="chunkingConfig.parent_chunk_size" type="number" :min="Math.max(512, chunkingConfig.chunk_size)" max="8192" /></label><label>重叠长度（字符）<input v-model.number="chunkingConfig.chunk_overlap" type="number" min="0" :max="Math.max(0, chunkingConfig.chunk_size - 1)" /></label><label class="chunking-toggle"><input v-model="chunkingConfig.enable_parent_child" type="checkbox" />启用父子切分</label></div><div class="drawer-actions"><button class="outline-button" type="button" @click="drawer = ''">取消</button><button class="primary-button compact-button" type="button" @click="saveChunkingSettings(false)">保存配置</button></div><p v-if="chunkingNeedsReindex" class="chunking-warning">配置已更新，新配置将在全部已有文档重新索引后生效。</p></template>
      <template v-else-if="drawer === 'evidence'"><span class="eyebrow">证据轨迹</span><h2>来源与证据</h2><button v-for="(item, index) in trace" :key="item.id" class="drawer-trace" type="button" :disabled="!item.citation" @click="item.citation && openCitation(item.citation)"><b>{{ String(index + 1).padStart(2, '0') }}</b><span><strong>{{ item.citation?.filename || item.title }}</strong><small v-if="item.citation">{{ sourceMeta(item.citation) }}</small>{{ item.citation?.quoted_text || item.detail }}</span></button></template>
      <template v-else-if="drawer === 'citation'"><span class="eyebrow">完整命中片段</span><h2 class="breakable">{{ citationSource?.filename || '完整命中片段' }}</h2><p class="drawer-note">{{ sourceLocation }}</p><p v-if="citationLoading" class="drawer-note">正在加载命中片段…</p><p v-if="citationError" class="request-error" role="alert">{{ citationError }}</p><blockquote>{{ citationSource?.content || (citationLoading ? '正在加载…' : '后端没有返回可展示的命中片段。') }}</blockquote><button v-if="citationSource?.document_id" class="outline-button original-source-button" type="button" @click="openOriginal(citationSource)">打开整份原文并定位</button></template>
      <template v-else-if="drawer === 'mcp'"><span class="eyebrow">设置 / MCP</span><h2>MCP 管理</h2><p class="drawer-note">MCP 仅在智能回答中使用。连接状态和工具清单均来自后端接口。</p><div v-for="server in mcpServers" :key="server.id" class="mcp-card"><div class="mcp-card-head"><strong>{{ server.name }}</strong><span :class="server.enabled ? 'status-indexed' : 'status-pending'">{{ server.enabled ? '已启用' : '未启用' }}</span></div><small>传输方式：{{ server.transport }}</small><div class="drawer-actions"><button class="outline-button" type="button" @click="toggleMcpEnabled(server)">{{ server.enabled ? '停用服务' : '启用服务' }}</button><button class="outline-button" type="button" @click="discoverMcp(server)">发现工具</button><button class="outline-button" type="button" @click="loadTools(server)">查看工具</button></div><div v-if="serverTools[server.id]?.length" class="tool-list"><label v-for="tool in serverTools[server.id]" :key="tool.id"><span><strong>{{ tool.tool_name }}</strong><small>{{ tool.description || '未提供工具说明' }}</small></span><input type="checkbox" :checked="tool.enabled" @change="toggleTool(tool, $event)" /></label></div><button class="text-danger-button" type="button" @click="selectedMcp = server; drawer = 'delete-mcp'">删除此服务</button></div><button class="primary-button" type="button" @click="addMcp">添加 MCP 服务</button></template>
      <template v-else-if="drawer === 'delete-mcp'"><span class="eyebrow danger-eyebrow">不可逆操作</span><h2>删除 MCP 服务</h2><div class="danger-box"><strong>确定要删除 {{ selectedMcp?.name }} 吗？</strong><p>这会移除服务配置及其工具清单；外部服务本身不会被删除。</p></div><div class="drawer-actions"><button class="outline-button" type="button" @click="drawer = 'mcp'">取消</button><button class="danger-button" type="button" :disabled="deletingMcp" @click="deleteMcp">{{ deletingMcp ? '删除中…' : '确认删除' }}</button></div></template>
      <template v-else><span class="eyebrow">设置 / 运行时记忆</span><h2>运行时记忆</h2><p class="drawer-note">只显示后端已保存的工作空间记忆，不展示虚构标签或实体。</p><div v-for="memory in memories" :key="memory.id" class="memory-item"><b>{{ memory.type }}</b><span>{{ memory.content }}</span><small>{{ memory.status }} · {{ Math.round((memory.confidence || 0) * 100) }}%</small></div><p v-if="!memories.length" class="drawer-note">还没有已保存的记忆。</p></template>
    </aside></div>
    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

<style scoped>
.source-file > div{min-width:0;flex:1}
.drawer-trace > span{min-width:0;overflow-wrap:anywhere}
.drawer-trace strong{overflow-wrap:anywhere}
</style>
<style scoped>
/* Hierarchical workspace navigation: one compact tree, with MCP kept global at the bottom. */
.sidebar{position:relative;display:flex;flex-direction:column;gap:0;padding:28px 20px 18px;background:#f4f1e8;color:#405c58;overflow-y:auto}
.hierarchy-label{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;color:#748178;font-size:11px;letter-spacing:.08em}
.hierarchy-label small{color:#9aa39b;font-size:10px;letter-spacing:0}
.workspace-switcher,.knowledge-row{display:flex;align-items:center;gap:8px;width:100%;border:1px solid #d4d0c5;border-radius:8px;color:#405c58;background:#fffdf9;cursor:pointer;text-align:left}
.workspace-switcher{justify-content:space-between;height:48px;padding:0 14px;font-size:14px}.tree-chevron{display:inline-flex;align-items:center;justify-content:center;width:16px;color:#6d8176;font-size:16px;line-height:1;transform:rotate(-90deg);transition:transform .16s ease}.tree-chevron.open{transform:rotate(0deg)}
.workspace-menu{display:grid;gap:3px;margin-top:5px;padding:5px;border:1px solid #d8d5ca;border-radius:8px;background:#fffdf9;box-shadow:0 8px 18px rgb(59 75 62 / .08)}.workspace-menu button{padding:8px 9px;border:0;border-radius:5px;color:#54665c;background:transparent;text-align:left;cursor:pointer;font-size:13px}.workspace-menu button:hover,.workspace-menu button.active{background:#e4ede4;color:#315d4e}
.hierarchy-create{display:flex;align-items:center;gap:7px;margin:11px 0 0;padding:0;border:0;color:#527b68;background:transparent;cursor:pointer;font-size:13px;text-align:left}.hierarchy-create:hover{text-decoration:underline;text-underline-offset:3px}
.hierarchy-workspace{padding-bottom:22px;border-bottom:1px solid #ddd7ca}.knowledge-tree{padding-top:19px}.knowledge-node{margin-top:7px}.knowledge-row{height:43px;padding:0 11px;border-color:transparent;background:transparent;font-size:15px}.knowledge-row:hover,.knowledge-row.active{border-color:#d3dfd2;background:#e2ece1}.knowledge-row .knowledge-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.knowledge-row small{margin-left:auto;color:#779084;font-size:10px}.knowledge-children{position:relative;display:grid;gap:2px;margin:4px 0 0 15px;padding-left:14px}.knowledge-children:before{content:"";position:absolute;top:0;bottom:4px;left:0;border-left:1px solid #cbd6ca}.knowledge-child{display:flex;align-items:center;gap:9px;min-height:38px;padding:0 9px;border:0;border-radius:5px;color:#4b6056;background:transparent;cursor:pointer;text-align:left;font-size:14px}.knowledge-child:hover,.knowledge-child.active{background:#e7eee5;color:#315d4e}.knowledge-child b{margin-left:auto;color:#7d9086;font-size:11px;font-weight:400}.tree-icon{width:16px;height:16px;flex:0 0 auto;color:#658377}.tree-chunking{margin:2px 0 3px;padding-left:0}.tree-chunking-button{min-height:34px!important;padding:6px 8px!important;border:1px solid transparent!important;border-radius:5px!important;color:#4b6056!important;background:transparent!important;font-size:12px!important}.tree-chunking-button:hover,.tree-chunking-button:focus-visible,.tree-chunking-button.active{border-color:#cbdaca!important;background:#eef3eb!important}.tree-chunking-button .mini-icon{width:15px;height:15px}.tree-chunking-button span{font-weight:500}.tree-chunking-button small{margin-left:auto;color:#82918a;font-size:10px}.tree-chunking .chunking-popover{top:38px;left:17px;width:268px}.tree-chunking .chunking-popover:before{top:-8px;left:24px}.tree-chunking .chunking-popover .chunking-advanced{margin-top:12px}.session-tree-list{display:grid;gap:0;margin:2px 0 3px 25px;padding-left:10px}.session-tree-row{display:flex;align-items:center;justify-content:space-between;gap:6px;min-width:0;padding:5px 5px;border:0;border-radius:4px;color:#65756c;background:transparent;cursor:pointer;text-align:left}.session-tree-row:hover,.session-tree-row.active{color:#315d4e;background:#edf2ea}.session-tree-row span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.session-tree-row small{flex:0 0 auto;color:#9aa39b;font-size:9px}.new-conversation-link{display:flex;align-items:center;gap:7px;margin:6px 0 0 25px;padding:4px 5px;border:0;color:#527b68;background:transparent;cursor:pointer;font-size:12px;text-align:left}.new-conversation-link:hover{text-decoration:underline;text-underline-offset:3px}.compact-recent{gap:3px;margin-top:20px;padding-top:17px;border-top:1px solid #ddd7ca}.compact-recent>button:not(.upload-link){padding:7px 5px;color:#435b50}.compact-recent .file-mark{width:25px;height:25px}.compact-recent .recent-name{font-size:11px}.compact-recent .recent small{font-size:9px}.mcp-bottom-link{display:flex;align-items:center;gap:10px;width:100%;padding:10px 5px;border:0;color:#405c58;background:transparent;cursor:pointer;text-align:left;font-size:13px}.mcp-bottom-link:hover{background:#e6ede4}.mcp-bottom-link b{margin-left:auto;color:#6b8578;font-size:10px;font-weight:400}.sidebar-foot{margin-top:auto;padding-top:11px;border-top:1px solid #ddd7ca}.mcp-bottom-link .nav-icon{width:16px;height:16px;color:#668276}
@media (max-width:760px){.sidebar{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:14px 16px;overflow:visible}.hierarchy-workspace,.knowledge-tree{padding:0;border:0}.knowledge-tree{grid-column:1 / -1}.compact-recent,.sidebar-foot{display:none}}
</style>

<style scoped>
.message--streaming .answer-body{position:relative}
.streaming-label{display:inline-flex;align-items:center;gap:6px;color:#4f7967!important}
.streaming-dot{width:6px;height:6px;border-radius:50%;background:#5d9079;animation:streamPulse 1s ease-in-out infinite}
.answer-placeholder{color:#7d8b83!important}
.loading-ellipsis{display:inline-block;width:1.4em;overflow:hidden;vertical-align:bottom;animation:ellipsis 1.2s steps(4,end) infinite}
.stream-cursor{display:inline-block;width:2px;height:1.1em;margin-left:4px;vertical-align:-.18em;background:#4f806b;animation:cursorBlink .9s steps(1,end) infinite}
.message-list{overflow-anchor:none}
.live-stream-badge{margin-left:auto!important;color:#477764!important;font-size:11px!important}.live-stream-badge i{display:inline-block;width:6px;height:6px;margin-right:5px;border-radius:50%;background:#5d9079;animation:streamPulse 1s ease-in-out infinite}
@keyframes streamPulse{0%,100%{opacity:.35;transform:scale(.8)}50%{opacity:1;transform:scale(1.15)}}
@keyframes cursorBlink{0%,45%{opacity:1}46%,100%{opacity:0}}
@keyframes ellipsis{0%{width:.35em}33%{width:.7em}66%{width:1.05em}100%{width:1.4em}}
</style>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { runtimeApi, streamMessage } from '@/api/python-runtime'

type Mode = 'rag' | 'agent'
type Citation = { citation_index: number; chunk_id: string; document_id?: string; filename?: string; rerank_score?: number | null; rank?: number | null; retrieval_degraded?: boolean; quoted_text?: string; quote_truncated?: boolean; page_number?: number | null; char_start?: number | null; char_end?: number | null; heading_path?: string[] | null }
type DocumentPreview = { document_id?: string; filename: string; content: string; highlightStart?: number; highlightEnd?: number }
type Message = { id: string; role: 'user' | 'assistant'; content: string; mode?: Mode; pending?: boolean; events?: string[]; citations?: Citation[] }
type TraceItem = { id: string; title: string; detail: string; citation?: Citation }
type DrawerName = 'documents' | 'document-detail' | 'delete-document' | 'preview' | 'sessions' | 'evidence' | 'citation' | 'mcp' | 'delete-mcp' | 'memory' | 'chunking' | ''
type ChunkingStrategy = 'auto' | 'heading' | 'heuristic' | 'recursive' | 'legacy'
type ChunkingConfig = { strategy: ChunkingStrategy; chunk_size: number; chunk_overlap: number; separators: string[]; token_limit: number; languages: string[]; enable_parent_child: boolean; parent_chunk_size: number }

const route = useRoute(); const router = useRouter(); const mode = computed<Mode>(() => route.params.mode === 'agent' ? 'agent' : 'rag')
const demoMode = ref(!localStorage.getItem('weknora_python_token')); const serviceState = ref<'ready' | 'offline' | 'checking'>('checking'); const toast = ref(''); const requestError = ref('')
const workspaces = ref<any[]>([]); const knowledgeBases = ref<any[]>([]); const documents = ref<any[]>([]); const sessions = ref<any[]>([]); const memories = ref<any[]>([]); const mcpServers = ref<any[]>([]); const serverTools = ref<Record<string, any[]>>({})
const defaultChunkingConfig = (): ChunkingConfig => ({ strategy: 'auto', chunk_size: 512, chunk_overlap: 80, separators: ['\n\n', '\n', '。', '！', '？', ';', '；'], token_limit: 0, languages: [], enable_parent_child: true, parent_chunk_size: 4096 })
const chunkingConfig = ref<ChunkingConfig>(defaultChunkingConfig()); const chunkingOpen = ref(false); const chunkingNeedsReindex = ref(false)
const chunkingStrategyOptions: Array<{ value: ChunkingStrategy; label: string }> = [{ value: 'auto', label: '自动（推荐）' }, { value: 'heading', label: '按标题结构' }, { value: 'heuristic', label: '按章节与分页' }, { value: 'recursive', label: '递归切分' }]
const workspaceId = ref(''); const kbId = ref(''); const workspaceMenuOpen = ref(false); const knowledgeTreeOpen = ref(true); const question = ref(''); const followUp = ref(''); const messages = ref<Message[]>([]); const trace = ref<TraceItem[]>([]); const streaming = ref(false); const runStatus = ref('正在检索引用…'); const drawer = ref<DrawerName>('')
const selectedDocument = ref<any>(null); const documentDetail = ref<any>(null); const preview = ref<DocumentPreview | null>(null); const previewLoading = ref(false); const previewError = ref(''); const previewTextElement = ref<HTMLElement>(); const previewHighlightElement = ref<HTMLElement>(); const citationSource = ref<any>(null); const citationError = ref(''); const documentLoading = ref(false); const deleting = ref(false); const selectedMcp = ref<any>(null); const deletingMcp = ref(false); const activeSessionId = ref(''); const citationLoading = ref(false); const activeMcpId = ref('')
const fileInput = ref<HTMLInputElement>(); const questionInput = ref<HTMLTextAreaElement>(); const messageList = ref<HTMLElement>(); const drawerClose = ref<HTMLButtonElement>(); const REQUEST_TIMEOUT_MS = 65_000; let controller: AbortController | null = null; let timeoutTimer: number | undefined

const selectedKbName = computed(() => knowledgeBases.value.find(item => item.id === kbId.value)?.name || '未选择知识库')
const currentSession = computed(() => sessions.value.find(item => item.id === activeSessionId.value))
const citationCount = computed(() => trace.value.filter(item => item.citation).length)
const serviceLabel = computed(() => demoMode.value ? '演示模式' : serviceState.value === 'ready' ? '系统运行中' : serviceState.value === 'offline' ? '服务不可用' : '正在检查')
const drawerTitle = computed(() => ({ documents: '文档', 'document-detail': '文档详情', 'delete-document': '删除文档', preview: '原文预览', sessions: '对话记录', evidence: '来源与证据', citation: '引用原文', mcp: 'MCP 管理', 'delete-mcp': '删除 MCP 服务', memory: '运行时记忆', chunking: '文档切分策略' } as Record<string, string>)[drawer.value] || '')
const chunkingStrategyLabel = computed(() => chunkingStrategyOptions.find(option => option.value === chunkingConfig.value.strategy)?.label.replace('（推荐）', '') || '自动')
const sourceLocation = computed(() => sourceMeta(citationSource.value || {}))
function sourceMeta(citation: { page_number?: number | null; heading_path?: string[] | null; char_start?: number | null; char_end?: number | null }) {
  const page = citation.page_number ? `第 ${citation.page_number} 页` : ''
  const section = citation.heading_path?.filter(Boolean).slice(-1)[0]
  const range = typeof citation.char_start === 'number' && typeof citation.char_end === 'number' ? `字符 ${citation.char_start + 1}–${citation.char_end}` : ''
  return [page, section || range].filter(Boolean).join(' · ') || '文档引用'
}

function answerBlocks(content: string) {
  // The queue updates this tick so Vue rerenders the getter-backed message text.
  void streamDisplayTick.value
  return content.split(/\n{2,}/).filter(Boolean).map(item => {
    const text = item.trim()
    return { kind: /^(#{1,6}\s+|[一二三四五六七八九十]+、)/.test(text) ? 'heading' : 'paragraph', content: text.replace(/^#{1,6}\s+/, '') }
  })
}
let streamScrollFrame: number | undefined
function scrollToLatest(immediate = false) {
  if (!messageList.value) return
  if (streamScrollFrame) window.cancelAnimationFrame(streamScrollFrame)
  const scroll = () => messageList.value?.scrollTo({ top: messageList.value.scrollHeight, behavior: immediate ? 'auto' : 'smooth' })
  if (immediate) scroll()
  else streamScrollFrame = window.requestAnimationFrame(scroll)
}
type AssistantTextQueue = {
  visible: string
  queued: string
  timer?: number
  pending: boolean
  finishRequested: boolean
  signal?: AbortSignal
}
const assistantTextQueues = new Map<string, AssistantTextQueue>()
const activeAssistantQueues = new Set<AssistantTextQueue>()
const streamDisplayTick = ref(0)

function queueBatchSize(length: number) {
  if (length > 1800) return 12
  if (length > 800) return 8
  if (length > 300) return 5
  if (length > 80) return 3
  return 2
}

function queueState(message: Message) {
  return assistantTextQueues.get(message.id)
}

function flushAssistantText(message: Message, state: AssistantTextQueue) {
  state.timer = undefined
  if (state.signal?.aborted) {
    state.queued = ''
    state.pending = false
    state.finishRequested = false
    activeAssistantQueues.delete(state)
    streamDisplayTick.value += 1
    return
  }
  if (!state.queued) {
    if (state.finishRequested) {
      state.pending = false
      activeAssistantQueues.delete(state)
    }
    streamDisplayTick.value += 1
    return
  }
  const count = queueBatchSize(state.queued.length)
  state.visible += state.queued.slice(0, count)
  state.queued = state.queued.slice(count)
  streamDisplayTick.value += 1
  scrollToLatest()
  state.timer = window.setTimeout(() => flushAssistantText(message, state), state.queued.length > 800 ? 16 : 22)
}

function enqueueAssistantText(message: Message, text: string) {
  if (!text) return
  const state = queueState(message)
  if (!state) return
  state.signal ||= controller?.signal
  if (!state.pending) state.pending = true
  activeAssistantQueues.add(state)
  state.queued += text
  if (!state.timer) state.timer = window.setTimeout(() => flushAssistantText(message, state), 0)
  streamDisplayTick.value += 1
}

function drainAssistantText(message: Message) {
  return new Promise<void>(resolve => {
    const check = () => {
      const state = queueState(message)
      if (!state || (!state.queued && !state.timer)) return resolve()
      window.setTimeout(check, 16)
    }
    check()
  })
}

function installAssistantTextQueue(message: Message) {
  if (message.role !== 'assistant' || !message.pending || queueState(message)) return
  const state: AssistantTextQueue = {
    visible: message.content || '',
    queued: '',
    pending: true,
    finishRequested: false,
  }
  assistantTextQueues.set(message.id, state)
  activeAssistantQueues.add(state)
  Object.defineProperty(message, 'content', {
    configurable: true,
    enumerable: true,
    get: () => state.visible,
    set: (value: unknown) => {
      const next = String(value ?? '')
      if (next === state.visible) return
      if (next.startsWith(state.visible)) enqueueAssistantText(message, next.slice(state.visible.length))
      else {
        state.queued = ''
        state.visible = next
        streamDisplayTick.value += 1
      }
    },
  })
  Object.defineProperty(message, 'pending', {
    configurable: true,
    enumerable: true,
    get: () => state.pending,
    set: (value: unknown) => {
      if (Boolean(value)) {
        state.pending = true
        state.finishRequested = false
      } else {
        state.finishRequested = true
        if (!state.queued && !state.timer) {
          state.pending = false
          activeAssistantQueues.delete(state)
        }
      }
      streamDisplayTick.value += 1
    },
  })
}

function notify(message: string) { toast.value = message; window.setTimeout(() => { toast.value = '' }, 3200) }
function statusLabel(status: string) { return ({ pending: '等待索引', processing: '处理中', parsed: '已解析', embedding: '生成向量', indexed: '已索引', failed: '索引失败', deleting: '删除中', deleted: '已删除' } as Record<string, string>)[status] || status || '未知状态' }
function formatDate(value: string | undefined) { return value ? new Date(value).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }) : '未提供' }
function formatBytes(value: number | undefined) { if (!value) return '未提供'; if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`; return `${(value / 1024 / 1024).toFixed(1)} MB` }
function closeDrawer() { if (!drawer.value) return; drawer.value = ''; citationSource.value = null; citationError.value = ''; preview.value = null; previewError.value = ''; previewLoading.value = false; nextTick(() => questionInput.value?.focus()) }
function closeOverlays() { if (chunkingOpen.value) { chunkingOpen.value = false; return } closeDrawer() }
function openDrawer(next: DrawerName) { drawer.value = next; chunkingOpen.value = false; if (next === 'sessions') loadSessions(); if (next === 'memory') loadMemories(); if (next === 'mcp') loadMcpServers(); if (next === 'chunking') void loadChunkingConfig() }
function toggleChunkingMenu() { if (!kbId.value) return; chunkingOpen.value = !chunkingOpen.value; if (chunkingOpen.value) void loadChunkingConfig() }
function openChunkingSettings() { chunkingOpen.value = false; openDrawer('chunking') }
function selectChunkingStrategy(strategy: ChunkingStrategy) { chunkingConfig.value.strategy = strategy; void saveChunkingSettings(true) }
async function loadChunkingConfig() { if (!kbId.value) return; if (demoMode.value) { chunkingConfig.value = defaultChunkingConfig(); chunkingNeedsReindex.value = false; return } try { const response = await runtimeApi.chunkingConfig(kbId.value); chunkingConfig.value = { ...defaultChunkingConfig(), ...response.chunking_config }; chunkingNeedsReindex.value = response.needs_reindex } catch (error: any) { notify(`无法加载切分配置：${error.message}`) } }
async function saveChunkingSettings(closeAfter = false) { if (!kbId.value) return; if (chunkingConfig.value.chunk_overlap >= chunkingConfig.value.chunk_size) return notify('重叠长度必须小于子块大小'); if (chunkingConfig.value.enable_parent_child && chunkingConfig.value.parent_chunk_size < chunkingConfig.value.chunk_size) return notify('父块大小不能小于子块大小'); if (demoMode.value) { chunkingNeedsReindex.value = true; notify('演示模式仅预览切分策略，不会写入真实配置'); if (closeAfter) chunkingOpen.value = false; return } try { const response = await runtimeApi.updateChunkingConfig(kbId.value, chunkingConfig.value); chunkingNeedsReindex.value = response.needs_reindex; notify('切分策略已保存；重新索引后应用到已有文档'); if (closeAfter) chunkingOpen.value = false } catch (error: any) { notify(`保存切分策略失败：${error.message}`) } }
function toggleDemo() { if (demoMode.value) { demoMode.value = false; loadData() } else { localStorage.removeItem('weknora_python_token'); router.replace('/login') } }
function openUpload() { fileInput.value?.click() }
function loadDemoData() { const demoCitation = { citation_index: 1, chunk_id: 'demo-chunk', filename: 'Java Date.docx', rerank_score: .92, quoted_text: 'LocalDate 表示一个不包含时间的日期。' }; workspaces.value = [{ id: 'demo-workspace', name: '演示工作空间' }]; knowledgeBases.value = [{ id: 'demo-kb', name: 'Java 技术文档' }]; workspaceId.value = 'demo-workspace'; kbId.value = 'demo-kb'; workspaceMenuOpen.value = false; knowledgeTreeOpen.value = true; chunkingConfig.value = defaultChunkingConfig(); chunkingNeedsReindex.value = false; documents.value = [{ id: 'demo-doc', filename: 'Java Date.docx', file_type: '.docx', status: 'indexed' }]; memories.value = [{ id: 'demo-memory', type: 'preference', content: '回答保留可追溯引用。', status: 'active', confidence: .98 }]; mcpServers.value = []; loadDemoSessions(); messages.value = [{ id: 'demo-user', role: 'user', mode: 'rag', content: 'LocalDate 和 DateTimeFormatter 应该如何配合使用？' }, { id: 'demo-answer', role: 'assistant', mode: 'rag', content: 'LocalDate 表示不包含时间的日期；DateTimeFormatter 则负责日期与文本之间的格式化和解析。二者通常配合用于业务日期的输入、存储与展示。[1]\n\n# LocalDate 适合处理什么？\n\nLocalDate 用于只需要年、月、日的业务场景，例如生日、账单日、业务日期和报表日期。它不携带时区与具体时间，因此在表达纯日期语义时比旧版 Date 更直接，也能避免时间部分带来的歧义。[1]\n\n# DateTimeFormatter 如何参与？\n\nDateTimeFormatter 定义日期文本的格式规则。读取用户输入或外部接口字段时，可先用 formatter 解析文本，再得到 LocalDate；需要展示时，则使用同一个 formatter 将 LocalDate 输出为约定格式。这样可以把格式规则集中管理，减少不同页面之间的格式不一致。[1]\n\n# 建议的配合方式\n\n在边界处完成转换：输入或接口返回的字符串先通过 DateTimeFormatter 解析为 LocalDate，业务逻辑内部始终使用 LocalDate，最终展示时再统一格式化为文本。这样的分层能让日期计算与文本格式各自保持清晰。', citations: [demoCitation] }]; trace.value = [{ id: 'demo-trace', title: '引用 01 / Java Date.docx', detail: 'LocalDate 表示不包含时间的日期。', citation: demoCitation }]; serviceState.value = 'ready' }
async function loadData() { if (demoMode.value) { loadDemoData(); return } try { const spaces = await runtimeApi.workspaces(); workspaces.value = spaces; workspaceId.value = spaces[0]?.id || ''; if (workspaceId.value) await refreshWorkspace(); serviceState.value = 'ready' } catch (error: any) { serviceState.value = 'offline'; requestError.value = `无法加载真实数据：${error.message}` } }
async function selectWorkspace(nextWorkspaceId: string) { workspaceMenuOpen.value = false; if (workspaceId.value === nextWorkspaceId) return; workspaceId.value = nextWorkspaceId; await refreshWorkspace() }
async function refreshWorkspace() { if (!workspaceId.value || demoMode.value) return; try { knowledgeBases.value = await runtimeApi.knowledgeBases(workspaceId.value); kbId.value = knowledgeBases.value[0]?.id || ''; await refreshKnowledgeBase() } catch (error: any) { requestError.value = error.message } }
async function selectKnowledgeBase(nextKbId: string) { knowledgeTreeOpen.value = kbId.value === nextKbId ? !knowledgeTreeOpen.value : true; if (kbId.value === nextKbId && knowledgeTreeOpen.value === false) return; kbId.value = nextKbId; await refreshKnowledgeBase() }
function restoredTrace(loadedMessages: Message[]) {
  const latestAnswer = [...loadedMessages].reverse().find(message => message.role === 'assistant' && message.citations?.length)
  return (latestAnswer?.citations || []).map(citation => ({
    id: `restored-${citation.chunk_id}`,
    title: `引用 ${citation.citation_index} / ${citation.filename || '文档'}`,
    detail: citation.quoted_text || '打开查看原文片段',
    citation,
  }))
}
async function refreshKnowledgeBase() { messages.value = []; trace.value = []; activeSessionId.value = ''; sessions.value = []; chunkingOpen.value = false; if (!kbId.value) return; await loadChunkingConfig(); if (demoMode.value) { loadDemoSessions(); return } try { documents.value = await runtimeApi.documents(kbId.value); await loadSessions(); await restoreConversation() } catch (error: any) { requestError.value = error.message } }
function conversationStorageKey() { return `weknora_active_conversation:${workspaceId.value}:${kbId.value}` }
function saveConversationPointer() { if (!activeSessionId.value || demoMode.value) return; localStorage.setItem(conversationStorageKey(), activeSessionId.value) }
async function loadConversation(conversationId: string) {
  const loaded = await runtimeApi.conversation(conversationId)
  if (loaded.workspace_id !== workspaceId.value || loaded.knowledge_base_id !== kbId.value) throw new Error('会话不属于当前知识库')
  activeSessionId.value = loaded.id
  messages.value = (loaded.messages || []).map((message: any) => ({ ...message, mode: message.mode || loaded.legacy_mode || 'rag', citations: message.citations || [] }))
  const latestAnswer = [...messages.value].reverse().find(message => message.role === 'assistant' && message.citations?.length)
  trace.value = (latestAnswer?.citations || []).map(citation => ({ id: `restored-${citation.chunk_id}`, title: `引用 ${citation.citation_index} / ${citation.filename || '文档'}`, detail: citation.quoted_text || '打开查看原文片段', citation }))
  saveConversationPointer()
}
async function restoreConversation() {
  if (demoMode.value || !workspaceId.value || !kbId.value) return
  const conversationId = localStorage.getItem(conversationStorageKey())
  if (!conversationId) return
  try { await loadConversation(conversationId) } catch { localStorage.removeItem(conversationStorageKey()) }
}
function loadDemoSessions() { sessions.value = [{ id: 'demo-session-1', title: '智能回答的适用场景', mode: 'agent', created_at: new Date().toISOString(), updated_at: new Date().toISOString() }, { id: 'demo-session-2', title: '如何配置知识库检索', mode: 'rag', created_at: new Date(Date.now() - 86400000).toISOString(), updated_at: new Date(Date.now() - 86400000).toISOString() }, { id: 'demo-session-3', title: '项目文档中的权限说明', mode: 'rag', created_at: new Date(Date.now() - 172800000).toISOString(), updated_at: new Date(Date.now() - 172800000).toISOString() }] }
async function loadSessions() { if (demoMode.value || !workspaceId.value) { if (demoMode.value) loadDemoSessions(); return } try { sessions.value = await runtimeApi.conversations(workspaceId.value, kbId.value) } catch (error: any) { notify(error.message) } }
async function loadMemories() { if (demoMode.value || !workspaceId.value) return; try { memories.value = await runtimeApi.memories(workspaceId.value) } catch (error: any) { notify(error.message) } }
async function loadMcpServers() { if (demoMode.value || !workspaceId.value) { mcpServers.value = []; return } try { mcpServers.value = await runtimeApi.mcpServers(workspaceId.value) } catch (error: any) { notify(error.message) } }
async function createWorkspace() { if (demoMode.value) return notify('演示模式不会写入真实数据，请先连接账号'); const name = window.prompt('工作空间名称'); if (!name?.trim()) return; try { const created = await runtimeApi.createWorkspace(name.trim()); workspaces.value.push(created); workspaceId.value = created.id; await refreshWorkspace() } catch (error: any) { notify(error.message) } }
async function createKnowledgeBase() { if (demoMode.value) return notify('演示模式不会写入真实数据，请先连接账号'); if (!workspaceId.value) return notify('请先选择工作空间'); const name = window.prompt('知识库名称'); if (!name?.trim()) return; try { const created = await runtimeApi.createKnowledgeBase(workspaceId.value, name.trim()); knowledgeBases.value.push(created); kbId.value = created.id; await refreshKnowledgeBase() } catch (error: any) { notify(error.message) } }
async function switchMode(next: Mode) {
  if (mode.value === next) return
  if (streaming.value) return notify('当前回答尚未结束，暂不能切换问答方式')
  requestError.value = ''
  await router.push(`/runtime/${next}`)
}
async function trackIngestion(documentId: string, jobId?: string) {
  if (!jobId) return
  const terminal = new Set(['indexed', 'failed', 'deleted'])
  for (let attempt = 0; attempt < 30; attempt += 1) {
    await new Promise(resolve => window.setTimeout(resolve, 1000))
    try {
      const job = await runtimeApi.job(jobId)
      const current = documents.value.find(item => item.id === documentId)
      if (current) current.status = job.status
      if (terminal.has(job.status)) {
        if (job.status === 'failed') notify(`文档索引失败：${job.error || '后端未提供错误详情'}`)
        else notify(job.status === 'indexed' ? '文档已完成索引' : `文档状态：${statusLabel(job.status)}`)
        documents.value = await runtimeApi.documents(kbId.value)
        return
      }
    } catch (error: any) {
      notify(`无法读取索引进度：${error.message}`)
      return
    }
  }
  notify('索引仍在后台处理中，可稍后刷新文档列表查看状态')
}
async function handleFiles(event: Event) { const files = Array.from((event.target as HTMLInputElement).files || []); for (const file of files) { if (!/\.(pdf|md|markdown|txt|docx)$/i.test(file.name)) { notify(`${file.name} 格式不支持`); continue } if (demoMode.value) { notify('演示模式不会上传真实文件'); continue } if (!kbId.value) { notify('请先选择知识库'); continue } try { const result = await runtimeApi.uploadDocument(kbId.value, file); documents.value.unshift({ id: result.document_id, filename: file.name, file_type: `.${file.name.split('.').pop()}`, status: result.status, job_id: result.job_id }); notify(`${file.name} 已加入索引队列`); void trackIngestion(result.document_id, result.job_id) } catch (error: any) { notify(`上传失败：${error.message}`) } } ; (event.target as HTMLInputElement).value = '' }
async function ask() { if (!question.value.trim() || streaming.value || !kbId.value) return; const content = question.value.trim(); requestError.value = ''; messages.value.push({ id: crypto.randomUUID(), role: 'user', content, mode: mode.value }); const assistant: Message = { id: crypto.randomUUID(), role: 'assistant', content: '', mode: mode.value, pending: true, events: [], citations: [] }; messages.value.push(assistant); trace.value = []; streaming.value = true; runStatus.value = mode.value === 'agent' ? '正在准备智能研究…' : '正在检索文档证据…'; controller = new AbortController(); timeoutTimer = window.setTimeout(() => { requestError.value = '请求超时，已保留部分结果。'; controller?.abort() }, REQUEST_TIMEOUT_MS); await nextTick(); scrollToLatest(true); try { if (demoMode.value) { await new Promise(resolve => window.setTimeout(resolve, 700)); enqueueAssistantText(assistant, '演示回答：答案会基于当前知识库中的文档，并附带可打开的引用。'); const demoCitation: Citation = { citation_index: 1, chunk_id: 'demo-chunk', filename: 'Java Date.docx', rerank_score: .92, quoted_text: 'LocalDate 表示不包含时间的日期。' }; assistant.citations = [demoCitation]; trace.value = [{ id: 'demo-trace', title: '引用 01 / Java Date.docx', detail: demoCitation.quoted_text || '', citation: demoCitation }] } else { if (!activeSessionId.value) { const conversation = await runtimeApi.createConversation(workspaceId.value, kbId.value); activeSessionId.value = conversation.id; saveConversationPointer() } await streamMessage(`/conversations/${activeSessionId.value}/messages`, { content, mode: mode.value }, event => { if (event.type === 'token') { enqueueAssistantText(assistant, event.content || '') } if (event.type === 'retrieval_started') runStatus.value = mode.value === 'agent' ? '正在检索初始证据…' : '正在检索文档证据…'; if (event.type === 'retrieval_degraded') { runStatus.value = '重排不可用，显示候选片段'; assistant.events?.push('检索已降级') } if (event.type === 'planning_status') { runStatus.value = event.content || '正在选择下一步'; trace.value.push({ id: crypto.randomUUID(), title: `步骤 ${event.step || ''}`, detail: event.content || '' }); scrollToLatest() } if (event.type === 'retrieval_result') { const citations: Citation[] = (event.results || []).map((item: any, index: number) => ({ ...item, citation_index: item.citation_index || index + 1, quoted_text: item.quoted_text || item.content })); assistant.citations = citations; trace.value = citations.map(citation => ({ id: crypto.randomUUID(), title: `引用 ${citation.citation_index} / ${citation.filename || '文档'}`, detail: citation.quoted_text || '打开查看原文片段', citation })); scrollToLatest() } if (event.type === 'tool_call_start' || event.type === 'mcp_tool_call') { runStatus.value = `正在调用 ${event.name || '工具'}…`; trace.value.push({ id: crypto.randomUUID(), title: `工具调用 / ${event.name || 'MCP'}`, detail: '当前工作空间执行中' }) } if (event.type === 'tool_call_result' || event.type === 'mcp_tool_result') assistant.events?.push(event.name || 'MCP 工具'); if (event.type === 'error' || event.type === 'agent_error') { requestError.value = event.message || '请求未完成。'; assistant.events?.push('请求未完成') } if (event.type === 'citation') { const citation = event as Citation; const existing = assistant.citations?.find(item => item.chunk_id === citation.chunk_id); if (existing) Object.assign(existing, citation); else assistant.citations?.push(citation); scrollToLatest() } }, { signal: controller.signal }); await drainAssistantText(assistant); assistant.pending = false; if (!assistant.content) assistant.content = requestError.value ? '本次回答未完成，已保留检索到的引用。' : '已完成检索，但没有生成可展示的回答。' } } catch (error: any) { assistant.pending = false; if (error?.name !== 'AbortError') requestError.value = error.message } finally { await drainAssistantText(assistant); assistant.pending = false; streaming.value = false; controller = null; if (timeoutTimer) window.clearTimeout(timeoutTimer); if (!requestError.value) question.value = ''; await nextTick(); scrollToLatest(true) } }
async function cancelRequest() { controller?.abort(); if (activeSessionId.value && !demoMode.value) await runtimeApi.cancelConversation(activeSessionId.value).catch(() => undefined); streaming.value = false; notify('已请求取消，已保留当前结果') }
function retryLast() { if (!question.value) return; requestError.value = ''; ask() }
function sendFollowUp() { question.value = followUp.value; followUp.value = ''; ask() }
async function openCitation(citation: Citation) { drawer.value = 'citation'; citationLoading.value = true; citationError.value = ''; citationSource.value = null; try { citationSource.value = demoMode.value ? citation : await runtimeApi.citation(citation.chunk_id) } catch (error: any) { citationError.value = `无法加载后端命中片段：${error.message}`; citationSource.value = { ...citation, filename: citation.filename, content: citation.quoted_text || '' } } finally { citationLoading.value = false } }
async function openDocument(document: any) { selectedDocument.value = document; drawer.value = 'document-detail'; documentLoading.value = true; try { documentDetail.value = demoMode.value ? document : await runtimeApi.document(document.id) } catch (error: any) { notify(error.message) } finally { documentLoading.value = false } }
function previewRange(content: string, start?: number | null, end?: number | null) { if (typeof start !== 'number' || typeof end !== 'number' || !Number.isFinite(start) || !Number.isFinite(end)) return null; const safeStart = Math.max(0, Math.min(content.length, Math.trunc(start))); const safeEnd = Math.max(safeStart, Math.min(content.length, Math.trunc(end))); return safeEnd > safeStart ? { highlightStart: safeStart, highlightEnd: safeEnd } : null }
async function openOriginal(source: Partial<Citation> & { filename?: string; content?: string }) { const documentId = source.document_id; if (!documentId) return notify('当前引用没有关联的文档，无法打开原文'); drawer.value = 'preview'; preview.value = null; previewError.value = ''; previewLoading.value = true; try { const original = demoMode.value ? { filename: source.filename || '演示文档', content: source.content || source.quoted_text || '' } : await runtimeApi.previewDocument(documentId); const range = previewRange(original.content, source.char_start, source.char_end); preview.value = { ...original, ...(range || {}) }; await nextTick(); if (range) previewHighlightElement.value?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' }) } catch (error: any) { previewError.value = `无法加载原文：${error.message}` } finally { previewLoading.value = false } }
async function previewDocument() { if (!selectedDocument.value) return; drawer.value = 'preview'; preview.value = null; previewError.value = ''; previewLoading.value = true; try { preview.value = demoMode.value ? { filename: selectedDocument.value.filename, content: '演示模式未加载真实原文。' } : await runtimeApi.previewDocument(selectedDocument.value.id) } catch (error: any) { previewError.value = `无法加载原文：${error.message}` } finally { previewLoading.value = false } }
async function reindexDocument() { if (!selectedDocument.value || demoMode.value) return notify('演示模式不会修改真实索引'); try { await runtimeApi.reindexDocument(selectedDocument.value.id); notify('已开始重新索引'); await refreshKnowledgeBase() } catch (error: any) { notify(error.message) } }
async function deleteDocument() { if (!selectedDocument.value || demoMode.value) return notify('演示模式不会删除真实文档'); deleting.value = true; try { await runtimeApi.deleteDocument(selectedDocument.value.id); documents.value = documents.value.filter(item => item.id !== selectedDocument.value.id); closeDrawer(); notify('文档已删除，相关向量和源文件也已移除') } catch (error: any) { notify(`删除失败：${error.message}`) } finally { deleting.value = false } }
async function deleteMcp() { if (!selectedMcp.value || demoMode.value) return notify('演示模式不会删除真实 MCP'); deletingMcp.value = true; try { await runtimeApi.deleteMcpServer(selectedMcp.value.id); mcpServers.value = mcpServers.value.filter(item => item.id !== selectedMcp.value.id); delete serverTools.value[selectedMcp.value.id]; selectedMcp.value = null; drawer.value = 'mcp'; notify('MCP 服务已删除') } catch (error: any) { notify(`删除失败：${error.message}`) } finally { deletingMcp.value = false } }
async function restoreSession(session: any) { if (demoMode.value) { activeSessionId.value = session.id; drawer.value = ''; return } try { if (session.mode === 'conversation') { await loadConversation(session.id); } else { const loaded = await runtimeApi.session(session.mode, session.id); activeSessionId.value = loaded.id; messages.value = (loaded.messages || []).map((message: any) => ({ ...message, mode: session.mode, citations: message.citations || [] })); trace.value = restoredTrace(messages.value); } drawer.value = ''; } catch (error: any) { notify(error.message) } }
async function startNewConversation() { if (!kbId.value) return notify('请先选择知识库'); if (streaming.value) return notify('当前回答尚未结束，暂不能新建对话'); messages.value = []; trace.value = []; question.value = ''; requestError.value = ''; activeSessionId.value = ''; drawer.value = ''; if (demoMode.value) { const session = { id: `demo-session-${Date.now()}`, title: '新对话', mode: mode.value, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }; sessions.value.unshift(session); activeSessionId.value = session.id; return } try { const created = await runtimeApi.createConversation(workspaceId.value, kbId.value); activeSessionId.value = created.id; sessions.value = [created, ...sessions.value.filter(item => item.id !== created.id)]; saveConversationPointer() } catch (error: any) { notify(`新建对话失败：${error.message}`) } }
async function connectMcp(server: any) { if (demoMode.value) return notify('演示模式不会启用真实 MCP'); try { await runtimeApi.connectMcp(server.id); server.enabled = true; notify('MCP 服务已启用；是否可用需以工具发现结果为准') } catch (error: any) { notify(error.message) } }
async function toggleMcpEnabled(server: any) { if (server.enabled) { if (demoMode.value) return notify('演示模式不会修改 MCP'); try { const updated = await runtimeApi.updateMcpServer(server.id, { workspace_id: workspaceId.value, name: server.name, transport: server.transport, enabled: false }); server.enabled = updated.enabled; notify('MCP 服务已停用') } catch (error: any) { notify(error.message) } } else await connectMcp(server) }
async function discoverMcp(server: any) { if (demoMode.value) return notify('演示模式不会访问外部 MCP'); activeMcpId.value = server.id; try { const result = await runtimeApi.discoverMcp(server.id); server.enabled = true; serverTools.value[server.id] = result.tools || []; notify(`已发现 ${result.tools?.length || 0} 个工具`) } catch (error: any) { notify(error.message) } }
async function loadTools(server: any) { if (serverTools.value[server.id]) return; try { serverTools.value[server.id] = await runtimeApi.mcpTools(server.id) } catch (error: any) { notify(error.message) } }
async function toggleTool(tool: any, event: Event) { if (demoMode.value) return notify('演示模式不会修改 MCP 权限'); try { const enabled = (event.target as HTMLInputElement).checked; await runtimeApi.updateMcpTool(tool.id, enabled); tool.enabled = enabled } catch (error: any) { (event.target as HTMLInputElement).checked = tool.enabled; notify(error.message) } }
async function addMcp() { if (demoMode.value) return notify('演示模式不会创建真实 MCP'); const name = window.prompt('MCP 服务名称'); const endpoint = window.prompt('MCP 服务地址'); if (!name || !endpoint) return; try { const server = await runtimeApi.addMcpServer(workspaceId.value, { name, transport: 'streamable_http', endpoint, enabled: false, timeout_seconds: 30 }); mcpServers.value.push(server); notify('MCP 服务已添加') } catch (error: any) { notify(error.message) } }
watch(drawer, value => { if (value) nextTick(() => drawerClose.value?.focus()) })
watch(() => messages.value.length, () => {
  const latest = messages.value[messages.value.length - 1]
  if (latest) installAssistantTextQueue(latest)
}, { flush: 'sync' })
onMounted(loadData)
onBeforeUnmount(() => {
  controller?.abort()
  if (timeoutTimer) window.clearTimeout(timeoutTimer)
  activeAssistantQueues.forEach(state => { if (state.timer) window.clearTimeout(state.timer) })
  activeAssistantQueues.clear()
})
</script>

<style scoped>
:global(*){box-sizing:border-box}:global(body){margin:0;background:#f4f0e6;color:#1d2c28;font-family:"Noto Sans SC","Microsoft YaHei",sans-serif}:global(button),:global(input),:global(select),:global(textarea){font:inherit}.knownest{min-height:100dvh;background:#f4f0e6;color:#1d2c28}.topbar{height:72px;display:flex;align-items:center;padding:0 38px;border-bottom:1px solid #d7d0c2;background:#f8f5ed}.brand{display:flex;align-items:center;gap:12px;letter-spacing:2px}.brand-mark{display:grid;place-items:center;width:36px;height:36px;border-radius:10px;color:#f8f5ed;background:#315446;font-family:Georgia,serif;font-size:21px}.brand strong{font-size:15px}.brand-sub{padding-left:12px;border-left:1px solid #c9c0b1;color:#7b8278;font-size:12px;letter-spacing:0}.crumb{margin-left:48px;color:#7d837b;font-size:12px}.top-actions{display:flex;align-items:center;gap:18px;margin-left:auto}.service{color:#5e756a;font-size:12px}.service i{display:inline-block;width:8px;height:8px;margin-right:7px;border-radius:50%;background:#6ab59a}.service i.offline{background:#bb5f48}.quiet-button,.nav-group button,.nav-links button,.recent button,.conversation-head button,.evidence-foot button{border:0;color:#456f61;background:transparent;cursor:pointer}.quiet-button{padding:8px 10px;border-bottom:1px solid #9bb8ab;font-size:12px}.app-shell{display:grid;grid-template-columns:242px minmax(0,1fr) 330px;height:calc(100dvh - 72px)}.sidebar{display:flex;flex-direction:column;gap:22px;padding:28px 18px 18px;color:#dfe9df;background:#193b35}.nav-group{display:grid;gap:8px}.nav-group label,.recent label{color:#a6c0b2;font-size:10px;letter-spacing:1.4px}.nav-group select{width:100%;height:40px;padding:0 10px;border:1px solid #527366;border-radius:7px;color:#eaf1e9;background:#285247;outline:none}.nav-group button,.upload-link{padding:2px 0;text-align:left;color:#9ad0bd;font-size:11px}.nav-links{display:grid;gap:4px;padding:14px 0;border-top:1px solid #426258;border-bottom:1px solid #426258}.nav-links button{display:flex;align-items:center;gap:11px;padding:10px 8px;color:#dfe9df;text-align:left;font-size:13px}.nav-links button:hover,.nav-links button:focus-visible{background:#2a554a}.nav-links b{margin-left:auto;color:#abd5c2;font-size:11px}.recent{display:grid;gap:5px}.recent>button:not(.upload-link){display:flex;align-items:center;gap:8px;min-width:0;padding:9px 7px;color:#e3eee6;text-align:left}.recent>button:not(.upload-link):hover{background:#285247}.file-mark{display:inline-grid;place-items:center;flex:0 0 auto;width:26px;height:27px;border-radius:5px;color:#284f43;background:#e5eee2;font:700 8px Georgia,serif}.recent-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px}.recent small{margin-left:auto;font-size:9px}.status-indexed{color:#2e795c}.status-pending,.status-processing,.status-parsed,.status-embedding{color:#b17435}.status-failed,.status-deleting{color:#b55443}.sidebar .status-indexed{color:#9bd0b5}.demo-note{color:#e9be81}.sidebar-foot{margin-top:auto;padding-top:14px;border-top:1px solid #426258;color:#a6c0b2;font-size:10px;line-height:1.5}.chat-column{min-width:0;display:flex;flex-direction:column;overflow:hidden;padding:42px 44px 24px;background:linear-gradient(135deg,#f8f5ed,#f0eee5)}.eyebrow{color:#6d8b7e;font:10px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:1.5px}.thread-head{padding-bottom:17px;border-bottom:1px solid #d6d0c4}.thread-head h1{margin:9px 0 6px;color:#243c34;font:600 30px/1.2 Georgia,"Noto Serif SC",serif;letter-spacing:-.4px}.thread-head p{margin:0;color:#7a827a;font-size:12px}.meta-strip{display:flex;gap:24px;margin-top:18px;color:#7d877f;font-size:11px}.meta-strip b{margin-right:4px;color:#43715e;font:700 16px Georgia,serif}.question-card{margin-top:20px;padding:15px 18px 13px;border:1px solid #d2d5c9;border-radius:11px;background:#fbfaf5;box-shadow:0 12px 24px rgb(58 67 55 / .07)}.question-top{display:flex;align-items:center;justify-content:space-between;gap:10px}.question-label{color:#527265;font-size:11px;font-weight:700}.mode-note{color:#879187;font-size:10px}.mode-switch{display:flex;width:245px;margin-top:8px;padding:3px;border-radius:9px;background:#edf0e8}.mode-switch button{flex:1;padding:7px;border:0;border-radius:7px;color:#6e7c72;background:transparent;cursor:pointer;font-size:11px}.mode-switch button.active{color:#fff;background:#55796b;font-weight:700}.question-card textarea{display:block;width:100%;min-height:52px;margin-top:12px;padding:5px 0;border:0;resize:vertical;outline:none;color:#253b33;background:transparent;font:16px/1.55 "Noto Serif SC",Georgia,serif}.question-card textarea::placeholder{color:#889289}.question-actions{display:flex;align-items:center;justify-content:flex-end;color:#a0a79f;font-size:10px}.send-button,.follow-input button{border:0;border-radius:7px;color:#fff;background:#315d4e;cursor:pointer}.send-button{width:35px;height:35px;margin-left:12px;font-size:18px}.send-button:disabled{opacity:.45}.run-bar{display:flex;align-items:center;gap:8px;margin-top:10px;padding-top:10px;border-top:1px solid #e0ddd3;color:#537b6b;font-size:11px}.run-bar button,.request-error button{margin-left:auto;border:1px solid #b6cbbd;border-radius:5px;padding:5px 9px;color:#466d5e;background:#f6f8f1;cursor:pointer;font-size:11px}.spinner{width:10px;height:10px;border:2px solid #c9dbd0;border-top-color:#477764;border-radius:50%;animation:spin .8s linear infinite}.request-error{display:flex;gap:10px;margin-top:10px;padding:9px 10px;color:#974c3c;background:#f7e7de;font-size:11px}.conversation-head{display:flex;justify-content:space-between;align-items:center;margin-top:26px;padding-bottom:12px;border-bottom:1px solid #d6d0c4}.conversation-head button{font-size:11px}.message-list{min-height:0;flex:1;overflow-y:auto;padding:0 0 10px}.empty-state{padding:36px 8px}.empty-mark{display:grid;place-items:center;width:42px;height:42px;border-radius:50%;color:#fff;background:#648476;font:20px Georgia,serif}.empty-state h2{margin:14px 0 5px;font:600 21px Georgia,"Noto Serif SC",serif}.empty-state p{margin:0;color:#7d877e;font-size:13px}.message{padding:18px 0;border-bottom:1px solid #dedbd1}.message.assistant{padding-left:16px;border-left:2px solid #88aa99}.message-meta{display:flex;justify-content:space-between;color:#47705f;font-size:10px}.message.user .message-meta{color:#8a9189}.message p{max-width:780px;margin:8px 0 0;color:#334940;font:15px/1.85 "Noto Serif SC",Georgia,serif;white-space:pre-wrap;overflow-wrap:anywhere}.event-list,.citation-list{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.event-list span,.citation-list button{padding:5px 7px;border:1px solid #c2d1c7;border-radius:5px;color:#4d7866;background:#f0f5ed;font-size:10px}.citation-list button{cursor:pointer}.follow-up{padding-top:14px;border-top:1px solid #d5d1c7}.follow-up p{margin:8px 0;color:#7b857c;font-size:11px}.follow-input{display:flex;align-items:center;gap:9px;padding:9px 10px;border:1px solid #d1d4ca;border-radius:8px;background:#fbfaf5}.follow-input input{min-width:0;flex:1;border:0;outline:none;color:#2b4037;background:transparent;font-size:12px}.follow-input button{width:32px;height:32px}.evidence-panel{min-width:0;overflow-y:auto;margin:28px 28px 78px 0;padding:23px 20px;border:1px solid #d0d8ce;border-radius:11px;background:#eef2e9;box-shadow:0 12px 25px rgb(55 74 62 / .05)}.evidence-title{display:flex;justify-content:space-between;gap:10px;padding-bottom:14px;border-bottom:1px solid #d1d8ce}.evidence-title h2{margin:8px 0 0;font:600 22px Georgia,"Noto Serif SC",serif}.evidence-status{padding:5px 7px;border-radius:5px;color:#4d7865;background:#d9eadb;font-size:10px;align-self:flex-start}.evidence-placeholder{padding:18px 0;color:#7f8c84;font-size:12px;line-height:1.7}.trace-item{display:grid;width:100%;grid-template-columns:25px 1fr;gap:9px;padding:16px 0;border:0;border-bottom:1px solid #d4ddd3;color:inherit;background:transparent;text-align:left}.trace-item:disabled{opacity:.72}.trace-item:not(:disabled){cursor:pointer}.trace-item>span{color:#618a75;font:11px ui-monospace,monospace}.trace-item b{color:#2d5f4b;font-size:11px}.trace-item p{margin:5px 0 0;color:#708078;font-size:11px;line-height:1.5}.trace-item small{display:block;margin-top:7px;color:#6b8e7a;font-size:10px}.evidence-foot{display:flex;justify-content:space-between;gap:7px;margin-top:13px;padding-top:12px;border-top:1px solid #d1d8ce;color:#78857c;font-size:10px}.evidence-foot button{font-size:10px}.drawer-layer{position:fixed;inset:0;z-index:10;display:flex;justify-content:flex-end;background:rgb(25 48 40 / .25)}.drawer{width:min(500px,94vw);height:100%;overflow-y:auto;padding:46px 32px 38px;background:#fbfaf5;box-shadow:-18px 0 45px rgb(39 56 48 / .18)}.drawer-close{position:absolute;top:14px;right:18px;border:0;color:#557366;background:transparent;cursor:pointer;font-size:27px}.drawer h2{margin:10px 0 18px;color:#243b32;font:600 29px/1.2 Georgia,"Noto Serif SC",serif}.drawer-note{color:#78857c;font-size:12px;line-height:1.7}.document-row,.session-row{display:flex;align-items:center;gap:10px;width:100%;padding:14px 0;border:0;border-top:1px solid #dedbd2;color:#263f35;background:transparent;text-align:left;cursor:pointer}.document-row strong,.session-row strong{display:block;font-size:13px}.document-row small,.session-row small{display:block;margin-top:4px;color:#7d887e;font-size:10px}.row-arrow{margin-left:auto;color:#6e8b7b;font-size:20px}.primary-button,.danger-button{width:100%;margin-top:18px;padding:11px;border:0;border-radius:6px;color:#fff;background:#315d4e;cursor:pointer}.danger-button{background:#ab4d3c}.outline-button{padding:8px 10px;border:1px solid #adc4b5;border-radius:5px;color:#3e6d5b;background:#f5f7ef;cursor:pointer;font-size:11px}.danger-eyebrow{color:#a64e3e}.danger-box{padding:16px;border:1px solid #e0a893;background:#fbebe4}.danger-box strong{display:block;color:#913e32;font-size:14px}.danger-box p{margin:10px 0 0;color:#8a5a4c;font-size:12px;line-height:1.7}.drawer-actions{display:flex;gap:9px;margin-top:16px}.drawer-actions>*{flex:1}.detail-list{display:grid;gap:0;margin:0}.detail-list div{display:flex;justify-content:space-between;gap:15px;padding:12px 0;border-top:1px solid #e0ddd3;font-size:12px}.detail-list dt{color:#7c877e}.detail-list dd{margin:0;color:#2d483b;text-align:right}.preview-text{max-height:calc(100dvh - 190px);overflow:auto;white-space:pre-wrap;padding:14px;border:1px solid #dedbd2;color:#3f554b;background:#f1f2ea;font:13px/1.8 "Noto Serif SC",Georgia,serif}.drawer-trace{display:grid;width:100%;grid-template-columns:30px 1fr;gap:9px;padding:16px 0;border:0;border-top:1px solid #dedbd2;background:transparent;text-align:left;cursor:pointer}.drawer-trace>b{color:#5f8b72;font:11px ui-monospace,monospace}.drawer-trace span{color:#5d7167;font-size:12px;line-height:1.6}.drawer-trace strong{display:block;margin-bottom:4px;color:#2d503f}.mcp-card{padding:15px 0;border-top:1px solid #dedbd2}.mcp-card-head{display:flex;justify-content:space-between;align-items:center;gap:9px}.mcp-card small{display:block;margin-top:7px;color:#7a877f;font-size:11px}.tool-list{margin-top:12px;border-top:1px solid #e4e1d7}.tool-list label{display:flex;justify-content:space-between;gap:10px;padding:11px 0;border-bottom:1px solid #e4e1d7}.tool-list label strong,.tool-list label small{display:block}.tool-list label small{margin-top:3px;color:#7a877f;font-size:10px}.memory-item{display:grid;grid-template-columns:60px 1fr;gap:10px;padding:14px 0;border-top:1px solid #dedbd2;font-size:12px;line-height:1.6}.memory-item b{color:#477460;font-size:10px}.memory-item span{color:#40594d}.memory-item small{grid-column:2;color:#89938a;font-size:10px}.toast{position:fixed;right:22px;bottom:22px;z-index:20;max-width:380px;padding:12px 15px;color:#fff;background:#315d4e;box-shadow:0 10px 22px rgb(32 67 53 / .2);font-size:12px}@keyframes spin{to{transform:rotate(360deg)}}
@media (max-width:1120px){.app-shell{grid-template-columns:220px minmax(0,1fr)}.evidence-panel{display:none}.chat-column{padding-right:32px;padding-left:32px}}
@media (max-width:760px){.topbar{height:60px;padding:0 16px}.brand-sub,.crumb{display:none}.brand strong{font-size:13px}.top-actions{gap:8px}.service{font-size:10px}.app-shell{display:block;height:calc(100dvh - 60px)}.sidebar{display:grid;grid-template-columns:1fr 1fr;gap:12px;min-height:auto;padding:14px 16px}.nav-links,.recent,.sidebar-foot{display:none}.chat-column{height:calc(100dvh - 167px);padding:23px 17px 14px}.thread-head h1{font-size:24px}.question-top{align-items:flex-start;flex-direction:column}.mode-note{line-height:1.5}.mode-switch{width:100%}.question-card textarea{font-size:14px}.drawer{width:100%;padding:43px 21px 30px}.drawer h2{font-size:26px}.message p{font-size:14px}.meta-strip{gap:12px}}
@media (prefers-reduced-motion:reduce){.knownest *{animation-duration:.001ms!important;scroll-behavior:auto!important}}
</style>
<style scoped>
.chunking-entry-wrap{position:relative}
.chunking-entry{display:flex!important;align-items:center;gap:9px;width:100%;min-height:42px;padding:8px 9px!important;border:1px solid transparent!important;border-radius:8px;color:#30483d!important;text-align:left;background:transparent!important;font-size:14px!important}
.chunking-entry:hover,.chunking-entry:focus-visible,.chunking-entry.active{border-color:#b8cdbd!important;background:#e4ede5!important}
.chunking-entry:disabled{cursor:not-allowed;opacity:.5}
.chunking-entry span{font-weight:600}
.chunking-entry small{margin-left:auto;color:#71877b;font-size:11px}
.chunking-popover{position:absolute;z-index:12;top:calc(100% + 8px);left:0;width:310px;padding:19px 20px;border:1px solid #9db7a7;border-radius:11px;color:#40584c;background:#fffefb;box-shadow:0 14px 30px rgb(39 56 48 / .16)}
.chunking-popover:before{content:"";position:absolute;top:-8px;left:22px;width:14px;height:14px;border-top:1px solid #9db7a7;border-left:1px solid #9db7a7;background:#fffefb;transform:rotate(45deg)}
.chunking-popover strong{display:block;color:#345448;font-size:15px}
.chunking-popover p{margin:6px 0 14px;color:#87938c;font-size:11px;line-height:1.5}
.chunking-options{display:grid;gap:12px;padding-top:12px;border-top:1px solid #e1ddd3}
.chunking-option{display:flex;align-items:center;gap:10px;color:#69766f;font-size:13px;cursor:pointer}
.chunking-option input{width:16px;height:16px;margin:0;accent-color:#4f705f}
.chunking-option input:checked+span{color:#40584c;font-weight:600}
.chunking-advanced{display:block;margin:16px 0 0 auto;padding:8px 10px;border:0;border-radius:6px;color:#fffefb;background:#4f705f;cursor:pointer;font-size:11px}
.chunking-status{flex:0 0 auto;padding:6px 10px;border-radius:14px;color:#52745e;background:#e8efe8;font-size:11px;white-space:nowrap}
.chunking-settings{display:grid;gap:15px;margin-top:20px;padding:16px 0;border-top:1px solid #dedbd2;border-bottom:1px solid #dedbd2}
.chunking-settings label{display:grid;grid-template-columns:1fr 150px;align-items:center;gap:14px;color:#66746c;font-size:12px}
.chunking-settings select,.chunking-settings input[type=number]{width:100%;height:36px;padding:0 9px;border:1px solid #d0d6cc;border-radius:6px;color:#334d40;background:#fffefb;outline:none;font-size:12px}
.chunking-settings select:focus,.chunking-settings input:focus{border-color:#7fa18e;box-shadow:0 0 0 2px rgb(85 121 102 / .12)}
.chunking-settings .chunking-toggle{display:flex;grid-template-columns:none;gap:9px;cursor:pointer}
.chunking-toggle input{accent-color:#4f705f}
.compact-button{width:auto!important;margin-top:0!important;padding:9px 16px!important}
.chunking-warning{margin:14px 0 0;padding:10px 11px;border:1px solid #dccb9a;border-radius:6px;color:#816833;background:#fbf5df;font-size:12px;line-height:1.6}
.source-card:not(.source-card--trace){cursor:default}
.source-rank{display:grid;justify-items:end;gap:2px;flex:0 0 auto;padding:5px 8px;border-radius:5px;color:#315d4e;background:#e8efe8}
.source-rank small{color:#60746a;font-size:10px}
.source-rank b{color:#315d4e;font:600 13px/1.25 "Noto Sans SC","Microsoft YaHei",sans-serif;font-variant-numeric:tabular-nums}
.evidence-preview-note{display:block;margin:-3px 0 10px;color:#5f6e65;font-size:11px;line-height:1.5}
.source-actions{display:flex;align-items:center;flex-wrap:wrap;gap:14px;margin-top:10px;padding-top:9px;border-top:1px solid #e7e2d8}
.source-open:hover,.source-open:focus-visible{text-decoration:underline;text-underline-offset:3px}
.source-open:disabled{cursor:not-allowed;opacity:.55}
.preview-text mark{padding:1px 2px;border-radius:2px;color:#273b30;background:#e9dcae;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.original-source-button{margin-top:12px}
@media (min-width:1121px){.chunking-popover{top:44px;left:calc(100% - 56px)}.chunking-popover:before{top:24px;left:-8px;border-top:0;border-left:1px solid #9db7a7;border-bottom:1px solid #9db7a7}}
@media (max-width:1120px){.chunking-popover{left:auto;right:0}}
@media (max-width:760px){.chunking-entry-wrap{grid-column:1 / -1}.chunking-popover{position:fixed;top:132px;left:15px;right:15px;width:auto}.chunking-status{display:none}.chunking-settings label{grid-template-columns:1fr 125px}}
</style>
<style>
.knownest svg{display:block;fill:none;stroke:currentColor;stroke-width:1.35;stroke-linecap:round;stroke-linejoin:round}
.chat-column{background:#f5f2e9}
.nav-icon{width:17px;height:17px;flex:0 0 auto;color:#a8cfbd}
.mini-icon{width:14px;height:14px;flex:0 0 auto}
.send-button svg{width:18px;height:18px;margin:auto}
.drawer-close svg{width:18px;height:18px;margin:auto}
.row-arrow{width:18px;height:18px;flex:0 0 auto}
.text-danger-button{margin-top:12px;padding:4px 0;border:0;color:#a64e3e;background:transparent;cursor:pointer;font-size:11px;text-align:left}
.message.assistant{padding:18px 16px;background:#f1f4ec;border-radius:8px;border-left:0}
</style>
<style scoped>
.topbar{height:62px;padding:0 28px;background:#faf8f1}.brand-mark{width:31px;height:31px;border-radius:6px;font-size:18px}.brand strong{font-size:14px}.crumb{margin-left:30px}.app-shell{grid-template-columns:260px minmax(0,1fr) 360px;height:calc(100dvh - 62px);border-top:0}.sidebar{gap:20px;padding:24px 20px 18px;color:#283f35;background:#f4f1e8;border-right:1px solid #d9d3c7}.nav-group label,.recent label{color:#708075;letter-spacing:.08em}.nav-group select{border-color:#d4d0c5;color:#2d473a;background:#fbfaf5}.nav-group button,.upload-link{color:#356553}.nav-links{border-color:#ddd7ca}.nav-links button{color:#30483d}.nav-links button:hover,.nav-links button:focus-visible{background:#e5ebe1}.nav-links b{color:#537767}.nav-icon{color:#486d5b}.recent>button:not(.upload-link){color:#334d40}.recent>button:not(.upload-link):hover{background:#e8ede5}.recent small{color:#718077}.sidebar .status-indexed{color:#397358}.sidebar-foot{border-color:#ddd7ca;color:#748077}.chat-column{padding:0;min-height:0;background:#faf8f1}.conversation-toolbar{display:flex;align-items:center;justify-content:space-between;gap:24px;flex:0 0 auto;padding:23px 28px 18px;border-bottom:1px solid #ddd7ca}.conversation-context{display:flex;align-items:center;min-width:0;gap:13px}.conversation-context>svg{width:31px;height:31px;flex:0 0 auto;color:#466a58}.conversation-context h1{margin:0;color:#1f342b;font:600 21px/1.25 "Noto Serif SC","Songti SC",Georgia,serif;letter-spacing:0}.conversation-context p{margin:4px 0 0;color:#758078;font-size:12px}.document-link{flex:0 0 auto;padding:7px 0;border:0;color:#3e6c59;background:transparent;cursor:pointer;font-size:12px}.document-link:hover{text-decoration:underline;text-underline-offset:3px}.mode-bar{display:flex;align-items:center;gap:10px;flex:0 0 auto;min-height:56px;padding:10px 28px;border-bottom:1px solid #e2ddd2}.mode-bar button{width:142px;padding:8px 14px;border:1px solid #d1d0c6;color:#5b6b62;background:#faf9f4;cursor:pointer;font-size:13px}.mode-bar button:first-child{border-radius:8px 0 0 8px}.mode-bar button+button{margin-left:-11px;border-radius:0 8px 8px 0}.mode-bar button.active{position:relative;z-index:1;color:#fff;background:#557966;border-color:#557966}.mode-bar span{display:flex;align-items:center;gap:6px;margin-left:8px;color:#69766e;font-size:12px}.mode-bar span svg{width:16px;height:16px;color:#5d7468}.message-list{width:100%;padding:24px 28px 32px;scrollbar-color:#9aa69c transparent}.message{width:min(100%,790px);margin:0 auto;padding:21px 0;border:0}.message+.message{border-top:1px solid #e1dbd0}.message.user{width:min(100%,790px);padding:14px 17px;margin-top:6px;background:#edf1e9;border-radius:10px}.message.assistant{padding:27px 0!important;background:transparent!important;border-radius:0!important;border-left:0!important}.message-meta{justify-content:flex-start;gap:10px;color:#557565;font-size:11px}.message-meta span+span{color:#88938a}.message.user .message-meta{color:#637168}.message.user>p{max-width:none;margin:7px 0 0;color:#233b31;font:15px/1.7 "Noto Serif SC","Songti SC",Georgia,serif}.answer-body{max-width:740px;margin-top:10px;color:#273c33}.answer-body h2{margin:27px 0 9px;padding-top:22px;border-top:1px solid #ddd7ca;color:#1d3329;font:600 25px/1.3 "Noto Serif SC","Songti SC",Georgia,serif}.answer-body h2:first-child{margin-top:0;padding-top:0;border-top:0}.answer-body p{max-width:700px;margin:0;color:#31463c;font:16px/1.9 "Noto Serif SC","Songti SC",Georgia,serif;white-space:pre-wrap;overflow-wrap:anywhere}.event-list{margin-top:14px}.citation-list{margin-top:14px}.event-list span,.citation-list button{border-color:#cfd9ce;border-radius:5px;color:#3d6d59;background:#f4f7f1}.empty-state{width:min(100%,650px);margin:auto;padding:76px 0}.empty-mark{width:44px;height:44px;border-radius:8px}.empty-state h2{font:600 25px/1.3 "Noto Serif SC","Songti SC",Georgia,serif}.chat-composer{position:relative;z-index:2;flex:0 0 auto;margin:0 20px 18px;padding-top:14px;border-top:1px solid #ded8cd;background:#faf8f1}.composer-surface{display:flex;align-items:flex-end;gap:10px;min-height:55px;padding:9px 10px;border:1px solid #cfc9bd;border-radius:10px;background:#fffdfa;box-shadow:0 8px 18px rgb(46 58 49 / .08)}.attach-button{display:grid;place-items:center;width:34px;height:34px;border:0;border-radius:6px;color:#557363;background:transparent;cursor:pointer}.attach-button:hover,.attach-button:focus-visible{background:#e8eee6}.attach-button svg{width:20px;height:20px}.composer-surface textarea{min-width:0;max-height:96px;min-height:28px;flex:1;margin:0;padding:6px 0;border:0;resize:none;color:#263d33;background:transparent;font:15px/1.45 "Noto Serif SC","Songti SC",Georgia,serif}.composer-count{flex:0 0 auto;padding:0 2px 9px;color:#9aa198;font-size:10px}.send-button{display:grid;place-items:center;flex:0 0 auto;width:36px;height:36px;margin:0;border-radius:7px}.run-bar{margin:9px 2px 0;padding-top:0;border-top:0}.request-error{margin-top:9px;border-radius:6px}.evidence-panel{margin:0;min-height:0;padding:24px 21px 18px;border:0;border-left:1px solid #d9d3c7;border-radius:0;background:#f7f4ec;box-shadow:none}.evidence-title{padding-bottom:15px}.evidence-title h2{font-size:23px}.evidence-placeholder{padding-top:22px;line-height:1.75}.trace-item{padding:17px 0}.evidence-foot{margin-top:auto}.drawer{border-left:1px solid #d7d0c4;background:#fbf9f2}.knownest :focus-visible{outline:2px solid #557966;outline-offset:2px}.knownest ::selection{color:#fff;background:#557966}
.evidence-heading{display:flex;align-items:center;gap:12px}.evidence-heading>svg{width:28px;height:28px;flex:0 0 auto;color:#8a5d3d;stroke-width:1.5}.evidence-title h2{margin-top:5px;font-size:25px;letter-spacing:-.02em}.source-card{position:relative;margin-top:14px;padding:15px 14px 14px;border:1px solid #dfdcd2;border-radius:9px;background:#fbfaf5;cursor:pointer;transition:border-color .18s ease,box-shadow .18s ease,transform .18s ease}.source-card:hover,.source-card:focus-within{border-color:#9fb9aa;box-shadow:0 8px 18px rgb(54 72 59 / .08);transform:translateY(-1px)}.source-card--trace{cursor:default}.source-card-head{display:flex;align-items:flex-start;gap:9px}.source-index{display:none;color:#6a8878;font:11px ui-monospace,SFMono-Regular,monospace}.source-file{display:flex;align-items:center;min-width:0;gap:9px;flex:1}.file-icon{display:grid;place-items:center;width:26px;height:30px;flex:0 0 auto;border-radius:4px;color:#fff;background:#3778ba;font:700 14px/1 Arial,sans-serif}.source-file strong{display:block;overflow:hidden;color:#2a3d34;font-size:13px;line-height:1.3;text-overflow:ellipsis;white-space:nowrap}.source-file small{display:block;margin-top:4px;color:#7a847e;font-size:11px}.source-score{display:flex;flex-direction:column;align-items:flex-end;flex:0 0 auto}.source-score small{color:#7f877f;font-size:10px}.source-score b{margin-top:1px;color:#1f332b;font:500 18px/1.1 Georgia,"Noto Serif SC",serif}.source-card blockquote{margin:13px 0 11px;padding:10px 11px;border:0;border-radius:7px;color:#405248;background:#f4f1e9;font:14px/1.65 "Noto Serif SC","Songti SC",serif;overflow-wrap:anywhere}.trace-detail{margin:13px 0 0;color:#6f7d74;font-size:12px;line-height:1.6}.source-open{display:inline-flex;align-items:center;gap:5px;padding:0;border:0;color:#2e5e4b;background:transparent;cursor:pointer;font-size:12px;font-weight:600}.source-open span{font-size:15px;line-height:1}.evidence-panel>.evidence-foot{position:sticky;bottom:0;margin-top:16px;padding:12px 0 2px;background:#f7f4ec}
.app-shell{grid-template-columns:278px minmax(0,1fr) 386px}.sidebar{padding-left:22px;padding-right:22px}.nav-group select{height:44px;font-size:14px}.nav-group label,.recent label{font-size:11px}.nav-group button,.upload-link{font-size:13px}.nav-links button{font-size:14px;padding-top:11px;padding-bottom:11px}.recent-name{font-size:12px}.recent small{font-size:10px}.sidebar-foot{font-size:11px}
.message--streaming .answer-body{position:relative}.streaming-label{display:inline-flex;align-items:center;gap:6px;color:#4f7967!important}.streaming-dot{width:6px;height:6px;border-radius:50%;background:#5d9079;animation:streamPulse 1s ease-in-out infinite}.answer-placeholder{color:#7d8b83!important}.loading-ellipsis{display:inline-block;width:1.4em;overflow:hidden;vertical-align:bottom;animation:ellipsis 1.2s steps(4,end) infinite}.stream-cursor{display:inline-block;width:2px;height:1.1em;margin-left:4px;vertical-align:-.18em;background:#4f806b;animation:cursorBlink .9s steps(1,end) infinite}.message-list{overflow-anchor:none}
@media (max-width:1120px){.app-shell{grid-template-columns:240px minmax(0,1fr)}.chat-column{padding:0}.conversation-toolbar,.mode-bar{padding-left:24px;padding-right:24px}.message-list{padding-left:24px;padding-right:24px}}
@media (max-width:760px){.topbar{height:56px;padding:0 15px}.app-shell{height:calc(100dvh - 56px)}.sidebar{padding:10px 15px;background:#f4f1e8;border-bottom:1px solid #d9d3c7}.conversation-toolbar{padding:17px 17px 14px}.conversation-context h1{font-size:18px}.conversation-context p{font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.conversation-context>svg{width:25px;height:25px}.document-link{font-size:11px}.mode-bar{min-height:52px;padding:8px 17px;gap:5px;overflow-x:auto}.mode-bar button{width:128px;flex:0 0 128px;font-size:12px}.mode-bar span{display:none}.message-list{padding:18px 17px 23px}.message{padding:17px 0}.message.user{padding:12px 14px}.answer-body h2{font-size:21px}.answer-body p,.message.user>p{font-size:15px;line-height:1.8}.chat-composer{margin:0 12px 12px;padding-top:10px}.composer-count{display:none}.composer-surface{min-height:51px}.evidence-panel{display:none}.empty-state{padding:45px 0}.empty-state h2{font-size:22px}}
</style>
