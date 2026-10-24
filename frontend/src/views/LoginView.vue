<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { runtimeApi, runtimeAuth } from '../api/python-runtime'

type FormMode = 'login' | 'setup'
type CheckState = 'checking' | 'ready' | 'offline' | 'unknown'

const router = useRouter()
const formMode = ref<FormMode>('login')
const username = ref('')
const password = ref('')
const showPassword = ref(false)
const setupKnown = ref<boolean | null>(null)
const serviceState = ref<CheckState>('checking')
const accountState = ref<CheckState>('checking')
const checking = ref(true)
const submitting = ref(false)
const formError = ref('')
const statusError = ref('')
const usernameError = ref('')
const passwordError = ref('')
const usernameInput = ref<HTMLInputElement | null>(null)

const isSetup = computed(() => formMode.value === 'setup')
const pageTitle = computed(() => isSetup.value ? '创建你的本地知识空间' : '欢迎回到 KNOWNEST')
const pageIntro = computed(() => isSetup.value ? '创建首个账号，同时初始化一个默认工作区。' : '使用本地账号继续访问你的文档、知识库与对话。')
const submitLabel = computed(() => isSetup.value ? '创建账号并进入' : '登录 KNOWNEST')
const serviceLabel = computed(() => ({ checking: '正在检查服务', ready: '服务已就绪', offline: '服务不可用', unknown: '服务状态未知' })[serviceState.value])
const accountLabel = computed(() => {
  if (accountState.value === 'checking') return '正在读取账号状态'
  if (accountState.value === 'offline') return '无法读取账号状态'
  return setupKnown.value ? '已有账号，可直接登录' : '尚未初始化，可创建首个账号'
})

function clearErrors() {
  formError.value = ''
  usernameError.value = ''
  passwordError.value = ''
}

function validateForm() {
  clearErrors()
  const name = username.value.trim()
  if (name.length < 3) usernameError.value = '用户名至少需要 3 个字符。'
  if (name.length > 120) usernameError.value = '用户名不能超过 120 个字符。'
  if (password.value.length < 8) passwordError.value = '密码至少需要 8 个字符。'
  if (password.value.length > 72) passwordError.value = '密码不能超过 72 个字符。'
  return !usernameError.value && !passwordError.value
}

async function refreshStatus() {
  checking.value = true
  statusError.value = ''
  const [readyResult, setupResult] = await Promise.allSettled([runtimeApi.ready(), runtimeAuth.setupStatus()])
  serviceState.value = readyResult.status === 'fulfilled' ? 'ready' : 'offline'
  if (setupResult.status === 'fulfilled') {
    setupKnown.value = setupResult.value.initialized
    accountState.value = 'ready'
    formMode.value = setupResult.value.initialized ? 'login' : 'setup'
  } else {
    accountState.value = 'offline'
    statusError.value = '暂时无法读取账号状态，请确认本地服务已启动后重试。'
  }
  checking.value = false
  await nextTick()
  usernameInput.value?.focus()
}

function chooseMode(mode: FormMode) {
  if (mode === 'setup' && setupKnown.value === true) return
  formMode.value = mode
  clearErrors()
  password.value = ''
  nextTick(() => usernameInput.value?.focus())
}

async function submit() {
  if (submitting.value || !validateForm()) return
  submitting.value = true
  try {
    const response = isSetup.value
      ? await runtimeAuth.setup(username.value.trim(), password.value)
      : await runtimeAuth.login(username.value.trim(), password.value)
    localStorage.setItem('knownest_python_token', response.token)
    await router.replace('/runtime/rag')
  } catch (error: any) {
    const message = String(error?.message || '')
    if (isSetup.value && /setup already completed/i.test(message)) {
      await refreshStatus()
      formMode.value = 'login'
      formError.value = '首个账号已完成初始化，请使用该账号登录。'
    } else if (/invalid username or password/i.test(message)) {
      formError.value = '用户名或密码不正确，请检查后重试。'
    } else if (/failed to fetch|networkerror|load failed/i.test(message)) {
      formError.value = '暂时无法连接本地服务，请检查服务状态后重试。'
    } else {
      formError.value = message || '请求未完成，请稍后重试。'
    }
  } finally {
    submitting.value = false
  }
}

onMounted(refreshStatus)
</script>

