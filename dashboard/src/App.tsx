import { useState, useEffect } from 'react'
import {
  Zap,
  Users,
  Database,
  Cpu,
  Plus,
  RefreshCw,
  Trash2,
  Play,
  CheckCircle2,
  Clock,
  AlertCircle,
  ExternalLink,
  Settings,
  Activity,
  Sparkles,
  Link2,
  ChevronRight,
  Loader2,
  MessageSquare,
  BookOpen,
  LogIn,
  ShieldCheck,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Toaster } from '@/components/ui/sonner'
import { toast } from 'sonner'
import { ScrollArea } from '@/components/ui/scroll-area'
import KnowledgeDoc from './KnowledgeDoc'

const API_BASE = import.meta.env.VITE_API_BASE || ''

interface Blogger {
  id: number
  sec_user_id: string
  nickname: string
  avatar_url: string
  signature: string
  follower_count: number
  aweme_count: number
  status: string
  total_videos: number
  processed_videos: number
  summarized_videos: number
  failed_videos?: number
  pending_videos?: number
  current_video_index: number
  progress: number
  current_stage: string
  error_message: string
  created_at: string
}

interface SystemStatus {
  orchestrator: string
  douyin_api: string
  dify: string
  asr_model: string
}

interface SystemConfig {
  douyin_cookie_configured?: boolean
  max_concurrent_videos?: number
  max_videos_per_blogger?: number
}

interface DouyinLoginSession {
  active: boolean
  session_token?: string
  viewer_url?: string
  expires_in?: number
  captured?: boolean
  login_detected?: boolean
  cookie_count?: number
  cookie_names?: string[]
  expired?: boolean
}

