import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/login' },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
    },
    { path: '/runtime', redirect: '/runtime/rag' },
    {
      path: '/runtime/:mode(rag|agent)',
      name: 'python-runtime',
      component: () => import('../views/python/RuntimeApp.vue'),
    },
    { path: '/:pathMatch(.*)*', redirect: '/login' },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('knownest_python_token')
  if (to.path.startsWith('/runtime') && !token) return '/login'
  if (to.path === '/login' && token) return '/runtime/rag'
  return true
})

export default router