<template>
  <main class="login-page">
    <aside class="brand-rail" aria-labelledby="brand-title">
      <div>
        <div class="brand-lockup"><span class="brand-mark" aria-hidden="true">K</span><span id="brand-title">KNOWNEST</span></div>
        <p class="brand-kicker">LOCAL KNOWLEDGE RUNTIME</p>
        <div class="rail-rule" aria-hidden="true"></div>
        <h2>把答案留在<br />可追溯的来源里。</h2>
        <p class="rail-copy">KNOWNEST 将文档、检索和研究工作放在同一个本地工作区中，让每个回答都能回到它的依据。</p>
        <ul class="principles" aria-label="产品能力">
          <li><span class="line-mark" aria-hidden="true"></span><span>文档检索与知识问答</span></li>
          <li><span class="line-mark" aria-hidden="true"></span><span>可打开的引用证据</span></li>
          <li><span class="line-mark" aria-hidden="true"></span><span>RAG 与 Agent 研究模式</span></li>
        </ul>
      </div>
      <p class="rail-foot">LOCAL-FIRST<br />账号与资料属于当前运行环境</p>
    </aside>

    <section class="form-column" aria-labelledby="login-title">
      <header class="page-heading"><p class="section-label">ACCOUNT ACCESS</p><h1 id="login-title">进入 KNOWNEST</h1><p>从这里开始管理你的本地知识空间。</p></header>
      <form class="auth-form" @submit.prevent="submit" novalidate>
        <div class="form-heading"><h2>{{ pageTitle }}</h2><p>{{ pageIntro }}</p></div>
        <div class="mode-switch" role="group" aria-label="账号操作">
          <button type="button" :aria-pressed="formMode === 'login'" :class="{ active: formMode === 'login' }" @click="chooseMode('login')">登录</button>
          <button type="button" :aria-pressed="formMode === 'setup'" :disabled="setupKnown === true" :class="{ active: formMode === 'setup' }" @click="chooseMode('setup')">首次初始化</button>
        </div>
        <div class="field-group"><label for="username">用户名</label><input id="username" ref="usernameInput" v-model="username" autocomplete="username" minlength="3" maxlength="120" required :aria-invalid="Boolean(usernameError)" :aria-describedby="usernameError ? 'username-error' : 'username-hint'" placeholder="输入本地用户名" /><small id="username-hint">3–120 个字符</small><small v-if="usernameError" id="username-error" class="field-error">{{ usernameError }}</small></div>
        <div class="field-group"><label for="password">密码</label><div class="password-wrap"><input id="password" v-model="password" :type="showPassword ? 'text' : 'password'" :autocomplete="isSetup ? 'new-password' : 'current-password'" minlength="8" maxlength="72" required :aria-invalid="Boolean(passwordError)" :aria-describedby="passwordError ? 'password-error' : 'password-hint'" placeholder="输入密码" /><button class="password-toggle" type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.4-5 9.5-5 9.5 5 9.5 5-3.4 5-9.5 5-9.5-5-9.5-5Z" /><circle cx="12" cy="12" r="2.5" /></svg></button></div><small id="password-hint">8–72 个字符</small><small v-if="passwordError" id="password-error" class="field-error">{{ passwordError }}</small></div>
        <div v-if="formError" class="form-error" role="alert">{{ formError }}</div>
        <button class="submit-button" type="submit" :disabled="submitting || checking || serviceState === 'offline'"><span v-if="submitting" class="button-spinner" aria-hidden="true"></span>{{ submitting ? '正在处理…' : submitLabel }}</button>
        <p class="form-note" v-if="isSetup">创建成功后会自动建立默认工作区。</p><p class="form-note" v-else>登录后将进入知识库与对话工作台。</p>
      </form>
    </section>

    <aside class="status-rail" aria-labelledby="status-title">
      <h2 id="status-title">本地运行状态</h2><p class="status-lead">提交前会检查服务和账号初始化状态。</p><div class="rail-rule" aria-hidden="true"></div>
      <section class="status-block" aria-live="polite"><div class="status-heading"><h3>服务</h3><span class="state-dot" :class="serviceState"></span></div><strong>{{ serviceLabel }}</strong><p v-if="serviceState === 'ready'">可以提交登录请求。</p><p v-else-if="serviceState === 'offline'">请确认后端已在本地运行。</p><p v-else>正在连接后端服务。</p></section>
      <section class="status-block" aria-live="polite"><div class="status-heading"><h3>账号</h3><span class="state-dot" :class="accountState"></span></div><strong>{{ accountLabel }}</strong><p v-if="setupKnown === true">已有账号时，首次初始化入口会保持关闭。</p><p v-else-if="setupKnown === false">这是这个运行环境的第一次使用。</p><p v-else>等待后端返回账号状态。</p></section>
      <section class="status-block status-note"><h3>关于首次使用</h3><p>没有账号时，创建的第一个用户会同时获得默认工作区。登录页不会显示当前服务未实现的找回密码或第三方登录入口。</p></section>
      <div v-if="statusError" class="status-error" role="status"><p>{{ statusError }}</p><button type="button" @click="refreshStatus">重新检查</button></div><button v-else-if="serviceState === 'offline'" class="status-retry" type="button" @click="refreshStatus">重新检查服务</button>
    </aside>
  </main>