export default function App() {
  const [bloggers, setBloggers] = useState<Blogger[]>([])
  const [loading, setLoading] = useState(true)
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null)
  const [systemConfig, setSystemConfig] = useState<SystemConfig | null>(null)
  const [shareUrl, setShareUrl] = useState('')
  const [adding, setAdding] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [selectedBlogger, setSelectedBlogger] = useState<Blogger | null>(null)
  const [loginOpen, setLoginOpen] = useState(false)
  const [loginStarting, setLoginStarting] = useState(false)
  const [loginSession, setLoginSession] = useState<DouyinLoginSession | null>(null)
  const [loginError, setLoginError] = useState('')

  const fetchBloggers = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/bloggers`)
      const data = await res.json()
      setBloggers(data)
    } catch (e) {
      console.error('Failed to fetch bloggers:', e)
    } finally {
      setLoading(false)
    }
  }

  const fetchSystemStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/system/status`)
      const data = await res.json()
      setSystemStatus(data)
    } catch (e) {
      console.error('Failed to fetch system status:', e)
    }
  }

  const fetchSystemConfig = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/system/config`)
      const data = await res.json()
      setSystemConfig(data)
    } catch (e) {
      console.error('Failed to fetch system config:', e)
    }
  }

  useEffect(() => {
    fetchBloggers()
    fetchSystemStatus()
    fetchSystemConfig()
  }, [])

  const startDouyinLogin = async () => {
    setLoginOpen(true)
    setLoginStarting(true)
    setLoginError('')
    try {
      const res = await fetch(`${API_BASE}/api/system/douyin-login/start`, {
        method: 'POST',
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || '登录窗口启动失败')
      setLoginSession(data)
    } catch (e: any) {
      setLoginError(e.message || '登录窗口启动失败')
      toast.error('登录窗口启动失败', { description: e.message })
    } finally {
      setLoginStarting(false)
    }
  }

  const stopDouyinLogin = async () => {
    const token = loginSession?.session_token
    setLoginOpen(false)
    setLoginSession(null)
    setLoginError('')
    if (!token) return
    try {
      await fetch(`${API_BASE}/api/system/douyin-login/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_token: token }),
      })
    } catch {
      // 窗口到期/后端重启时无需打扰用户
    }
  }

  useEffect(() => {
    const token = loginSession?.session_token
    if (!loginOpen || !token || loginSession?.captured) return

    let cancelled = false
    const check = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/system/douyin-login/status`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_token: token }),
        })
        const data = await res.json()
        if (cancelled) return
        if (!res.ok) throw new Error(data.detail || '登录状态检测失败')
        setLoginSession(data)
        if (data.captured) {
          toast.success('抖音登录成功', {
            description: 'Cookie 已永久保存到服务端，重启不会丢失。现在可刷新博主抓取全量。',
          })
          fetchSystemConfig()
        } else if (data.expired) {
          setLoginError('登录窗口已过期，请重新打开')
        }
      } catch (e: any) {
        if (!cancelled) setLoginError(e.message || '登录状态检测失败')
      }
    }

    check()
    const interval = setInterval(check, 3000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [loginOpen, loginSession?.session_token, loginSession?.captured])

  useEffect(() => {
    const processingStatuses = ['pending', 'crawling', 'downloading', 'transcribing', 'summarizing', 'processing']
    const hasProcessing = bloggers.some(b => processingStatuses.includes(b.status))
    if (!hasProcessing) return

    const interval = setInterval(() => {
      fetchBloggers()
    }, 2000)

    return () => clearInterval(interval)
  }, [bloggers])

  const handleAddBlogger = async () => {
    if (!shareUrl.trim()) {
      toast.warning('请输入抖音链接')
      return
    }

    setAdding(true)
    try {
      const res = await fetch(`${API_BASE}/api/bloggers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ share_url: shareUrl.trim() }),
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || '添加失败')
      }

      const blogger = await res.json()
      setBloggers(prev => [blogger, ...prev])
      setShareUrl('')
      setDialogOpen(false)
      toast.success('博主添加成功', {
        description: '正在后台爬取视频并分析...',
      })
    } catch (e: any) {
      toast.error('添加失败', { description: e.message })
    } finally {
      setAdding(false)
    }
  }

  const handleRefresh = async (id: number) => {
    try {
      await fetch(`${API_BASE}/api/bloggers/${id}/refresh`, { method: 'POST' })
      toast.success('已开始重新处理')
      fetchBloggers()
    } catch (e: any) {
      toast.error('刷新失败')
    }
  }

  const handleResume = async (id: number) => {
    try {
      await fetch(`${API_BASE}/api/bloggers/${id}/resume`, { method: 'POST' })
      toast.success('已开始恢复未完成视频', {
        description: '已成功的视频会保留，只重试未完成项',
      })
      fetchBloggers()
    } catch {
      toast.error('恢复失败')
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除该博主及其所有数据？')) return
    try {
      await fetch(`${API_BASE}/api/bloggers/${id}`, { method: 'DELETE' })
      setBloggers(prev => prev.filter(b => b.id !== id))
      toast.success('删除成功')
    } catch (e) {
      toast.error('删除失败')
    }
  }

  const getStatusInfo = (status: string) => {
    switch (status) {
      case 'completed':
        return { icon: CheckCircle2, text: '已完成', variant: 'success' }
      case 'crawling':
      case 'downloading':
      case 'transcribing':
      case 'summarizing':
      case 'processing':
        return { icon: Loader2, text: '处理中', variant: 'processing' }
      case 'failed':
        return { icon: AlertCircle, text: '失败', variant: 'failed' }
      default:
        return { icon: Clock, text: '等待中', variant: 'pending' }
    }
  }

  const formatNumber = (num: number) => {
    if (num >= 10000) return (num / 10000).toFixed(1) + 'w'
    if (num >= 1000) return (num / 1000).toFixed(1) + 'k'
    return num.toString()
  }

  const isCrawlTruncated = (blogger: Blogger) =>
    blogger.aweme_count > 0 && blogger.total_videos > 0 && blogger.total_videos < blogger.aweme_count

  const formatVideoCount = (blogger: Blogger) => {
    if (blogger.aweme_count > 0) {
      return `已抓 ${blogger.total_videos} / 作品 ${blogger.aweme_count}`
    }
    return `${blogger.total_videos} 视频`
  }

  const totalBloggers = bloggers.length
  const totalVideos = bloggers.reduce((sum, b) => sum + (b.total_videos || 0), 0)
  const processedVideos = bloggers.reduce(
    (sum, b) => sum + (b.summarized_videos || b.processed_videos || 0),
    0,
  )
  const completionRate = totalVideos > 0 ? Math.round((processedVideos / totalVideos) * 100) : 0

  return (
    <div className="min-h-screen bg-[#FAFAFA]">
      {/* 顶部导航 */}
      <header className="sticky top-0 z-50 border-b border-[#E8E8E8] bg-white/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-[1280px] items-center justify-between px-8">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSelectedBlogger(null)}
              className="flex items-center gap-3"
            >
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#2C5FFF]">
                <Zap size={18} className="text-white" />
              </div>
              <div>
                <h1 className="text-[15px] font-semibold text-[#1A1A1A] tracking-tight">
                  Douyin Learning
                </h1>
                <p className="text-[11px] text-[#999]">智能博主知识库</p>
              </div>
            </button>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 rounded-full bg-[#F2F6FF] px-3 py-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-[#2C5FFF]" />
              <span className="text-[12px] font-medium text-[#2C5FFF]">系统运行中</span>
            </div>
          </div>
        </div>
      </header>

      <Dialog
        open={loginOpen}
        onOpenChange={(open) => {
          if (!open) stopDouyinLogin()
          else setLoginOpen(true)
        }}
      >
        <DialogContent className="flex h-[90vh] w-[96vw] max-w-[1180px] flex-col gap-0 overflow-hidden border border-[#E8E8E8] bg-white p-0 shadow-2xl">
          <DialogHeader className="shrink-0 border-b border-[#F0F0F0] px-6 py-4">
            <DialogTitle className="flex items-center gap-2 text-[16px] font-semibold text-[#1A1A1A]">
              <LogIn size={17} className="text-[#2C5FFF]" />
              登录抖音，自动获取 Cookie
            </DialogTitle>
            <DialogDescription className="flex items-center gap-2 text-[12px] text-[#777]">
              <ShieldCheck size={13} className="text-[#16A34A]" />
              这是服务器隔离浏览器。Cookie 只保存在服务端，不会显示或返回到前端。
            </DialogDescription>
          </DialogHeader>

          <div className="min-h-0 flex-1 bg-[#F5F5F5] p-3">
            {loginStarting && (
              <div className="flex h-full items-center justify-center text-[13px] text-[#666]">
                <Loader2 size={18} className="mr-2 animate-spin text-[#2C5FFF]" />
                正在启动隔离浏览器和安全隧道…
              </div>
            )}

            {!loginStarting && loginError && (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
                <AlertCircle size={30} className="text-[#DC2626]" />
                <p className="max-w-xl text-[13px] text-[#DC2626]">{loginError}</p>
                <Button onClick={startDouyinLogin} variant="outline">重新启动</Button>
              </div>
            )}

            {!loginStarting && !loginError && loginSession?.viewer_url && (
              <iframe
                src={loginSession.viewer_url}
                title="抖音隔离登录窗口"
                className="h-full w-full rounded-lg border border-[#DDD] bg-black"
                allow="clipboard-read; clipboard-write"
              />
            )}
          </div>

          <div className="flex shrink-0 items-center justify-between border-t border-[#F0F0F0] px-6 py-3">
            <div className="text-[12px]">
              {loginSession?.captured ? (
                <span className="inline-flex items-center gap-1.5 font-medium text-[#16A34A]">
                  <CheckCircle2 size={14} />
                  登录成功，已安全保存 {loginSession.cookie_count || 0} 项 Cookie
                </span>
              ) : (
                <span className="text-[#777]">
                  请在窗口中扫码/登录；检测成功后会自动保存。
                  {loginSession?.expires_in ? ` 窗口约 ${Math.ceil(loginSession.expires_in / 60)} 分钟后失效。` : ''}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {loginSession?.captured && (
                <Button
                  onClick={() => {
                    stopDouyinLogin()
                    fetchBloggers()
                  }}
                  className="bg-[#16A34A] hover:bg-[#15803D]"
                >
                  完成
                </Button>
              )}
              <Button variant="outline" onClick={stopDouyinLogin}>
                {loginSession?.captured ? '关闭窗口' : '取消'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {selectedBlogger ? (
        <KnowledgeDoc bloggerId={selectedBlogger.id} onBack={() => setSelectedBlogger(null)} />
      ) : (
        <>
      {/* 主内容 */}
      <main className="mx-auto max-w-[1280px] px-8 py-8">
        {!systemConfig?.douyin_cookie_configured && (
          <div className="mb-6 flex items-center justify-between gap-4 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] px-4 py-3 text-[13px] text-[#92400E]">
            <div>
              <span className="font-medium">未配置 DOUYIN_COOKIE：</span>
              抖音未登录时只能抓到部分最近作品。登录成功后会永久保存在服务端，重启不丢失。
            </div>
            <Button
              size="sm"
              onClick={startDouyinLogin}
              className="shrink-0 gap-1.5 bg-[#D97706] text-white hover:bg-[#B45309]"
            >
              <LogIn size={14} />
              登录抖音自动获取
            </Button>
          </div>
        )}
        {systemConfig?.douyin_cookie_configured && (
          <div className="mb-6 flex items-center justify-between gap-4 rounded-xl border border-[#BBF7D0] bg-[#F0FDF4] px-4 py-3 text-[13px] text-[#166534]">
            <div className="flex items-center gap-2">
              <ShieldCheck size={15} />
              <span>抖音 Cookie 已永久保存到服务端，重启后仍会自动加载。</span>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={startDouyinLogin}
              className="shrink-0 gap-1.5 border-[#86EFAC] text-[#166534] hover:bg-[#DCFCE7]"
            >
              <LogIn size={14} />
              重新登录
            </Button>
          </div>
        )}

        {/* 页面标题区 */}
        <div className="mb-8 flex items-end justify-between">
          <div>
            <h2 className="text-[22px] font-semibold text-[#1A1A1A] tracking-tight">博主管理</h2>
            <p className="mt-1 text-[13px] text-[#888]">管理你要学习的抖音博主，自动爬取并构建知识库</p>
          </div>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button className="gap-2 bg-[#2C5FFF] text-white hover:bg-[#2555E8] shadow-sm">
                <Plus size={16} />
                添加博主
              </Button>
            </DialogTrigger>
            <DialogContent className="w-[440px] border border-[#E8E8E8] bg-white p-0 shadow-xl">
              <DialogHeader className="border-b border-[#F0F0F0] px-6 py-5">
                <DialogTitle className="text-[16px] font-semibold text-[#1A1A1A]">
                  添加抖音博主
                </DialogTitle>
                <DialogDescription className="text-[13px] text-[#888]">
                  输入博主主页链接，系统将自动爬取视频并构建知识库
                </DialogDescription>
              </DialogHeader>

              <div className="px-6 py-5">
                <div className="space-y-2">
                  <label className="text-[13px] font-medium text-[#333]">博主链接</label>
                  <Input
                    placeholder="粘贴抖音分享链接或主页链接"
                    value={shareUrl}
                    onChange={(e) => setShareUrl(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddBlogger()}
                    className="h-10 border-[#E0E0E0] bg-white text-[13px] text-[#1A1A1A] placeholder:text-[#BBB] focus:border-[#2C5FFF] focus:ring-2 focus:ring-[#2C5FFF]/10"
                  />
                  <p className="text-[12px] text-[#AAA]">
                    支持分享链接、用户主页链接
                  </p>
                </div>

                <div className="mt-5 rounded-lg border border-[#EDEDED] bg-[#FAFAFA] p-4">
                  <p className="mb-3 text-[12px] font-medium text-[#666]">处理流程</p>
                  <div className="flex items-center justify-between text-[12px] text-[#888]">
                    <div className="flex flex-1 items-center gap-2">
                      <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[#EEF2FF]">
                        <Link2 size={12} className="text-[#2C5FFF]" />
                      </div>
                      <span>爬取视频</span>
                    </div>
                    <ChevronRight size={14} className="text-[#CCC] mx-2" />
                    <div className="flex flex-1 items-center gap-2">
                      <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[#EEF2FF]">
                        <Cpu size={12} className="text-[#2C5FFF]" />
                      </div>
                      <span>语音转写</span>
                    </div>
                    <ChevronRight size={14} className="text-[#CCC] mx-2" />
                    <div className="flex flex-1 items-center gap-2">
                      <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[#EEF2FF]">
                        <Database size={12} className="text-[#2C5FFF]" />
                      </div>
                      <span>构建知识库</span>
                    </div>
                  </div>
                </div>
              </div>

              <DialogFooter className="border-t border-[#F0F0F0] px-6 py-4">
                <Button
                  variant="outline"
                  onClick={() => setDialogOpen(false)}
                  className="h-9 border-[#E0E0E0] text-[13px] text-[#555] hover:bg-[#F8F8F8]"
                >
                  取消
                </Button>
                <Button
                  onClick={handleAddBlogger}
                  disabled={adding}
                  className="h-9 gap-2 bg-[#2C5FFF] text-[13px] hover:bg-[#2555E8]"
                >
                  {adding && <Loader2 size={14} className="animate-spin" />}
                  {adding ? '添加中...' : '开始学习'}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>

        {/* 统计卡片 */}
        <div className="mb-8 grid grid-cols-4 gap-4">
          {[
            { label: '博主总数', value: totalBloggers, icon: Users, suffix: '位', trend: '+1' },
            { label: '视频总数', value: totalVideos, icon: Play, suffix: '个', trend: '' },
            { label: '已处理', value: processedVideos, icon: CheckCircle2, suffix: '个', trend: '' },
            { label: '完成率', value: completionRate, icon: Activity, suffix: '%', trend: '' },
          ].map((stat, i) => (
            <Card
              key={i}
              className="border border-[#EDEDED] bg-white shadow-sm transition-all duration-200 hover:shadow-md"
            >
              <CardContent className="p-5">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-[12px] text-[#888]">{stat.label}</p>
                    <div className="mt-2 flex items-baseline gap-1.5">
                      <span className="text-[28px] font-semibold text-[#1A1A1A] tracking-tight">
                        {stat.value}
                      </span>
                      <span className="text-[13px] text-[#999]">{stat.suffix}</span>
                    </div>
                  </div>
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#F5F7FF]">
                    <stat.icon size={18} className="text-[#2C5FFF]" />
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* 主面板 */}
        <div className="grid gap-6" style={{ gridTemplateColumns: '1fr 340px' }}>
          {/* 左侧：博主列表 */}
          <div>
            <Card className="border border-[#EDEDED] bg-white shadow-sm">
              <CardHeader className="flex flex-row items-center justify-between border-b border-[#F0F0F0] pb-4">
                <div>
                  <CardTitle className="text-[15px] font-semibold text-[#1A1A1A]">
                    博主列表
                  </CardTitle>
                  <CardDescription className="mt-0.5 text-[12px] text-[#999]">
                    共 {bloggers.length} 位博主
                  </CardDescription>
                </div>
              </CardHeader>

              <CardContent className="p-0">
                {loading ? (
                  <div className="space-y-px p-2">
                    {[1, 2, 3].map(i => (
                      <div key={i} className="flex items-center gap-4 rounded-md p-4">
                        <Skeleton className="h-11 w-11 rounded-full" />
                        <div className="flex-1 space-y-2">
                          <Skeleton className="h-3.5 w-32" />
                          <Skeleton className="h-3 w-48" />
                        </div>
                      </div>
                    ))}
                  </div>
                ) : bloggers.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-16">
                    <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-xl border border-[#EDEDED] bg-[#FAFAFA]">
                      <Users size={24} className="text-[#BBB]" />
                    </div>
                    <h3 className="mb-1 text-[14px] font-medium text-[#333]">还没有添加博主</h3>
                    <p className="mb-4 text-[12px] text-[#999]">添加一位抖音博主，开始智能学习</p>
                    <Button
                      onClick={() => setDialogOpen(true)}
                      size="sm"
                      className="h-8 gap-1.5 bg-[#2C5FFF] text-[12px] hover:bg-[#2555E8]"
                    >
                      <Plus size={14} />
                      添加第一个博主
                    </Button>
                  </div>
                ) : (
                  <div className="divide-y divide-[#F5F5F5]">
                    {bloggers.map((blogger, index) => {
                      const statusInfo = getStatusInfo(blogger.status)
                      const StatusIcon = statusInfo.icon

                      return (
                        <div
                              key={blogger.id}
                              onClick={() => setSelectedBlogger(blogger)}
                              className="group cursor-pointer flex items-center gap-4 px-5 py-4 transition-colors hover:bg-[#FAFBFF]"
                          style={{ animationDelay: `${index * 50}ms` }}
                        >
                          {/* 头像 */}
                          <div className="relative h-11 w-11 shrink-0 overflow-hidden rounded-full bg-[#E8EDFF]">
                            {blogger.avatar_url ? (
                              <img
                                src={blogger.avatar_url}
                                alt={blogger.nickname}
                                className="h-full w-full object-cover"
                              />
                            ) : (
                              <div className="flex h-full w-full items-center justify-center text-[14px] font-medium text-[#2C5FFF]">
                                {blogger.nickname?.[0] || '?'}
                              </div>
                            )}
                          </div>

                          {/* 信息 */}
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <h3 className="truncate text-[14px] font-medium text-[#1A1A1A]">
                                {blogger.nickname}
                              </h3>
                              {statusInfo.variant === 'success' && (
                                <span className="inline-flex items-center gap-1 rounded-full bg-[#ECFDF3] px-2 py-0.5 text-[11px] font-medium text-[#008B57]">
                                  <CheckCircle2 size={10} />
                                  已完成
                                </span>
                              )}
                              {statusInfo.variant === 'processing' && (
                                <span className="inline-flex items-center gap-1 rounded-full bg-[#EFF4FF] px-2 py-0.5 text-[11px] font-medium text-[#2C5FFF]">
                                  <Loader2 size={10} className="animate-spin" />
                                  处理中
                                </span>
                              )}
                              {statusInfo.variant === 'failed' && (
                                <span className="inline-flex items-center gap-1 rounded-full bg-[#FEF2F2] px-2 py-0.5 text-[11px] font-medium text-[#DC2626]">
                                  <AlertCircle size={10} />
                                  失败
                                </span>
                              )}
                              {statusInfo.variant === 'pending' && (
                                <span className="inline-flex items-center gap-1 rounded-full bg-[#F5F5F5] px-2 py-0.5 text-[11px] font-medium text-[#888]">
                                  <Clock size={10} />
                                  等待中
                                </span>
                              )}
                            </div>

                            <p className="mt-1 truncate text-[12px] text-[#999]">
                              {blogger.signature || '暂无简介'}
                            </p>

                            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[#AAA]">
                              <span>{formatNumber(blogger.follower_count)} 粉丝</span>
                              <span className="text-[#DDD]">·</span>
                              <span className={isCrawlTruncated(blogger) ? 'font-medium text-[#D97706]' : ''}>
                                {formatVideoCount(blogger)}
                              </span>
                              <span className="text-[#DDD]">·</span>
                              <span className="text-[#16A34A]">
                                成功 {blogger.summarized_videos || blogger.processed_videos || 0}
                              </span>
                              {(blogger.failed_videos || 0) > 0 && (
                                <>
                                  <span className="text-[#DDD]">·</span>
                                  <span className="text-[#DC2626]">失败 {blogger.failed_videos}</span>
                                </>
                              )}
                              {(blogger.pending_videos || 0) > 0 && (
                                <>
                                  <span className="text-[#DDD]">·</span>
                                  <span className="text-[#2C5FFF]">处理中 {blogger.pending_videos}</span>
                                </>
                              )}
                            </div>

                            {isCrawlTruncated(blogger) && (
                              <p className="mt-1.5 text-[11px] leading-relaxed text-[#D97706]">
                                未登录截断：仅抓到 {blogger.total_videos}/{blogger.aweme_count}。
                                配置 DOUYIN_COOKIE 后刷新可抓全量。
                              </p>
                            )}

                            {/* 进度条 - 处理中时显示 */}
                            {['crawling', 'downloading', 'transcribing', 'summarizing', 'processing'].includes(blogger.status) && (
                              <div className="mt-2.5">
                                <div className="mb-1 flex items-center justify-between gap-2">
                                  <span className="truncate text-[11px] text-[#2C5FFF]">
                                    <Loader2 size={10} className="mr-1 inline animate-spin" />
                                    {blogger.current_stage || '处理中...'}
                                  </span>
                                  <span className="shrink-0 text-[10px] font-medium text-[#2C5FFF]">
                                    {blogger.status === 'crawling' ? (
                                      blogger.total_videos > 0
                                        ? `已获取 ${blogger.total_videos} 个视频`
                                        : '正在获取...'
                                    ) : blogger.total_videos > 0 ? (
                                      `成功 ${blogger.summarized_videos || blogger.processed_videos || 0}/${blogger.total_videos}`
                                      + ((blogger.pending_videos || 0) > 0 ? ` · 进行中 ${blogger.pending_videos}` : '')
                                    ) : (
                                      `${Math.round(blogger.progress)}%`
                                    )}
                                  </span>
                                </div>
                                <div className="h-1.5 overflow-hidden rounded-full bg-[#EEF2FF]">
                                  <div
                                    className="h-full rounded-full bg-gradient-to-r from-[#2C5FFF] to-[#5B8DEF] transition-all duration-500 ease-out"
                                    style={{
                                      width: `${Math.max(
                                        blogger.total_videos > 0
                                          ? ((blogger.summarized_videos || blogger.processed_videos || 0) / blogger.total_videos) * 100
                                          : blogger.progress,
                                        2,
                                      )}%`,
                                    }}
                                  />
                                </div>
                              </div>
                            )}

                            {/* 错误 / 截断提示 */}
                            {blogger.error_message && (
                              <p className={`mt-1.5 truncate text-[11px] ${
                                blogger.status === 'failed' ? 'text-[#DC2626]' : 'text-[#D97706]'
                              }`}>
                                {blogger.error_message}
                              </p>
                            )}
                          </div>

                          {/* 操作按钮：常显删除，避免找不到 */}
                          <div className="flex shrink-0 items-center gap-1">
                            {(blogger.pending_videos || 0) > 0 || blogger.status === 'failed' ? (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-[#999] hover:text-[#16A34A] hover:bg-[#F0FDF4]"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  handleResume(blogger.id)
                                }}
                                title="恢复未完成视频"
                              >
                                <Play size={14} />
                              </Button>
                            ) : null}
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-[#999] hover:text-[#2C5FFF] hover:bg-[#F0F4FF]"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleRefresh(blogger.id)
                              }}
                              title="重新处理"
                            >
                              <RefreshCw size={14} />
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-8 gap-1 border-[#FECACA] px-2 text-[12px] text-[#DC2626] hover:bg-[#FEF2F2]"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleDelete(blogger.id)
                              }}
                              title="删除博主"
                            >
                              <Trash2 size={13} />
                              删除
                            </Button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* 右侧：系统状态 + 快捷入口 */}
          <div className="space-y-5">
            {/* 系统状态 */}
            <Card className="border border-[#EDEDED] bg-white shadow-sm">
              <CardHeader className="pb-4">
                <CardTitle className="text-[14px] font-semibold text-[#1A1A1A]">
                  系统状态
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2.5 pb-5">
                {[
                  { name: '编排服务', status: systemStatus?.orchestrator || 'running', ok: true },
                  { name: '抖音爬虫 API', status: systemStatus?.douyin_api || 'checking', ok: systemStatus?.douyin_api === 'configured' },
                  { name: '知识库', status: 'ChromaDB', ok: true },
                  { name: 'AI 模型', status: 'Gemini 3.1', ok: true },
                ].map((item, i) => (
                  <div key={i} className="flex items-center justify-between rounded-md px-3 py-2.5 hover:bg-[#FAFAFA]">
                    <span className="text-[13px] text-[#555]">{item.name}</span>
                    <div className="flex items-center gap-2">
                      <span className={`h-1.5 w-1.5 rounded-full ${item.ok ? 'bg-[#22C55E]' : 'bg-[#F59E0B]'}`} />
                      <span className="text-[12px] text-[#666]">
                        {item.ok ? '正常' : item.status}
                      </span>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            {/* 快捷入口 */}
            <Card className="border border-[#EDEDED] bg-white shadow-sm">
              <CardHeader className="pb-4">
                <CardTitle className="text-[14px] font-semibold text-[#1A1A1A]">
                  快捷入口
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5 pb-5">
                {[
                  { name: '知识库问答', desc: '向 AI 提问学习', icon: MessageSquare, accent: 'bg-[#EEF2FF] text-[#2C5FFF]' },
                  { name: '知识浏览', desc: '查看已处理的内容', icon: BookOpen, accent: 'bg-[#EEF2FF] text-[#2C5FFF]' },
                  { name: 'API 文档', desc: '接口说明与调试', icon: Settings, accent: 'bg-[#EEF2FF] text-[#2C5FFF]' },
                ].map((item, i) => (
                  <button
                    key={i}
                    className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors hover:bg-[#FAFBFF] group"
                  >
                    <div className={`flex h-8 w-8 items-center justify-center rounded-md ${item.accent}`}>
                      <item.icon size={15} />
                    </div>
                    <div className="flex-1">
                      <p className="text-[13px] font-medium text-[#333]">{item.name}</p>
                      <p className="text-[11px] text-[#999]">{item.desc}</p>
                    </div>
                    <ChevronRight size={14} className="text-[#CCC] transition-colors group-hover:text-[#2C5FFF]" />
                  </button>
                ))}
              </CardContent>
            </Card>

            {/* 技术栈 */}
            <div className="rounded-lg border border-[#EDEDED] bg-white p-4 shadow-sm">
              <p className="mb-3 text-[11px] font-medium text-[#999]">技术架构</p>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded-md bg-[#FAFAFA] py-2.5">
                  <p className="text-[13px] font-semibold text-[#2C5FFF]">Gemini</p>
                  <p className="text-[10px] text-[#AAA]">AI 模型</p>
                </div>
                <div className="rounded-md bg-[#FAFAFA] py-2.5">
                  <p className="text-[13px] font-semibold text-[#2C5FFF]">ChromaDB</p>
                  <p className="text-[10px] text-[#AAA]">向量库</p>
                </div>
                <div className="rounded-md bg-[#FAFAFA] py-2.5">
                  <p className="text-[13px] font-semibold text-[#2C5FFF]">Whisper</p>
                  <p className="text-[10px] text-[#AAA]">语音识别</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* 底部 */}
      <footer className="border-t border-[#EFEFEF] py-5 text-center">
        <p className="text-[11px] text-[#BBB]">
          Douyin Learning Agent · 基于开源项目构建 · 仅供学习使用
        </p>
      </footer>
        </>
      )}

      <Toaster
        position="top-right"
        theme="light"
        toastOptions={{
          style: {
            background: '#FFFFFF',
            border: '1px solid #E8E8E8',
            color: '#333',
            fontSize: '13px',
            borderRadius: '8px',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)',
          },
        }}
      />
    </div>
  )
}
