const apiBase = (import.meta.env.VITE_PYTHON_API_BASE || 'http://localhost:8000/api/v1').replace(/\/$/, '')

export type JobStatus = 'pending' | 'processing' | 'parsed' | 'embedding' | 'indexed' | 'failed' | 'deleting' | 'deleted'
export type ChunkingStrategy = 'auto' | 'heading' | 'heuristic' | 'recursive' | 'legacy'
export type ChunkingConfig = { strategy: ChunkingStrategy; chunk_size: number; chunk_overlap: number; separators: string[]; token_limit: number; languages: string[]; enable_parent_child: boolean; parent_chunk_size: number }

function getToken() { return localStorage.getItem('weknora_python_token') || '' }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (!(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const token = getToken(); if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${apiBase}${path}`, { ...init, headers })
  if (!response.ok) {
    const body = await response.text(); let detail = body || `Request failed: ${response.status}`
    try { const parsed = JSON.parse(body); detail = Array.isArray(parsed.detail) ? parsed.detail.map((item: any) => item.msg).join(', ') : parsed.detail || detail } catch { /* keep plain response */ }
    throw new Error(detail)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export const runtimeAuth = {
  setupStatus: () => request<{ initialized: boolean }>('/auth/setup-status'),
  setup: (username: string, password: string) => request<{ token: string; user: any; workspace: any }>('/auth/setup', { method: 'POST', body: JSON.stringify({ username, password }) }),
  login: (username: string, password: string) => request<{ token: string; user: any }>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
}

export const runtimeApi = {
  ready: () => request<{ status: string }>('/ready'),
  workspaces: () => request<any[]>('/workspaces'),
  createWorkspace: (name: string) => request<any>('/workspaces', { method: 'POST', body: JSON.stringify({ name }) }),
  knowledgeBases: (workspaceId: string) => request<any[]>(`/knowledge-bases?workspace_id=${encodeURIComponent(workspaceId)}`),
  chunkingConfig: (kbId: string) => request<{ knowledge_base_id: string; chunking_config: ChunkingConfig; version: number; needs_reindex: boolean }>(`/knowledge-bases/${kbId}/chunking-config`),
  updateChunkingConfig: (kbId: string, config: ChunkingConfig) => request<any>(`/knowledge-bases/${kbId}/chunking-config`, { method: 'PUT', body: JSON.stringify(config) }),
  createKnowledgeBase: (workspaceId: string, name: string) => request<any>('/knowledge-bases', { method: 'POST', body: JSON.stringify({ workspace_id: workspaceId, name }) }),
  folders: (kbId: string) => request<any[]>(`/knowledge-bases/${kbId}/folders/tree`),
  createFolder: (kbId: string, name: string, parentId: string | null) => request<any>(`/knowledge-bases/${kbId}/folders`, { method: 'POST', body: JSON.stringify({ name, parent_id: parentId }) }),
  documents: (kbId: string) => request<any[]>(`/knowledge-bases/${kbId}/documents`),
  document: (documentId: string) => request<any>(`/documents/${documentId}`),
  previewDocument: (documentId: string) => request<any>(`/documents/${documentId}/preview`),
  deleteDocument: (documentId: string) => request<void>(`/documents/${documentId}`, { method: 'DELETE' }),
  reindexDocument: (documentId: string) => request<any>(`/documents/${documentId}/reindex`, { method: 'POST' }),
  documentChunks: (documentId: string) => request<any[]>(`/documents/${documentId}/chunks`),
  job: (jobId: string) => request<any>(`/jobs/${jobId}`),
  citation: (chunkId: string) => request<any>(`/chunks/${chunkId}/citation`),
  uploadDocument: async (kbId: string, file: File, folderId?: string) => {
    const headers = new Headers({ 'Content-Type': file.type || 'application/octet-stream' })
    const token = getToken(); if (token) headers.set('Authorization', `Bearer ${token}`)
    const params = new URLSearchParams({ filename: file.name }); if (folderId) params.set('folder_id', folderId)
    const response = await fetch(`${apiBase}/knowledge-bases/${kbId}/documents?${params}`, { method: 'POST', headers, body: file })
    if (!response.ok) throw new Error(await response.text() || `Upload failed: ${response.status}`)
    return response.json()
  },
  createSession: (mode: 'rag' | 'agent', workspaceId: string, kbId: string, modelId?: string) => request<any>(`/${mode}/sessions`, { method: 'POST', body: JSON.stringify({ workspace_id: workspaceId, knowledge_base_id: kbId, model_id: modelId || null }) }),
  sessions: (mode: 'rag' | 'agent', workspaceId: string) => request<any[]>(`/${mode}/sessions?workspace_id=${encodeURIComponent(workspaceId)}`),
  session: (mode: 'rag' | 'agent', sessionId: string) => request<any>(`/${mode}/sessions/${sessionId}`),
  createConversation: (workspaceId: string, kbId: string, modelId?: string) => request<any>('/conversations', { method: 'POST', body: JSON.stringify({ workspace_id: workspaceId, knowledge_base_id: kbId, model_id: modelId || null }) }),
  conversations: (workspaceId: string, kbId?: string) => request<any[]>(`/conversations?workspace_id=${encodeURIComponent(workspaceId)}${kbId ? `&knowledge_base_id=${encodeURIComponent(kbId)}` : ''}`),
  conversation: (conversationId: string) => request<any>(`/conversations/${conversationId}`),
  cancelConversation: (conversationId: string) => request<any>(`/conversations/${conversationId}/cancel`, { method: 'POST' }),
  cancelAgent: (sessionId: string) => request<any>(`/agent/sessions/${sessionId}/cancel`, { method: 'POST' }),
  models: (workspaceId: string) => request<any[]>(`/workspaces/${workspaceId}/models`),
  memories: (workspaceId: string) => request<any[]>(`/workspaces/${workspaceId}/memories`),
  createMemory: (workspaceId: string, payload: any) => request<any>(`/workspaces/${workspaceId}/memories`, { method: 'POST', body: JSON.stringify({ ...payload, workspace_id: workspaceId }) }),
  updateMemory: (memoryId: string, payload: any) => request<any>(`/memories/${memoryId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  confirmMemory: (memoryId: string) => request<any>(`/memories/${memoryId}/confirm`, { method: 'POST' }),
  rejectMemory: (memoryId: string) => request<any>(`/memories/${memoryId}/reject`, { method: 'POST' }),
  deleteMemory: (memoryId: string) => request<void>(`/memories/${memoryId}`, { method: 'DELETE' }),
  mcpServers: (workspaceId: string) => request<any[]>(`/workspaces/${workspaceId}/mcp-servers`),
  mcpServer: (serverId: string) => request<any>(`/mcp-servers/${serverId}`),
  mcpTools: (serverId: string) => request<any[]>(`/mcp-servers/${serverId}/tools`),
  addMcpServer: (workspaceId: string, payload: any) => request<any>(`/workspaces/${workspaceId}/mcp-servers`, { method: 'POST', body: JSON.stringify({ ...payload, workspace_id: workspaceId }) }),
  updateMcpServer: (serverId: string, payload: any) => request<any>(`/mcp-servers/${serverId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteMcpServer: (serverId: string) => request<void>(`/mcp-servers/${serverId}`, { method: 'DELETE' }),
  connectMcp: (serverId: string) => request<any>(`/mcp-servers/${serverId}/connect`, { method: 'POST' }),
  discoverMcp: (serverId: string) => request<any>(`/mcp-servers/${serverId}/discover`, { method: 'POST' }),
  updateMcpTool: (toolId: string, enabled: boolean) => request<any>(`/mcp-tools/${toolId}?enabled=${enabled}`, { method: 'PATCH' }),
}

export async function streamMessage(path: string, payload: string | Record<string, unknown>, onEvent: (event: any) => void, options: { signal?: AbortSignal } = {}) {
  const headers = new Headers({ 'Content-Type': 'application/json', Accept: 'text/event-stream' })
  const token = getToken(); if (token) headers.set('Authorization', `Bearer ${token}`)
  const body = typeof payload === 'string' ? { content: payload } : payload
  const response = await fetch(`${apiBase}${path}`, { method: 'POST', headers, body: JSON.stringify(body), signal: options.signal })
  if (!response.ok || !response.body) throw new Error((await response.text()) || 'Stream failed')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const consumeFrame = (frame: string) => {
    const data = frame
      .split(/\r?\n/)
      .filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart())
      .join('\n')
    if (!data || data === '[DONE]') return
    try { onEvent(JSON.parse(data)) } catch { /* one malformed frame must not end the stream */ }
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() || ''
    frames.forEach(consumeFrame)
    if (done) break
  }
  if (buffer.trim()) consumeFrame(buffer)
}