</template>

<style scoped>
:global(*) { box-sizing: border-box; }
:global(html) { min-width: 320px; background: #f5f2e9; }
:global(body) { margin: 0; min-width: 320px; min-height: 100vh; background: #f5f2e9; color: #292a24; font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif; }
:global(button), :global(input) { font: inherit; }
:global(button:focus-visible), :global(input:focus-visible) { outline: 3px solid #9ab6a4; outline-offset: 3px; }
:global(::selection) { color: #f5f2e9; background: #526f60; }
.login-page { display: grid; grid-template-columns: minmax(220px, .82fr) minmax(420px, 1.55fr) minmax(260px, .9fr); width: min(1440px, 100%); min-height: 100vh; margin: 0 auto; background: #f5f2e9; overflow-x: clip; }
.brand-rail, .form-column, .status-rail { min-width: 0; padding: clamp(28px, 5vw, 64px) clamp(20px, 3.5vw, 54px); }
.brand-rail { display: flex; flex-direction: column; justify-content: space-between; border-right: 1px solid #d8d2c5; background: #edf0e7; }
.brand-lockup { display: flex; align-items: center; gap: 12px; color: #263f34; font: 700 clamp(18px, 2vw, 25px)/1 Georgia, "Noto Serif SC", serif; letter-spacing: .08em; }
.brand-mark { display: grid; place-items: center; width: 36px; height: 36px; border: 1px solid #657f70; border-radius: 50%; color: #4f705f; font: 700 18px/1 Georgia, serif; }
.brand-kicker, .section-label, .rail-foot { color: #738275; font: 10px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .12em; }
.brand-kicker { margin: 12px 0 0 48px; }
.rail-rule { width: 100%; margin: 28px 0; border: 0; border-top: 1px solid #d8d2c5; }
.brand-rail h2 { margin: 0; color: #2e4439; font: 600 clamp(24px, 2.7vw, 36px)/1.25 Georgia, "Noto Serif SC", serif; letter-spacing: -.02em; }
.rail-copy, .status-lead, .status-block p, .page-heading > p, .form-heading p, .form-note { color: #66736a; font-size: 14px; line-height: 1.8; }
.rail-copy { max-width: 30ch; margin: 22px 0 0; }
.principles { display: grid; gap: 0; margin: 36px 0 0; padding: 0; list-style: none; }
.principles li { display: flex; align-items: center; gap: 12px; padding: 13px 0; border-top: 1px solid #d8d2c5; color: #405a4c; font-size: 13px; }
.line-mark { width: 18px; height: 1px; background: #6b8978; }
.rail-foot { margin: 32px 0 0; letter-spacing: .07em; }
.form-column { display: flex; flex-direction: column; justify-content: center; padding-inline: clamp(28px, 5.4vw, 86px); }
.page-heading { border-bottom: 1px solid #d8d2c5; padding-bottom: 20px; }
.section-label { margin: 0 0 14px; color: #6e8778; }
.page-heading h1 { margin: 0; color: #293b32; font: 600 clamp(27px, 3vw, 42px)/1.15 Georgia, "Noto Serif SC", serif; letter-spacing: -.02em; }
.page-heading > p:not(.section-label) { margin: 11px 0 0; }
.auth-form { width: min(100%, 560px); margin: clamp(34px, 7vh, 78px) auto 0; padding: clamp(26px, 4vw, 42px); border: 1px solid #d8d2c5; border-radius: 10px; background: #faf8f1; box-shadow: 0 14px 28px rgb(56 70 58 / 8%); min-width: 0; }
.form-heading h2 { margin: 0; color: #2c3e34; font: 600 clamp(25px, 2.5vw, 34px)/1.25 Georgia, "Noto Serif SC", serif; }
.form-heading p { margin: 10px 0 0; }
.mode-switch { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px; width: 100%; margin: 28px 0 24px; padding: 4px; border-radius: 7px; background: #e9eee7; min-width: 0; }
.mode-switch button { min-width: 0; min-height: 42px; padding-inline: 4px; border: 0; border-radius: 5px; color: #637167; background: transparent; cursor: pointer; font-size: 14px; white-space: normal; }
.mode-switch button.active { color: #f8fbf4; background: #5d7c6b; font-weight: 700; }
.mode-switch button:disabled { cursor: not-allowed; opacity: .45; }
.field-group { display: grid; gap: 8px; min-width: 0; margin-top: 19px; }
.field-group label { color: #3c5146; font-size: 14px; font-weight: 700; }
.field-group input { width: 100%; max-width: 100%; min-width: 0; min-height: 50px; border: 1px solid #c7cec3; border-radius: 6px; padding: 12px 14px; color: #2b4035; background: #fffdf8; font-size: 16px; }
.field-group input::placeholder { color: #879188; }
.field-group input[aria-invalid="true"] { border-color: #ae6652; }
.field-group small { color: #7c877e; font-size: 11px; }
.field-group .field-error { color: #9a4d3d; }
.password-wrap { position: relative; min-width: 0; }
.password-wrap input { padding-right: 52px; }
.password-toggle { position: absolute; top: 50%; right: 8px; display: grid; place-items: center; width: 36px; height: 36px; transform: translateY(-50%); border: 0; border-radius: 5px; color: #597565; background: transparent; cursor: pointer; }
.password-toggle:hover { background: #edf1e9; }
.password-toggle svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.6; }
.form-error, .status-error { border: 1px solid #e0b2a2; color: #8f4638; background: #fbebe4; font-size: 13px; line-height: 1.6; }
.form-error { margin-top: 18px; padding: 11px 12px; }
.submit-button { display: flex; align-items: center; justify-content: center; gap: 9px; width: 100%; min-height: 50px; margin-top: 27px; border: 0; border-radius: 6px; color: #f8fbf4; background: #4f705f; cursor: pointer; font-size: 16px; font-weight: 700; }
.submit-button:hover:not(:disabled) { background: #3f604f; }
.submit-button:disabled { cursor: wait; opacity: .62; }
.button-spinner { width: 16px; height: 16px; border: 2px solid rgb(248 251 244 / 45%); border-top-color: #f8fbf4; border-radius: 50%; animation: spin .8s linear infinite; }
.form-note { margin: 18px 0 0; text-align: center; font-size: 12px; }
.status-rail { border-left: 1px solid #d8d2c5; background: #f1f0e8; }
.status-rail > h2 { margin: 0; color: #31483b; font: 600 clamp(22px, 2vw, 28px)/1.25 Georgia, "Noto Serif SC", serif; }
.status-lead { margin: 12px 0 0; font-size: 13px; }
.status-rail .rail-rule { margin-block: 24px; }
.status-block { padding: 0 0 21px; margin-bottom: 21px; border-bottom: 1px solid #d8d2c5; }
.status-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.status-block h3 { margin: 0 0 10px; color: #53685b; font-size: 12px; letter-spacing: .08em; }
.status-block strong { display: block; color: #2e483a; font: 600 17px/1.4 Georgia, "Noto Serif SC", serif; }
.status-block p { margin: 7px 0 0; font-size: 12px; line-height: 1.65; }
.state-dot { width: 9px; height: 9px; border-radius: 50%; background: #a7b0a8; }
.state-dot.ready { background: #5d9778; }
.state-dot.offline { background: #b36551; }
.state-dot.checking { background: #bd9657; animation: pulse 1.2s ease-in-out infinite; }
.status-note p { max-width: 31ch; }
.status-error { padding: 12px; }
.status-error p { margin: 0; }
.status-error button, .status-retry { margin-top: 11px; border: 1px solid #b7cabc; border-radius: 5px; padding: 8px 10px; color: #436b57; background: #f7faf3; cursor: pointer; font-size: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse { 50% { opacity: .35; } }
@media (max-width: 1080px) { .login-page { grid-template-columns: minmax(210px, .72fr) minmax(0, 1.28fr); } .status-rail { grid-column: 2; border-top: 1px solid #d8d2c5; border-left: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 24px; } .status-rail > h2, .status-rail > .status-lead, .status-rail > .rail-rule, .status-rail > .status-error, .status-rail > .status-retry { grid-column: 1 / -1; } .status-note { grid-column: 1 / -1; } }
@media (max-width: 760px) { .login-page { display: block; min-height: 100vh; } .brand-rail, .form-column, .status-rail { width: 100%; max-width: 100%; padding: 24px 20px; } .brand-rail { display: block; border-right: 0; border-bottom: 1px solid #d8d2c5; } .brand-kicker { display: inline-block; margin: 0 0 0 12px; } .brand-rail .rail-rule, .brand-rail h2, .brand-rail .rail-copy, .principles, .rail-foot { display: none; } .form-column { display: block; } .page-heading { padding-bottom: 16px; } .auth-form { width: 100%; max-width: 100%; margin-top: 26px; padding: 24px 20px; } .status-rail { display: block; border-top: 1px solid #d8d2c5; } .status-rail .status-block { margin-bottom: 20px; } }
@media (prefers-reduced-motion: reduce) { .state-dot, .button-spinner { animation-duration: .001ms !important; } }
</style>
