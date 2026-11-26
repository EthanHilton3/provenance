import { createRouter, createWebHistory } from 'vue-router'
import { auth, authReady } from './lib/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'items', component: () => import('./views/ItemsView.vue') },
    { path: '/items/new', name: 'add', component: () => import('./views/AddItemView.vue') },
    { path: '/items/:id', name: 'item', component: () => import('./views/ItemDetailView.vue'), props: true },
    { path: '/scan', name: 'scan', component: () => import('./views/ScanView.vue') },
    { path: '/intake', name: 'intake', component: () => import('./views/IntakeView.vue') },
    { path: '/intake/:id', name: 'review', component: () => import('./views/ReviewView.vue'), props: true, meta: { wide: true } },
    { path: '/signin', name: 'signin', component: () => import('./views/SignInView.vue'), meta: { public: true } },
    { path: '/:rest(.*)*', redirect: '/' },
  ],
  scrollBehavior: (_to, _from, saved) => saved || { top: 0 },
})

router.beforeEach(async (to) => {
  await authReady
  if (!to.meta.public && !auth.user) return { name: 'signin', query: { redirect: to.fullPath } }
  if (to.name === 'signin' && auth.user) return { name: 'items' }
})

export default router
